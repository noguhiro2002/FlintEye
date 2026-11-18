"""Release safety: immutable tested artifacts and install failure boundaries."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging'))
import release
from container_sources import package_owner
from release_lib import REPOSITORY, version, binary_architecture
from validation_install import prepare as prepare_validation_install


class ReleaseTests(unittest.TestCase):
    def test_per_os_validation_download_has_pinned_scripts_and_checksums(self):
        prepare_validation_install(self.inputs, self.commit)
        identity = json.loads((self.inputs/'validation-build.json').read_text())
        self.assertEqual(identity['commit'], self.commit)
        for name in ('install.sh', 'install.ps1'):
            self.assertIn(identity['release'], (self.inputs/name).read_text())
            self.assertNotIn('@RELEASE_VERSION@', (self.inputs/name).read_text())
        checksums = dict((line.split('  ', 1)[1], line.split('  ', 1)[0])
                         for line in (self.inputs/'SHA256SUMS').read_text().splitlines())
        for name, expected in checksums.items():
            self.assertEqual(hashlib.sha256((self.inputs/name).read_bytes()).hexdigest(), expected)
        self.assertEqual(identity['packages']['FlintEye-'+version()+'-macos-arm64.dmg'],
                         checksums['FlintEye-'+version()+'-macos-arm64.dmg'])

    def test_debian_diversions_are_not_mistaken_for_package_names(self):
        output = ('diversion by libc6 from: /lib64/ld-linux-x86-64.so.2\n'
                  'diversion by libc6 to: /lib64/ld-linux-x86-64.so.2.usr-is-merged\n'
                  'libc6:amd64: /lib64/ld-linux-x86-64.so.2\n')
        self.assertEqual(package_owner(output), 'libc6:amd64')
        self.assertIsNone(package_owner('diversion by libc6 from: /lib/example\n'))

    def test_native_architecture_detection_does_not_accept_emulation_as_native(self):
        elf = bytearray(64); elf[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<H', elf, 18, 183)
        pe = bytearray(70); pe[:2] = b'MZ'; struct.pack_into('<I', pe, 60, 64)
        pe[64:68] = b'PE\0\0'; struct.pack_into('<H', pe, 68, 0x8664)
        macho = bytearray(64); macho[:4] = b'\xcf\xfa\xed\xfe'; struct.pack_into('<I', macho, 4, 0x0100000C)
        for name, contents, architecture in [('elf', elf, 'arm64'), ('pe', pe, 'amd64'), ('macho', macho, 'arm64')]:
            path = self.root / name; path.write_bytes(contents)
            self.assertEqual(binary_architecture(path), architecture)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='FlintEye release tests ')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        self.output = self.root / 'release'
        self.commit = 'a' * 40
        for name in release.required_assets(version()) | {'container-amd64.tar.gz', 'container-arm64.tar.gz'}:
            (self.inputs / name).write_bytes(('test artifact: ' + name).encode())

    def test_complete_build_has_version_pinned_scripts_and_public_checksums(self):
        release.assemble(self.inputs, self.output, self.commit)
        manifest = release.verify(self.output, self.commit)
        self.assertEqual(manifest['version'], version())
        for name in ('install.sh', 'install.ps1'):
            text = (self.output / 'public' / name).read_text()
            self.assertNotIn('@RELEASE_VERSION@', text)
            self.assertIn(version(), text)
        with zipfile.ZipFile(self.output / 'public/documentation.zip') as docs:
            self.assertIn('docs/ACCEPTANCE.ja.md', docs.namelist())
            self.assertIn('docs/INSTALL.ja.md', docs.namelist())
            self.assertIn('images/FlintEyeLogo-white.png', docs.namelist())
            self.assertNotIn('.env', docs.namelist())
        self.assertIn(self.commit, (self.output / 'public/ACCEPTANCE.ja.md').read_text())

    def test_missing_platform_or_sources_cannot_be_assembled(self):
        (self.inputs / f'FlintEye-{version()}-windows-arm64-sources.tar.gz').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing artifacts'):
            release.assemble(self.inputs, self.output, self.commit)
        self.assertFalse(self.output.exists())

    def test_modified_installer_and_foreign_commit_are_rejected(self):
        release.assemble(self.inputs, self.output, self.commit)
        with self.assertRaisesRegex(ValueError, 'different commit'):
            release.verify(self.output, 'b' * 40)
        package = self.output / 'public' / f'FlintEye-{version()}-linux-amd64.deb'
        package.write_bytes(b'changed after testing')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            release.verify(self.output, self.commit)

    def test_added_files_cannot_sneak_into_a_tested_release(self):
        release.assemble(self.inputs, self.output, self.commit)
        (self.output / 'public/unreviewed.exe').write_bytes(b'unreviewed')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            release.verify(self.output)

    def test_publication_requires_public_repo_matching_trusted_run_and_signoff(self):
        repo = {'full_name': REPOSITORY, 'private': False, 'visibility': 'public', 'default_branch': 'main'}
        run = {'path': '.github/workflows/build-release.yml', 'event': 'workflow_dispatch',
               'conclusion': 'success', 'head_sha': self.commit, 'head_branch': 'main',
               'head_repository': {'full_name': REPOSITORY}}
        kwargs = dict(commit=self.commit, enabled=True, tested=True, licenses_reviewed=True, ref='refs/heads/main')
        release.validate_publish_context(repo, run, **kwargs)
        release.validate_publish_context(repo, {**run, 'event': 'push'}, **kwargs)
        cases = [('private repository', {**repo, 'private': True}, run, kwargs),
                 ('wrong commit', repo, {**run, 'head_sha': 'b' * 40}, kwargs),
                 ('pull request', repo, {**run, 'event': 'pull_request'}, kwargs),
                 ('other branch push', repo, {**run, 'event': 'push', 'head_branch': 'feature'}, kwargs),
                 ('fork', repo, {**run, 'head_repository': {'full_name': 'other/FlintEye'}}, kwargs),
                 ('no device checks', repo, run, {**kwargs, 'tested': False}),
                 ('no license review', repo, run, {**kwargs, 'licenses_reviewed': False}),
                 ('publication disabled', repo, run, {**kwargs, 'enabled': False})]
        for label, repository, build, arguments in cases:
            with self.subTest(label=label), self.assertRaises(ValueError):
                release.validate_publish_context(repository, build, **arguments)


    def test_private_channel_requires_private_repo_and_same_trusted_commit(self):
        repo = {'full_name': REPOSITORY, 'private': True, 'visibility': 'private', 'default_branch': 'main'}
        run = {'path': '.github/workflows/build-release.yml', 'event': 'workflow_dispatch',
               'conclusion': 'success', 'head_sha': self.commit, 'head_branch': 'main',
               'head_repository': {'full_name': REPOSITORY}}
        kwargs = dict(commit=self.commit, enabled=False, tested=False, licenses_reviewed=False,
                      ref='refs/heads/main', channel='private-test')
        release.validate_publish_context(repo, run, **kwargs)
        with self.assertRaises(ValueError):
            release.validate_publish_context({**repo, 'private': False, 'visibility': 'public'}, run, **kwargs)
        with self.assertRaises(ValueError):
            release.validate_publish_context(repo, {**run, 'head_sha': 'b'*40}, **kwargs)

    def test_public_preview_can_be_published_for_device_acceptance(self):
        repo = {'full_name': REPOSITORY, 'private': False, 'visibility': 'public', 'default_branch': 'main'}
        run = {'path': '.github/workflows/build-release.yml', 'event': 'workflow_dispatch',
               'conclusion': 'success', 'head_sha': self.commit, 'head_branch': 'main',
               'head_repository': {'full_name': REPOSITORY}}
        arguments = dict(commit=self.commit, enabled=True, tested=True, licenses_reviewed=True,
                         ref='refs/heads/main', channel='public-preview')
        release.validate_publish_context(repo, run, **arguments)
        release.validate_publish_context(repo, run, **{**arguments, 'tested': False})
        for field in ('enabled', 'licenses_reviewed'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                release.validate_publish_context(repo, run, **{**arguments, field: False})

    def test_publication_can_update_docs_but_cannot_replace_tested_application(self):
        release.validate_publication_revision(self.commit, 'b'*40,
                                             ['README.md', 'docs/INSTALL.md', 'packaging/publish_release.py'])
        for name in ('flinteye_app/cli.py', 'frontend/src/App.tsx', 'requirements.txt',
                     'Dockerfile', 'packaging/windows.iss', 'packaging/install.sh',
                     'LICENSE', 'images/demo.gif', 'docs/../flinteye_app/cli.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                release.validate_publication_revision(self.commit, 'b'*40, [name])

    def test_documentation_is_identical_across_publication_phases(self):
        from unittest.mock import patch
        source = self.root/'docs-source'; (source/'docs').mkdir(parents=True)
        (source/'images').mkdir(); (source/'.github').mkdir()
        (source/'packaging').mkdir()
        (source/'packaging/acceptance-1.2.0.json').write_text('{}')
        for name in ('README.md', 'README.ja.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'docs/INSTALL.md'):
            (source/name).write_text('Retained text: '+name)
        with patch('release.ROOT', source):
            release.write_documentation(self.root/'first.zip')
            for path in source.rglob('*.md'):
                os.utime(path, (1_700_000_000, 1_700_000_000))
            release.write_documentation(self.root/'second.zip')
        self.assertEqual((self.root/'first.zip').read_bytes(), (self.root/'second.zip').read_bytes())

    def test_new_preview_is_blocked_until_every_p1_case_is_evidenced(self):
        root = self.root/'acceptance-source'; (root/'packaging').mkdir(parents=True)
        path = root/'packaging/acceptance-1.2.0.json'
        data = {'version': version(), 'commit': self.commit,
                'cases': {name: {'status': 'passed', 'evidence': 'https://example.test/qa/'+name} for name in release.ACCEPTANCE_CASES}}
        path.write_text(json.dumps(data))
        release.check_development_acceptance(self.commit, root=root)
        case = next(iter(data['cases'])); data['cases'][case]['status'] = 'pending'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'pending or failed'): release.check_development_acceptance(self.commit, root=root)
        with self.assertRaisesRegex(ValueError, 'commit'): release.check_development_acceptance('b'*40, root=root)

    def test_actions_rejects_workflow_mismatch_before_distribution(self):
        release.validate_publication_revision(self.commit, 'b'*40, ['docs/INSTALL.md'], workflow_token=True)
        with self.assertRaisesRegex(ValueError, 'GITHUB_TOKEN'):
            release.validate_publication_revision(self.commit, 'b'*40,
                                                 ['.github/workflows/publish-release.yml'], workflow_token=True)
        release.validate_publication_revision(self.commit, 'b'*40, ['.github/workflows/publish-release.yml'])

    def test_release_lookup_includes_unpublished_drafts_and_all_pages(self):
        from publish_release import find_release
        from unittest.mock import patch
        draft = {'tag_name': 'v1.1.3-preview.1', 'draft': True, 'id': 42}
        with patch('publish_release.run', return_value=json.dumps([[{'tag_name': 'older'}], [draft]])) as query:
            self.assertEqual(find_release(draft['tag_name']), draft)
            self.assertIn('--paginate', query.call_args.args)
            self.assertIsNone(find_release('missing'))
        with patch('publish_release.run', return_value=json.dumps([[draft], [draft]])):
            with self.assertRaisesRegex(ValueError, 'Multiple releases'):
                find_release(draft['tag_name'])

    def test_preview_distribution_matches_embedded_build_identity(self):
        from publish_release import prepare, finalize
        from unittest.mock import patch
        with patch('release.release_identity', return_value=(version()+'-preview.2', 'preview')):
            release.assemble(self.inputs, self.output, self.commit)
        original = release.verify(self.output, self.commit)
        with self.assertRaisesRegex(ValueError, 'embedded release'):
            prepare(self.output, self.root/'wrong-number', self.commit, original['run_id'], 'public-preview', '1')
        selected = self.root/'selected-preview'
        metadata = prepare(self.output, selected, self.commit, original['run_id'], 'public-preview', '2')
        finalize(selected, metadata)
        self.assertEqual(metadata['tag'], 'v'+version()+'-preview.2')
        self.assertIn(version()+'-preview.2', (selected/'install.sh').read_text())
        self.assertIn('UNDER DEVELOPMENT', (selected/'RELEASE-NOTES.en.md').read_text())
        self.assertIn('Real-device acceptance is still in progress', (selected/'RELEASE-NOTES.en.md').read_text())
        self.assertTrue(metadata['device_acceptance_pending'])
        self.assertEqual(release.verify(self.output, self.commit), original)

    def test_public_preview_cannot_publish_with_private_package_or_changed_assets(self):
        from publish_release import finish_publication
        from types import SimpleNamespace
        from unittest.mock import patch
        args = SimpleNamespace(channel='public-preview', output=self.root/'selected')
        metadata = {'tag': 'v'+version()+'-preview.1'}
        draft = {'draft': True, 'target_commitish': self.commit, 'id': 42}
        for failing_check in ('check_visibility', 'verify_remote_assets'):
            with patch('publish_release.find_release', return_value=draft), \
                 patch('publish_release.verify_container_receipt'), \
                 patch('publish_release.check_visibility'), \
                 patch('publish_release.verify_remote_assets'), \
                 patch('publish_release.'+failing_check, side_effect=ValueError('invalid')), \
                 patch('publish_release.subprocess.run') as mutation:
                with self.assertRaises(ValueError):
                    finish_publication(args, metadata, self.commit)
                mutation.assert_not_called()

    def test_public_preview_is_prerelease_and_never_moves_latest(self):
        from publish_release import finish_publication
        from types import SimpleNamespace
        from unittest.mock import patch
        selected = self.root/'selected'; selected.mkdir()
        args = SimpleNamespace(channel='public-preview', output=selected)
        metadata = {'tag': 'v'+version()+'-preview.1', 'container_digest': 'sha256:'+'a'*64}
        responses = [
            {'draft': False, 'prerelease': True, 'html_url': 'https://github.com/'+REPOSITORY+'/releases/tag/'+metadata['tag']},
            {'object': {'type': 'commit', 'sha': self.commit}},
        ]
        with patch('publish_release.api', side_effect=responses), \
             patch('publish_release.find_release', return_value={'draft': True, 'target_commitish': self.commit, 'id': 42}), \
             patch('publish_release.verify_container_receipt'), \
             patch('publish_release.check_visibility'), \
             patch('publish_release.verify_remote_assets'), \
             patch('publish_release.subprocess.run') as mutation:
            finish_publication(args, metadata, self.commit)
        mutation.assert_called_once()
        command = mutation.call_args.args[0]
        self.assertIn('--prerelease=true', command)
        self.assertIn('--latest=false', command)

    def test_private_assets_are_derived_without_changing_tested_bundle(self):
        from publish_release import prepare, finalize
        release.assemble(self.inputs, self.output, self.commit)
        original = release.verify(self.output, self.commit)
        selected = self.root/'selected'
        metadata = prepare(self.output, selected, self.commit, original['run_id'], 'private-test', '1')
        finalize(selected, metadata)
        self.assertFalse((selected/'install.sh').exists())
        self.assertFalse((selected/'install.ps1').exists())
        self.assertTrue((selected/'RELEASE-NOTES.ja.md').is_file())
        self.assertEqual(metadata['tag'], 'v'+version()+'-preview.1')
        self.assertEqual(release.verify(self.output,self.commit),original)
        checksums=(selected/'SHA256SUMS').read_text().splitlines()
        from release_lib import digest
        self.assertEqual(checksums,[f'{digest(p)}  {p.name}' for p in sorted(selected.iterdir()) if p.name!='SHA256SUMS'])
        with self.assertRaisesRegex(ValueError,'run ID'):
            prepare(self.output,self.root/'wrong-run',self.commit,'foreign','private-test','1')

    def test_remote_asset_verification_requires_exact_names_sizes_and_digests(self):
        from publish_release import verify_remote_assets
        from release_lib import digest
        from unittest.mock import patch
        selected=self.root/'remote-test';selected.mkdir()
        artifact=selected/'package.exe';artifact.write_bytes(b'tested payload')
        asset={'name':artifact.name,'size':artifact.stat().st_size,'digest':'sha256:'+digest(artifact)}
        with patch('publish_release.run',return_value=json.dumps([[asset]])):
            verify_remote_assets(123,selected)
        for invalid in ({**asset,'digest':'sha256:'+'0'*64},{**asset,'size':1},{**asset,'name':'other.exe'}):
            with patch('publish_release.run',return_value=json.dumps([[invalid]])), patch('publish_release.time.sleep'), self.assertRaises(ValueError):
                verify_remote_assets(123,selected)

    def test_stable_order_ignores_latest_preview_but_not_newer_stable(self):
        from check_release_order import check_order
        check_order('1.1.1',[{'tag_name':'v1.1.1-preview.1'},{'tag_name':'v1.1.0'}])
        with self.assertRaises(ValueError):
            check_order('1.1.1',[{'tag_name':'v1.1.2'}])
        from publish_release import release_version
        for value in ('0','../tag','1;echo','-1','1.1'):
            with self.assertRaises(ValueError):release_version('private-test',value)


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('bash'), 'Linux shell installer checks')
class ShellInstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='FlintEye install tests ')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.payload = self.root / 'payload'; self.payload.mkdir()
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'TEST_PAYLOAD': str(self.payload), 'TEST_MARKER': str(self.root / 'installed'),
                    'TEST_URLS': str(self.root / 'urls')}
        self.command('id', 'echo 1000')
        self.command('uname', 'if [ "${1:-}" = -m ]; then echo x86_64; else echo Linux; fi')
        self.command('pgrep', 'exit 1')
        self.command('sudo', 'printf "%s\\n" "$*" > "$TEST_MARKER"')
        self.command('curl', '''out=''
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then out=$2; shift 2; else url=$1; shift; fi
done
printf '%s\\n' "$url" >> "$TEST_URLS"
cp "$TEST_PAYLOAD/${url##*/}" "$out"''')

    def command(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\nset -eu\n' + body + '\n')
        path.chmod(0o755)

    def run_installer(self, *arguments):
        return subprocess.run(['bash', str(ROOT / 'packaging/install.sh'), *arguments],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def fixture(self, checksum=None):
        name = 'FlintEye-1.2.3-linux-amd64.deb'
        payload = b'test package only'
        (self.payload / name).write_bytes(payload)
        (self.payload / 'SHA256SUMS').write_text(f'{checksum or hashlib.sha256(payload).hexdigest()}  {name}\n')

    def test_invalid_version_and_unsupported_cpu_do_not_download(self):
        result = self.run_installer('--version', '../other')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'urls').exists())
        self.command('uname', 'echo i686')
        result = self.run_installer('--version', '1.2.3')
        self.assertIn('64-bit', result.stderr)
        self.assertFalse((self.root / 'installed').exists())

    def test_bad_checksum_never_invokes_package_manager(self):
        self.fixture('0' * 64)
        result = self.run_installer('--version', '1.2.3', '--no-start')
        self.assertIn('Checksum mismatch', result.stderr)
        self.assertFalse((self.root / 'installed').exists())

    def test_verified_download_uses_one_fixed_version_and_quoted_path(self):
        self.fixture()
        result = self.run_installer('--version', '1.2.3', '--no-start')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('apt-get install', (self.root / 'installed').read_text())
        urls = (self.root / 'urls').read_text().splitlines()
        self.assertEqual(len(urls), 2)
        self.assertTrue(all('/releases/download/v1.2.3/' in url for url in urls))

    def test_running_app_prevents_upgrade(self):
        self.command('pgrep', 'exit 0')
        result = self.run_installer('--version', '1.2.3')
        self.assertIn('Quit FlintEye', result.stderr)
        self.assertFalse((self.root / 'urls').exists())

    def test_preview_tag_downloads_numeric_installer_version(self):
        self.fixture()
        result = self.run_installer('--version', '1.2.3-preview.2', '--no-start')
        self.assertEqual(result.returncode, 0, result.stderr)
        urls = (self.root / 'urls').read_text().splitlines()
        self.assertTrue(all('/releases/download/v1.2.3-preview.2/' in url for url in urls))
        self.assertTrue(any(url.endswith('FlintEye-1.2.3-linux-amd64.deb') for url in urls))


if __name__ == '__main__':
    unittest.main()
