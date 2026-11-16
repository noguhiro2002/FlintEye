"""Isolated TLS/ownership/state tests; no real profiles, firewall or cameras."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from fastapi import HTTPException
from flinteye_app.cli import initialize
from flinteye_app.network_access import Bootstrap, ensure_certificates, export_guide, permitted_source
from flinteye_app.orchestrator_models import RuntimeConfig, NetworkAccessConfig
from flinteye_app.orchestrator_snapshot import SnapshotPool
from flinteye_app.orchestrator_store import RuntimeStore


class NetworkTests(unittest.TestCase):
    def test_https_and_local_http_share_exactly_one_lifespan(self):
        from contextlib import asynccontextmanager
        import socket, ssl, threading, urllib.request
        from fastapi import FastAPI
        from types import SimpleNamespace
        from flinteye_app.server_runtime import ListenerGroup
        events = []
        @asynccontextmanager
        async def lifespan(app):
            events.append('start'); yield; events.append('stop')
        app = FastAPI(lifespan=lifespan)
        @app.get('/health')
        def health(): return {'ok': True}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            # Isolated loopback alias replaces a real LAN interface in this test only.
            network = NetworkAccessConfig.model_construct(enabled=True, address='127.0.0.2', allowed_subnets=['127.0.0.0/8'])
            with patch('flinteye_app.orchestrator_store.RuntimeStore.get_effective', return_value=SimpleNamespace(auth=SimpleNamespace(provider='local', viewer_auth_required=True))):
                group = ListenerGroup(app, root=root, host='127.0.0.1', port=port, network=network)
            thread = threading.Thread(target=group.run); thread.start()
            try:
                for _ in range(100):
                    if group.started and len(group.servers) == 2 and group.servers[1].started: break
                    time.sleep(.05)
                self.assertEqual(events, ['start'])
                self.assertEqual(urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3).status, 200)
                trust = ssl.create_default_context(cafile=str(root/'tls/ca.crt'))
                self.assertEqual(urllib.request.urlopen(f'https://127.0.0.2:{port}/health', context=trust, timeout=3).status, 200)
                with self.assertRaises(Exception): urllib.request.urlopen(f'https://127.0.0.2:{port}/health', timeout=3)
            finally:
                group.should_exit = True; thread.join(timeout=12)
            self.assertFalse(thread.is_alive())
            self.assertEqual(events, ['start', 'stop'])

    def test_lan_routes_enforce_source_scheme_host_and_local_management(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from flinteye_app.orchestrator_api import AppContext, require_admin
        from flinteye_app.flinteye_routes import install_routes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = initialize(root)
            store = RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False)
            store.patch_runtime({'network': {'enabled': True, 'address': '192.168.1.10', 'allowed_subnets': ['192.168.1.0/24']}})
            context = AppContext(env_file='', runtime_file=str(runtime), no_env=True)
            app = FastAPI(); app.state.context = context; app.dependency_overrides[require_admin] = lambda: None
            install_routes(app, context, setup_token='synthetic-token', desktop=False)
            try:
                client = TestClient(app, base_url='https://192.168.1.10', client=('192.168.1.25', 123))
                self.assertEqual(client.get('/api/v1/network').status_code, 403)
                self.assertEqual(client.post('/api/v1/setup', json={'token': 'wrong'}).status_code, 403)
                self.assertEqual(client.get('http://192.168.1.10/').status_code, 403)
                self.assertEqual(client.get('https://wrong.example/').status_code, 400)
                outside = TestClient(app, base_url='https://192.168.1.10', client=('192.168.2.25', 123))
                self.assertEqual(outside.get('/').status_code, 403)
                local = TestClient(app, client=('127.0.0.1', 123))
                self.assertEqual(local.get('/api/v1/network', headers={'host': '127.0.0.1'}).status_code, 200)
            finally: context.shutdown()

    def test_lan_is_opt_in_and_rejects_public_auth_and_wildcards(self):
        self.assertFalse(RuntimeConfig().network.enabled)
        for address in ('0.0.0.0', '8.8.8.8', '127.0.0.1', '224.0.0.1'):
            with self.assertRaises(ValueError): NetworkAccessConfig(enabled=True, address=address, allowed_subnets=['192.168.1.0/24'])
        with self.assertRaises(ValueError):
            RuntimeConfig(network={'enabled': True, 'address': '192.168.1.10', 'allowed_subnets': ['192.168.1.0/24']})
        self.assertTrue(permitted_source('192.168.1.25', ['192.168.1.0/24']))
        self.assertFalse(permitted_source('192.168.2.25', ['192.168.1.0/24']))

    def test_certificates_persist_reissue_for_new_ip_and_export_only_public_data(self):
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import ec
        import ipaddress
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = ensure_certificates(root, '192.168.1.10')
            self.assertEqual(first, ensure_certificates(root, '192.168.1.10'))
            updated = ensure_certificates(root, '192.168.1.11')
            self.assertEqual(first['fingerprint'], updated['fingerprint'])
            cert = x509.load_pem_x509_certificate((root/'tls/server.crt').read_bytes())
            self.assertIn(ipaddress.ip_address('192.168.1.11'), cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress))
            ca = x509.load_pem_x509_certificate((root/'tls/ca.crt').read_bytes())
            ca.public_key().verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
            (root/'setup-token').write_text('do-not-export-this-token')
            guide = export_guide(root, '192.168.1.11', 18080)
            self.assertTrue((guide/'FlintEye.mobileconfig').is_file())
            for file in guide.iterdir():
                self.assertNotIn(b'PRIVATE KEY', file.read_bytes())
                self.assertNotIn(b'do-not-export-this-token', file.read_bytes())
            if os.name != 'nt': self.assertEqual((root/'tls/ca.key').stat().st_mode & 0o777, 0o600)
            rotated = ensure_certificates(root, '192.168.1.11', rotate_ca=True)
            self.assertNotEqual(rotated['fingerprint'], first['fingerprint'])

    def test_bootstrap_expiry_rate_limits_consumption_and_renewal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bootstrap = Bootstrap(root, 'synthetic-owner-token')
            for _ in range(5):
                with self.assertRaises(HTTPException) as error: bootstrap.verify('wrong', '192.168.1.1')
                self.assertEqual(error.exception.status_code, 403)
            with self.assertRaises(HTTPException) as error: bootstrap.verify('wrong', '192.168.1.1')
            self.assertEqual(error.exception.status_code, 429)
            bootstrap.expires = 0
            with self.assertRaises(HTTPException): bootstrap.verify('synthetic-owner-token', '192.168.1.2')
            bootstrap.renew()
            bootstrap.verify(bootstrap.token, '192.168.1.3')
            bootstrap.consume()
            self.assertFalse((root/'setup-token').exists())
            with self.assertRaises(HTTPException): bootstrap.verify('', '192.168.1.4')

    def test_snapshot_requests_for_same_camera_are_coalesced(self):
        pool = SnapshotPool()
        def capture(**kwargs): time.sleep(.1); return b'jpeg'
        with patch('flinteye_app.orchestrator_snapshot.capture_snapshot_jpeg', side_effect=capture) as run:
            with ThreadPoolExecutor(max_workers=8) as executor:
                result = list(executor.map(lambda _: pool.capture(ffmpeg_bin='ffmpeg', rtsp_url='rtsp://127.0.0.1/synthetic', timeout_sec=1), range(8)))
            self.assertEqual(result, [b'jpeg'] * 8)
            self.assertEqual(run.call_count, 1)

    def test_completion_does_not_wait_for_mtime_age_and_changed_files_are_rejected(self):
        from flinteye_app.recording_events import record_event, file_evidence
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); initialize(root)
            segment = root/'recordings/test/2026-11-16/10-20-30-000000.mp4'
            segment.parent.mkdir(parents=True); segment.write_bytes(b'synthetic')
            record_event(root, segment, complete=False, session='test')
            self.assertFalse(file_evidence(root, [segment])[str(segment)]['is_stable'])
            with patch.dict(os.environ, {'MTX_SEGMENT_DURATION': '12.5'}): record_event(root, segment, complete=True, session='test')
            evidence = file_evidence(root, [segment])[str(segment)]
            self.assertTrue(evidence['is_stable'])
            self.assertEqual(evidence['duration_sec'], 12.5)
            self.assertEqual(evidence['ended_at']-evidence['started_at'], 12.5)
            segment.write_bytes(b'changed after completion')
            self.assertFalse(file_evidence(root, [segment])[str(segment)]['is_stable'])

    def test_diagnostics_exclude_custom_secrets_paths_and_raw_errors(self):
        from flinteye_app.orchestrator_api import AppContext
        from flinteye_app.diagnostics import diagnostic_archive
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = initialize(root)
            context = AppContext(env_file='', runtime_file=str(runtime), no_env=True)
            try:
                with patch.object(context.supervisor, 'process_status', return_value={'items': [{'id': 'mediamtx:direct', 'last_error': 'secret-value rtsp://user:private@camera /private/profile [WinError 2]'}]}):
                    content = diagnostic_archive(context)
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    text = archive.read('diagnostics.json').decode()
                for secret in ('secret-value', 'private@camera', '/private/profile', str(root)):
                    self.assertNotIn(secret, text)
                self.assertIn('"os_error_number": "2"', text)
            finally: context.shutdown()


if __name__ == '__main__': unittest.main()
