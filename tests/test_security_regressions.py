from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from starlette.requests import Request

from flinteye_app.cli import initialize
from flinteye_app.flinteye_runtime import load_worker_secrets, private_media_input_command
from flinteye_app.flinteye_storage import cleanup, register_segment
from tools.manage_auth import cmd_set_password
from flinteye_app.workers.multiview_input_to_rtsp import _inject_source_credentials
from flinteye_app.orchestrator_api import (
    AppContext,
    _prepare_recording_playback_file,
    _resolve_recording_file,
    post_auth_login,
)
from flinteye_app.orchestrator_auth import AuthIdentity, authenticate_local_user, create_session_value, hash_password, parse_session_value
from flinteye_app.orchestrator_ip_camera_probe import _create_onvif_client, _discovered_candidates
from flinteye_app.orchestrator_store import RuntimeRevisionMismatch, RuntimeStore
from flinteye_app.orchestrator_supervisor import _format_cmd, _protected_worker_command


def recording_id(relative: str) -> str:
    return base64.urlsafe_b64encode(relative.encode()).decode().rstrip('=')


class CredentialRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = initialize(self.root)
        self.store = RuntimeStore(env_file='', runtime_file=str(self.runtime), use_env=False)
        self.store.patch_runtime({'auth': {'provider': 'local', 'session_secret': 'old-secret',
                                          'local': {'admin': {'username': 'admin',
                                                              'password_hash': hash_password('old-password', iterations=1000)}}}})

    def test_cli_reset_revokes_live_session_and_file_is_private(self) -> None:
        old = create_session_value('old-secret', AuthIdentity('admin', 'admin', 'local'), 3600)
        revision = self.store.runtime_revision()
        with patch('tools.manage_auth._prompt_password', return_value='new-password'):
            cmd_set_password(SimpleNamespace(runtime_file=str(self.runtime), role='admin', username=''))
        new_secret = self.store.get_effective().auth.session_secret
        self.assertNotEqual(new_secret, 'old-secret')
        self.assertIsNone(parse_session_value(new_secret, old))
        with self.assertRaises(RuntimeRevisionMismatch):
            self.store.patch_runtime({'ui': {'app_title': 'stale'}}, expected_revision=revision,
                                     protect_credentials=True)
        with self.assertRaises(ValueError):
            self.store.patch_runtime({'auth': {'session_secret': 'old-secret'}}, protect_credentials=True)
        self.store.patch_runtime({'ui': {'app_title': 'safe'}}, protect_credentials=True)
        self.assertEqual(self.store.get_effective().auth.session_secret, new_secret)
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode), 0o600)

    def test_effective_secret_is_not_frozen_into_runtime_override(self) -> None:
        env = self.root / '.env'
        env.write_text('API_ADMIN_TOKEN=first-api-token\nAUTH_SESSION_SECRET=first-session-secret\n')
        runtime = self.root / 'env-runtime.json'
        store = RuntimeStore(env_file=str(env), runtime_file=str(runtime), use_env=True)
        effective = store.get_effective().model_dump()
        store.set_runtime(effective, protect_credentials=True)
        saved = json.loads(runtime.read_text())
        self.assertNotIn('session_secret', saved.get('auth', {}))
        self.assertNotIn('admin_token', saved.get('api', {}))
        env.write_text('API_ADMIN_TOKEN=second-api-token\nAUTH_SESSION_SECRET=second-session-secret\n')
        self.assertEqual(store.get_effective().auth.session_secret, 'second-session-secret')
        self.assertEqual(store.get_effective().api.admin_token, 'second-api-token')

    def test_login_attempts_and_input_work_are_bounded(self) -> None:
        context = AppContext(env_file='', runtime_file=str(self.runtime), no_env=True)
        self.addCleanup(context.shutdown)
        request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(context=context)),
                           'client': ('192.0.2.1', 1000), 'scheme': 'http', 'server': ('localhost', 18080),
                           'path': '/api/v1/auth/login', 'headers': []})
        with self.assertRaises(HTTPException) as too_long:
            post_auth_login(request, {'username': 'admin', 'password': 'x' * 1025}, Response())
        self.assertEqual(too_long.exception.status_code, 422)
        for _ in range(10):
            with self.assertRaises(HTTPException) as denied:
                post_auth_login(request, {'username': 'unknown', 'password': 'bad'}, Response())
            self.assertEqual(denied.exception.status_code, 401)
        with self.assertRaises(HTTPException) as limited:
            post_auth_login(request, {'username': 'admin', 'password': 'old-password'}, Response())
        self.assertEqual(limited.exception.status_code, 429)

    def test_login_hash_saturation_rejects_work_and_recovers(self) -> None:
        context = AppContext(env_file='', runtime_file=str(self.runtime), no_env=True)
        self.addCleanup(context.shutdown)
        self.assertEqual(self.store.get_effective().api.host, '127.0.0.1')
        request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(context=context)),
                           'client': ('192.0.2.2', 1000), 'scheme': 'http', 'server': ('localhost', 18080),
                           'path': '/api/v1/auth/login', 'headers': []})
        for _ in range(4):
            self.assertTrue(context._login_workers.acquire(blocking=False))
        try:
            with patch('flinteye_app.orchestrator_api.authenticate_local_user') as authenticate:
                with self.assertRaises(HTTPException) as busy:
                    post_auth_login(request, {'username': 'admin', 'password': 'old-password'}, Response())
                self.assertEqual(busy.exception.status_code, 429)
                authenticate.assert_not_called()
        finally:
            for _ in range(4):
                context._login_workers.release()
        result = post_auth_login(request, {'username': 'admin', 'password': 'old-password'}, Response())
        self.assertTrue(result['authenticated'])

    def test_concurrent_cli_reset_cannot_be_undone_by_api_save(self) -> None:
        before_save = threading.Event()
        release_save = threading.Event()
        errors = []
        original_save = self.store._save_runtime_file

        def paused_save(payload):
            before_save.set()
            if not release_save.wait(10):
                raise RuntimeError('test save barrier timed out')
            original_save(payload)

        def save_settings():
            try:
                self.store.patch_runtime({'ui': {'app_title': 'concurrent-save'}}, protect_credentials=True)
            except Exception as error:
                errors.append(error)

        script = '''
import contextlib, sys
from types import SimpleNamespace
import tools.manage_auth as manage_auth
from flinteye_app.orchestrator_auth import hash_password
original_lock = manage_auth.runtime_file_lock
@contextlib.contextmanager
def signaled_lock(path):
    print("trying-lock", flush=True)
    with original_lock(path):
        yield
manage_auth.runtime_file_lock = signaled_lock
manage_auth._prompt_password = lambda _: "new-password"
new_hash = hash_password("new-password", iterations=1000)
manage_auth.hash_password = lambda _: new_hash
manage_auth.cmd_set_password(SimpleNamespace(runtime_file=sys.argv[1], role="admin", username=""))
'''
        with patch.object(self.store, '_save_runtime_file', side_effect=paused_save):
            worker = threading.Thread(target=save_settings)
            worker.start()
            self.assertTrue(before_save.wait(5))
            process = subprocess.Popen([sys.executable, '-c', script, str(self.runtime)],
                                       cwd=Path(__file__).resolve().parents[1],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'trying-lock')
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.2)
            finally:
                release_save.set()
                worker.join(timeout=5)
                stdout, stderr = process.communicate(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(process.returncode, 0, stderr)
        final = self.store.get_effective()
        self.assertEqual(final.ui.app_title, 'concurrent-save')
        self.assertIsNone(authenticate_local_user(final.auth, 'admin', 'old-password'))
        self.assertIsNotNone(authenticate_local_user(final.auth, 'admin', 'new-password'))

    def test_login_verification_racing_reset_does_not_mint_new_session(self) -> None:
        context = AppContext(env_file='', runtime_file=str(self.runtime), no_env=True)
        self.addCleanup(context.shutdown)
        request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(context=context)),
                           'client': ('192.0.2.1', 1000), 'scheme': 'https', 'server': ('localhost', 18080),
                           'path': '/api/v1/auth/login', 'headers': []})
        response = Response()

        def reset_after_verification(auth, username, password):
            identity = authenticate_local_user(auth, username, password)
            context.store.patch_runtime({'auth': {'session_secret': 'new-secret', 'local': {'admin': {
                'password_hash': hash_password('new-password', iterations=1000)}}}})
            return identity

        with patch('flinteye_app.orchestrator_api.authenticate_local_user', side_effect=reset_after_verification):
            post_auth_login(request, {'username': 'admin', 'password': 'old-password'}, response)
        cookie = SimpleCookie(response.headers['set-cookie'])['orch_session']
        self.assertTrue(cookie['secure'])
        self.assertIsNone(parse_session_value('new-secret', cookie.value))

    def test_global_login_rejection_does_not_grow_client_state(self) -> None:
        context = AppContext(env_file='', runtime_file=str(self.runtime), no_env=True)
        self.addCleanup(context.shutdown)
        with patch('flinteye_app.orchestrator_api.time.monotonic', return_value=100):
            for index in range(5000):
                try:
                    context.check_login_budget(f'2001:db8::{index:x}')
                except HTTPException as error:
                    self.assertEqual(error.status_code, 429)
        self.assertLessEqual(len(context._login_attempts), 120)


class RecordingRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        runtime = initialize(self.root)
        self.context = AppContext(env_file='', runtime_file=str(runtime), no_env=True)
        self.addCleanup(self.context.shutdown)
        self.recording_root = self.root / 'recordings'
        self.recording = self.recording_root / 'cam' / '2026-10-29' / 'clip.mp4'
        self.recording.parent.mkdir(parents=True)
        self.recording.write_bytes(b'video-source')
        age = time.time() - 120
        os.utime(self.recording, (age, age))

    def test_aliases_and_parent_symlinks_cannot_create_extra_caches(self) -> None:
        config = self.context.store.get_effective()
        direct = recording_id('cam/2026-10-29/clip.mp4')
        self.assertEqual(_resolve_recording_file(config, self.context.workspace_dir, direct)[2], self.recording)
        for alias in ('cam/2026-10-29/../2026-10-29/clip.mp4',
                      'cam//2026-10-29/clip.mp4', 'cam/./2026-10-29/clip.mp4'):
            with self.assertRaises(HTTPException):
                _resolve_recording_file(config, self.context.workspace_dir, recording_id(alias))
        try:
            (self.recording_root / 'alias').symlink_to(self.recording.parent, target_is_directory=True)
        except OSError:
            if os.name == 'nt':
                self.skipTest('Windows symlink creation requires Developer Mode or administrator rights')
            raise
        with self.assertRaises(HTTPException):
            _resolve_recording_file(config, self.context.workspace_dir, recording_id('alias/clip.mp4'))

    def test_cache_is_private_and_legacy_cache_does_not_delete_recordings(self) -> None:
        secret = self.root / 'private.mp4'
        secret.write_bytes(b'private-data')
        legacy_cache = self.recording_root / '.playback_cache'
        legacy_cache.mkdir()
        (legacy_cache / 'large.mp4').write_bytes(b'x' * 100)
        self.context.store.patch_runtime({'recording': {'max_bytes': 20, 'min_free_bytes': 0}})
        register_segment(self.root, self.recording)
        config = self.context.store.get_effective()
        self.assertEqual(cleanup(self.root, config, self.context.workspace_dir), 0)
        self.assertTrue(self.recording.exists())
        legacy_cache.rename(self.recording_root / 'old-cache')
        try:
            legacy_cache.symlink_to(self.root, target_is_directory=True)
        except OSError:
            if os.name == 'nt':
                self.skipTest('Windows symlink creation requires Developer Mode or administrator rights')
            raise

        def fake_ffmpeg(command: list[str], **_: object) -> SimpleNamespace:
            Path(command[-1]).write_bytes(b'playable-video')
            return SimpleNamespace(returncode=0, stderr='', stdout='')

        with patch('flinteye_app.orchestrator_api.run_background', side_effect=fake_ffmpeg):
            cached = _prepare_recording_playback_file(self.context, config, root=self.recording_root,
                                                      relative_path='cam/2026-10-29/clip.mp4',
                                                      file_path=self.recording)
        self.assertEqual(cached.parent, self.context.playback_cache_dir)
        self.assertEqual(cached.read_bytes(), b'playable-video')
        self.assertEqual(secret.read_bytes(), b'private-data')
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(cached.parent.stat().st_mode), 0o700)

    def test_playback_cannot_consume_the_recording_disk_reserve(self) -> None:
        config = self.context.store.get_effective()
        with patch('flinteye_app.orchestrator_api.shutil.disk_usage', return_value=SimpleNamespace(free=config.recording.min_free_bytes)), \
                patch('flinteye_app.orchestrator_api.run_background') as remux:
            with self.assertRaises(HTTPException) as denied:
                _prepare_recording_playback_file(self.context, config, root=self.recording_root,
                                                relative_path='cam/2026-10-29/clip.mp4', file_path=self.recording)
            self.assertEqual(denied.exception.status_code, 507)
            remux.assert_not_called()
        self.assertTrue(self.recording.exists())


