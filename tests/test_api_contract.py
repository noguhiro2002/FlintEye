"""Exercise the registered HTTP routes with independent anonymous, viewer and admin clients."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from threading import Barrier
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import httpx
from starlette.requests import ClientDisconnect

from flinteye_app import orchestrator_api as core
from flinteye_app.cli import initialize
from flinteye_app.flinteye_routes import install_routes
from flinteye_app.orchestrator_auth import generate_session_secret, hash_password

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'packaging'))
from qa_onvif import onvif_fixture, USERNAME, PASSWORD


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
                                   ({'time_basis': 'other'}, 400), ({'recorded_from': 'nan'}, 400),
                                   ({'limit': 'invalid'}, 422), ({'limit': 1}, 200), ({'limit': 5000}, 200)]:
                with self.subTest(role=role, params=params):
                    response = client.get('/api/v1/recordings', params=params)
                    self.assertEqual(response.status_code, status)
                    if status == 200:
                        self.assertEqual(response.json()['items'], [])
                    else:
                        self.assertIn('detail', response.json())

    def test_event_settings_token_submission_status_and_cancellation(self):
        admin, viewer, device = (self.clients[role] for role in ('admin', 'viewer', 'anonymous'))
        archive = self.app.state.context.recording_archive
        events = '/api/v1/recording-events'
        settings = events+'/settings'
        self.assertFalse(admin.get(settings).json()['enabled'])
        self.assertEqual(viewer.get(events).json(), {'items': []})
        root = self.runtime.parent/'event recordings'
        root.mkdir()
        config = {'enabled': True, 'folder': str(root), 'max_lookback_sec': 90}
        owner = self.app.state.context
        owner.store.patch_runtime({'cameras': [{'id': 'fixture-camera', 'path': 'fixture-camera', 'type': 'ip',
            'ip': {'source_url': 'rtsp://127.0.0.1:8997/synthetic', 'onvif_mode': 'disabled'}}]})
        with patch.object(archive, 'start'):
            self.assertEqual(admin.put(settings, json={**config, 'folder': str(root.parent)}).status_code, 422)
            configured = admin.put(settings, json=config)
            self.assertEqual(configured.status_code, 200, configured.text)
            self.assertEqual(configured.headers['cache-control'], 'no-store')
            token = configured.json()['token']
            self.assertNotIn('token', admin.get(settings).json())
            self.assertNotIn(token, self.runtime.read_text(encoding='utf-8'))
            headers = {'Authorization': f'Bearer {token}', 'Idempotency-Key': 'equipment-7'}
            payload = {'camera_ids': ['fixture-camera'], 'lookback_sec': 10, 'label': 'fixture alert'}
            for bad in ({'lookback_sec': 91}, {'camera_ids': ['absent']},
                        {'camera_ids': ['fixture-camera', 'FIXTURE-CAMERA']},
                        {'occurred_at': '2026-01-01T00:00:00'}, {'occurred_at': '2099-01-01T00:00:00Z'}):
                self.assertEqual(device.post(events, json={**payload, **bad}, headers=headers).status_code, 422)
            now = time.time()
            result = device.post(events, json=payload, headers=headers)
            self.assertEqual(result.status_code, 202, result.text)
            event = result.json()
            self.assertGreaterEqual(event['occurred_at'], now)
            self.assertEqual(event['occurred_at'] - event['requested_from'], 10)
            self.assertEqual(event['status'], 'waiting_recording')
            self.assertEqual(device.post(events, json=payload, headers=headers).json(), event)
            self.assertEqual(device.post(events, json={**payload, 'label': 'new'}, headers=headers).status_code, 409)
            self.assertEqual(device.get(events, headers=headers).status_code, 401)
            status = events+'/'+event['id']
            self.assertEqual(device.get(status, headers=headers).json(), event)
            self.assertEqual(viewer.get(events).json(), {'items': [event]})
            self.assertEqual(admin.post(status+'/cancel').json(), {'ok': True})
            self.assertEqual(device.get(status, headers=headers).json()['status'], 'cancelled')
            self.assertEqual(admin.post(status+'/cancel').status_code, 409)
            self.assertEqual(admin.put(settings, json={**config, 'rotate_token': True}).status_code, 200)
            self.assertEqual(device.get(status, headers=headers).status_code, 401)

    def test_recording_time_filter_overlaps_the_capture_interval(self):
        from flinteye_app import recording_events
        viewer = self.clients['viewer']
        root = self.runtime.parent
        directory = root/'recordings/camera/2026-01-01'
        directory.mkdir(parents=True)
        file = directory/'10-00-00-000000_+0900.mp4'
        file.write_bytes(b'synthetic recording')
        start = datetime.fromisoformat('2026-01-01T10:00:00+09:00').timestamp()
        changed = start + 3600
        os.utime(file, (changed, changed))
        with patch.dict(os.environ, {'MTX_SEGMENT_DURATION': '60'}):
            recording_events.record_event(root, file, session='test-session', complete=True)
        legacy = directory/'legacy.mp4'
        legacy.write_bytes(b'legacy file without capture time')
        os.utime(legacy, (changed, changed))
        path = '/api/v1/recordings'
        search = {'recorded_from': start+20, 'recorded_to': start+21}
        [found] = viewer.get(path, params={**search, 'time_basis': 'recorded'}).json()['items']
        self.assertEqual((found['started_at'], found['ended_at'], found['modified_at']), (start, start+60, changed))
        self.assertEqual(viewer.get(path, params=search).json()['items'], [])
        updated = viewer.get(path, params={'recorded_from': changed, 'recorded_to': changed}).json()['items']
        self.assertEqual(len(updated), 2)

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

    def test_setup_token_renewal_requires_server_access(self):
        app = FastAPI()
        with tempfile.TemporaryDirectory() as directory:
            runtime = initialize(Path(directory))
            with patch('flinteye_app.orchestrator_logging.LogManager.configure'):
                owner = core.AppContext(runtime_file=str(runtime), env_file='', no_env=True)
            try:
                app.state.context = owner
                install_routes(app, owner, setup_token='test-only-setup-token', desktop=False)
                original = runtime.read_bytes()
                with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 10002)) as local:
                    response = local.post('/api/v1/setup/renew')
                self.assertEqual(response.status_code, 403)
                self.assertIn('server control window', response.json()['detail'])
                self.assertEqual(runtime.read_bytes(), original)
            finally:
                owner.shutdown()

    def test_authenticated_media_proxy_preserves_each_supported_method(self):
        client = self.clients['viewer']
        expected_url = 'http://127.0.0.1:8889/test/whep'
        upstream = AsyncMock()
        manager = AsyncMock()
        manager.__aenter__.return_value = upstream
        with patch('flinteye_app.flinteye_routes.httpx.AsyncClient', return_value=manager):
            for method, status in [('GET', 200), ('HEAD', 200), ('POST', 201), ('PATCH', 204),
                                   ('DELETE', 204), ('OPTIONS', 204)]:
                with self.subTest(method=method):
                    upstream.request.return_value = httpx.Response(status,
                        headers={'location': '/test/whep/session', 'accept-patch': 'application/trickle-ice-sdpfrag'},
                        request=httpx.Request(method, expected_url))
                    body = b'test-offer' if method in {'POST', 'PATCH'} else b''
                    headers = {'Content-Type': 'application/sdp', 'If-Match': 'fixture-etag', 'Authorization': 'fixture'}
                    response = client.request(method, '/media/test/whep?fixture=1', headers=headers, content=body)
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(response.headers['location'], '/media/test/whep/session')
                    self.assertEqual(response.headers['accept-patch'], 'application/trickle-ice-sdpfrag')
                    call = upstream.request.await_args
                    self.assertEqual(call.args, (method, expected_url))
                    self.assertEqual(call.kwargs['content'], body)
                    self.assertEqual(dict(call.kwargs['params'])['fixture'], '1')
                    self.assertEqual(call.kwargs['headers']['if-match'], 'fixture-etag')
                    self.assertNotIn('cookie', call.kwargs['headers'])
                    self.assertNotIn('authorization', call.kwargs['headers'])
            upstream.request.side_effect = httpx.ConnectError('fixture media service offline')
            self.assertEqual(client.get('/media/test/whep').status_code, 502)

    def test_media_proxy_handles_client_leaving_during_offer(self):
        with patch('starlette.requests.Request.body', side_effect=ClientDisconnect), \
             patch('flinteye_app.flinteye_routes.httpx.AsyncClient') as upstream:
            response = self.clients['viewer'].post('/media/test/whep', content='incomplete offer')
        self.assertEqual(response.status_code, 499)
        upstream.assert_not_called()

    def test_whep_audio_falls_back_to_video_and_pins_the_session(self):
        from flinteye_app.camera_audio import live_path

        context = self.app.state.context
        context.store.patch_runtime({'cameras': [{'id': 'cam', 'path': 'cam', 'type': 'ip',
            'ip': {'source_url': 'rtsp://127.0.0.1:8555/qa'}, 'audio': {'enabled': True}}]})
        viewer = self.clients['viewer']
        relay = live_path('cam')
        session = f'/{relay}/whep/qa-session'
        def reply(status, path, location=None):
            return httpx.Response(status, request=httpx.Request('POST', 'http://127.0.0.1:8889'+path),
                                  headers={'Location': location} if location else {})
        with patch.object(context.supervisor, 'live_audio_ready', return_value=False) as ready, \
             patch('flinteye_app.flinteye_routes.httpx.AsyncClient') as client:
            forward = client.return_value.__aenter__.return_value.request
            forward.return_value = reply(201, '/cam/whep', '/cam/whep/primary')
            self.assertEqual(viewer.post('/media/cam/whep').status_code, 201)
            self.assertTrue(forward.call_args.args[1].endswith('/cam/whep'))
            ready.return_value = True
            forward.side_effect = [reply(404, f'/{relay}/whep'), reply(201, '/cam/whep', '/cam/whep/primary')]
            self.assertEqual(viewer.post('/media/cam/whep').headers['location'], '/media/cam/whep/primary')
            self.assertTrue(forward.call_args_list[-2].args[1].endswith(f'/{relay}/whep'))
            self.assertTrue(forward.call_args.args[1].endswith('/cam/whep'))

            forward.side_effect = None
            forward.return_value = reply(201, f'/{relay}/whep', session+'?fixture=1')
            location = viewer.post('/media/cam/whep').headers['location']
            self.assertEqual(location, '/media/cam/whep/qa-session?fixture=1&flinteye_audio=1')
            ready.return_value = False
            forward.return_value = reply(204, session)
            self.assertEqual(viewer.delete(location).status_code, 204)
            self.assertTrue(forward.call_args.args[1].endswith(session))
            self.assertEqual(dict(forward.call_args.kwargs['params']), {'fixture': '1'})
            self.assertEqual(viewer.post(f'/media/{relay}/whep').status_code, 404)

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

    def test_operator_read_models_have_the_expected_shapes(self):
        viewer = self.clients['viewer']
        for resource, key in {
            'status/monitoring': 'controls', 'status/mediamtx': 'running', 'status/processes': 'items',
            'storage/status': 'recording_paused', 'multiview/status': 'views', 'multiview/views': 'items',
            'recordings/streams': 'items', 'viewer/cameras': 'items', 'viewer/info': 'api',
            'streams/qa-stream/addresses': 'webrtc_url',
        }.items():
            with self.subTest(resource=resource):
                response = viewer.get('/api/v1/'+resource)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn(key, response.json())
        self.assertEqual(viewer.get('/api/v1/streams/qa-stream/addresses').json()['id'], 'qa-stream')
        for suffix in ('snapshot', 'addresses'):
            self.assertEqual(viewer.get('/api/v1/multiview/views/qa-missing/'+suffix).status_code, 404)
        admin = self.clients['admin']
        for resource, key in {
            'config/runtime': 'auth', 'desktop': 'folder_picker', 'monitoring/preferences': 'resume_on_startup',
            'status/listener': 'port', 'multiview': 'source_mode', 'cameras': 'items', 'network': 'saved',
            'mediamtx/config': 'managed',
        }.items():
            with self.subTest(resource=resource):
                response = admin.get('/api/v1/'+resource)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn(key, response.json())

    def test_monitoring_controls_report_the_effective_state(self):
        admin = self.clients['admin']
        owner = self.app.state.context
        with patch.object(owner.supervisor, 'mediamtx_start', return_value={'ok': True}), \
             patch.object(owner.supervisor, '_start_process'):
            for action, desired in [('start', True), ('restart', True), ('stop', False)]:
                with self.subTest(action=action):
                    response = admin.post(f'/api/v1/control/{action}')
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertTrue(response.json()['result']['ok'])
                    self.assertEqual(admin.get('/api/v1/status/monitoring').json()['desired_running'], desired)
            self.assertEqual(admin.post('/api/v1/control/restart').status_code, 409)
        before = self.runtime.parent/'monitoring.json'
        old = before.read_bytes()
        for value in ('true', 1, None):
            self.assertEqual(admin.patch('/api/v1/monitoring/preferences', json={'resume_on_startup':value}).status_code, 422)
        self.assertEqual(before.read_bytes(), old)
        self.assertTrue(admin.patch('/api/v1/monitoring/preferences', json={'resume_on_startup':True}).json()['resume_on_startup'])

    def test_rest_api_keys_are_scoped_persistent_and_revocable(self):
        from flinteye_app.api_keys import ApiKeyStore, CONTROL_ROUTES, READ_ROUTES

        admin, external = self.clients['admin'], self.clients['anonymous']
        endpoint = '/api/v1/auth/api-keys'
        self.assertEqual(admin.get(endpoint).json(), {'items': []})
        self.assertEqual(admin.post(endpoint, json={'name': 'test', 'scope': 'admin'}).status_code, 422)
        issued = {}
        for scope in ('read', 'monitor'):
            response = admin.post(endpoint, json={'name': 'Synthetic '+scope, 'scope': scope})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            issued[scope] = response.json()
        settings = admin.get(endpoint).json()['items']
        self.assertEqual({row['scope'] for row in settings}, {'read', 'monitor'})
        self.assertTrue(all('token' not in row and 'digest' not in row for row in settings))

        store = ApiKeyStore(self.runtime.parent)
        self.assertEqual(store.scope(issued['monitor']['token']), 'monitor')
        context = self.app.state.context
        self.assertNotIn(issued['monitor']['token'].encode(), store.path.read_bytes())
        self.assertNotIn(issued['read']['token'].encode(), self.runtime.read_bytes())
        bearer = lambda scope: {'Authorization': 'Bearer '+issued[scope]['token']}
        for scope in ('read', 'monitor'):
            for route in READ_ROUTES:
                actual = external.get(route, headers=bearer(scope))
                self.assertEqual(actual.status_code, 200, actual.text)
            for method, route in [('GET', endpoint), ('GET', '/api/v1/config/runtime'),
                                  ('POST', '/api/v1/cameras/qa-camera/ptz/move'),
                                  ('POST', '/api/v1/config/apply')]:
                self.assertEqual(external.request(method, route, headers=bearer(scope)).status_code, 403)
        for route in CONTROL_ROUTES:
            self.assertEqual(external.post(route, headers=bearer('read')).status_code, 403)
        with patch.object(context.supervisor, 'mediamtx_start', return_value={'ok': True}), \
             patch.object(context.supervisor, '_start_process'):
            for action, running in [('start', True), ('restart', True), ('stop', False)]:
                result = external.post('/api/v1/control/'+action, headers=bearer('monitor'))
                self.assertEqual(result.status_code, 200, result.text)
                self.assertIs(external.get('/api/v1/status/monitoring', headers=bearer('monitor')).json()['desired_running'], running)
        revoke = endpoint+'/'+issued['monitor']['id']
        for _ in range(2):
            self.assertEqual(admin.delete(revoke).status_code, 200)
        self.assertEqual(admin.delete(endpoint+'/qa-unknown').status_code, 404)
        self.assertEqual(external.get('/api/v1/status/monitoring', headers=bearer('monitor')).status_code, 401)
        self.assertEqual(external.get('/api/v1/status/monitoring', headers=bearer('read')).status_code, 200)
        self.assertIsNotNone(next(row for row in admin.get(endpoint).json()['items'] if row['scope'] == 'monitor')['revoked_at'])

    def test_multiview_positions_follow_camera_rename_and_removal(self):
        admin, viewer = self.clients['admin'], self.clients['viewer']
        context = self.app.state.context
        config_path = '/api/v1/config/runtime'
        cameras = [{'id': f'cam{i}', 'path': f'cam{i}', 'type': 'ip',
                    'ip': {'source_url': f'rtsp://127.0.0.1:8997/camera{i}', 'onvif_mode': 'disabled'}}
                   for i in (1, 2, 3)]
        slots = [['cam2', None, 'cam1', 'cam3']]
        cfg = {'enabled': True, 'tile_count': 4, 'source_paths': ['cam1', 'cam2', 'cam3'],
               'layout': {'source_slots': slots}}
        with patch.object(context.supervisor, '_start_process'):
            initial = admin.patch(config_path, json={'cameras': cameras, 'multiview': cfg})
            self.assertEqual(initial.status_code, 200, initial.text)
            self.assertEqual(admin.patch(config_path, json={'multiview': {'layout': {
                'source_slots': [['cam2', None, 'cam1', 'CAM2']]}}}).status_code, 422)
            renamed = admin.patch('/api/v1/cameras/cam2', json={'path': 'renamed'})
            self.assertEqual(renamed.status_code, 200, renamed.text)
            self.assertEqual(admin.delete('/api/v1/cameras/cam3').status_code, 200)
            prefs = admin.get(config_path).json()['multiview']
            self.assertEqual(prefs['layout']['source_slots'], [['renamed', None, 'cam1', None]])
            self.assertEqual(prefs['source_paths'], ['cam1', 'renamed'])
            for client in (admin, viewer):
                view = client.get('/api/v1/multiview/views').json()['items'][0]
                self.assertEqual(view['sources'], ['renamed', 'cam1'])
                self.assertEqual([row['slot'] for row in view['source_items']], [1, 3])

    def test_lan_settings_export_and_rotation_only_change_synthetic_profile(self):
        admin = self.clients['admin']
        root = self.runtime.parent
        for action in ('guide', 'rtsps-credential'):
            self.assertEqual(admin.post('/api/v1/network/'+action).status_code, 409)
        self.assertEqual(admin.post('/api/v1/network/renew-trust', json={'confirm': False}).status_code, 422)
        payload = {'enabled': True, 'address': '192.168.59.4', 'allowed_subnets': ['192.168.59.0/24'], 'rtsp_enabled': True}
        before = self.runtime.read_bytes()
        denied = admin.put('/api/v1/network', json={**payload, 'allowed_subnets': ['0.0.0.0/0']})
        self.assertEqual(denied.status_code, 422)
        self.assertEqual(self.runtime.read_bytes(), before)
        response = admin.put('/api/v1/network', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        status = admin.get('/api/v1/network').json()
        self.assertTrue(status['restart_required'])
        self.assertTrue(status['saved']['enabled'])
        self.assertFalse(status['active']['enabled'])
        guide = admin.post('/api/v1/network/guide')
        self.assertEqual(guide.status_code, 200, guide.text)
        public = Path(guide.json()['path'])
        self.assertTrue(public.is_relative_to(root))
        self.assertFalse(list(public.glob('*.key')))
        with patch.object(self.app.state.context.supervisor, 'reconcile_rtsps'):
            credential = admin.post('/api/v1/network/rtsps-credential')
            self.assertEqual(credential.status_code, 200, credential.text)
            self.assertEqual(credential.headers['cache-control'], 'no-store')
        old_cert = (root/'tls/ca.crt').read_bytes()
        self.assertTrue(admin.post('/api/v1/network/renew-trust', json={'confirm':True}).json()['restart_required'])
        self.assertNotEqual((root/'tls/ca.crt').read_bytes(), old_cert)
        result = admin.get('/api/v1/diagnostics')
        self.assertEqual(result.status_code, 200)
        with zipfile.ZipFile(BytesIO(result.content)) as archive:
            self.assertTrue(archive.namelist())
            self.assertFalse(any(name.endswith(('.key', '.log', '.sqlite3')) for name in archive.namelist()))
            private_key = (root/'tls/ca.key').read_bytes()
            self.assertTrue(all(private_key not in archive.read(name) for name in archive.namelist()))

    def test_camera_paths_validation_and_multiview_control(self):
        admin, viewer = self.clients['admin'], self.clients['viewer']
        context = self.app.state.context
        with patch.object(context.supervisor, '_start_process'), patch.object(context.snapshot_pool, 'capture', return_value=b'jpeg'):
            cameras = [{'id': f'cam{i}', 'path': f'cam{i}', 'type': 'ip', 'ip': {
                'source_url': f'rtsp://127.0.0.1:8997/camera{i}', 'onvif_mode': 'disabled'}} for i in (1, 2)]
            for camera in cameras:
                self.assertEqual(admin.post('/api/v1/cameras', json=camera).status_code, 200)
            current = self.runtime.read_bytes()
            bad = admin.patch('/api/v1/config/runtime', json={'cameras': [*cameras, cameras[0]]})
            self.assertEqual(bad.status_code, 422)
            self.assertEqual(self.runtime.read_bytes(), current)
            runtime = admin.get('/api/v1/config/runtime').json()
            self.assertEqual(admin.put('/api/v1/config/runtime', json=runtime).status_code, 200)
            self.assertTrue(admin.post('/api/v1/config/apply').json()['applied'])
            response = admin.get('/api/v1/cameras/cam1/multiview-input/capabilities')
            self.assertEqual(response.json()['onvif_status'], 'disabled')
            self.assertNotIn('onvif', response.json()['supported_modes'])
            for action in ('exclude', 'restore'):
                self.assertEqual(admin.post('/api/v1/cameras/cam1/'+action).status_code, 200)
            self.assertEqual(viewer.get('/api/v1/cameras/cam1/addresses').json()['id'], 'cam1')
            self.assertEqual(viewer.get('/api/v1/cameras/cam1/snapshot').headers['content-type'], 'image/jpeg')
            self.assertEqual(admin.patch('/api/v1/multiview', json={'source_mode':'env', 'source_paths':['cam2','cam1']}).status_code, 200)
            self.assertTrue(admin.post('/api/v1/multiview/enable').json()['enabled'])
            view = viewer.get('/api/v1/multiview/views').json()['items'][0]
            self.assertEqual(view['sources'], ['cam2', 'cam1'])
            path = f'/api/v1/multiview/views/{view["id"]}'
            self.assertEqual(viewer.get(path+'/addresses').json()['webrtc_url'], view['webrtc_url'])
            self.assertEqual(viewer.get(path+'/snapshot').content, b'jpeg')
            self.assertFalse(admin.post('/api/v1/multiview/disable').json()['enabled'])

    def test_ptz_routes_inspect_and_control_the_loopback_camera(self):
        from flinteye_app.orchestrator_ip_camera_probe import IpCameraProbeError
        context = self.app.state.context
        source = 'rtsp://127.0.0.1:8996'
        admin, viewer = self.clients['admin'], self.clients['viewer']
        with onvif_fixture(source) as url, patch.object(context.supervisor, '_start_process'):
            data = {'source_url': source+'/qa-input-1', 'onvif_mode':'manual', 'onvif_address':url+'/media1/device',
                    'onvif_username':USERNAME, 'onvif_password':PASSWORD}
            url_path = '/api/v1/ip-cameras/probe'
            for invalid in ({'source_url':'bad'}, {'onvif_mode':'wrong'}, {'onvif_address':''},
                            {'probe_duration_sec':'bad'}, {'probe_duration_sec':16}, {'probe_duration_sec':'nan'}):
                self.assertEqual(admin.post(url_path, json={**data, **invalid}).status_code, 422)
            with patch('flinteye_app.orchestrator_ip_camera_probe.probe_rtsp_timing', side_effect=IpCameraProbeError('no test video')):
                probe = admin.post(url_path, json=data)
                self.assertEqual(probe.status_code, 200, probe.text)
                self.assertFalse(probe.json()['rtsp']['available'])
                self.assertTrue(probe.json()['onvif']['ptz']['supported'])
            camera = {'id':'qa-ptz','path':'qa-ptz','type':'ip','ip':{**data, 'ptz':{'enabled':True, 'access':'admin'}}}
            self.assertEqual(admin.post('/api/v1/cameras', json=camera).status_code, 200)
            prefix = '/api/v1/cameras/qa-ptz/ptz/'
            self.assertEqual(viewer.get(prefix+'capabilities').status_code, 403)
            capabilities = admin.get(prefix+'capabilities')
            self.assertEqual(capabilities.status_code, 200, capabilities.text)
            self.assertEqual(capabilities.json()['selected_profile_token'], 'qa-main')
            for op, fields in [('move',{'pan':.5}), ('position',{'zoom':.4}), ('stop',{})]:
                response = admin.post(prefix+op, json={'operation_id':'qa-operation', **fields})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()['ok'])
            for bad in ({'pan':1.1, 'operation_id':'bad-pan'}, {'pan':0,'operation_id':'zero'},
                        {'pan':'NaN','operation_id':'not-finite'}, {}):
                response = admin.post(prefix+'move', json=bad)
                self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(admin.post(prefix+'position', json={'zoom':'Infinity', 'operation_id':'bad-position'}).status_code, 409)
            context.ptz_controller.shutdown()

    def test_local_maintenance_routes_validate_before_calling_os(self):
        from types import SimpleNamespace
        desktop_app = FastAPI()
        desktop_app.state.context = self.app.state.context
        desktop_app.router.routes.extend(route for route in core.app.routes if isinstance(route, APIRoute))
        install_routes(desktop_app, desktop_app.state.context, setup_token='', desktop=True)
        with TestClient(desktop_app, base_url='http://127.0.0.1', client=('127.0.0.1',10002)) as client:
            self.assertEqual(client.post('/api/v1/auth/login', json={'username':'admin','password':'fixture-password-only'}).status_code, 200)
            with patch('flinteye_app.cli.set_autostart') as set_autostart, \
                 patch('flinteye_app.cli.autostart_status', return_value={'enabled':True,'available':True}):
                self.assertTrue(client.get('/api/v1/desktop/startup').json()['available'])
                for value in (None, 'true', 1):
                    self.assertEqual(client.put('/api/v1/desktop/startup', json={'enabled':value}).status_code, 422)
                set_autostart.assert_not_called()
                self.assertTrue(client.put('/api/v1/desktop/startup', json={'enabled':True}).json()['enabled'])
                set_autostart.assert_called_once_with(True)

            def pick(command, **options):
                Path(command[-1]).write_text(json.dumps({'path': str(self.runtime.parent)}))
                return SimpleNamespace(returncode=0)

            with patch('flinteye_app.flinteye_routes.run_background', side_effect=pick):
                self.assertEqual(client.post('/api/v1/storage/pick-folder').json()['path'], str(self.runtime.parent))
            self.assertEqual(client.post('/api/v1/storage/suggest', json={'path':'relative'}).status_code, 422)
            with patch('flinteye_app.flinteye_routes.suggested_quota', return_value=1_000_000_000):
                self.assertEqual(client.post('/api/v1/storage/suggest', json={'path':str(self.runtime.parent)}).json()['max_bytes'], 1_000_000_000)
            with patch('flinteye_app.windows_maintenance.manage_firewall', return_value={'ok':True}) as firewall:
                self.assertEqual(client.post('/api/v1/network/firewall', json={'action':'invalid'}).status_code, 422)
                firewall.assert_not_called()
                self.assertTrue(client.post('/api/v1/network/firewall', json={'action':'remove'}).json()['ok'])
                self.assertEqual(firewall.call_args.args[0], self.runtime.parent)

    def test_media_and_update_settings_with_isolated_dependencies(self):
        admin = self.clients['admin']
        self.assertEqual(admin.patch('/api/v1/mediamtx/config', json={}).status_code, 400)
        patched = admin.patch('/api/v1/mediamtx/config', json={'recording':{'record_segment_duration':'30s'}})
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()['recording']['record_segment_duration'], '30s')
        response = admin.post('/api/v1/mediamtx/config/apply')
        self.assertEqual(response.status_code, 200)
        self.assertIn('managed', response.json())
        bundle = self.runtime.parent/'bundle'
        with patch('flinteye_app.flinteye_routes.application_dir', return_value=bundle):
            self.assertEqual(admin.post('/api/v1/media/use-bundled').status_code, 409)
            (bundle/'bin').mkdir(parents=True)
            (bundle/'bin'/'mediamtx').touch()
            self.assertTrue(admin.post('/api/v1/media/use-bundled').json()['ok'])
        manager = AsyncMock()
        response = AsyncMock()
        response.json = lambda: []
        response.raise_for_status = lambda: None
        manager.__aenter__.return_value.get.return_value = response
        with patch('flinteye_app.flinteye_routes.httpx.AsyncClient', return_value=manager):
            self.assertFalse(admin.get('/api/v1/updates').json()['available'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires local media tools')
    def test_viewer_can_play_and_prepare_a_real_recording(self):
        viewer = self.clients['viewer']
        self.app.state.context.store.patch_runtime({'recording': {'min_free_bytes': 0}})
        clip = self.runtime.parent/'recordings/camera/2026-01-01/clip.mp4'
        clip.parent.mkdir(parents=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=10',
                        '-t', '1', '-c:v', 'libx264', '-threads', '1', str(clip)], check=True, timeout=15)
        from flinteye_app import recording_events
        session = self.app.state.context.monitoring.session
        recording_events.record_event(self.runtime.parent, clip, session=session, complete=False)
        [item] = viewer.get('/api/v1/recordings').json()['items']
        path = '/api/v1/recordings/files/'+item['file_id']
        self.assertEqual(viewer.post(path+'/prepare').status_code, 409)
        recording_events.record_event(self.runtime.parent, clip, session=session, complete=True)
        prepared = viewer.post(path+'/prepare')
        self.assertEqual(prepared.status_code, 200, prepared.text)
        self.assertIs(prepared.json()['has_audio'], False)
        play = viewer.get(path+'/playable', headers={'Range': 'bytes=0-15'})
        self.assertEqual((play.status_code, play.content), (206, clip.read_bytes()[:16]))
        preview = viewer.get(path+'/thumbnail')
        self.assertEqual(preview.status_code, 200, preview.text[:200])
        self.assertTrue(preview.content.startswith(b'\xff\xd8'))

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

    def test_usb_discovery_add_remove_and_readd_supported_modes(self):
        admin = self.clients['admin']
        store = self.app.state.context.store
        base = '/api/v1/uvc/devices'
        for driver, capture_device, input_format in (
            ('dshow', 'video=QA camera', 'codec:mjpeg'),
            ('avfoundation', 'QA camera:none', ''),
            ('v4l2', '/dev/flinteye-qa', 'mjpeg'),
        ):
            with self.subTest(driver=driver):
                modes = [{'width': width, 'height': height, 'fps': 30, 'input_format': input_format}
                         for width, height in [(1280, 720), (1920, 1080)]]
                device = {'device_id': f'qa-{driver}', 'driver': driver, 'display_name': 'QA camera',
                          'ffmpeg_device': capture_device, 'modes': modes, 'recommended': modes[1]}
                device_url = f'{base}/{device["device_id"]}'
                camera_url = f'/api/v1/cameras/qa-{driver}'
                fixture = {'driver': driver, 'ffmpeg_bin': 'ffmpeg', 'devices': [device]}
                with (patch.object(self.app.state.context.uvc_probe_cache, 'get', return_value=fixture),
                      patch.object(core, '_restart_affected')):
                    self.assertEqual(admin.get(base, params={'refresh': True}).json()['items'][0]['modes'], modes)
                    expected = {**modes[1], 'path': f'qa-{driver}'}
                    suggestion = admin.post(device_url+'/suggest', json=expected).json()['suggestion']
                    self.assertEqual(suggestion['runtime_camera']['uvc']['env']['HEIGHT'], '1080')
                    prior = self.runtime.read_bytes()
                    self.assertEqual(admin.post(device_url+'/apply', json={**expected, 'input_format': 'unsupported'}).status_code, 422)
                    self.assertEqual(self.runtime.read_bytes(), prior)
                    self.assertEqual(admin.post(device_url+'/apply', json=expected).status_code, 200)
                    saved = store.get_effective().cameras[0]
                    self.assertEqual(saved.uvc.env['DEVICE'], capture_device)
                    self.assertEqual(saved.uvc.env['INPUT_DRIVER'], driver)
                    self.assertFalse(saved.audio.enabled)
                    self.assertEqual(admin.delete(camera_url).status_code, 200)
                    self.assertEqual(admin.get(camera_url).status_code, 404)
                    prior = admin.get('/api/v1/config/effective')
                    ignored = admin.patch('/api/v1/config/runtime', headers={'If-Match': prior.headers['etag']},
                                          json={'device_discovery': {'ignored_uvc_devices': [device['device_id']]}})
                    self.assertEqual(ignored.status_code, 200)
                    self.assertTrue(admin.get(device_url).json()['ignored'])
                    self.assertEqual(admin.post(device_url+'/apply', json=expected).status_code, 200)
                    self.assertFalse(admin.get(device_url).json()['ignored'])
                    self.assertEqual(admin.get(camera_url).status_code, 200)
                    self.assertEqual(admin.delete(camera_url).status_code, 200)

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
