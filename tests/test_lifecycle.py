"""Keep partial installation checks from becoming claimed GUI acceptance."""
import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'packaging'))
from lifecycle import owned_profile, remove_owned_profile
from lifecycle_common import seed_runtime
from lifecycle_report import Report, STAGES, validate, collect, required_matrix
from verify_macos import verify_structure
from public_install_inputs import validate_manifest


class LifecycleTests(unittest.TestCase):
    def test_complete_report_requires_every_stage_and_matching_build(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Report(Path(directory), method='windows-exe', release='1.2.0-preview.4', commit='a'*40)
            with self.assertRaises(ValueError): validate(report.data, release='1.2.0-preview.4', commit='a'*40)

            for stage in STAGES: report.stage(stage, 'passed', 'Actual check log')
            self.assertEqual(validate(report.data, release='1.2.0-preview.4', commit='a'*40), 'passed')
            with self.assertRaises(ValueError): validate(report.data, release='1.2.0-preview.4', commit='b'*40)
            report.stage('quit', 'failed', 'Owned process survived')
            with self.assertRaises(ValueError): validate(report.data, release='1.2.0-preview.4', commit='a'*40)

    def test_missing_platform_matrix_cannot_be_published(self):
        self.assertEqual(len(required_matrix()), 32)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'Missing lifecycle cases'):
                collect(Path(directory), release='1.2.0-preview.4', commit='a'*40)

    def test_public_download_provenance_must_match_release_and_source(self):
        value = {'schema': 1, 'tag': 'v1.2.0-preview.4', 'commit': 'a'*40,
                 'image': 'ghcr.io/noguhiro2002/flinteye:1.2.0-preview.4'}
        validate_manifest(value, release='1.2.0-preview.4', commit='a'*40)
        for changed in ({'commit': 'b'*40}, {'tag': 'v1.2.0-preview.3'}, {'image': 'other/image:latest'}):
            with self.assertRaises(ValueError): validate_manifest({**value, **changed}, release='1.2.0-preview.4', commit='a'*40)

    def test_macos_approval_cannot_claim_gui_or_normal_quit(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Report(Path(directory), method='macos-script', release='1.2.0-preview.4', commit='a'*40)
            report.data['platform'] = 'darwin'
            for stage in ('install', 'integrity', 'uninstall'): report.stage(stage, 'passed', 'Actual check log')
            report.stage('os_launch', 'manual-required', 'amfid explicitly denied adhoc execution')
            self.assertFalse(report.data['complete'])
            self.assertEqual(validate(report.data, release='1.2.0-preview.4', commit='a'*40), 'manual-required')
            report.data['complete'] = True
            with self.assertRaises(ValueError): validate(report.data, release='1.2.0-preview.4', commit='a'*40)
            report.data['complete'] = False
            report.stage('api_gui', 'passed', 'Not actually tested')
            with self.assertRaises(ValueError): validate(report.data, release='1.2.0-preview.4', commit='a'*40)

    def test_existing_profile_and_unowned_removal_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'real-data'; path.mkdir(); (path/'recording').write_text('keep')
            with self.assertRaises(RuntimeError): owned_profile(path)
            with self.assertRaises(RuntimeError): remove_owned_profile(path)
            self.assertEqual((path/'recording').read_text(), 'keep')
            own = Path(directory)/'qa'; owned_profile(own)
            remove_owned_profile(own); self.assertFalse(own.exists())

    def test_runtime_uses_private_ports_without_shared_data(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)/'qa'; owned_profile(profile)
            port = seed_runtime(profile, str(profile), '/owned/media/mediamtx')
            runtime = json.loads((profile/'runtime.json').read_text())
            self.assertEqual(runtime['api']['port'], port)
            self.assertEqual(runtime['cameras'], [])
            self.assertNotEqual(runtime['mediamtx']['rtsp_base_url'], 'rtsp://127.0.0.1:8554')
            self.assertEqual(seed_runtime(profile, str(profile), '/owned/media/mediamtx'), port)

    def test_macos_declared_executable_and_link_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)/'FlintEye.app'; contents = app/'Contents'
            (contents/'MacOS').mkdir(parents=True)
            info = contents/'Info.plist'
            info.write_bytes(plistlib.dumps({'CFBundleExecutable': 'FlintEye', 'CFBundlePackageType': 'APPL'}))
            with self.assertRaisesRegex(RuntimeError, 'missing'): verify_structure(app)
            executable = contents/'MacOS/FlintEye'; executable.write_bytes(b'fake executable for structure test'); executable.chmod(0o755)
            verify_structure(app)
            link = contents/'bad-link'
            try: link.symlink_to(Path(directory)/'outside')
            except (OSError, NotImplementedError): self.skipTest('Symlink creation unavailable')
            (Path(directory)/'outside').write_text('outside')
            with self.assertRaisesRegex(RuntimeError, 'outside-bundle'): verify_structure(app)
            link.unlink(); link.symlink_to('missing')
            with self.assertRaisesRegex(RuntimeError, 'Broken'): verify_structure(app)


if __name__ == '__main__': unittest.main()
