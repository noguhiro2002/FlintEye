import json, os, pathlib, subprocess, tempfile, time, urllib.request
import httpx
from flinteye_app.cli import initialize
from flinteye_app.orchestrator_store import RuntimeStore

root = pathlib.Path(tempfile.mkdtemp(prefix='flinteye-smoke-'))
runtime = initialize(root)
store = RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False)
store.patch_runtime({'recording': {'record_paths': ['test'], 'record_all_cameras': False, 'include_multiview': False, 'record_segment_duration': '1s'}})
log = (root / 'smoke.log').open('w+')
proc = subprocess.Popen(['python', 'flinteye.py', '--headless', '--data-dir', str(root)], stdout=log, stderr=log)
try:
    with httpx.Client(base_url='http://127.0.0.1:18080', follow_redirects=True) as client:
        for attempt in range(100):
            try:
                if client.get('/api/v1/health').status_code == 200: break
            except httpx.HTTPError: pass
            time.sleep(.1)
        else: raise AssertionError('Server failed to start')
        assert client.get('/').status_code == 200
        assert client.post('/api/v1/setup', json={'token': 'wrong', 'password': 'smoke-password-123'}).status_code == 403
        token = (root / 'setup-token').read_text()
        result = client.post('/api/v1/setup', json={'token': token, 'password': 'smoke-password-123'})
        assert result.status_code == 200, result.text
        assert not (root / 'setup-token').exists()
        assert client.get('/media/test/').status_code == 401
        assert client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'smoke-password-123'}).status_code == 200
        old_config = client.get('/api/v1/config/effective')
        assert old_config.status_code == 200
        assert client.post('/api/v1/accounts/viewer', json={'password': 'smoke-viewer-password'}).status_code == 200
        assert client.get('/api/v1/config/effective').status_code == 401
        assert client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'smoke-password-123'}).status_code == 200
        stale = client.patch('/api/v1/config/runtime', json={'auth': old_config.json()['auth']},
                             headers={'If-Match': old_config.headers['etag']})
        assert stale.status_code == 409, stale.text
        time.sleep(2)
        assert client.get('/media/test/').status_code == 200
        stream = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-re', '-f', 'lavfi', '-i',
                                 'testsrc=size=160x90:rate=5', '-t', '4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                                 '-g', '5', '-f', 'rtsp', 'rtsp://127.0.0.1:8554/test'], capture_output=True, text=True, timeout=20)
        assert stream.returncode == 0, stream.stderr
        time.sleep(3)
        recordings = client.get('/api/v1/recordings').json()['items']
        assert recordings, 'No recordings'
        file_id = recordings[0]['file_id']
        assert client.get('/api/v1/recordings/files/' + file_id).status_code == 200
        segment = pathlib.Path(recordings[0]['record_root']) / recordings[0]['relative_path']
        assert recordings[0]['is_stable'], 'Completion receipt did not finalize the recording'
        prepared = client.post('/api/v1/recordings/files/' + file_id + '/prepare')
        assert prepared.status_code == 200, prepared.text
        assert not pathlib.Path(prepared.json()['cache_file']).is_relative_to(root / 'recordings')
        assert client.get('/api/v1/recordings/files/' + file_id + '/playable').status_code == 200
        import sqlite3
        db = sqlite3.connect(root / 'recordings.sqlite3')
        assert db.execute('select count(*) from segments').fetchone()[0] > 0, 'Completion hook did not register recordings'
        db.close()
        print('PASS: setup, session revocation, stale-save rejection, media proxy, synthetic RTSP recording, private-cache playback, download, inventory')
finally:
    proc.terminate()
    try: proc.wait(timeout=20)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
    log.seek(0)
    print(log.read()[-2000:])
    medialog = root / 'logs/mediamtx.log'
    if medialog.exists(): print(medialog.read_text()[-2000:])
