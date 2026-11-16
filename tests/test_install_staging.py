"""Exercise checksum staging without network access or a real OS installation."""
import hashlib
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from flinteye_app._version import VERSION, RELEASE_VERSION

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') and os.getuid() != 0, 'Linux normal-user shell installer')
class StagingTests(unittest.TestCase):
    def test_local_artifacts_use_checksum_and_never_download_or_install_on_host(self):
        with tempfile.TemporaryDirectory(prefix='FlintEye staging ') as directory:
            distribution = platform.freedesktop_os_release().get('ID', '')
            if distribution not in {'ubuntu', 'debian', 'raspbian', 'rocky', 'almalinux', 'rhel'}:
                self.skipTest('Automatic installer intentionally does not support this distribution')
            kind = 'rpm' if distribution in {'rocky', 'almalinux', 'rhel'} else 'deb'
            manager = 'dnf' if kind == 'rpm' else 'apt-get'
            root = Path(directory); tools = root/'tools'; tools.mkdir(); packages = root/'packages'; packages.mkdir()
            architecture = 'arm64' if os.uname().machine in {'aarch64', 'arm64'} else 'amd64'
            name = f'FlintEye-{VERSION}-linux-{architecture}.{kind}'
            package = packages/name; package.write_bytes(b'synthetic package, never executed')
            capture = root/'package-manager.txt'
            for command, script in {
                'pgrep': '#!/bin/sh\nexit 1\n',
                'curl': '#!/bin/sh\necho Unexpected network request >&2\nexit 99\n',
                'sudo': '#!/bin/sh\nprintf "%s\\n" "$@" > "$FLINTEYE_INSTALL_CAPTURE"\n',
            }.items():
                path = tools/command; path.write_text(script); path.chmod(0o755)
            env = {**os.environ, 'PATH': str(tools)+os.pathsep+os.environ['PATH'],
                   'DISPLAY': '', 'WAYLAND_DISPLAY': '', 'FLINTEYE_INSTALL_CAPTURE': str(capture)}
            for valid in (False, True):
                digest = hashlib.sha256(package.read_bytes()).hexdigest() if valid else '0'*64
                (packages/'SHA256SUMS').write_text(digest+'  '+name+'\n')
                result = subprocess.run(['bash', str(ROOT/'packaging/install.sh'), '--version', RELEASE_VERSION,
                    '--package-directory', str(packages), '--no-start'], env=env, capture_output=True, text=True, timeout=20)
                if valid:
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertIn(manager+'\ninstall\n-y\n', capture.read_text())
                    self.assertIn(name, capture.read_text())
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Checksum mismatch', result.stderr)
                    self.assertFalse(capture.exists())

