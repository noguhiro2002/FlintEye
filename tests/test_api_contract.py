"""Exercise the registered HTTP routes with independent anonymous, viewer and admin clients."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from flinteye_app import orchestrator_api as core
from flinteye_app.cli import initialize
from flinteye_app.flinteye_routes import install_routes
from flinteye_app.orchestrator_auth import generate_session_secret, hash_password


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.runtime = initialize(Path(directory.name))
        with patch('flinteye_app.orchestrator_logging.LogManager.configure'):
            context = core.AppContext(runtime_file=str(self.runtime), env_file='', no_env=True)
        self.addCleanup(context.shutdown)
        password = 'fixture-password-only'
        context.store.patch_runtime({'auth': {'session_secret': generate_session_secret(), 'local': {
            role: {'username': role, 'password_hash': hash_password(password)}
            for role in ('admin', 'viewer')
        }}})
        self.app = FastAPI()
        self.app.state.context = context
        # Use the production handlers and their dependency graphs without starting
        # a listener or acquiring cameras during a contract test.
        self.app.router.routes.extend(route for route in core.app.routes if isinstance(route, APIRoute))
        install_routes(self.app, context, setup_token='', desktop=False)
        self.clients = {}
        for role in ('anonymous', 'viewer', 'admin'):
            client = TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 10001))
            self.addCleanup(client.close)
            if role != 'anonymous':
                response = client.post('/api/v1/auth/login', json={'username': role, 'password': password})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['role'], role)
            self.clients[role] = client

    def test_access_policy_for_every_registered_operation(self):
        policy = json.loads(Path(__file__).with_name('api-access.json').read_text())
        registered = {(method, route.path) for route in self.app.routes if isinstance(route, APIRoute)
                      for method in route.methods}
        expected = {(method, path) for paths in policy.values() for path, methods in paths.items()
                    for method in methods.split()}
        self.assertEqual(registered, expected, 'Every new operation needs an explicit access policy')
        before = self.runtime.read_bytes()
        for role, paths in policy.items():
            if role == 'public':
                continue
            for template, methods in paths.items():
                path = re.sub(r'\{[^}]+\}', 'qa-missing', template)
                for method in methods.split():
                    for identity, status in ([('anonymous', 401), ('viewer', 403)] if role == 'admin'
                                             else [('anonymous', 401)]):
                        with self.subTest(method=method, path=path, identity=identity):
                            response = self.clients[identity].request(method, path, json={})
                            self.assertEqual(response.status_code, status)
                            if method != 'HEAD':
                                self.assertIn('detail', response.json())
        self.assertEqual(before, self.runtime.read_bytes())

    def test_recording_filters_and_empty_inventory(self):
        for role in ('viewer', 'admin'):
            client = self.clients[role]
            for params, status in [({'limit': 0}, 400), ({'limit': 5001}, 400), ({'offset': -1}, 400),
                                   ({'recorded_from': 2, 'recorded_to': 1}, 400), ({'status': 'other'}, 400),
                                   ({'sort_by': 'other'}, 400), ({'sort_dir': 'other'}, 400),
                                   ({'limit': 'invalid'}, 422), ({'limit': 1}, 200), ({'limit': 5000}, 200)]:
                with self.subTest(role=role, params=params):
                    response = client.get('/api/v1/recordings', params=params)
                    self.assertEqual(response.status_code, status)
                    if status == 200:
                        self.assertEqual(response.json()['items'], [])
                    else:
                        self.assertIn('detail', response.json())

    def test_rotation_invalidates_both_sessions_and_rejects_old_viewer_password(self):
        admin, viewer = self.clients['admin'], self.clients['viewer']
        self.assertEqual(viewer.get('/api/v1/build').status_code, 200)
        self.assertEqual(admin.get('/api/v1/config/effective').status_code, 200)
        new_password = 'changed-fixture-password'
        self.assertEqual(admin.post('/api/v1/accounts/viewer', json={'password': new_password}).status_code, 200)
        for client in (admin, viewer):
            self.assertEqual(client.get('/api/v1/build').status_code, 401)
        for password, status in [('fixture-password-only', 401), (new_password, 200)]:
            self.assertEqual(viewer.post('/api/v1/auth/login', json={'username': 'viewer', 'password': password}).status_code, status)
        self.assertEqual(viewer.get('/api/v1/config/effective').status_code, 403)

    def test_public_routes_on_an_initialized_server(self):
        client = self.clients['anonymous']
        self.assertTrue(client.get('/api/v1/health').json()['ok'])
        self.assertEqual(client.get('/api/v1/status').json()['cameras_total'], 0)
        self.assertFalse(client.get('/api/v1/auth/me').json()['authenticated'])
        self.assertTrue(client.post('/api/v1/auth/logout').json()['ok'])
        for path in ('setup', 'setup/renew'):
            self.assertEqual(client.post('/api/v1/'+path, json={}).status_code, 409)
        self.assertEqual(client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'incorrect'}).status_code, 401)

    def test_missing_camera_is_reported_to_authenticated_clients(self):
        admin = self.clients['admin']
        before = self.runtime.read_bytes()
        for method, suffix in [('GET', ''), ('DELETE', ''), ('PATCH', ''), ('GET', '/multiview-input/capabilities'),
                               ('POST', '/enable'), ('POST', '/disable'), ('POST', '/exclude'), ('POST', '/restore'),
                               ('GET', '/audio'), ('PUT', '/audio'), ('GET', '/addresses'), ('GET', '/snapshot'),
                               ('GET', '/ptz/capabilities'), ('POST', '/ptz/move'), ('POST', '/ptz/stop'),
                               ('POST', '/ptz/position')]:
            with self.subTest(method=method, suffix=suffix):
                response = admin.request(method, '/api/v1/cameras/qa-missing'+suffix, json={})
                self.assertEqual(response.status_code, 404, response.text)
                self.assertIn('detail', response.json())
        self.assertEqual(before, self.runtime.read_bytes())

    def test_simultaneous_saves_reject_stale_revision_and_preserve_winner(self):
        first = self.clients['admin']
        with TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 10002)) as second:
            self.assertEqual(second.post('/api/v1/auth/login', json={
                'username': 'admin', 'password': 'fixture-password-only'}).status_code, 200)
            revision = first.get('/api/v1/config/effective').headers['etag']
            ready = Barrier(2)

            def save(client, title):
                ready.wait(timeout=10)
                response = client.patch('/api/v1/config/runtime', json={'ui': {'app_title': title}},
                                        headers={'If-Match': revision})
                return response.status_code, title

            # No hardware is needed to verify the actual persistence/ETag transaction.
            with patch.object(core, '_restart_affected'), ThreadPoolExecutor(max_workers=2) as pool:
                attempts = [pool.submit(save, client, title)
                            for client, title in [(first, 'First edit'), (second, 'Second edit')]]
                results = dict(future.result(timeout=15) for future in attempts)
            self.assertEqual(set(results), {200, 409})
            saved = second.get('/api/v1/config/effective')
            self.assertEqual(saved.json()['ui']['app_title'], results[200])
            self.assertNotEqual(saved.headers['etag'], revision)
            self.assertEqual(json.loads(self.runtime.read_text())['ui']['app_title'], results[200])

    def test_camera_lifecycle_and_audio_consent(self):
        admin = self.clients['admin']
        cameras = '/api/v1/cameras'
        path = cameras+'/fixture'
        # Substitutes physical detection and worker reconfiguration only.
        with patch.object(core, '_restart_affected'), patch.object(core, '_camera_audio_availability') as detect:
            camera = {'id': 'fixture', 'path': 'fixture', 'type': 'uvc'}
            self.assertEqual(admin.post(cameras, json=camera).status_code, 200)
            detect.return_value = 'no_input'
            self.assertFalse(admin.get(path+'/audio').json()['settings']['enabled'])
            before = self.runtime.read_bytes()
            for state in ('no_input', 'unknown', 'permission'):
                detect.return_value = state
                self.assertEqual(admin.put(path+'/audio', json={'enabled': True}).status_code, 409)
            self.assertEqual(before, self.runtime.read_bytes())
            detect.return_value = 'available'
            for preset, rate, bits in [('standard', 16000, 16), ('high', 48000, 24),
                                       ('middle', 12000, 16), ('low', 8000, 16)]:
                with self.subTest(preset=preset):
                    response = admin.put(path+'/audio', json={'enabled': True, 'preset': preset})
                    self.assertEqual(response.status_code, 200)
                    settings = admin.get(path+'/audio').json()['settings']
                    self.assertEqual((settings['sample_rate'], settings['bit_depth'], settings['channels']),
                                     (rate, bits, 1))
            custom = {'enabled': True, 'preset': 'custom', 'codec': 'aac', 'sample_rate': 44100,
                      'channels': 2, 'bitrate_kbps': 128, 'bit_depth': 16}
            self.assertEqual(admin.put(path+'/audio', json=custom).json()['settings'], custom)
            self.assertEqual(admin.put(path+'/audio', json={**custom, 'bitrate_kbps': 0}).status_code, 422)
            self.assertEqual(admin.get(path+'/audio').json()['settings'], custom)
            self.assertFalse(admin.put(path+'/audio', json={'enabled': False}).json()['settings']['enabled'])
            for action in ('disable', 'enable'):
                self.assertEqual(admin.post(path+'/'+action).status_code, 200)
                self.assertEqual(admin.get(path).json()['enabled'], action == 'enable')
            self.assertEqual(admin.patch(path, json={'display_name': 'Renamed'}).json()['camera']['display_name'], 'Renamed')
            self.assertEqual(admin.delete(path).status_code, 200)
            self.assertEqual(admin.get(path).status_code, 404)

    def test_download_ranges_and_hidden_previous_location(self):
        admin = self.clients['admin']
        clip = self.runtime.parent/'recordings'/'camera'/'2026-01-01'/'clip.ts'
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b'0123456789')
        [item] = admin.get('/api/v1/recordings').json()['items']
        path = '/api/v1/recordings/files/'+item['file_id']
        partial = admin.get(path, headers={'Range': 'bytes=3-5'})
        self.assertEqual((partial.status_code, partial.content), (206, b'345'))
        self.assertEqual(partial.headers['content-range'], 'bytes 3-5/10')
        self.assertEqual(admin.get(path, headers={'Range': 'bytes=20-30'}).status_code, 416)
        other = self.runtime.parent/'other-recordings'
        other.mkdir()
        with patch.object(core, '_restart_affected'):
            response = admin.patch('/api/v1/config/runtime', json={'recording': {'record_root': str(other)}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(admin.get(path).content, clip.read_bytes())
            self.assertEqual(admin.patch('/api/v1/config/runtime',
                             json={'recording': {'show_previous': False}}).status_code, 200)
            self.assertEqual(admin.get('/api/v1/recordings').json()['items'], [])
            for suffix in ('', '/playable', '/thumbnail'):
                self.assertEqual(admin.get(path+suffix).status_code, 404)
            self.assertEqual(admin.post(path+'/prepare').status_code, 404)
            self.assertEqual(clip.read_bytes(), b'0123456789')
