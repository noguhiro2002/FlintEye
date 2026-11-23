"""Exercise checksum staging without network access or a real OS installation."""
import hashlib
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from flinteye_app._version import VERSION, RELEASE_VERSION

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform in {'linux', 'darwin'} and os.getuid() != 0, 'Normal-user shell installer')
class DownloadStagingTests(unittest.TestCase):
    def test_write_failure_preserves_previous_installation_and_allows_retry(self):
        curl = shutil.which('curl')
        if not curl:
            self.skipTest('curl is not available')
        linux = sys.platform == 'linux'
        if linux and platform.freedesktop_os_release().get('ID') not in {'debian', 'ubuntu', 'raspbian'}:
            self.skipTest('DEB installer fault exercised on Debian-family CI')
        modes = ([], ['--user']) if linux else ([],)
        for mode in modes:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='FlintEye installer fault ') as directory:
                root = Path(directory).resolve()
                tools, staging, profile, home = [root/name for name in ('bin', 'staging', 'profile', 'home')]
                for folder in (tools, staging, profile, home):
                    folder.mkdir()
                recording = profile/'recordings/camera/clip.mp4'
                recording.parent.mkdir(parents=True)
                recording.write_bytes(b'retained recording')
                (profile/'runtime.json').write_text('retained settings')
                application = (home/'.local/opt/flinteye-user' if mode else root/'Applications/FlintEye.app')
                application.mkdir(parents=True)
                (application/'previous-app').write_text('retained executable')
                if mode:
                    (application/'.flinteye-user-install').write_text('old version')
                package = root/'synthetic-package'
                package.write_bytes(b'FlintEye synthetic bytes\n' * 4096)
                digest = hashlib.sha256(package.read_bytes()).hexdigest()
                capture = root/'install-called'
                commands = {
                    'pgrep': 'exit 1',
                    'sudo': 'touch "$FLINTEYE_QA_CAPTURE"',
                    'hdiutil': '[ "$1" != attach ] || { touch "$FLINTEYE_QA_CAPTURE"; exit 71; }',
                    'dpkg-deb': ('mkdir -p "$3/opt/flinteye"\n'
                                 'printf "#!/bin/sh\\nprintf \'%%s\\\\n\' \\"\\$FLINTEYE_QA_RELEASE\\"\\n" > "$3/opt/flinteye/FlintEye"\n'
                                 'chmod +x "$3/opt/flinteye/FlintEye"\ntouch "$FLINTEYE_QA_CAPTURE"'),
                    'curl': '''out='' head=0
while [ "$#" -gt 1 ]; do
  case "$1" in
    --output) out=$2; shift ;;
    --head) head=1 ;;
  esac
  shift
done
if [ "$head" = 1 ]; then
  printf 'HTTP/1.1 200 OK\\r\\nContent-Length: %s\\r\\n\\r\\n' "$FLINTEYE_QA_CONTENT_LENGTH"
elif [ "$(basename "$1")" = SHA256SUMS ]; then
  for platform in linux macos; do
    for arch in amd64 arm64; do
      for format in deb dmg; do
        printf '%s  FlintEye-%s-%s-%s.%s\\n' "$FLINTEYE_QA_DIGEST" "$FLINTEYE_QA_VERSION" "$platform" "$arch" "$format"
      done
    done
  done > "$out"
else
  if [ "$FLINTEYE_QA_FAIL_WRITE" = 1 ]; then
    ulimit -f 8
    trap '' XFSZ
  fi
  exec "$FLINTEYE_QA_CURL" --fail --silent --show-error --output "$out" "file://$FLINTEYE_QA_PACKAGE"
fi''',
                }
                for command, script in commands.items():
                    path = tools/command
                    path.write_text('#!/bin/bash\n'+script+'\n')
                    path.chmod(0o755)
                # Only the installer subprocess sees the synthetic login directory.
                env = {**os.environ, 'PATH': str(tools)+os.pathsep+os.environ['PATH'],
                       'HOME': str(home), 'TMPDIR': str(staging), 'FLINTEYE_DATA_DIR': str(profile),
                       'FLINTEYE_QA_PACKAGE': str(package).replace(' ', '%20'),
                       'FLINTEYE_QA_CAPTURE': str(capture), 'FLINTEYE_QA_DIGEST': digest,
                       'FLINTEYE_QA_RELEASE': RELEASE_VERSION, 'FLINTEYE_QA_VERSION': VERSION,
                       'FLINTEYE_QA_CURL': curl, 'FLINTEYE_QA_CONTENT_LENGTH': str(package.stat().st_size)}
                command = ['bash', str(ROOT/'packaging/install.sh'), '--version', RELEASE_VERSION, '--no-start',
                           *mode, *([] if linux else ['--install-directory', str(application.parent)])]
                def install(fail_write, length=env['FLINTEYE_QA_CONTENT_LENGTH']):
                    return subprocess.run(command, env={**env, 'FLINTEYE_QA_FAIL_WRITE': fail_write,
                                          'FLINTEYE_QA_CONTENT_LENGTH': length}, capture_output=True, text=True, timeout=30)

                result = install('0', '9000000000000000000')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('Package download needs', result.stderr)
                self.assertFalse(capture.exists())
                self.assertEqual(list(staging.iterdir()), [])
                result = install('1')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                for detail in ('curl 23', str(staging), 'user quota', 'file size limit', 'TMPDIR'):
                    self.assertIn(detail, result.stderr)
                self.assertFalse(capture.exists())
                self.assertEqual(list(staging.iterdir()), [])
                self.assertTrue((application/'previous-app').is_file())
                result = install('0')
                self.assertEqual(result.returncode, 0 if linux else 71, result.stdout+result.stderr)
                self.assertTrue(capture.exists())
                self.assertEqual(list(staging.iterdir()), [])
                self.assertEqual((profile/'runtime.json').read_text(), 'retained settings')
                self.assertEqual(recording.read_bytes(), b'retained recording')


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
                'rpm': '#!/bin/sh\n[ "$1" = -qp ] || exit 1\nprintf "0:1.2.0-1.x86_64"\n',
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
                    command = capture.read_text().splitlines()
                    expected = [manager, 'install', *(['--reinstall'] if kind == 'deb' else []), '-y']
                    self.assertEqual(command[:-1], expected)
                    self.assertEqual(Path(command[-1]).name, name)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Checksum mismatch', result.stderr)
                    self.assertFalse(capture.exists())
