"""Verify the documented installer, Linux probe and shipped Japanese font."""
import errno
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from flinteye_app.orchestrator_uvc_probe import _probe_v4l2_devices
from flinteye_app.workers.multiview_to_rtsp import auto_default_font_path

ROOT = Path(__file__).resolve().parents[1]


class Preview10Regressions(unittest.TestCase):
    @unittest.skipUnless(shutil.which("bash"), "Bash is needed for the Linux installer test")
    def test_readme_command_requires_complete_download_runs_as_user_and_cleans_up(self):
        commands = []
        for readme in ("README.md", "README.ja.md"):
            commands.append(next(line for line in (ROOT / readme).read_text().splitlines()
                                 if line.startswith("bash -c ") and '"$script" --user' in line))
        self.assertEqual(commands[0], commands[1])
        self.assertRegex(commands[0], r"https://github\.com/noguhiro2002/FlintEye/releases/download/v\d+\.\d+\.\d+-preview\.\d+/install\.sh$")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            downloaded = directory / "download"
            marker = directory / "executed"
            (directory / "mktemp").write_text('#!/bin/sh\n: > "$FLINTEYE_TEST_DOWNLOAD"\nprintf "%s\\n" "$FLINTEYE_TEST_DOWNLOAD"\n')
            (directory / "curl").write_text("""#!/bin/sh
set -eu
[ "$1" = -fsSL ] && [ "$3" = -o ] && [ "$4" = "$FLINTEYE_TEST_DOWNLOAD" ]
printf '%s\\n' 'printf "%s" "$*" > "$FLINTEYE_TEST_MARKER"' > "$4"
exit "$FLINTEYE_TEST_CURL_STATUS"
""")
            for program in ("mktemp", "curl"):
                (directory / program).chmod(0o700)
            env = {**os.environ, "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                   "FLINTEYE_TEST_DOWNLOAD": str(downloaded), "FLINTEYE_TEST_MARKER": str(marker)}
            for status in (23, 0):
                with self.subTest(download_status=status):
                    result = subprocess.run(commands[0], shell=True, check=False, env={
                        **env, "FLINTEYE_TEST_CURL_STATUS": str(status),
                    }, cwd=directory, timeout=10)
                    self.assertEqual(result.returncode, status)
                    self.assertFalse(downloaded.exists())
                    self.assertEqual(marker.read_text() if marker.exists() else None, "--user" if not status else None)

    @unittest.skipIf(os.name == "nt", "Requires Linux-style video device symlinks")
    def test_linux_probe_distinguishes_capabilities_and_uses_unique_capture_alias(self):
        mode = {"width": 640, "height": 480, "fps": 30.0, "input_format": "mjpeg"}
        capabilities = {
            "video0": [mode], "video1": None, "video2": PermissionError(errno.EACCES, "denied"),
            "video3": OSError(errno.EBUSY, "busy"), "video4": [], "video5": FileNotFoundError(errno.ENOENT, "removed"),
        }

        def enumerate_modes(path):
            value = capabilities[path.name]
            if isinstance(value, OSError):
                raise value
            return value

        with tempfile.TemporaryDirectory() as tmp:
            devices = Path(tmp)
            by_id = devices / "v4l/by-id"
            by_id.mkdir(parents=True)
            for name in capabilities:
                (devices / name).touch()
            capture_alias = by_id / "usb-Capture-video-index0"
            capture_alias.symlink_to("../../video0")
            (by_id / "usb-Capture-video-index1").symlink_to("../../video1")
            for name in ("one", "two"):
                (by_id / name).symlink_to("../../video4")
            fallback = subprocess.CompletedProcess([], 1, "", "Compressed : mjpeg : Motion-JPEG : 320x240")
            with patch("flinteye_app.v4l2_modes.enumerate_modes", side_effect=enumerate_modes), \
                 patch("flinteye_app.orchestrator_uvc_probe._run_capture", return_value=fallback) as run:
                found = _probe_v4l2_devices("ffmpeg", 1, device_directory=devices)
            self.assertEqual([item["display_name"] for item in found], ["video0", "video2", "video3", "video4"])
            self.assertEqual([item["probe_state"] for item in found],
                             ["available", "permission_denied", "busy", "modes_unavailable"])
            self.assertEqual(found[0]["stable_device"], str(capture_alias))
            self.assertEqual(found[0]["recommended"], mode)
            self.assertIsNone(found[-1]["stable_device"])
            self.assertEqual(len(found[-1]["device_aliases"]), 2)
            self.assertEqual(run.call_count, 1, "Busy and denied devices should not cause capture retries")

    def test_bundled_font_renders_distinct_japanese_labels_in_ffmpeg(self):
        path = ROOT / "flinteye_app/fonts/NotoSansJP-Regular.otf"
        self.assertEqual(Path(auto_default_font_path() or ""), path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         "dff723ba59d57d136764a04b9b2d03205544f7cd785a711442d6d2d085ac5073")
        self.assertIn("SIL OPEN FONT LICENSE", (path.parent / "OFL.txt").read_text())
        ffmpeg = shutil.which("ffmpeg")
        self.assertIsNotNone(ffmpeg, "Install FFmpeg with drawtext for the distribution checks")

        def frame(label):
            return subprocess.check_output([
                ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=160x64",
                "-vf", f"drawtext=fontfile=flinteye_app/fonts/{path.name}:text={label}:fontsize=28:fontcolor=white:x=4:y=4",
                "-frames:v", "1", "-f", "framehash", "-",
            ], cwd=ROOT, timeout=10).splitlines()[-1]

        self.assertNotEqual(frame("試験"), frame("監視"))
