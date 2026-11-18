from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from flinteye_app.orchestrator_models import CameraAudioConfig, NetworkAccessConfig, RuntimeConfig
from flinteye_app.orchestrator_uvc_probe import _parse_dshow_modes, _parse_avfoundation_modes, _parse_v4l2_modes
from flinteye_app.rtsps_relay import prepare_relay, rotate_password
from flinteye_app.orchestrator_uvc_probe import avfoundation_camera_device, probe_uvc_devices, UvcProbeError

MAC_DEVICES = '''[AVFoundation] AVFoundation video devices:
[AVFoundation] [0] FaceTime HD Camera
[AVFoundation] [1] OBS Virtual Camera
[AVFoundation] [2] Capture screen 0
[AVFoundation] [3] Capture screen 1
[AVFoundation] AVFoundation audio devices:
[AVFoundation] [0] MacBook Microphone
'''


class CameraCapabilitiesTests(unittest.TestCase):
    def test_mac_discovery_never_opens_a_screen_input(self):
        def capture(cmd, timeout_sec):
            if '-list_devices' in cmd:
                return subprocess.CompletedProcess(cmd, 1, '', MAC_DEVICES)
            self.assertIn(cmd[cmd.index('-i') + 1],
                          {'FaceTime HD Camera:none', 'OBS Virtual Camera:none'})
            return subprocess.CompletedProcess(cmd, 1, '', '1280x720@[1 30]')
        with patch('flinteye_app.orchestrator_uvc_probe._run_capture', side_effect=capture) as run:
            result = probe_uvc_devices(platform_name='darwin')
        self.assertEqual([item['display_name'] for item in result['devices']],
                         ['FaceTime HD Camera', 'OBS Virtual Camera'])
        self.assertEqual(run.call_count, 3)
        self.assertEqual(result['devices'][0]['recommended']['fps'], 30)

    def test_mac_saved_indices_cannot_fall_through_to_screen_capture(self):
        with patch('flinteye_app.orchestrator_uvc_probe._run_capture', return_value=
                   subprocess.CompletedProcess([], 1, '', MAC_DEVICES)):
            self.assertEqual(avfoundation_camera_device('ffmpeg', '0:none'), 'FaceTime HD Camera:none')
            self.assertEqual(avfoundation_camera_device('ffmpeg', 'OBS Virtual Camera:none'), 'OBS Virtual Camera:none')
            for selector in ('2:none', '3:none', 'Capture screen 0:none', 'Removed camera:none'):
                with self.subTest(selector=selector), self.assertRaises(UvcProbeError):
                    avfoundation_camera_device('ffmpeg', selector)

    def test_mac_numeric_camera_name_is_not_reinterpreted_as_a_display_index(self):
        listing = MAC_DEVICES.replace('FaceTime HD Camera', '2K USB Camera')
        with patch('flinteye_app.orchestrator_uvc_probe._run_capture', return_value=
                   subprocess.CompletedProcess([], 1, '', listing)):
            with self.assertRaisesRegex(UvcProbeError, 'leading number'):
                avfoundation_camera_device('ffmpeg', '0:none')

    def test_linux_formats_do_not_turn_widths_into_frame_rates(self):
        modes = _parse_v4l2_modes(
            '[video4linux2] Compressed: mjpeg : Motion-JPEG : 640x480 160x120 1280x720 1920x1080'
        )
        self.assertEqual({(mode["width"], mode["height"]) for mode in modes},
                         {(640, 480), (160, 120), (1280, 720), (1920, 1080)})
        self.assertTrue(all("fps" not in mode for mode in modes))

    def test_native_desktop_modes_keep_fractional_rates_and_formats(self):
        windows = _parse_dshow_modes('vcodec=mjpeg  min s=1280x720 fps=29.97 max s=1920x1080 fps=60')
        self.assertEqual(windows[0], {"width": 1280, "height": 720, "fps": 29.97, "input_format": "codec:mjpeg"})
        self.assertEqual(windows[1]["width"], 1920)
        self.assertEqual([mode["fps"] for mode in _parse_avfoundation_modes(
            '1920x1080@[29.970030 59.940060]')], [29.970030, 59.940060])

    def test_old_camera_profile_keeps_audio_off(self):
        config = RuntimeConfig.model_validate({"cameras": [{"id": "camera", "path": "camera", "type": "uvc"}]})
        self.assertFalse(config.cameras[0].audio.enabled)
        high = CameraAudioConfig(enabled=True, preset="high")
        self.assertEqual((high.sample_rate, high.bit_depth, high.channels), (48000, 24, 1))


class SecureRelayTests(unittest.TestCase):
    def test_relay_uses_selected_network_only_and_has_no_endpoint_to_publish(self):
        network = NetworkAccessConfig(enabled=True, address="100.96.0.4",
                                      allowed_subnets=["100.96.0.8/32"], rtsp_enabled=True)
        config = RuntimeConfig.model_validate({
            "mediamtx": {"control_mode": "direct", "managed": {"enabled": True},
                         "direct": {"command": ["mediamtx", "main.yml"]}},
            "cameras": [{"id": "cam", "path": "cam", "type": "uvc"},
                        {"id": "old", "path": "old", "type": "uvc", "enabled": False}],
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            password = rotate_password(root)
            command, _ = prepare_relay(root, network, config)
            config_text = Path(command[1]).read_text()
            self.assertNotIn(password, config_text)
            relay = json.loads(config_text)
            self.assertEqual(relay["rtspsAddress"], "100.96.0.4:8322")
            self.assertEqual(relay["rtspEncryption"], "strict")
            self.assertEqual(relay["authInternalUsers"][0]["ips"], ["100.96.0.8/32"])
            self.assertEqual(relay["authInternalUsers"][0]["permissions"], [{"action": "read", "path": "cam"}])
            self.assertEqual(relay["paths"]["cam"]["source"], "rtsp://127.0.0.1:8554/cam")
            self.assertEqual(set(relay["paths"]), {"cam"})
