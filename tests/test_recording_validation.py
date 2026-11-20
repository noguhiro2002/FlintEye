"""Regression cases for footage that used to pass installed application checks."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'packaging'))
from lifecycle_common import decode_recordings


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and FFprobe needed')
class RecordingValidationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.ffmpeg = shutil.which('ffmpeg')

    def clip(self, stream, inputs):
        path = self.root/'recordings'/stream/'2026-01-01'/'clip.mp4'
        path.parent.mkdir(parents=True)
        subprocess.run([self.ffmpeg, '-v', 'error', *inputs, '-t', '0.5', '-threads', '1',
                        '-c:v', 'libx264', '-c:a', 'pcm_s16be', '-f', 'mov', str(path)],
                       check=True, timeout=20)
        return path

    def test_audio_only_is_not_footage(self):
        self.clip('qa-camera-1', ['-f', 'lavfi', '-i', 'sine=sample_rate=16000'])
        with self.assertRaisesRegex(AssertionError, 'one video track'):
            decode_recordings(self.root, self.ffmpeg, self.root)

    def test_audio_from_other_camera_fails_even_with_correct_format(self):
        self.clip('qa-camera-1', ['-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10',
                                 '-f', 'lavfi', '-i', 'sine=sample_rate=16000:frequency=880'])
        with self.assertRaisesRegex(AssertionError, 'Wrong camera audio tone'):
            decode_recordings(self.root, self.ffmpeg, self.root)

    def test_missing_camera_and_duplicate_tile_fail(self):
        red = 'testsrc2=s=160x90:r=10,drawbox=x=0:y=ih/3:w=iw:h=ih/3:color=red:t=fill'
        blue = red.replace('red', 'blue')
        self.clip('qa-camera-1', ['-f', 'lavfi', '-i', red, '-f', 'lavfi', '-i', 'sine=sample_rate=16000'])
        with self.assertRaisesRegex(AssertionError, 'Missing moving footage.*qa-camera-2'):
            decode_recordings(self.root, self.ffmpeg, self.root)
        self.clip('qa-camera-2', ['-f', 'lavfi', '-i', blue])
        self.clip('multiview_1', ['-f', 'lavfi', '-i', f'{red},split[a][b];[a][b]hstack'])
        with self.assertRaisesRegex(AssertionError, 'Wrong camera marker'):
            decode_recordings(self.root, self.ffmpeg, self.root)
