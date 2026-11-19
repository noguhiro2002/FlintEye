"""Diagnostic rechecks must never weaken immutable release evidence."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'packaging'))
from recheck_installers import matrix, validate_changes, overlay
from lifecycle_report import Report, STAGES, validate
from release_lib import digest, release_identity


class RecheckTests(unittest.TestCase):
    def test_test_only_revision_cannot_hide_changed_binary_inputs(self):
        validate_changes(['packaging/lifecycle.py', '.github/workflows/recheck-installers.yml', 'docs/INSTALLATION_QA.md'])
        for name in ['flinteye_app/cli.py', 'frontend/src/App.tsx', 'packaging/build_bundle.py',
                     'requirements.txt', 'images/icons/flinteye.icns', 'docs/../flinteye_app/cli.md']:
            with self.assertRaises(ValueError): validate_changes([name])
        self.assertEqual(len(matrix('all')['include']), 12)
        self.assertEqual(len(matrix('windows')['include']), 4)
        self.assertEqual(len(matrix('macos')['include']), 8)

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