class CameraBoundaryRegressionTests(unittest.TestCase):
    def test_https_onvif_keeps_certificate_verification_on(self) -> None:
        import requests
        from onvif import CacheMode, ONVIFClient
        seen = []

        def reject_tls(session, request, **kwargs):
            self.assertTrue(request.url.startswith('https://192.0.2.10:443/'))
            seen.append(kwargs.get('verify'))
            raise requests.exceptions.SSLError('synthetic untrusted certificate')

        with patch('requests.sessions.Session.send', reject_tls):
            client = _create_onvif_client(ONVIFClient, device_xaddr='https://192.0.2.10:443/onvif/device_service',
                                          host='192.0.2.10', port=443, username='user', password='synthetic',
                                          timeout=1, use_https=True, cache=CacheMode.MEM)
            with self.assertRaises(Exception) as rejected:
                client.devicemgmt().GetSystemDateAndTime()
            self.assertIsInstance(rejected.exception.__cause__, requests.exceptions.SSLError)
        self.assertTrue(seen)
        self.assertTrue(all(value is True for value in seen))

    def test_mixed_discovery_never_contacts_advertised_foreign_host(self) -> None:
        class FakeDiscovery:
            def __init__(self, **_: object) -> None:
                pass

            def discover(self) -> list[dict[str, object]]:
                return [{'host': '192.0.2.10', 'xaddrs': [
                    'http://192.0.2.10/onvif/device_service',
                    'http://192.0.2.11/onvif/device_service',
                ]}]

        with patch.dict(sys.modules, {'onvif': SimpleNamespace(ONVIFDiscovery=FakeDiscovery)}):
            candidates = _discovered_candidates('192.0.2.10', 1)
        self.assertEqual([candidate[0] for candidate in candidates], ['192.0.2.10'])

        class RebindingDiscovery(FakeDiscovery):
            def discover(self):
                return [{'host': '192.0.2.10', 'xaddrs': ['https://rebind.example:443/onvif/device_service']}]

        with patch.dict(sys.modules, {'onvif': SimpleNamespace(ONVIFDiscovery=RebindingDiscovery)}), \
                patch('flinteye_app.orchestrator_ip_camera_probe._hosts_match', return_value=True):
            candidates = _discovered_candidates('192.0.2.10', 1)
        self.assertEqual(candidates[0][0], '192.0.2.10')
        self.assertEqual(candidates[0][3], 'https://192.0.2.10:443/onvif/device_service')

    def test_onvif_stream_credentials_stay_with_camera_host(self) -> None:
        source = 'rtsp://user:secret@192.0.2.10/main'
        self.assertIn('user:secret@192.0.2.10', _inject_source_credentials('rtsp://192.0.2.10/low', source))
        with self.assertRaises(ValueError):
            _inject_source_credentials('rtsp://192.0.2.11/low', source)
        with patch('flinteye_app.workers.multiview_input_to_rtsp._hosts_match', return_value=True):
            pinned = _inject_source_credentials('rtsp://rebind.example/low', source)
        self.assertEqual(pinned, 'rtsp://user:secret@192.0.2.10/low')

    def test_worker_and_native_input_arguments_hide_credentials(self) -> None:
        url = 'rtsp://user:secret@192.0.2.10/main'
        command = ['python', 'ip_camera_to_rtsp.py', '--source-url', url, '--rtsp-url',
                   'rtsp://127.0.0.1:8554/cam']
        safe, secrets = _protected_worker_command(command)
        self.assertNotIn('user:secret@', ' '.join(safe))
        self.assertIn('--secret-stdin', safe)
        self.assertNotIn('user:secret@', _format_cmd(command))
        with patch('sys.stdin', io.StringIO(json.dumps(secrets))):
            args = load_worker_secrets(SimpleNamespace(secret_stdin=True, source_url=''))
        self.assertEqual(args.source_url, url)
        with private_media_input_command(['ffmpeg', '-i', url, '-f', 'null', '-'], url) as native:
            self.assertNotIn('user:secret@', ' '.join(native))
            manifest = Path(native[native.index('-i') + 1])
            self.assertIn("file '" + url + "'", manifest.read_text())
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(manifest.parent.stat().st_mode), 0o700)
        self.assertFalse(manifest.exists())
        query_url = 'rtsp://192.0.2.10/live?token=synthetic-query-token'
        command[3] = query_url
        safe, secrets = _protected_worker_command(command)
        self.assertNotIn('synthetic-query-token', ' '.join(safe))
        self.assertNotIn('synthetic-query-token', _format_cmd(command))
        with private_media_input_command(['ffprobe', query_url], query_url) as native:
            self.assertNotIn('synthetic-query-token', ' '.join(native))
        command = ['ffmpeg', '-rtsp_transport', 'tcp', '-rw_timeout', '3000000', '-i', url,
                   '-rtsp_transport', 'tcp', '-f', 'rtsp', 'rtsp://127.0.0.1/cam']
        with private_media_input_command(command, url) as native:
            manifest = Path(native[native.index('-i') + 1]).read_text()
            self.assertIn("option rtsp_transport 'tcp'", manifest)
            self.assertIn("option rw_timeout '3000000'", manifest)
            self.assertNotIn('-rtsp_transport', native[:native.index('-i')])
            self.assertIn('-rtsp_transport', native[native.index('-i') + 2:])
        with self.assertRaises(ValueError):
            with private_media_input_command(['ffprobe', url + "\nfile '/etc/passwd'"], url + "\nfile '/etc/passwd'"):
                self.fail('Manifest directive injection was accepted')


if __name__ == '__main__':
    unittest.main()
