"""Diagnostic rechecks must never weaken immutable release evidence."""
import json
import hashlib
import os
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'packaging'))
from recheck_installers import matrix, validate_changes, overlay
from lifecycle_report import Report, STAGES, validate
from release_lib import digest, release_identity
from lifecycle_common import stage_fixture_tools
from verify_macos import validate_policy_control, confirmed_approval_refusal
from macos_ci_policy import CONTROL_SOURCE, CONTROL_ID


class RecheckTests(unittest.TestCase):
    def test_external_cameras_survive_removal_of_the_application_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); install = root/'app'; install.mkdir()
            media, ffmpeg = install/'media', install/'ffmpeg'
            for tool in (media, ffmpeg): tool.write_text("print('independent synthetic camera')\n")
            fixture = root/'fixture'; fixture.mkdir()
            copied = stage_fixture_tools(fixture, str(media), str(ffmpeg))
            shutil.rmtree(install)
            for tool in copied:
                r = subprocess.run([sys.executable, tool], capture_output=True, text=True, check=True)
                self.assertIn('independent synthetic camera', r.stdout)

    def test_internal_scanner_error_requires_an_identical_independent_control(self):
        policy = {'system_policy': {'exit_code': 70, 'output': 'File: FlintEye.app\nInternal Xprotect Error'}}
        control = {'os': 'test OS', 'bundle_id': CONTROL_ID,
                   'source_sha256': hashlib.sha256(CONTROL_SOURCE.encode()).hexdigest(),
                   'distribution': {'exit_code': 70, 'output': 'File: PolicyControl.app\nInternal Xprotect Error'}}
        validate_policy_control(policy, control, 'test OS')
        for changed in ({}, {**control, 'os': 'another OS'},
                        {**control, 'source_sha256': '0'*64},
                        {**control, 'distribution': {'exit_code': 70, 'output': 'Other error'}}):
            with self.assertRaises(RuntimeError): validate_policy_control(policy, changed, 'test OS')
        with self.assertRaises(RuntimeError):
            validate_policy_control({'system_policy': {'output': 'Internal Xprotect Error: malware detected'}}, control, 'test OS')

    def test_generic_errors_or_threats_cannot_be_excused_as_first_launch_consent(self):
        refusal = 'amfid: The file is adhoc signed or signed by an unknown certificate chain'
        self.assertTrue(confirmed_approval_refusal(refusal))
        for text in ['open error 2', 'spctl: rejected', 'Internal Xprotect Error', refusal+'; malware detected']:
            self.assertFalse(confirmed_approval_refusal(text))

    def test_test_only_revision_cannot_hide_changed_binary_inputs(self):
        validate_changes(['packaging/lifecycle.py', '.github/workflows/recheck-installers.yml', 'docs/INSTALLATION_QA.md'])
        for name in ['flinteye_app/cli.py', 'frontend/src/App.tsx', 'packaging/build_bundle.py',
                     'requirements.txt', 'images/icons/flinteye.icns', 'docs/../flinteye_app/cli.md']:
            with self.assertRaises(ValueError): validate_changes([name])
        self.assertEqual(len(matrix('all')['include']), 12)
        self.assertEqual(len(matrix('windows')['include']), 4)
        self.assertEqual(len(matrix('macos')['include']), 8)

    def test_linux_user_diagnostic_covers_each_package_and_cpu_with_original_binaries(self):
        allowed = ['packaging/install.sh', 'packaging/lifecycle_linux.py',
                   '.github/workflows/build-release.yml', 'README.md']
        validate_changes(allowed, target='linux-user')
        for name in ('packaging/nfpm.yaml', 'packaging/LinuxBuilder.Dockerfile', 'flinteye_app/cli.py'):
            with self.assertRaises(ValueError):
                validate_changes([name], target='linux-user')
        cases = matrix('linux-user')['include']
        self.assertEqual({(case['method'], case['arch'], case['runner']) for case in cases}, {
            ('linux-deb-user-script', 'amd64', 'ubuntu-24.04'),
            ('linux-rpm-user-script', 'amd64', 'ubuntu-24.04'),
            ('linux-deb-user-script', 'arm64', 'ubuntu-24.04-arm'),
            ('linux-rpm-user-script', 'arm64', 'ubuntu-24.04-arm'),
        })

    def test_diagnostic_pass_cannot_become_publication_acceptance(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'FLINTEYE_QA_DIAGNOSTIC': '1'}):
            r = Report(Path(directory), method='windows-exe', release='1.2.0-preview.4', commit='a'*40)
            for name in STAGES: r.stage(name, 'passed', 'Diagnostic evidence')
            self.assertEqual(r.data['result'], 'passed')
            with self.assertRaisesRegex(ValueError, 'Diagnostic'):
                validate(r.data, release='1.2.0-preview.4', commit='a'*40)

    def test_script_overlay_keeps_the_original_binary_and_checks_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            package = p/'fixture.exe'; package.write_bytes(b'unchanged diagnostic installer fixture')
            (p/'validation-build.json').write_text(json.dumps({'commit': 'a'*40, 'release': release_identity()[0]}))
            (p/'SHA256SUMS').write_text(f'{digest(package)}  fixture.exe\n')
            original = digest(package)
            overlay(p, 'a'*40)
            self.assertEqual(digest(package), original)
            self.assertTrue(json.loads((p/'diagnostic-inputs.json').read_text())['diagnostic_only'])
            self.assertNotIn('@RELEASE_VERSION@', (p/'install.ps1').read_text())
            package.write_bytes(b'corrupted bytes')
            with self.assertRaisesRegex(ValueError, 'Original artifact changed'):
                overlay(p, 'a'*40)


if __name__ == '__main__': unittest.main()
