"""Disposable Linux package, systemd and real Compose installation adapters."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time

from lifecycle import Adapter, Native, owned_profile, remove_owned_profile
from lifecycle_common import ROOT, request_quit, seed_runtime, wait_http


class PackageContainer(Adapter):
    """The desktop menu entry runs in Xvfb; no Python/Node app dependencies."""
    def __init__(self, *args):
        super().__init__(*args)
        if os.name == 'nt' or os.getuid() == 0:
            raise RuntimeError('Linux package QA runs as a non-root host user')
        self.inputs = self.args.artifact_directory.resolve()
        self.name = 'flinteye-package-qa-'+secrets.token_hex(8)
        self.image = self.name+':local'
        self.rpm = 'rpm' in self.args.method
        self.app_profile = '/qa/profile'
        self.executable = '/opt/flinteye/FlintEye'
        self.media = '/opt/flinteye/_internal/bin/mediamtx'
        self.ffmpeg = '/opt/flinteye/_internal/bin/ffmpeg'
        self.fixture_prefix = ['docker', 'exec', self.name]
        self.fixture_app_directory = '/qa/fixture'
        self.ready = False
        owned_profile(self.profile)

    def run(self, command, **kwargs):
        return self.command(['docker', 'exec', self.name, *command], **kwargs)

    def install(self):
        if not self.ready:
            base = 'rockylinux:9@sha256:d7be1c094cc5845ee815d4632fe377514ee6ebcf8efaed6892889657e5ddaaa6' if self.rpm else 'ubuntu:24.04'
            self.command(['docker', 'build', '-f', ROOT/'packaging/LifecycleLinux.Dockerfile',
                          '--build-arg', 'BASE='+base, '--build-arg', 'QA_UID='+str(os.getuid()),
                          '--build-arg', 'QA_GID='+str(os.getgid()), '-t', self.image, ROOT], timeout=600)
            self.command(['docker', 'run', '-d', '--init', '--network', 'host', '--name', self.name,
                          '--label', 'community.flinteye.qa='+self.name,
                          '--mount', f'type=bind,src={self.directory},dst=/qa',
                          '--mount', f'type=bind,src={self.inputs},dst=/artifacts,readonly', self.image])
            self.ready = True
            self.run(['sh', '-c', 'for attempt in $(seq 1 50); do xdpyinfo >/dev/null 2>&1 && exit 0; sleep .1; done; exit 1'])
        suffix = '.rpm' if self.rpm else '.deb'
        package = Native.package(self, suffix)
        if self.args.method.endswith('script'):
            self.run(['bash', '/artifacts/install.sh',
                      *([] if self.args.online else ['--package-directory', '/artifacts']), '--no-start'])
        else:
            self.run(['sudo', 'dnf' if self.rpm else 'apt-get', 'install', '-y', '/artifacts/'+package.name])
        self.run(['test', '-x', self.executable])

    def verify(self):
        result = subprocess.run(['docker', 'exec', self.name, self.executable, '--version'],
                                capture_output=True, text=True, timeout=30, check=True)
        if result.stdout.strip() != self.args.release:
            raise AssertionError('Installed Linux package release mismatch')

    def start(self):
        # Exercise the package's actual desktop entry without --headless.
        self.run(['gtk-launch', 'flinteye'], name='os-launch.log')
        wait_http(f'http://127.0.0.1:{self.port}')

    def quit(self):
        self.run([self.executable, '--disable-autostart'], name='quit.log')
        request_quit(self.profile)
        self.check_closed()

    def uninstall(self):
        self.run(['sudo', 'dnf' if self.rpm else 'apt-get', 'remove', '-y', 'flinteye'])
        self.run(['sh', '-c', 'test ! -e /opt/flinteye/FlintEye && test ! -e /opt/flinteye/_internal/bin/ffmpeg && test ! -e /opt/flinteye/_internal/bin/mediamtx && test ! -e /usr/share/applications/flinteye.desktop && test ! -e /usr/lib/systemd/system/flinteye.service && test ! -e "$HOME/.config/autostart/flinteye.desktop"'])
        if not (self.profile/'.flinteye-qa-owned').is_file(): raise AssertionError('Package removal erased data')

    def cleanup(self):
        self.command(['docker', 'rm', '-f', self.name], name='cleanup.log', check=False)
        self.command(['docker', 'image', 'rm', self.image], name='cleanup.log', check=False)
        super().cleanup()


class Systemd(Native):
    """Run the shipped unit in a fresh hosted VM with a unique state directory."""
    def __init__(self, *args):
        super().__init__(*args)
        # Native preflight has also rejected any existing application/default data.
        self.empty_default = self.profile
        name = 'flinteye-qa-'+secrets.token_hex(8)
        self.unit_name = name+'.service'
        self.unit = Path('/etc/systemd/system')/self.unit_name
        self.profile = Path('/var/lib')/name
        self.app_profile = str(self.profile)
        if self.profile.exists() or self.unit.exists(): raise RuntimeError('Existing systemd QA paths')
        self.command(['sudo', 'install', '-d', '-o', str(os.getuid()), '-g', str(os.getgid()), self.profile])
        (self.profile/'.flinteye-qa-owned').write_text('Synthetic systemd lifecycle data\n')

    def install(self):
        super().install()
        text = (ROOT/'packaging/flinteye.service').read_text()
        import pwd, grp
        text = text.replace('User=flinteye', 'User='+pwd.getpwuid(os.getuid()).pw_name)
        text = text.replace('Group=flinteye', 'Group='+grp.getgrgid(os.getgid()).gr_name)
        text = text.replace('StateDirectory=flinteye', 'StateDirectory='+self.profile.name)
        text = text.replace('/var/lib/flinteye', str(self.profile))
        copy = self.directory/self.unit_name; copy.write_text(text)
        self.command(['sudo', 'install', '-m', '0644', copy, self.unit])
        self.command(['sudo', 'systemctl', 'daemon-reload'])

    def start(self):
        self.command(['sudo', 'systemctl', 'enable', '--now', self.unit_name], name='os-launch.log')
        wait_http(f'http://127.0.0.1:{self.port}')

    def quit(self):
        self.command(['sudo', 'systemctl', 'disable', '--now', self.unit_name], name='quit.log')
        self.check_closed()
        if (self.profile/'instance-control.json').exists(): raise AssertionError('systemd stop did not finish normally')

    def uninstall(self):
        self.command(['sudo', 'rm', '--', self.unit])
        self.command(['sudo', 'systemctl', 'daemon-reload'])
        super().uninstall()
        result = subprocess.run(['systemctl', 'is-enabled', self.unit_name], capture_output=True, text=True)
        if result.returncode == 0: raise AssertionError('Removed service remains enabled')

    def finish(self):
        self.command(['sudo', 'journalctl', '-u', self.unit_name, '--no-pager', '-n', '300'], name='journal.log', check=False)
        super().finish()

    def cleanup(self):
        # Cleanup of a failed test is separate from the normal quit result.
        self.command(['sudo', 'systemctl', 'disable', '--now', self.unit_name], name='cleanup.log', check=False)
        if self.unit.exists(): self.command(['sudo', 'rm', '--', self.unit], name='cleanup.log')
        self.command(['sudo', 'systemctl', 'daemon-reload'], name='cleanup.log')
        if (self.empty_default/'.flinteye-qa-owned').is_file(): remove_owned_profile(self.empty_default)
        # /var/lib is root-owned even though this unique StateDirectory and its
        # contents belong to the QA user. Never remove a shared service profile.
        if (self.profile.parent != Path('/var/lib') or self.profile.name != self.unit_name.removesuffix('.service')
                or self.profile.is_symlink() or not (self.profile/'.flinteye-qa-owned').is_file()):
            raise RuntimeError('Refusing removal of an unowned systemd state directory')
        self.command(['sudo', 'rm', '-rf', '--', self.profile], name='cleanup.log')


class Compose(Adapter):
    """Use the real distribution/development Compose file and its named volume."""
    def __init__(self, *args):
        super().__init__(*args)
        self.image = self.args.image
        self.name = 'flinteye-compose-qa-'+secrets.token_hex(8)
        self.volume = self.name+'-data'
        self.helper = self.name+'-fixtures'
        self.app_profile = '/data'
        self.media, self.ffmpeg = '/opt/flinteye/bin/mediamtx', '/usr/bin/ffmpeg'
        self.fixture_prefix = ['docker', 'exec', self.helper]
        self.fixture_app_directory = '/qa/fixture'
        owned_profile(self.profile)
        original = ROOT/('deploy/compose.dev.yaml' if self.args.method == 'compose-development' else 'compose.yaml')
        override = self.directory/'compose.qa.json'
        override.write_text(json.dumps({'services': {'flinteye': {'image': self.image, 'pull_policy': 'never',
            'restart': 'no', 'environment': {'FLINTEYE_LAN_ADDRESS': '', 'FLINTEYE_LAN_SOURCES': ''}}},
            'volumes': {'flinteye-data': {'name': self.volume}}}))
        self.compose = ['docker', 'compose', '-p', self.name, '-f', str(original), '-f', str(override)]
        self.ready = False

    def install(self):
        if not self.ready:
            # Refuse an accidental tag/commit mismatch before running anything.
            details = json.loads(subprocess.check_output(['docker', 'image', 'inspect', self.image], text=True))[0]
            labels = details['Config'].get('Labels') or {}
            if self.args.commit and labels.get('org.opencontainers.image.revision') != self.args.commit:
                raise AssertionError('Compose image belongs to another commit')
            self.port = seed_runtime(self.profile, self.app_profile, self.media)
            self.command(['docker', 'volume', 'create', '--label', 'community.flinteye.qa='+self.name, self.volume])
            self.command(['docker', 'run', '--rm', '--user', '0', '--entrypoint', 'sh',
                          '--mount', f'type=volume,src={self.volume},dst=/data',
                          '--mount', f'type=bind,src={self.profile},dst=/seed,readonly',
                          self.image, '-c', 'cp -a /seed/. /data/ && chown -R 10001:10001 /data'])
            self.command(['docker', 'run', '-d', '--init', '--network', 'host', '--name', self.helper,
                          '--label', 'community.flinteye.qa='+self.name,
                          '--user', '0', '--entrypoint', 'sleep',
                          '--mount', f'type=bind,src={self.directory},dst=/qa',
                          '--mount', f'type=volume,src={self.volume},dst=/data,readonly', self.image, 'infinity'])
            self.ready = True
        # `create --no-build` also resolves/validates the real source Compose file.
        self.command(self.compose+['create', '--no-build'], timeout=120)

    def verify(self):
        result = subprocess.run(['docker', 'exec', self.helper, 'python', '/opt/flinteye/flinteye.py', '--version'],
                                capture_output=True, text=True, timeout=30, check=True)
        if result.stdout.strip() != self.args.release: raise AssertionError('Compose release mismatch')

    def prepare_profile(self):
        return f'http://127.0.0.1:{self.port}'

    def start(self):
        self.command(self.compose+['up', '-d', '--no-build'], name='os-launch.log', timeout=120)
        wait_http(f'http://127.0.0.1:{self.port}')

    def sync_profile(self):
        # Root reads the private volume; it exports only our synthetic QA profile.
        self.command(['docker', 'exec', self.helper, 'test', '-f', '/data/.flinteye-qa-owned'], name='snapshot.log')
        remove_owned_profile(self.profile)
        self.profile.mkdir()
        self.command(['docker', 'run', '--rm', '--user', '0', '--entrypoint', 'sh',
                      '--mount', f'type=volume,src={self.volume},dst=/data,readonly',
                      '--mount', f'type=bind,src={self.profile},dst=/copy', self.image, '-c',
                      f'cp -a /data/. /copy/ && chown -R {os.getuid()}:{os.getgid()} /copy'], name='snapshot.log')

    def quit(self):
        # Same authenticated local Quit request as the application, not docker kill.
        code = "import json,pathlib; p=pathlib.Path('/data'); c=json.loads((p/'instance-control.json').read_text()); (p/'stop-request.json').write_text(json.dumps({'token':c['token']}))"
        self.command(self.compose+['exec', '-T', 'flinteye', 'python', '-c', code], name='quit.log')
        self.check_closed()
        end = time.monotonic()+60
        while time.monotonic() < end:
            active = subprocess.check_output(self.compose+['ps', '--status', 'running', '-q'], text=True).strip()
            if not active: break
            time.sleep(.25)
        else: raise AssertionError('Compose API container survived normal Quit')
        ids = subprocess.check_output(self.compose+['ps', '-a', '-q'], text=True).strip().splitlines()
        if len(ids) != 1: raise AssertionError('Unexpected Compose container set')
        status = json.loads(subprocess.check_output(['docker', 'inspect', ids[0]], text=True))[0]['State']
        if status['ExitCode'] != 0: raise AssertionError('Compose application did not exit cleanly')

    def uninstall(self):
        self.command(self.compose+['down'], timeout=90)
        if subprocess.check_output(self.compose+['ps', '-a', '-q'], text=True).strip():
            raise AssertionError('Compose application survived removal')
        self.command(['docker', 'volume', 'inspect', self.volume], name='retention.log')
        self.sync_profile()
        if not (self.profile/'.flinteye-qa-owned').is_file(): raise AssertionError('Compose removal erased data')

    def finish(self):
        self.command(self.compose+['logs', '--no-color', '--tail', '300'], name='compose.log', check=False)
        super().finish()

    def cleanup(self):
        self.command(self.compose+['down'], name='cleanup.log', check=False, timeout=90)
        self.command(['docker', 'rm', '-f', self.helper], name='cleanup.log', check=False)
        # This unique volume was created here; never use a shared project's down -v.
        if self.ready: self.command(['docker', 'volume', 'rm', self.volume], name='cleanup.log', timeout=60)
        super().cleanup()
