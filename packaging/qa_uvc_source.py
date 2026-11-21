"""Linux source QA using real workers and a generated video capture input."""
from __future__ import annotations

from pathlib import Path
import sys
import time
from unittest.mock import patch

DEVICE = '/dev/flinteye-qa-video'
NAME = 'FlintEye QA USB camera'
MODE = {'width': 320, 'height': 180, 'fps': 10}


def synthetic_worker():
    from flinteye_app.workers import uvc_to_rtsp

    def capture_input(args, driver):
        if driver != 'v4l2' or args.device != DEVICE:
            raise ValueError('Refusing to open a physical capture device in QA')
        pattern = (f'testsrc2=size={args.width}x{args.height}:rate={args.fps:g},'
                   'drawbox=x=0:y=ih/3:w=iw:h=ih/3:color=blue:t=fill')
        return ['-re', '-f', 'lavfi', '-i', pattern]

    # Replace just the capture arguments in this test process.
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    with patch.object(uvc_to_rtsp, 'build_input_args', side_effect=capture_input):
        raise SystemExit(uvc_to_rtsp.main())


def synthetic_application():
    from flinteye_app.cli import entrypoint
    from flinteye_app.orchestrator_supervisor import worker_command

    profile = Path(sys.argv[sys.argv.index('--data-dir') + 1])
    if not (profile / '.flinteye-qa-owned').is_file() or '--disable-lan' not in sys.argv:
        raise SystemExit('Use a disposable source lifecycle profile for UVC QA')
    fixture = {'driver': 'v4l2', 'ffmpeg_bin': 'ffmpeg', 'devices': [{
        'device_id': 'flinteye-qa-usb', 'display_name': NAME, 'driver': 'v4l2',
        'ffmpeg_device': DEVICE, 'ffmpeg_device_index': DEVICE, 'modes': [MODE], 'recommended': MODE,
    }]}

    def command(name, python_bin=None):
        if name == 'uvc_to_rtsp':
            return [sys.executable, str(Path(__file__).resolve()), '--qa-uvc-worker']
        return worker_command(name, python_bin)

    def pass_to_test_browser(url):
        (profile/'qa-browser-url.txt').write_text(url, encoding='utf-8')
        return True

    def wait_for_quit(_url, server, _root, _monitoring, _open_browser):
        while not server.should_exit:
            time.sleep(.1)

    # Use the real desktop launcher and setup page with the lifecycle's browser.
    with (patch('flinteye_app.cli.desktop_available', return_value=True),
          patch('flinteye_app.cli.enable_autostart', return_value=True),
          patch('flinteye_app.flinteye_desktop.run_desktop', side_effect=wait_for_quit),
          patch('webbrowser.open', side_effect=pass_to_test_browser),
          patch('flinteye_app.orchestrator_uvc_probe.probe_uvc_devices', return_value=fixture),
          patch('flinteye_app.orchestrator_supervisor.worker_command', side_effect=command)):
        entrypoint()


if __name__ == '__main__':
    if sys.argv[1:2] == ['--qa-uvc-worker']:
        synthetic_worker()
    else:
        synthetic_application()
