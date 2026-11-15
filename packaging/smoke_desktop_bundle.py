"""Test installed media, recording, authentication and macOS bundle relocation."""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx

from release_lib import version

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'synthetic-bundle-password'


@contextmanager
def installed_executable(directory: Path):
    if sys.platform != 'darwin':
        yield ROOT / ('dist/FlintEye/FlintEye.exe' if os.name == 'nt' else 'dist/FlintEye/FlintEye')
        return
    architecture = {'arm64': 'arm64', 'x86_64': 'amd64'}[platform.machine().lower()]
    dmg = ROOT / f'dist/FlintEye-{version()}-macos-{architecture}.dmg'
    mount = directory / 'Mounted installer'
    mount.mkdir()
    subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(dmg)],
                   check=True, timeout=120)
    installed = directory / 'Applications first/FlintEye.app'
    try:
        from verify_macos import verify_app, assess_gatekeeper
        verify_app(mount/'FlintEye.app')
        shutil.copytree(mount/'FlintEye.app', installed, symlinks=True)
    finally:
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True, timeout=60)
    verify_app(installed)
    assess_gatekeeper(installed, ROOT/f'dist/FlintEye-{version()}-macos-{architecture}-signature.json')
    # A real integrity check must reject modified final-bundle resources.
    info = installed/'Contents/Info.plist'
    original = info.read_bytes()
    try:
        info.write_bytes(original + b'\n')
        try:
            verify_app(installed)
        except subprocess.CalledProcessError:
            print('PASS: final DMG signature rejects changed bundle metadata')
        else:
            raise AssertionError('Modified bundle unexpectedly passed signature verification')
    finally:
        info.write_bytes(original)
    verify_app(installed)
    yield installed / 'Contents/MacOS/FlintEye'


def inventory_count(profile: Path) -> int:
    database = profile/'recordings.sqlite3'
    if not database.is_file():
        return 0
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute('select count(*) from segments').fetchone()[0]


