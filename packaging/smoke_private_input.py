"""Check native FFmpeg/FFprobe input authentication without secrets in argv."""
from __future__ import annotations

import base64
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flinteye_app.flinteye_runtime import private_media_input_command


def main(ffmpeg: str = 'ffmpeg', ffprobe: str = 'ffprobe', mediamtx: str | None = None) -> None:
    with tempfile.TemporaryDirectory(prefix='flinteye-private-input-test-') as directory:
        sample = Path(directory) / 'sample.mp4'
        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'color=c=black:s=32x32:r=1', '-frames:v', '1', '-c:v', 'libx264',
                        '-movflags', '+faststart', str(sample)], check=True, capture_output=True)
        received = threading.Event()
        release = threading.Event()
        authorization = 'Basic ' + base64.b64encode(b'test-user:synthetic-test-password').decode()

        class AuthenticatedHandler(SimpleHTTPRequestHandler):
            def log_message(self, *_: object) -> None:
                pass

            def do_GET(self) -> None:
                if self.headers.get('Authorization') != authorization:
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Basic realm="synthetic camera"')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                received.set()
                if not release.wait(10):
                    self.send_error(503)
                    return
                super().do_GET()

        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(AuthenticatedHandler, directory=directory))
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        url = f"http://test-user:synthetic-test-password@127.0.0.1:{server.server_port}/sample.mp4?key=synthetic-query-'token"
        process = None
        try:
            command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', url,
                       '-frames:v', '1', '-f', 'null', '-']
            with private_media_input_command(command, url, force=True) as safe:
                process = subprocess.Popen(safe, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if not received.wait(8):
                    process.kill()
                    _, stderr = process.communicate(timeout=5)
                    raise AssertionError('Native FFmpeg did not authenticate: ' + stderr.decode(errors='replace'))
                cmdline = Path(f'/proc/{process.pid}/cmdline')
                if cmdline.exists():
                    assert b'synthetic-test-password' not in cmdline.read_bytes(), 'Password appeared in native argv'
                    assert b'synthetic-query-' not in cmdline.read_bytes(), 'Query token appeared in native argv'
                assert 'synthetic-test-password' not in ' '.join(safe)
                release.set()
                stdout, stderr = process.communicate(timeout=10)
                assert process.returncode == 0, stderr.decode(errors='replace')
            command = [ffprobe, '-v', 'error', '-show_entries', 'stream=codec_name', '-of', 'json', url]
            with private_media_input_command(command, url, force=True) as safe:
                result = subprocess.run(safe, capture_output=True, text=True, check=True, timeout=10)
                assert json.loads(result.stdout)['streams'][0]['codec_name'] == 'h264'
            print('PASS: native FFmpeg and FFprobe authenticated input; camera password absent from process argv')
        finally:
            release.set()
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
        if mediamtx:
            check_rtsp(ffmpeg, ffprobe, mediamtx, Path(directory))


def check_rtsp(ffmpeg: str, ffprobe: str, mediamtx: str, directory: Path) -> None:
    from flinteye_app.orchestrator_ip_camera_probe import probe_rtsp_timing
    from flinteye_app.orchestrator_snapshot import capture_snapshot_jpeg
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    config = directory / 'mediamtx.json'
    config.write_text(json.dumps({
        'logLevel': 'error', 'rtspAddress': f'127.0.0.1:{port}', 'rtspTransports': ['tcp'],
        'rtmp': False, 'hls': False, 'webrtc': False, 'srt': False, 'moq': False,
        'authInternalUsers': [
            {'user': 'any', 'ips': ['127.0.0.1'], 'permissions': [{'action': 'publish', 'path': 'camera'}]},
            {'user': 'test-user', 'pass': 'synthetic-test-password',
             'permissions': [{'action': 'read', 'path': 'camera'}]}],
        'paths': {'camera': {}}
    }), encoding='utf-8')
    log = (directory / 'rtsp.log').open('w+')
    media = subprocess.Popen([mediamtx, str(config)], stdout=log, stderr=log)
    publisher = None
    try:
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    break
            except OSError:
                if media.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
                time.sleep(.05)
        else:
            raise AssertionError('Synthetic RTSP server did not start')
        publisher = subprocess.Popen([
            ffmpeg, '-hide_banner', '-loglevel', 'error', '-re', '-f', 'lavfi', '-i',
            'testsrc=size=160x90:rate=10', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-tune', 'zerolatency', '-g', '10', '-f', 'rtsp', '-rtsp_transport', 'tcp',
            f'rtsp://127.0.0.1:{port}/camera'], stdout=log, stderr=log)
        time.sleep(1)
        url = f'rtsp://test-user:synthetic-test-password@127.0.0.1:{port}/camera'
        for timestamp_options in (['-fflags', '+genpts+nobuffer'], ['-use_wallclock_as_timestamps', '1', '-fflags', '+genpts']):
            command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-rtsp_transport', 'tcp',
                       '-rw_timeout', '5000000', *timestamp_options, '-i', url,
                       '-t', '1', '-c:v', 'copy', '-f', 'mpegts', '-']
            with private_media_input_command(command, url, force=True) as safe:
                process = subprocess.Popen(safe, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    time.sleep(.3)
                    cmdline = Path(f'/proc/{process.pid}/cmdline')
                    if cmdline.exists():
                        assert b'synthetic-test-password' not in cmdline.read_bytes()
                    stdout, stderr = process.communicate(timeout=20)
                    assert process.returncode == 0, stderr.decode(errors='replace')
                    assert len(stdout) > 188 and len(stdout) % 188 == 0, 'RTSP relay did not output MPEG-TS packets'
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        probe = probe_rtsp_timing(url, ffprobe_bin=ffprobe, duration_sec=1, timeout_sec=20)
        assert probe['codec'] == 'h264' and probe['frame_count'] >= 2, probe
        assert probe['timestamp_healthy'], probe
        jpeg = capture_snapshot_jpeg(ffmpeg_bin=ffmpeg, rtsp_url=url)
        assert jpeg.startswith(b'\xff\xd8'), 'RTSP snapshot was not a JPEG'
        print('PASS: authenticated RTSP source/wallclock relay, timing probe and snapshot; password absent from argv')
    finally:
        for process in (publisher, media):
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--ffprobe', default='ffprobe')
    parser.add_argument('--mediamtx')
    args = parser.parse_args()
    main(args.ffmpeg, args.ffprobe, args.mediamtx)
