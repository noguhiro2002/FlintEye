"""Local builds preserve source provenance and do not certify failed artifacts."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'packaging'))
import build_macos_local as build


class LocalMacBuildTests(unittest.TestCase):
    def test_snapshot_excludes_ignored_settings_and_build_products(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*arguments):
                return subprocess.check_output(['git', *arguments], cwd=root, text=True, stderr=subprocess.STDOUT).strip()
            git('init')
            (root / '.gitignore').write_text('dist/\nruntime.json\n')
            (root / 'app.py').write_text('print("committed version")\n')
            git('add', '.gitignore', 'app.py')
            git('-c', 'user.name=Build test', '-c', 'user.email=build@example.invalid', 'commit', '-m', 'fixture')
            (root / 'runtime.json').write_text('private runtime fixture')
            (root / 'dist').mkdir()
            (root / 'dist/stale.dmg').write_bytes(b'stale')
            destination = root / 'dist/build/source'
            # output's default cwd is the real repository; pass the fixture explicitly.
            actual_output = build.output
            with patch.object(build, 'ROOT', root), patch.object(build, 'output',
                    side_effect=lambda command, env: actual_output(command, env, root)):
                commit = build.snapshot(destination, dict(os.environ))
                self.assertEqual(commit, git('rev-parse', 'HEAD'))
                self.assertEqual((destination / 'app.py').read_text(), (root / 'app.py').read_text())
                self.assertFalse((destination / 'runtime.json').exists())
                self.assertFalse((destination / 'dist').exists())
                (root / 'app.py').write_text('uncommitted change')
                with self.assertRaisesRegex(RuntimeError, 'clean checkout'):
                    build.snapshot(root / 'dist/another/source', dict(os.environ))

    def test_verified_collection_records_commit_and_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            (source / 'dist').mkdir(parents=True)
            for suffix in ('.dmg', '-sources.tar.gz', '-licenses.zip', '-signature.json'):
                (source / f'dist/FlintEye-1.1.1-macos-arm64{suffix}').write_bytes(suffix.encode())
            (source / 'dist/vendor-sha256.json').write_text('{}')
            artifacts = root / 'artifacts'
            dmg = build.collect_artifacts(source, artifacts, 'a' * 40, {'python': '3.14.10'}, '1.1.1')
            self.assertEqual(dmg.name, 'FlintEye-1.1.1-local-aaaaaaaaaaaa-macos-arm64.dmg')
            receipt = json.loads((artifacts / 'build-info.json').read_text())
            self.assertEqual(receipt['commit'], 'a' * 40)
            self.assertIn('desktop-settings', receipt['pending'])
            for line in (artifacts / 'SHA256SUMS').read_text().splitlines():
                expected, name = line.split('  ')
                self.assertEqual(hashlib.sha256((artifacts / name).read_bytes()).hexdigest(), expected)

    def test_failed_build_never_collects_verified_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def snapshot(destination, env):
                destination.mkdir(parents=True)
                return 'a' * 40
            with patch.object(build, 'ROOT', root), patch.object(build, 'preflight', return_value={}), \
                 patch.object(build, 'snapshot', side_effect=snapshot), \
                 patch.object(build, 'run', side_effect=subprocess.CalledProcessError(1, ['build'])), \
                 patch.object(build, 'collect_artifacts') as collect, \
                 patch.object(sys, 'argv', ['build_macos_local.py']), redirect_stderr(io.StringIO()):
                self.assertEqual(build.main(), 1)
                collect.assert_not_called()
            self.assertEqual(len(list(root.glob('dist/local-macos/*/build.log'))), 1)

    def test_preflight_only_does_not_download_or_build(self):
        with patch.object(build, 'preflight', return_value={'macos': 'test'}), \
             patch.object(build, 'snapshot') as snapshot, patch.object(build, 'run') as run, \
             patch.object(sys, 'argv', ['build_macos_local.py', '--check-only']), redirect_stdout(io.StringIO()):
            self.assertEqual(build.main(), 0)
            snapshot.assert_not_called()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
