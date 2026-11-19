from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from flinteye_app.cli import initialize
from flinteye_app.flinteye_runtime import worker_command
from flinteye_app.flinteye_storage import cleanup, register_segment, suggested_quota
from flinteye_app.flinteye_routes import install_routes
from flinteye_app.orchestrator_api import AppContext, _all_recording_files, _resolve_recording_file
from flinteye_app.orchestrator_auth import authenticate_local_user, hash_password
from flinteye_app.orchestrator_store import RuntimeStore


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = initialize(self.root)
        self.store = RuntimeStore(env_file='', runtime_file=str(self.runtime), use_env=False)
        self.store.patch_runtime({'recording': {'max_bytes': 15, 'min_free_bytes': 0}})
        self.recordings = self.root / 'recordings'

    def segment(self, name, age=20, registered=True):
        file = self.recordings / 'cam' / '2026-10-29' / (name + '.mp4')
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'x' * 10)
        os.utime(file, (time.time() - age, time.time() - age))
        if registered: register_segment(self.root, file)
        return file

    def test_only_completed_registered_oldest_is_deleted(self):
        old = self.segment('old', age=100)
        new = self.segment('new', age=10)
        active = self.segment('active', registered=False)
        other = self.recordings / 'important.txt'; other.write_text('keep')
        cleanup(self.root, self.store.get_effective(), str(self.root))
        self.assertFalse(old.exists())
        self.assertTrue(active.exists()); self.assertTrue(other.exists())

    def test_modified_segment_is_never_deleted(self):
        file = self.segment('changed')
        file.write_bytes(b'changed after registration' * 20)
        cleanup(self.root, self.store.get_effective(), str(self.root))
        self.assertTrue(file.exists())

    def test_expiry_deletes_even_below_quota(self):
        file = self.segment('expired', age=8 * 86400)
        self.store.patch_runtime({'recording': {'max_bytes': 50_000_000_000}})
        self.assertEqual(cleanup(self.root, self.store.get_effective(), str(self.root)), 1)
        self.assertFalse(file.exists())

    def test_hidden_old_root_retains_cleanup_but_not_access(self):
        old = self.segment('old', age=8 * 86400)
        newroot = self.root / 'new'; newroot.mkdir()
        self.store.patch_runtime({'recording': {'record_root': str(newroot)}})
        config = self.store.get_effective()
        items = _all_recording_files(config, str(self.root))
        old_id = items[0]['file_id']
        self.assertEqual(_resolve_recording_file(config, str(self.root), old_id)[2], old)
        self.store.patch_runtime({'recording': {'show_previous': False}})
        config = self.store.get_effective()
        self.assertEqual(_all_recording_files(config, str(self.root)), [])
        with self.assertRaises(HTTPException): _resolve_recording_file(config, str(self.root), old_id)
        cleanup(self.root, config, str(self.root))
        self.assertFalse(old.exists())

    def test_ids_do_not_collide_across_roots(self):
        self.segment('same')
        newroot = self.root / 'new'; newroot.mkdir()
        self.store.patch_runtime({'recording': {'record_root': str(newroot)}})
        copy = newroot / 'cam/2026-10-29/same.mp4'; copy.parent.mkdir(parents=True); copy.write_bytes(b'new')
        files = _all_recording_files(self.store.get_effective(), str(self.root))
        self.assertEqual(len({f['file_id'] for f in files}), 2)

    def test_symlink_cannot_delete_outside_root(self):
        file = self.segment('link')
        external = self.root / 'outside.mp4'; external.write_bytes(b'keep')
        file.unlink(); file.symlink_to(external)
        cleanup(self.root, self.store.get_effective(), str(self.root))
        self.assertTrue(external.exists())

    def test_quota_is_capped_half_free(self):
        from types import SimpleNamespace
        with patch('flinteye_app.flinteye_storage.shutil.disk_usage', return_value=SimpleNamespace(free=20_000_000_000)):
            self.assertEqual(suggested_quota(self.root), 10_000_000_000)
        with patch('flinteye_app.flinteye_storage.shutil.disk_usage', return_value=SimpleNamespace(free=200_000_000_000)):
            self.assertEqual(suggested_quota(self.root), 50_000_000_000)

    def test_reinitialize_preserves_configuration(self):
        before = self.runtime.read_bytes()
        initialize(self.root)
        self.assertEqual(before, self.runtime.read_bytes())


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        runtime = initialize(root)
        self.context = AppContext(env_file='', runtime_file=str(runtime), no_env=True)
        self.addCleanup(self.context.shutdown)
        app = FastAPI(); app.state.context = self.context
        install_routes(app, self.context, setup_token='private-token', desktop=False)
        self.client = TestClient(app)

    def test_token_and_password_validation_then_one_time_setup(self):
        self.assertEqual(self.client.post('/api/v1/setup', json={'token': 'wrong', 'password': 'long-password'}).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/setup', json={'token': 'private-token', 'password': 'short'}).status_code, 422)
        with patch('flinteye_app.orchestrator_api._on_startup'):
            # route holds a reference to startup; do not launch processes in this test
            import flinteye_app.flinteye_routes as flinteye_routes
            self.context.store.patch_runtime({'mediamtx': {'autostart_on_api_start': False}})
            with patch('flinteye_app.orchestrator_api.app.state.context', self.context, create=True):
                response = self.client.post('/api/v1/setup', json={'token': 'private-token', 'password': 'long-password'})
        self.assertEqual(response.status_code, 200)
        auth = self.context.store.get_effective().auth
        self.assertEqual(authenticate_local_user(auth, 'admin', 'long-password').role, 'admin')
        self.assertEqual(self.client.post('/api/v1/setup', json={}).status_code, 409)
        self.assertNotIn('long-password', Path(self.context.store.runtime_file).read_text())

    def test_media_requires_login_and_cross_origin_setup_is_rejected(self):
        self.assertEqual(self.client.get('/media/cam/').status_code, 503)
        self.assertEqual(self.client.post('/api/v1/setup', headers={'Origin': 'https://other.example'}, json={}).status_code, 403)

    def test_authenticated_media_proxy_rewrites_session_location(self):
        from unittest.mock import AsyncMock
        import httpx
        from flinteye_app.orchestrator_api import require_viewer
        self.client.app.dependency_overrides[require_viewer] = lambda: None
        response = httpx.Response(201, content=b'answer', headers={'Location': '/test/whep/session', 'ETag': 'abc'},
                                  request=httpx.Request('POST', 'http://127.0.0.1:8889/test/whep'))
        upstream = AsyncMock()
        upstream.request.return_value = response
        manager = AsyncMock()
        manager.__aenter__.return_value = upstream
        with patch('flinteye_app.flinteye_routes.httpx.AsyncClient', return_value=manager):
            result = self.client.post('/media/test/whep', content='offer', headers={'Content-Type': 'application/sdp', 'Cookie': 'private=session'})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.headers['location'], '/media/test/whep/session')
        self.assertNotIn('cookie', upstream.request.call_args.kwargs['headers'])

    def test_media_uses_managed_port_but_never_a_configured_remote_host(self):
        from unittest.mock import AsyncMock
        import httpx
        from flinteye_app.orchestrator_api import require_viewer
        self.client.app.dependency_overrides[require_viewer] = lambda: None
        self.context.store.patch_runtime({'mediamtx': {'control_mode': 'direct', 'managed': {
            'enabled': True, 'global': {'webrtcAddress': '127.0.0.1:18889'}}}})
        upstream = AsyncMock()
        upstream.request.return_value = httpx.Response(200, content=b'player', request=httpx.Request('GET', 'http://127.0.0.1:18889/test/'))
        manager = AsyncMock(); manager.__aenter__.return_value = upstream
        with patch('flinteye_app.flinteye_routes.httpx.AsyncClient', return_value=manager):
            self.assertEqual(self.client.get('/media/test/').status_code, 200)
        self.assertEqual(upstream.request.call_args.args[1], 'http://127.0.0.1:18889/test/')
        self.context.store.patch_runtime({'mediamtx': {'managed': {'global': {'webrtcAddress': 'remote.example:1234'}}}})
        with patch('flinteye_app.flinteye_routes.httpx.AsyncClient', return_value=manager):
            self.assertEqual(self.client.get('/media/test/').status_code, 503)

    def test_packaged_worker_uses_dispatch_not_python_script(self):
        with patch('sys.frozen', True, create=True):
            self.assertEqual(worker_command('uvc_to_rtsp')[1:], ['--worker', 'uvc_to_rtsp'])



