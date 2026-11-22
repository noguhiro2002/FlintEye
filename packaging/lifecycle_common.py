"""Real media/browser checks shared by native, source and container installers."""
from __future__ import annotations

from array import array
from contextlib import contextmanager
import json
import math
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
        value = json.loads(runtime.read_text(encoding='utf-8'))
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
                      'layout': {'canvas_width': 640, 'canvas_height': 360, 'grid_columns': 2},
                      'quality': {'gop': 5},
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
    runtime.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
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
        process = subprocess.Popen(prefix+command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=os.name != 'nt')
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
        # Pre-encode both signals so the independent fixture publishers can
        # keep up on runners that are also decoding, recording and compositing.
        for i, color in enumerate(('red', 'blue'), start=1):
            clip = str(Path(app_directory)/f'qa-input-{i}.mp4')
            pattern = f'testsrc2=size=320x180:rate=10,drawbox=x=0:y=ih/3:w=iw:h=ih/3:color={color}:t=fill'
            with (directory/f'fixture-encode-{i}.log').open('w', encoding='utf-8') as log:
                subprocess.run(prefix+[ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', pattern, '-f', 'lavfi', '-i', f'sine=frequency={i*440}:sample_rate=48000',
                    '-t', '4', '-c:v', 'libx264', '-threads', '1', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                    '-g', '10', '-c:a', 'aac', '-b:a', '64k', '-ac', '1', clip],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, check=True, timeout=30)
            start([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'warning', '-stream_loop', '-1', '-re',
                   '-i', clip, '-c', 'copy', '-rtsp_transport', 'tcp', '-f', 'rtsp',
                   f'rtsp://127.0.0.1:{port}/qa-input-{i}'], f'fixture-publisher-{i}.log')
        time.sleep(2)
        if any(p.poll() is not None for p in children):
            raise RuntimeError('Synthetic media publisher failed; inspect fixture logs')
        yield f'rtsp://127.0.0.1:{port}'
        if any(p.poll() is not None for p in children):
            raise RuntimeError('Synthetic media publisher stopped during validation; inspect fixture logs')
    finally:
        for process in reversed(children): stop_process(process)
        for log in logs: log.close()


def browser_check(url: str, profile: Path, output: Path, release: str, commit: str,
                  fixture_url: str, *, retained: bool = False, synthetic_uvc: bool = False, onvif_url: str | None = None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    command = ['node', str(ROOT/'frontend/tests/installed.mjs'), '--url', url, '--profile', str(profile),
               '--output', str(output), '--release', release, '--fixture-url', fixture_url]
    if commit: command += ['--commit', commit]
    if retained: command += ['--retained']
    if synthetic_uvc: command += ['--synthetic-uvc']
    if onvif_url: command += ['--onvif-url', onvif_url]
    log_path = output/'browser.log'
    with log_path.open('w', encoding='utf-8') as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=420)
    if completed.returncode:
        raise AssertionError(f'Installed browser checks failed (exit {completed.returncode}):\n'
                             + log_path.read_text(encoding='utf-8', errors='replace')[-2500:])
    receipt = json.loads((output/'browser.json').read_text(encoding='utf-8'))
    if receipt.get('result') != 'passed' or receipt.get('apiMocked') is not False:
        raise AssertionError('Browser did not validate the installed API')


def request_quit(profile: Path, process=None) -> None:
    control = json.loads((profile/'instance-control.json').read_text(encoding='utf-8'))
    (profile/'stop-request.json').write_text(json.dumps({'token': control['token']}), encoding='utf-8')
    if process:
        if process.wait(timeout=60) != 0:
            raise AssertionError('Application did not quit normally')
    end = time.monotonic()+60
    while (profile/'instance-control.json').exists() and time.monotonic() < end:
        time.sleep(.25)
    if (profile/'instance-control.json').exists():
        raise AssertionError('Application did not clean its control file')


def verify_camera_tone(samples: array, relative: Path) -> bool:
    """A short or silent boundary is inconclusive. The other fixture's tone fails."""
    found = False
    for start in range(0, len(samples)-1599, 1600):
        window = samples[start:start+1600]
        energy = sum(v*v for v in window)
        if energy < len(window)*256**2:
            continue
        # Goertzel energy at both known fixture frequencies. Partial windows,
        # encoder delay and quiet segment edges should not imply swapped audio.
        powers = []
        for frequency in (440, 880):
            coefficient = 2*math.cos(2*math.pi*frequency/16000)
            previous = older = 0.
            for sample in window:
                value = sample + coefficient*previous - older
                older, previous = previous, value
            powers.append(previous**2 + older**2 - coefficient*previous*older)
        if powers[1] > powers[0] and powers[1] > 0.1*len(window)*energy:
            raise AssertionError(f'Wrong camera audio tone in {relative}: 880 Hz')
        if powers[0] > 0.25*len(window)*energy:
            found = True
    return found