def check_application(executable: Path, profile: Path, cwd: Path, *, first_run: bool) -> None:
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    log_path = profile/'startup.log'
    with log_path.open('w+', encoding='utf-8') as log:
        process = subprocess.Popen(
            [str(executable), '--headless', '--data-dir', str(profile), '--port', str(port)],
            cwd=cwd, stdout=log, stderr=log, start_new_session=os.name != 'nt')
        try:
            base = f'http://127.0.0.1:{port}'
            with httpx.Client(base_url=base, timeout=5, trust_env=False, headers={'Origin': base}) as client:
                deadline = time.monotonic()+90
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise AssertionError(f'Frozen app exited with {process.returncode}')
                    try:
                        if client.get('/api/v1/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.25)
                else:
                    raise AssertionError('Frozen app did not become ready')
                if first_run:
                    assert client.get('/api/v1/config/runtime').status_code == 503
                    assert client.post('/api/v1/setup', json={'token':'wrong','password':PASSWORD}).status_code == 403
                    token_file = profile/'setup-token'
                    result = client.post('/api/v1/setup', json={'token':token_file.read_text(),'password':PASSWORD})
                    assert result.status_code == 200, result.text
                    assert not token_file.exists(), 'Setup token was not consumed'
                assert client.get('/api/v1/config/runtime').status_code == 401
                assert client.get('/media/bundle-smoke/').status_code == 401
                result = client.post('/api/v1/auth/login', json={'username':'admin','password':PASSWORD})
                assert result.status_code == 200, result.text
                runtime = client.get('/api/v1/config/effective')
                assert runtime.status_code == 200
                active_listener = client.get('/api/v1/status/listener').json()
                assert active_listener['port'] == port and active_listener['source'] == 'command line'
                assert runtime.json()['api']['port'] == 18080, 'CLI override must not change saved settings'
                result = client.patch('/api/v1/config/runtime', headers={'If-Match':runtime.headers['etag']}, json={
                    'recording': {'record_paths':['bundle-smoke'], 'record_all_cameras':False,
                                  'include_multiview':False, 'record_segment_duration':'1s'}})
                assert result.status_code == 200, result.text
                page = client.get('/')
                assert page.status_code == 200 and '<div id="root">' in page.text
                for _ in range(60):
                    status = client.get('/api/v1/status/mediamtx').json()
                    if status.get('running') and client.get('/media/bundle-smoke/').status_code == 200:
                        break
                    time.sleep(.25)
                else:
                    raise AssertionError(f'Bundled MediaMTX did not serve authenticated video: {status}')
                media_bin = (executable.parents[1]/'Frameworks/bin' if sys.platform == 'darwin'
                             else executable.parent/'_internal/bin')
                ffmpeg = media_bin/('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
                previous = inventory_count(profile)
                stream = subprocess.run([str(ffmpeg), '-hide_banner','-loglevel','error','-re',
                    '-f','lavfi','-i','testsrc=size=160x90:rate=5','-t','4','-c:v','libx264',
                    '-pix_fmt','yuv420p','-g','5','-f','rtsp','rtsp://127.0.0.1:8554/bundle-smoke'],
                    capture_output=True, text=True, timeout=30, cwd=cwd)
                assert stream.returncode == 0, stream.stderr
                for _ in range(40):
                    if inventory_count(profile) > previous:
                        break
                    time.sleep(.25)
                else:
                    raise AssertionError('Recording completion hook did not register a new segment')
                recordings = client.get('/api/v1/recordings').json()['items']
                assert recordings, 'No synthetic recordings were created'
                assert client.get('/api/v1/recordings/files/'+recordings[0]['file_id']).status_code == 200
                print('PASS: installed app setup/auth, bundled MediaMTX, video proxy, synthetic recording and completion hook')
                # Same request used by the Windows uninstaller; exercises graceful
                # lifetime cleanup instead of taskkill hiding leftover children.
                control = json.loads((profile/'instance-control.json').read_text())
                (profile/'stop-request.json').write_text(json.dumps({'token':control['token']}))
                assert process.wait(timeout=45) == 0, 'App did not stop cleanly'
                assert not (profile/'instance-control.json').exists()
                for closed_port in (port, 8554, 8889, 9997):
                    with socket.socket() as probe:
                        probe.settimeout(.5)
                        assert probe.connect_ex(('127.0.0.1', closed_port)) != 0, f'Port {closed_port} still served after quit'
                print('PASS: quit closes API and MediaMTX listeners without an external process kill')
        except Exception:
            log.flush()
            for path in (log_path, profile/'logs/orchestrator.log', profile/'logs/mediamtx.log'):
                if path.is_file():
                    print(path.name+':\n'+path.read_text(errors='replace')[-4000:])
            raise
        finally:
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
                else:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='FlintEye installed bundle ') as temporary:
        directory = Path(temporary)
        profile = directory/'Application Support/FlintEye'
        profile.mkdir(parents=True)
        cwd = directory/'Unrelated working directory'
        cwd.mkdir()
        with installed_executable(directory) as executable:
            if not executable.is_file():
                raise FileNotFoundError(executable)
            for worker in ('uvc_to_rtsp','ip_camera_to_rtsp','multiview_input_to_rtsp',
                           'multiview_buffer_to_rtsp','multiview_raw_compositor','multiview_to_rtsp'):
                result = subprocess.run([str(executable),'--worker',worker,'--help'],cwd=cwd,
                                        capture_output=True,text=True,timeout=30,check=True)
                assert 'usage:' in result.stdout.lower(), f'{worker}: redirected stdout was lost'
            # Windowed Windows executables must recover the supervisor's pipes,
            # including stdin for private camera credentials. Fail validation
            # after reading stdin, before opening any camera or network stream.
            secret = 'rtsp://test:bundle-private-marker@127.0.0.1/unused'
            result = subprocess.run([str(executable),'--worker','ip_camera_to_rtsp',
                '--source-url','<camera-source>','--secret-stdin',
                '--rtsp-url','rtsp://127.0.0.1:8554/unused','--cfr-fps','0'],
                input=json.dumps({'source_url':secret}),capture_output=True,text=True,timeout=30,cwd=cwd)
            assert result.returncode == 2 and '--cfr-fps must be in range' in result.stderr, result.stderr
            assert 'bundle-private-marker' not in result.stdout + result.stderr
            print('PASS: all six frozen workers load; redirected output and private credential stdin survive')
            check_application(executable, profile, cwd, first_run=True)
            if sys.platform == 'darwin':
                # Same saved profile, old executable no longer exists: reproduces
                # DMG-to-Applications moves and expired AppTranslocation paths.
                old = directory/'Applications first'
                moved = directory/'Applications moved'
                old.rename(moved)
                check_application(moved/'FlintEye.app/Contents/MacOS/FlintEye',profile,cwd,first_run=False)
                print('PASS: moved macOS app reuses passwords/settings/recordings and starts its current media binary')


if __name__ == '__main__':
    main()
