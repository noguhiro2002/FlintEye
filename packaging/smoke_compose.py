"""Isolated Compose persistence check; removes only the volume it creates."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--image', required=True)
args = parser.parse_args()
project = 'flinteye-qa-' + secrets.token_hex(6)
check = '''
import json, pathlib, time, httpx
root=pathlib.Path('/data')
with httpx.Client(base_url='http://127.0.0.1:18080',timeout=45,trust_env=False) as client:
    for attempt in range(100):
        try:
            if client.get('/api/v1/health').status_code==200: break
        except httpx.HTTPError: pass
        time.sleep(.2)
    else: raise AssertionError('No API after Compose startup')
    token=root/'setup-token'
    first=token.exists()
    if first:
        result=client.post('/api/v1/setup',json={'token':token.read_text(),'password':'compose-synthetic-password'})
        assert result.status_code==200,result.text
    assert client.post('/api/v1/auth/login',json={'username':'admin','password':'compose-synthetic-password'}).status_code==200
    assert client.get('/api/v1/desktop/startup').status_code==403
    if first:
        result=client.post('/api/v1/control/stop')
        assert result.status_code==200,result.text
        (root/'qa-persistence-marker').write_text('keep test data')
    else:
        assert (root/'qa-persistence-marker').read_text()=='keep test data'
        assert not client.get('/api/v1/status/monitoring').json()['desired_running']
        assert not client.get('/api/v1/status/mediamtx').json()['running']
        assert (root/'recordings.sqlite3').exists()
    print('PASS: headless Compose '+('first run' if first else 'recreation')+' preserves auth/data and monitoring intent')
'''
with tempfile.TemporaryDirectory(prefix='flinteye-compose-check-') as directory:
    path = Path(directory)/'compose.json'
    path.write_text(json.dumps({'services': {'app': {'image': args.image, 'init': True,
        'volumes': ['data:/data']}}, 'volumes': {'data': {}}}))
    command = ['docker', 'compose', '-p', project, '-f', str(path)]
    try:
        for flags in ([], ['--force-recreate']):
            subprocess.run(command+['up', '-d', *flags], check=True, timeout=120)
            subprocess.run(command+['exec', '-T', 'app', 'python', '-'], input=check, text=True, check=True, timeout=120)
    finally:
        subprocess.run(command+['down', '-v', '--remove-orphans'], check=True, timeout=90)
