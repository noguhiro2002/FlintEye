"""Real media/browser checks shared by native, source and container installers."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def free_port(*, udp: bool = False) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def wait_http(url: str, process=None, seconds: int = 90) -> None:
    import httpx
    with httpx.Client(timeout=2, trust_env=False) as client:
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            if process and process.poll() is not None:
                raise RuntimeError(f'Application exited before readiness ({process.returncode})')
            try:
                if client.get(url+'/api/v1/health').status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.25)
    raise TimeoutError('Installed API did not become ready')


def wait_closed(port: int, seconds: int = 45) -> None:
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        with socket.socket() as probe:
            probe.settimeout(.3)
            if probe.connect_ex(('127.0.0.1', port)) != 0:
                return
        time.sleep(.25)
    raise AssertionError(f'Owned listener still active after quit: {port}')


def seed_runtime(profile: Path, app_profile: str, media: str, *, prefix: list[str] | None = None) -> int:
    """Use only a QA-owned profile; no device discovery or default media ports."""
    if not (profile/'.flinteye-qa-owned').is_file():
        raise ValueError('Refusing to initialize an unowned test profile')
    profile.mkdir(parents=True, exist_ok=True)
    (profile/'recordings').mkdir(exist_ok=True)
    runtime = profile/'runtime.json'
    if runtime.exists():
        value = json.loads(runtime.read_text())
        return value['api']['port']
    port, rtsp, web, api, rtc = free_port(), free_port(), free_port(), free_port(), free_port(udp=True)
    # Full config defaults are applied by the actual installed application.
    value = {
        'api': {'host': '127.0.0.1', 'port': port},
        'auth': {'provider': 'local', 'viewer_auth_required': True},
        'cameras': [], 'ui': {'onboarding_done': False},
        'logging': {'directory': str(Path(app_profile)/'logs')},
        'recording': {'record_root': str(Path(app_profile)/'recordings'), 'managed_storage': True,
                      'max_bytes': 1_000_000_000, 'min_free_bytes': 100_000_000},
        'multiview': {'enabled': False, 'mtx_api_url': f'http://127.0.0.1:{api}/v3/paths/list',
                      'input_rtsp_base_url': f'rtsp://127.0.0.1:{rtsp}', 'output_rtsp_base_url': f'rtsp://127.0.0.1:{rtsp}',
                      'status_file': str(Path(app_profile)/'logs/multiview.json')},
        'mediamtx': {'control_mode': 'direct', 'rtsp_base_url': f'rtsp://127.0.0.1:{rtsp}',
                     'internal_rtsp_base_url': f'rtsp://127.0.0.1:{rtsp}', 'webrtc_base_url': '/media',
                     'direct': {'source': 'external', 'command': [media, str(Path(app_profile)/'mediamtx.yml')],
                                'working_dir': app_profile},
                     'managed': {'enabled': True, 'global': {
                         'rtspAddress': f'127.0.0.1:{rtsp}', 'webrtcAddress': f'127.0.0.1:{web}',
                         'api': True, 'apiAddress': f'127.0.0.1:{api}', 'apiEncryption': False,
                         'rtspTransports': ['tcp'], 'hls': False, 'rtmp': False, 'srt': False, 'moq': False, 'playback': False,
                         'webrtcLocalUDPAddress': f'127.0.0.1:{rtc}', 'webrtcIPsFromInterfaces': False,
                         'webrtcAdditionalHosts': ['127.0.0.1']}}},
    }
    runtime.write_text(json.dumps(value, indent=2)+'\n')
    (profile/'mediamtx.yml').write_text('paths:\n  all_others: {}\n')
    return port


def stop_process(process, *, force: bool = False) -> None:
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', *(['/F'] if force else [])],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if force:
            raise
        stop_process(process, force=True)


def stage_fixture_tools(directory: Path, media: str, ffmpeg: str, *, prefix=None, app_directory=None):
    """External cameras must not hold an installed application's binaries open."""
    from release_lib import digest
    tools = directory/'external-camera-tools'; tools.mkdir()
    target = Path(app_directory)/tools.name if prefix else tools
    names, checksums = [], {}
    for original in (media, ffmpeg):
        name = Path(original).name
        if prefix:
            subprocess.run([*prefix, 'cp', '-L', original, str(target/name)], check=True, timeout=30)
        else:
            shutil.copy2(original, tools/name)
        names.append(str(target/name))
        checksums[name] = digest(tools/name)
    (directory/'external-camera-tools.json').write_text(json.dumps({
        'purpose': 'Independent synthetic cameras outside the application installation',
        'sha256': checksums}, indent=2)+'\n')
    return tuple(names)