def decode_recordings(profile: Path, ffmpeg: str, output: Path, *, prefix: list[str] | None = None,
                      app_profile: str | None = None) -> None:
    streams = {'qa-camera-1': ('red',), 'qa-camera-2': ('blue',), 'multiview_1': ('red', 'blue')}
    progressing = set()
    checked, audio_enabled = [], []
    verified_tone = False
    ffprobe = str(Path(ffmpeg).with_name('ffprobe.exe' if ffmpeg.endswith('.exe') else 'ffprobe'))
    with (output/'decode.log').open('w') as log:
        for path in sorted((profile/'recordings').rglob('*')):
            if path.suffix not in {'.mp4', '.ts'}:
                continue
            relative = path.relative_to(profile)
            stream = relative.parts[1]
            if stream not in streams:
                raise AssertionError(f'Unexpected recording source: {relative}')
            target = str(Path(app_profile)/relative) if app_profile else str(path)
            probe = subprocess.run((prefix or [])+[ffprobe, '-v', 'error', '-show_streams', '-of', 'json', target],
                                   capture_output=True, text=True, timeout=30, check=True)
            tracks = json.loads(probe.stdout)['streams']
            if sum(t['codec_type'] == 'video' for t in tracks) != 1:
                raise AssertionError(f'Expected one video track: {relative}')
            audio = [t for t in tracks if t['codec_type'] == 'audio']
            if stream == 'qa-camera-2' and audio:
                raise AssertionError(f'Audio-off camera recorded audio: {relative}')
            if stream == 'qa-camera-1' and audio:
                if len(audio) != 1 or not (audio[0]['codec_name'].startswith('pcm_s16') and
                                          audio[0]['sample_rate'] == '16000' and audio[0]['channels'] == 1):
                    raise AssertionError(f'Unexpected Standard recording audio: {relative}')
                audio_enabled.extend(audio)
                # The two fixture microphones emit 440 and 880 Hz respectively.
                # Check complete, audible 100-ms windows; segment edges may be silent.
                pcm = subprocess.run((prefix or [])+[ffmpeg, '-nostdin', '-v', 'error', '-xerror',
                                     '-i', target, '-map', '0:a:0', '-t', '1', '-f', 's16le', '-'],
                                     capture_output=True, check=True, timeout=30)
                samples = array('h')
                samples.frombytes(pcm.stdout)
                if sys.byteorder == 'big':
                    samples.byteswap()
                if verify_camera_tone(samples, relative):
                    verified_tone = True

            # Decode all tracks to completion, and inspect actual video pixels. The center
            # stripe labels the camera while the moving test pattern around it proves progress.
            result = subprocess.run((prefix or [])+[ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', target,
                                    '-map', '0:v:0', '-vf', 'scale=32:16', '-pix_fmt', 'rgb24',
                                    '-threads', '1', '-fps_mode', 'passthrough', '-f', 'rawvideo', 'pipe:1',
                                    '-map', '0:v', '-map', '0:a?', '-f', 'null', '-'],
                                    capture_output=True, timeout=60)
            if result.returncode or result.stderr:
                raise AssertionError(f'{relative}: {result.stderr.decode(errors="replace")}')
            size = 32*16*3
            pixels = result.stdout
            if not pixels or len(pixels) % size:
                raise AssertionError(f'No complete video frames: {relative}')
            first_marked = None
            for offset in range(0, len(pixels), size):
                frame = pixels[offset:offset+size]
                markers = []
                for x in ([8, 24] if stream == 'multiview_1' else [16]):
                    i = (8*32+x)*3
                    r, g, b = frame[i:i+3]
                    markers.append('red' if r > max(g,b)+80 else 'blue' if b > max(r,g)+80 else None)
                if tuple(markers) != streams[stream]:
                    # The compositor draws a placeholder until each camera connects.
                    if stream == 'multiview_1' and all(m is None or m == want for m, want in zip(markers, streams[stream])):
                        continue
                    raise AssertionError(f'Wrong camera marker in {relative}: {markers}')
                if first_marked is None:
                    first_marked = frame
                elif frame != first_marked:
                    progressing.add(stream)
            log.write(f'{relative.as_posix()}: {len(pixels)//size} video frames\n')
            checked.append(relative.as_posix())
    if missing := streams.keys()-progressing:
        raise AssertionError(f'Missing moving footage with expected camera markers: {sorted(missing)}')
    if not audio_enabled or not verified_tone:
        raise AssertionError('No recording with the saved Standard 16-bit/16-kHz/mono audio')
    (output/'recording-audio.json').write_text(json.dumps({'enabled_camera': audio_enabled, 'disabled_camera': []}, indent=2)+'\n')
    (output/'decoded-recordings.json').write_text(json.dumps(checked, indent=2)+'\n')
