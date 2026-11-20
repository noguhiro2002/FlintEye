"""Exercise Compose recreation or upgrade and restore on disposable named volumes."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--image', required=True)
parser.add_argument('--previous-image', help='Pinned previous GHCR image (enable upgrade and restore)')
args = parser.parse_args()
project = 'flinteye-qa-' + secrets.token_hex(6)
check = '''
import hashlib, pathlib, subprocess, sys, time
import httpx
from flinteye_app.recording_events import record_event

first = sys.argv[1] == 'fresh'
root = pathlib.Path('/data')
token = root/'setup-token'
admin = {'username': 'admin', 'password': 'compose-synthetic-password'}
viewer = {'username': 'viewer', 'password': 'synthetic-viewer-password'}
with httpx.Client(base_url='http://127.0.0.1:18080', timeout=45, trust_env=False) as client:
    for attempt in range(150):
        try:
            if client.get('/api/v1/health').status_code == 200: break
        except httpx.HTTPError: pass
        time.sleep(.2)
    else: raise AssertionError('No API after Compose startup')
    assert token.is_file() == first, 'Unexpected first-run/retained profile state'
    if first:
        response = client.post('/api/v1/setup', json={'token': token.read_text(), 'password': admin['password']})
        assert response.status_code == 200, response.text
        assert client.post('/api/v1/auth/login', json=admin).status_code == 200
        assert client.post('/api/v1/accounts/viewer', json={'password': viewer['password']}).status_code == 200
    assert client.post('/api/v1/auth/login', json=admin).status_code == 200
    assert client.get('/api/v1/desktop/startup').status_code == 403
    clip = root/'recordings'/'fixture'/'2026-01-01'/'12-00-00-000000.mp4'
    if first:
        response = client.post('/api/v1/control/stop')
        assert response.status_code == 200, response.text
        clip.parent.mkdir(parents=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10',
                        '-t', '1', '-c:v', 'libx264', str(clip)], check=True, timeout=20)
        record_event(root, clip, session='qa', complete=True)
        (root/'qa-clip.sha256').write_text(hashlib.sha256(clip.read_bytes()).hexdigest())
    assert not client.get('/api/v1/status/monitoring').json()['desired_running']
    assert not client.get('/api/v1/status/mediamtx').json()['running']
    items = client.get('/api/v1/recordings').json()['items']
    [item] = [item for item in items if item['relative_path'] == clip.relative_to(root/'recordings').as_posix()]
    assert item['is_stable']
    url = '/api/v1/recordings/files/' + item['file_id']
    download = client.get(url)
    assert download.status_code == 200 and hashlib.sha256(download.content).hexdigest() == (root/'qa-clip.sha256').read_text()
    assert client.post('/api/v1/auth/login', json=viewer).status_code == 200
    assert client.get(url).status_code == 403
    assert client.post(url+'/prepare').status_code == 200
    assert client.get(url+'/playable').status_code == 200
    print('PASS', sys.argv[1], client.get('/api/v1/build').json()['release'])
'''
with tempfile.TemporaryDirectory(prefix='flinteye-compose-check-') as directory:
    path = Path(directory)/'compose.json'
    command = ['docker', 'compose', '-p', project, '-f', str(path)]
    try:
        plan = [(args.previous_image or args.image, 'fresh', 'data'), (args.image, 'retained', 'data')]
        if args.previous_image:
            plan.append((args.previous_image, 'restored', 'backup'))
        for image, phase, volume in plan:
            services = {'app': {'image': image, 'init': True, 'volumes': [f'{volume}:/data']},
                        'snapshot': {'image': image, 'profiles': ['qa'], 'network_mode': 'none',
                                     'entrypoint': ['cp', '-a', '/from/.', '/data/'],
                                     'volumes': ['data:/from:ro', 'backup:/data']}}
            path.write_text(json.dumps({'services': services, 'volumes': {'data': {}, 'backup': {}}}))
            subprocess.run(command+['up', '-d', '--force-recreate'], check=True, timeout=240)
            subprocess.run(command+['exec', '-T', 'app', 'python', '-', phase], input=check,
                           text=True, check=True, timeout=150)
            if phase == 'fresh' and args.previous_image:
                subprocess.run(command+['stop'], check=True, timeout=60)
                # Snapshot only our stopped container's volume. Restore boots the old
                # binary against this snapshot, never against a migrated database.
                subprocess.run(command+['run', '--rm', '--no-deps', '-T', 'snapshot'], check=True, timeout=60)
    finally:
        subprocess.run(command+['--profile', 'qa', 'down', '-v', '--remove-orphans'], check=True, timeout=90)