@contextmanager
def media_fixture(directory: Path, media: str, ffmpeg: str, *, prefix: list[str] | None = None,
                  app_directory: str | None = None):
    """Two independent RTSP publishers; they are not owned by the application."""
    prefix = prefix or []
    app_directory = app_directory or str(directory)
    media, ffmpeg = stage_fixture_tools(directory, media, ffmpeg, prefix=prefix, app_directory=app_directory)
    port = free_port()
    config = directory/'fixture.yml'
    config.write_text(f'rtspAddress: 127.0.0.1:{port}\nrtspTransports: [tcp]\n'
                      'api: no\nhls: no\nwebrtc: no\nrtmp: no\nsrt: no\nmoq: no\nplayback: no\n'
                      'paths:\n  all_others:\n    source: publisher\n')
    children, logs = [], []
    def start(command, name):
        log = (directory/name).open('w', encoding='utf-8'); logs.append(log)
        process = subprocess.Popen(prefix+command, stdout=log, stderr=log, start_new_session=os.name != 'nt')
        children.append(process)
        return process
    try:
        start([media, str(Path(app_directory)/config.name)], 'fixture-mediamtx.log')
        end = time.monotonic()+20
        while time.monotonic() < end:
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1', port)) == 0: break
            time.sleep(.1)
        else: raise TimeoutError('Synthetic RTSP server did not start')
        for i in (1, 2):
            command = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-re',
                       '-f', 'lavfi', '-i', f'testsrc2=size=320x180:rate=10',
                       '-f', 'lavfi', '-i', f'sine=frequency={i*440}:sample_rate=48000',
                       '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-g', '10',
                       '-c:a', 'aac', '-b:a', '64k', '-ac', '1', '-rtsp_transport', 'tcp',
                       '-f', 'rtsp', f'rtsp://127.0.0.1:{port}/qa-input-{i}']
            start(command, f'fixture-publisher-{i}.log')
        time.sleep(2)
        if any(p.poll() is not None for p in children):
            raise RuntimeError('Synthetic media publisher failed; inspect fixture logs')
        yield f'rtsp://127.0.0.1:{port}'
    finally:
        for process in reversed(children): stop_process(process)
        for log in logs: log.close()


def browser_check(url: str, profile: Path, output: Path, release: str, commit: str,
                  fixture_url: str, *, retained: bool = False) -> None:
    output.mkdir(parents=True, exist_ok=True)
    command = ['node', str(ROOT/'frontend/tests/installed.mjs'), '--url', url, '--profile', str(profile),
               '--output', str(output), '--release', release, '--fixture-url', fixture_url]
    if commit: command += ['--commit', commit]
    if retained: command += ['--retained']
    with (output/'browser.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=420)
    receipt = json.loads((output/'browser.json').read_text())
    if receipt.get('result') != 'passed' or receipt.get('apiMocked') is not False:
        raise AssertionError('Browser did not validate the installed API')


def request_quit(profile: Path, process=None) -> None:
    control = json.loads((profile/'instance-control.json').read_text())
    (profile/'stop-request.json').write_text(json.dumps({'token': control['token']}))
    if process:
        if process.wait(timeout=60) != 0:
            raise AssertionError('Application did not quit normally')
    end = time.monotonic()+60
    while (profile/'instance-control.json').exists() and time.monotonic() < end:
        time.sleep(.25)
    if (profile/'instance-control.json').exists():
        raise AssertionError('Application did not clean its control file')


def decode_recordings(profile: Path, ffmpeg: str, output: Path, *, prefix: list[str] | None = None,
                      app_profile: str | None = None) -> None:
    files = [p for p in (profile/'recordings').rglob('*') if p.suffix in {'.mp4', '.ts'}]
    if not files:
        raise AssertionError('No real recordings to decode')
    checked, audio_enabled, audio_disabled = [], [], []
    with (output/'decode.log').open('w') as log:
        for path in files:
            target = str(Path(app_profile)/path.relative_to(profile)) if app_profile else str(path)
            result = subprocess.run((prefix or [])+[ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', target, '-f', 'null', '-'],
                                    capture_output=True, text=True, check=True, timeout=60)
            log.write(result.stdout+result.stderr)
            if result.stderr.strip(): raise AssertionError('Recording decode reported errors: '+result.stderr)
            relative = path.relative_to(profile)
            ffprobe = str(Path(ffmpeg).with_name('ffprobe.exe' if ffmpeg.endswith('.exe') else 'ffprobe'))
            probe = subprocess.run((prefix or [])+[ffprobe, '-v', 'error', '-show_streams', '-of', 'json', target],
                                   capture_output=True, text=True, timeout=30, check=True)
            tracks = [s for s in json.loads(probe.stdout)['streams'] if s['codec_type'] == 'audio']
            if relative.parts[1] == 'qa-camera-1' and tracks:
                audio_enabled += tracks
            if relative.parts[1] == 'qa-camera-2': audio_disabled += tracks
            checked.append(str(relative))
    if not any(s.get('codec_name', '').startswith('pcm_s16') and str(s.get('sample_rate')) == '16000'
               and s.get('channels') == 1 for s in audio_enabled):
        raise AssertionError('No recording with the saved Standard 16-bit/16-kHz/mono audio')
    if audio_disabled: raise AssertionError('Audio-off camera recorded audio')
    (output/'recording-audio.json').write_text(json.dumps({'enabled_camera': audio_enabled, 'disabled_camera': audio_disabled}, indent=2)+'\n')
    (output/'decoded-recordings.json').write_text(json.dumps(checked, indent=2)+'\n')