class StorageGuardTests(unittest.TestCase):
    def test_recording_hook_preserves_windows_paths_for_mediamtx_parser(self):
        import shlex
        import yaml
        from flinteye_app.orchestrator_models import RuntimeConfig
        from flinteye_app.orchestrator_recording import apply_recording_config
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / 'mediamtx.yml'
            config_path.write_text('paths: {}\n')
            config = RuntimeConfig(recording={'record_root': directory, 'managed_storage': True,
                'record_paths': ['cam'], 'record_all_cameras': False, 'include_multiview': False})
            executable = r'C:\Users\camera\Programs\FlintEye\FlintEye.exe'
            profile = r"C:\Users\Camera Owner's PC\AppData\Local\FlintEye"
            with patch('flinteye_app.orchestrator_recording._resolve_config_path', return_value=config_path), \
                 patch('flinteye_app.flinteye_runtime.launch_command', return_value=[executable]), \
                 patch.dict(os.environ, {'FLINTEYE_DATA_DIR': profile}):
                result = apply_recording_config(config, workspace_dir=directory)
            self.assertTrue(result.ok)
            command = yaml.safe_load(config_path.read_text())['paths']['cam']['runOnRecordSegmentComplete']
            self.assertEqual(shlex.split(command), [executable, '--segment-complete', profile])

    def test_missing_and_full_storage_are_paused(self):
        from types import SimpleNamespace
        from flinteye_app.flinteye_storage import storage_problem
        from flinteye_app.orchestrator_models import RuntimeConfig
        with tempfile.TemporaryDirectory() as directory:
            config = RuntimeConfig(recording={'record_root': directory, 'managed_storage': True})
            with patch('flinteye_app.flinteye_storage.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
                self.assertIn('paused', storage_problem(config))
            with patch('flinteye_app.flinteye_storage.shutil.disk_usage', return_value=SimpleNamespace(free=2_000_000_000)):
                self.assertIsNone(storage_problem(config))
            config.recording.record_root = str(Path(directory) / 'missing')
            self.assertIn('unavailable', storage_problem(config))

    def test_recording_listing_excludes_unrelated_files(self):
        from flinteye_app.orchestrator_api import _list_recording_files
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'runtime.json').write_text('{"secret":"private"}')
            (root / 'test.mp4').write_bytes(b'video')
            self.assertEqual([item['relative_path'] for item in _list_recording_files(root)], ['test.mp4'])

if __name__ == '__main__': unittest.main()
