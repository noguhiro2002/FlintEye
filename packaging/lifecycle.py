"""Install, run the real API/browser workflow, remove, and reinstall in isolation.

Native/system/Compose adapters require a disposable CI runner (or an explicit
--disposable assertion AND empty target locations). Source tests use only a new
temporary snapshot. No adapter may delete an existing installation or profile.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import venv

from lifecycle_common import (ROOT, browser_check, decode_recordings, media_fixture,
                              request_quit, seed_runtime, stop_process, wait_closed, wait_http)
from lifecycle_report import LINUX_USER_METHODS, Report, requires_preview_7_checks
from qa_onvif import onvif_fixture
from release_lib import digest, release_identity, version


class ApprovalRequired(RuntimeError):
    pass


def owned_profile(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError('Refusing an existing profile: '+str(path))
    path.mkdir(parents=True)
    (path/'.flinteye-qa-owned').write_text('Synthetic lifecycle data; no user recordings.\n')


def remove_owned_profile(path: Path) -> None:
    if path.is_symlink() or not (path/'.flinteye-qa-owned').is_file():
        raise RuntimeError('Refusing to remove an unowned profile')
    shutil.rmtree(path)


def default_profile() -> Path:
    if os.name == 'nt': return Path(os.environ['LOCALAPPDATA'])/'FlintEye'
    if sys.platform == 'darwin': return Path.home()/'Library/Application Support/FlintEye'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))/'flinteye'


class Adapter:
    def __init__(self, args, directory: Path, report: Report):
        self.args, self.directory, self.report = args, directory, report
        self.profile = directory/'profile'
        self.app_profile = str(self.profile)
        self.process = None
        self.prefix = []
        self.executable = None
        self.media = self.ffmpeg = ''
        self.port = None
        self.logs = []
        self.fixture_prefix = []
        self.fixture_app_directory = None

    def command(self, command, *, name='installation.log', timeout=300, env=None, check=True):
        with (self.report.output/name).open('a', encoding='utf-8') as log:
            return subprocess.run([str(x) for x in command], stdout=log, stderr=subprocess.STDOUT,
                                  env=env, timeout=timeout, check=check)

    def launch(self, command, *, env=None):
        log = (self.report.output/'application.log').open('a', encoding='utf-8'); self.logs.append(log)
        self.process = subprocess.Popen([str(x) for x in command], stdout=log, stderr=log,
                                        cwd=self.directory, env=env, start_new_session=os.name != 'nt')

    def prepare_profile(self):
        self.port = seed_runtime(self.profile, self.app_profile, self.media)
        return f'http://127.0.0.1:{self.port}'

    def quit(self):
        request_quit(self.profile, self.process)
        self.check_closed()

    def check_closed(self):
        config = json.loads((self.profile/'runtime.json').read_text(encoding='utf-8'))
        wait_closed(self.port)
        for key in ('rtspAddress', 'webrtcAddress', 'apiAddress'):
            wait_closed(int(config['mediamtx']['managed']['global'][key].rsplit(':', 1)[1]))

    def sync_profile(self):
        """Container adapters copy synthetic data out for the host-side verifier."""

    def cleanup(self):
        if (self.profile/'.flinteye-qa-owned').is_file(): remove_owned_profile(self.profile)

    def finish(self):
        if self.process: stop_process(self.process)
        for log in self.logs: log.close()
        logs = self.profile/'logs'
        if logs.is_dir():
            target = self.report.output/'application-logs'
            target.mkdir(exist_ok=True)
            for path in logs.rglob('*.log'):
                relative = path.relative_to(logs)
                copy = target/relative; copy.parent.mkdir(parents=True, exist_ok=True)
                # QA profiles contain only synthetic media and credentials.
                copy.write_text(path.read_text(encoding='utf-8', errors='replace')[-100_000:], encoding='utf-8')
        for name in ('uninstall-failure.txt', 'uninstall.log', 'last-stop-result.json', 'last-monitoring-stop.json'):
            path = self.profile/name
            if path.is_file():
                (self.report.output/name).write_text(
                    path.read_text(encoding='utf-8', errors='replace')[-100_000:], encoding='utf-8')

    def verify(self):
        result = subprocess.run([str(self.executable), '--version'], capture_output=True, text=True, timeout=30)
        if result.returncode or result.stdout.strip() != self.args.release:
            raise RuntimeError('Installed executable has the wrong embedded preview: '+result.stdout+result.stderr)


class Source(Adapter):
    def __init__(self, *args):
        super().__init__(*args)
        self.source = self.directory/'source'
        self.environment = self.directory/'venv'
        self.python = self.args.python
        owned_profile(self.profile)
        media_dir = self.args.media_directory.resolve()
        self.media = str(media_dir/('mediamtx.exe' if os.name == 'nt' else 'mediamtx'))
        self.ffmpeg = str(media_dir/('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'))
        if not Path(self.media).is_file() or not Path(self.ffmpeg).is_file():
            raise RuntimeError('Supply the native verified media directory with --media-directory')

    def install(self):
        self.source.mkdir()
        for name in ('flinteye.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'requirements.txt'):
            shutil.copy2(ROOT/name, self.source/name)
        shutil.copytree(ROOT/'flinteye_app', self.source/'flinteye_app', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT/'frontend/dist', self.source/'frontend/dist')
        shutil.copytree(ROOT/'images/icons', self.source/'images/icons')
        if self.args.synthetic_uvc:
            shutil.copy2(ROOT/'packaging/qa_uvc_source.py', self.source/'qa_uvc_source.py')
        (self.source/'build-info.json').write_text(json.dumps({'commit': self.args.commit or None, 'dirty': False}))
        if not self.python:
            venv.EnvBuilder(with_pip=True).create(self.environment)
            self.python = str(self.environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
            command = [self.python, '-m', 'pip', 'install', '-c', str(ROOT/'packaging/constraints.txt'), '-r', str(ROOT/'requirements.txt')]
            if (ROOT/'vendor/crypto-wheels').exists(): command += ['--find-links', str(ROOT/'vendor/crypto-wheels')]
            self.command(command, timeout=600)
        self.executable = self.source/'flinteye.py'

    def verify(self):
        result = subprocess.run([self.python, str(self.executable), '--version'], capture_output=True, text=True, check=True, timeout=30)
        if result.stdout.strip() != self.args.release: raise RuntimeError('Wrong source snapshot release')

    def start(self):
        env = {**os.environ, 'PATH': str(Path(self.ffmpeg).parent)+os.pathsep+os.environ.get('PATH', '')}
        for name in ('FLINTEYE_LAN_ADDRESS', 'FLINTEYE_LAN_SOURCES', 'FLINTEYE_CONTAINER_BRIDGE'):
            env.pop(name, None)
        script = self.source/'qa_uvc_source.py' if self.args.synthetic_uvc else self.executable
        mode = '--disable-lan' if self.args.synthetic_uvc else '--headless'
        self.launch([self.python, script, mode, '--data-dir', self.profile], env=env)
        wait_http(f'http://127.0.0.1:{self.port}', self.process)

    def uninstall(self):
        shutil.rmtree(self.source)
        if self.environment.exists():
            shutil.rmtree(self.environment)
            self.python = None
        if self.source.exists() or self.environment.exists(): raise AssertionError('Source environment survived removal')


class Native(Adapter):
    def __init__(self, *args):
        super().__init__(*args)
        self.installer_process = self.open_process = None
        if os.environ.get('GITHUB_ACTIONS') != 'true' and not self.args.disposable:
            raise RuntimeError('Native removal tests require a disposable runner or --disposable in a fresh QA account')
        self.inputs = self.args.artifact_directory.resolve()
        self.profile = default_profile()
        self.app_profile = str(self.profile)
        if any(os.environ.get(name) for name in ('FLINTEYE_DATA_DIR', 'FLINTEYE_LAN_ADDRESS', 'FLINTEYE_LAN_SOURCES', 'FLINTEYE_CONTAINER_BRIDGE')):
            raise RuntimeError('Native QA requires a fresh account without FlintEye data/network environment overrides')
        if sys.platform == 'darwin':
            self.app = Path.home()/'Applications/FlintEye.app'
            for path in (self.app, self.app.with_name('FlintEye.previous.app'), Path('/Applications/FlintEye.app')):
                if path.exists() or path.is_symlink(): raise RuntimeError('Refusing an existing app: '+str(path))
            if (Path.home()/'Library/LaunchAgents/community.flinteye.plist').exists():
                raise RuntimeError('Refusing an existing macOS startup registration')
            self.executable = self.app/'Contents/MacOS/FlintEye'
            binaries = self.app/'Contents/Frameworks/bin'
        elif os.name == 'nt':
            self.app = Path(os.environ['LOCALAPPDATA'])/'Programs/FlintEye'
            if self.app.exists(): raise RuntimeError('Refusing an existing Windows installation')
            # Never overwrite an existing uninstall or autostart registration.
            import winreg
            for key in (r'Software\Microsoft\Windows\CurrentVersion\Uninstall\FlintEye.Community_is1',):
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key): raise RuntimeError('An installation is already registered')
                except FileNotFoundError: pass
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                    winreg.QueryValueEx(key, 'FlintEye')
                raise RuntimeError('Refusing an existing autostart registration')
            except FileNotFoundError: pass
            self.executable = self.app/'FlintEye.exe'
            binaries = self.app/'_internal/bin'
        else:
            self.app = Path('/opt/flinteye')
            if self.app.exists(): raise RuntimeError('Refusing an existing Linux package')
            self.executable = self.app/'FlintEye'
            binaries = self.app/'_internal/bin'
        self.media = str(binaries/('mediamtx.exe' if os.name == 'nt' else 'mediamtx'))
        self.ffmpeg = str(binaries/('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'))
        owned_profile(self.profile)

    def package(self, suffix):
        arch = 'arm64' if platform.machine().lower() in {'arm64', 'aarch64'} else 'amd64'
        target = 'macos' if sys.platform == 'darwin' else 'windows' if os.name == 'nt' else 'linux'
        package = self.inputs/f'FlintEye-{version()}-{target}-{arch}{suffix}'
        sums = dict(line.split('  ', 1)[::-1] for line in (self.inputs/'SHA256SUMS').read_text(encoding='utf-8').splitlines())
        if sums.get(package.name) != digest(package): raise RuntimeError('Installer checksum mismatch')
        build = json.loads((self.inputs/'validation-build.json').read_text(encoding='utf-8'))
        if build.get('release') != self.args.release or (self.args.commit and build.get('commit') != self.args.commit):
            raise RuntimeError('Validation artifacts belong to another release/commit')
        if build.get('packages', {}).get(package.name) != digest(package): raise RuntimeError('Installer provenance mismatch')
        script = 'install.ps1' if os.name == 'nt' else 'install.sh'
        if self.args.method.endswith('script') and sums.get(script) != digest(self.inputs/script):
            raise RuntimeError('Installer script checksum mismatch')
        return package

    def install(self):
        script = self.args.method.endswith('script')
        if sys.platform == 'darwin':
            package = self.package('.dmg')
            if script:
                # Installation itself tests its normal open call, not --no-start.
                self.prepare_profile()
                log = (self.report.output/'installation.log').open('a', encoding='utf-8'); self.logs.append(log)
                self.installer_process = subprocess.Popen(['bash', str(self.inputs/'install.sh'),
                    *([] if self.args.online else ['--package-directory', str(self.inputs)])],
                    stdout=log, stderr=log, start_new_session=True)
                end = time.monotonic()+180
                # The script atomically installs the complete app before asking
                # Launch Services to open it. That request may await OS consent.
                while time.monotonic() < end:
                    installed = (self.report.output/'installation.log').read_text(encoding='utf-8', errors='replace')
                    if f'files installed at: {self.app}' in installed and self.executable.is_file(): break
                    if self.installer_process.poll() is not None:
                        raise RuntimeError(f'Installer did not complete the app copy (exit {self.installer_process.returncode})')
                    time.sleep(.2)
                else: raise TimeoutError('Installer did not finish copying the application')
            else:
                mount = self.directory/'DMG mount'; mount.mkdir(exist_ok=True)
                self.command(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', mount, package])
                try:
                    self.app.parent.mkdir(parents=True, exist_ok=True)
                    self.command(['ditto', mount/'FlintEye.app', self.app])
                    # Reproduce a browser download's first-run policy, never remove it.
                    self.command(['xattr', '-w', 'com.apple.quarantine', f'0083;{int(time.time()):x};FlintEyeLifecycle;', self.app])
                finally: self.command(['hdiutil', 'detach', mount])
        elif os.name == 'nt':
            package = self.package('-setup.exe')
            if script:
                self.command(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', self.inputs/'install.ps1',
                              *([] if self.args.online else ['-PackageDirectory', self.inputs]), '-NoStart', '-Silent'])
            else:
                self.command([package, '/CURRENTUSER', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOSTART'])
        else:
            if script:
                self.command(['bash', self.inputs/'install.sh', '--package-directory', self.inputs, '--no-start'])
            else:
                self.command(['sudo', 'apt-get', 'install', '-y', self.package('.deb')])
        if not self.executable.is_file(): raise RuntimeError('Installed executable is missing')

    def verify(self):
        if sys.platform == 'darwin':
            from verify_macos import verify_app, assess_gatekeeper, validate_policy_control
            verify_app(self.app)
            policy_path = self.report.output/'macos-policy.json'
            assess_gatekeeper(self.app, policy_path)
            policy = json.loads(policy_path.read_text(encoding='utf-8'))
            if 'Internal Xprotect Error' in policy.get('system_policy', {}).get('output', ''):
                from macos_ci_policy import assess
                control_dir = self.report.output/'os-control'
                control_dir.mkdir(exist_ok=True)
                previous = self.report.output.parent/'os-control/independent-policy-control.json'
                if previous.is_file(): shutil.copy2(previous, control_dir/previous.name)
                else: assess(control_dir)
                control = json.loads((control_dir/'independent-policy-control.json').read_text(encoding='utf-8'))
                validate_policy_control(policy, control, self.report.data['os_version'])
        else: super().verify()

    def start(self):
        if sys.platform == 'darwin':
            # Launch Services is essential: direct --headless misses Gatekeeper.
            if self.installer_process is None:
                log = (self.report.output/'os-launch.log').open('a', encoding='utf-8'); self.logs.append(log)
                self.open_process = subprocess.Popen(['open', str(self.app)], stdout=log, stderr=log, start_new_session=True)
            try: wait_http(f'http://127.0.0.1:{self.port}', seconds=45)
            except (RuntimeError, TimeoutError):
                evidence = self.macos_diagnostics().lower()
                # A generic open error or spctl rejection alone cannot excuse a crash.
                from verify_macos import confirmed_approval_refusal
                if confirmed_approval_refusal(evidence):
                    raise ApprovalRequired('macos-trust.log: OS explicitly denied first launch; API/GUI not run')
                launcher = self.installer_process or self.open_process
                raise RuntimeError(f'OS launch did not complete without a confirmed approval refusal (launcher exit {launcher.poll()})')
            if self.installer_process is not None:
                if self.installer_process.wait(timeout=15) != 0:
                    raise RuntimeError('Installer reported a launch failure; inspect installation.log')
        else:
            self.launch([self.executable, '--disable-lan'])
            wait_http(f'http://127.0.0.1:{self.port}', self.process)

    def quit(self):
        # Remove only the test installation/profile's own login startup first.
        self.command([self.executable, '--data-dir', self.profile, '--disable-autostart'], name='quit.log')
        super().quit()

    def uninstall(self):
        if sys.platform == 'darwin':
            self.stop_launch_helpers()
            if self.app.is_symlink() or not self.app.is_dir(): raise RuntimeError('Unexpected app removal target')
            shutil.rmtree(self.app)
        elif os.name == 'nt':
            self.command(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                          '-File', self.app/'uninstall_windows.ps1', '-InstallDir', self.app, '-Silent'])
        else: self.command(['sudo', 'apt-get', 'remove', '-y', 'flinteye'])
        if any(Path(path).exists() for path in (self.executable, self.media, self.ffmpeg)):
            raise RuntimeError('Application or bundled media executable survived uninstall')
        if sys.platform == 'darwin' and (Path.home()/'Library/LaunchAgents/community.flinteye.plist').exists():
            raise RuntimeError('macOS login startup survived removal')
        if os.name == 'nt':
            import winreg
            for path in (r'Software\Microsoft\Windows\CurrentVersion\Uninstall\FlintEye.Community_is1',):
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path): raise RuntimeError('Uninstall registration survived removal')
                except FileNotFoundError: pass
        if not (self.profile/'.flinteye-qa-owned').exists(): raise RuntimeError('Uninstall erased retained data')

    def macos_diagnostics(self):
        expression = '(process == "amfid" OR process == "syspolicyd" OR process CONTAINS[c] "XProtect") AND (eventMessage CONTAINS[c] "/FlintEye.app" OR eventMessage CONTAINS[c] "(id: community.flinteye)" OR eventMessage CONTAINS[c] "(bundle_id: community.flinteye)")'
        result = subprocess.run(['/usr/bin/log', 'show', '--last', '8m', '--style', 'compact', '--info', '--debug', '--predicate', expression],
                                capture_output=True, text=True, timeout=45)
        text = result.stdout+result.stderr
        (self.report.output/'macos-trust.log').write_text(text[-150_000:], encoding='utf-8')
        self.command(['ps', '-axo', 'pid,ppid,stat,comm'], name='os-processes.log', check=False)
        return text

    def stop_launch_helpers(self):
        for process in (self.installer_process, self.open_process):
            if process is not None: stop_process(process)
        self.installer_process = self.open_process = None

    def finish(self):
        if sys.platform == 'darwin':
            try:
                if not (self.report.output/'macos-trust.log').exists(): self.macos_diagnostics()
            finally:
                self.stop_launch_helpers()
        elif os.name == 'nt' and self.report.data['result'] == 'failed':
            self.command(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                          "Get-Process | Where-Object { $_.ProcessName -match 'FlintEye|SmartScreen|setup|powershell' } | Select-Object ProcessName,Id,MainWindowTitle | Format-List"],
                         name='os-processes.log', timeout=30, check=False)
        super().finish()


def exercise(adapter: Adapter, report: Report, args):
    phase = 'install'
    try:
        adapter.install(); report.stage(phase, 'passed', 'installation.log; installed files verified')
        phase = 'integrity'
        adapter.verify(); report.stage(phase, 'passed', 'Embedded release / bundle integrity checked')
        url = adapter.prepare_profile()
        phase = 'os_launch'
        try: adapter.start()
        except ApprovalRequired as exc:
            report.stage(phase, 'manual-required', str(exc))
            adapter.uninstall()
            report.stage('uninstall', 'passed', 'Installed app removed; retained profile marker exists')
            return
        report.stage(phase, 'passed', 'Normal installed entry point started the real API')
        phase = 'api_gui'
        fixture_dir = adapter.directory/'fixture'; fixture_dir.mkdir()
        with ExitStack() as resources:
            fixture = resources.enter_context(media_fixture(fixture_dir, adapter.media, adapter.ffmpeg,
                                              prefix=adapter.fixture_prefix, app_directory=adapter.fixture_app_directory))
            onvif = (resources.enter_context(onvif_fixture(fixture, fixture_dir/'onvif-operations.json'))
                     if requires_preview_7_checks(args.release) else None)
            adapter.sync_profile()
            browser_check(url, adapter.profile, report.output/'browser', args.release, args.commit, fixture,
                          synthetic_uvc=args.synthetic_uvc, onvif_url=onvif)
            report.stage(phase, 'passed', 'browser/browser.json; real API; browser video/trace/screenshots')
            phase = 'quit'
            adapter.quit()
            adapter.sync_profile()
            completion = json.loads((adapter.profile/'last-monitoring-stop.json').read_text(encoding='utf-8'))
            if completion.get('ok') is not True or completion.get('forced') or completion.get('pending_segments') != 0:
                raise AssertionError('Normal Quit did not finish active recordings cleanly')
            decode_recordings(adapter.profile, adapter.ffmpeg, report.output,
                              prefix=adapter.fixture_prefix, app_profile=adapter.app_profile)
            report.stage(phase, 'passed', 'Normal quit closed the API; recording files fully decoded')
            retained = {str(path.relative_to(adapter.profile)): digest(path) for path in
                        [adapter.profile/'runtime.json', *(adapter.profile/'recordings').rglob('*')]
                        if path.is_file() and (path.name == 'runtime.json' or path.suffix in {'.mp4', '.ts'})}
            selection = json.loads((report.output/'browser/download-selection.json').read_text(encoding='utf-8'))
            selected = str(Path('recordings')/selection['relativePath'])
            downloaded = report.output/'browser'/selection['savedName']
            if selected not in retained or digest(downloaded) != retained[selected]:
                raise AssertionError(f'Browser download differs from the selected recording: {selected}')
            phase = 'uninstall'
            adapter.uninstall(); report.stage(phase, 'passed', 'Program removed; accounts/config/recordings retained')
            adapter.sync_profile()
            for name, expected in retained.items():
                if not (adapter.profile/name).is_file() or digest(adapter.profile/name) != expected:
                    raise AssertionError('Uninstall changed retained settings/recordings: '+name)
            (report.output/'retained-files.json').write_text(json.dumps(retained, indent=2)+'\n')
            phase = 'retained_reinstall'
            adapter.install(); adapter.verify(); adapter.prepare_profile(); adapter.start()
            adapter.sync_profile()
            for name, expected in retained.items():
                if name == 'runtime.json': continue  # Launch may normalize saved settings; GUI compares their values.
                if not (adapter.profile/name).is_file() or digest(adapter.profile/name) != expected:
                    raise AssertionError('Reinstall changed a finalized recording: '+name)
            browser_check(url, adapter.profile, report.output/'retained', args.release, args.commit, fixture,
                          retained=True, synthetic_uvc=args.synthetic_uvc, onvif_url=onvif)
            adapter.quit(); adapter.uninstall()
            report.stage(phase, 'passed', 'retained/browser.json; existing credentials, config and recordings reused')
    except BaseException as exc:
        report.stage(phase, 'failed', f'{type(exc).__name__}: {exc}')
        raise
    finally:
        adapter.finish()
        fixture_dir = adapter.directory/'fixture'
        if fixture_dir.is_dir():
            shutil.copytree(fixture_dir, report.output/'fixture', dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('external-camera-tools'))
        report.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--method', required=True, choices=[
        'source', 'windows-exe', 'windows-script', 'macos-dmg', 'macos-script',
        'linux-deb', 'linux-deb-script', 'linux-rpm', 'linux-rpm-script', *LINUX_USER_METHODS,
        'linux-systemd', 'compose', 'compose-development',
    ])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--artifact-directory', type=Path)
    parser.add_argument('--media-directory', type=Path)
    parser.add_argument('--python', help='An existing dedicated QA Python environment (source checks only)')
    parser.add_argument('--synthetic-uvc', action='store_true', help='Use a generated UVC capture input in a Linux source check')
    parser.add_argument('--release', default=release_identity()[0])
    parser.add_argument('--commit', default=os.environ.get('GITHUB_SHA', ''))
    parser.add_argument('--disposable', action='store_true', help='Assert this is a disposable QA user/VM; existing target locations are still refused')
    parser.add_argument('--image', help='Already-built exact-commit image for Compose lifecycle tests')
    parser.add_argument('--online', action='store_true', help='Scripts fetch the real public release URLs (no local package override)')
    args = parser.parse_args()
    if args.synthetic_uvc and (args.method != 'source' or not sys.platform.startswith('linux')):
        parser.error('--synthetic-uvc requires the Linux source method')
    args.output = args.output.resolve()
    report = Report(args.output, method=args.method, release=args.release, commit=args.commit)
    if args.method == 'source' and not args.media_directory: parser.error('Source checks require --media-directory')
    if args.method.startswith('compose'):
        if not args.image: parser.error('Compose checks require an already-built --image')
    elif args.method != 'source' and not args.artifact_directory: parser.error('Native checks require --artifact-directory')
    with tempfile.TemporaryDirectory(prefix='FlintEye lifecycle ') as temp:
        if args.method == 'source': factory = Source
        elif args.method.startswith('linux-') or args.method.startswith('compose'):
            from lifecycle_linux import PackageContainer, Systemd, Compose
            factory = Compose if args.method.startswith('compose') else Systemd if args.method == 'linux-systemd' else PackageContainer
        else: factory = Native
        adapter = factory(args, Path(temp), report)
        try:
            exercise(adapter, report, args)
        finally:
            adapter.cleanup()
    print(json.dumps({'result': report.data['result'], 'complete': report.data['complete'], 'report': str(args.output/'lifecycle.json')}))


if __name__ == '__main__': main()
