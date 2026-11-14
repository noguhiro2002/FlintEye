from __future__ import annotations

import json
import logging
import plistlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flinteye_app.cli import enable_autostart, initialize
from flinteye_app.orchestrator_logging import LogManager, infer_line_level
from flinteye_app.orchestrator_models import RuntimeConfig
from flinteye_app.orchestrator_store import RuntimeStore
from flinteye_app.orchestrator_supervisor import OrchestratorSupervisor


class BundledMediaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='FlintEye moved bundle ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / 'Application Support/FlintEye'
        self.old = self.binary('AppTranslocation/old/d')
        self.new = self.binary('Applications')

    def binary(self, parent):
        directory = self.root / parent / 'FlintEye.app/Contents/Frameworks'
        (directory / 'bin').mkdir(parents=True)
        (directory / 'bin/mediamtx').write_bytes(b'test executable')
        return directory

    def launch(self, directory):
        with patch('sys.platform', 'darwin'), patch('sys.frozen', True, create=True), \
             patch('flinteye_app.cli.application_dir', return_value=directory):
            return initialize(self.profile)

    def test_app_translocation_path_is_repaired_without_resetting_user_data(self):
        runtime = self.launch(self.old)
        store = RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False)
        (self.root / 'custom recordings').mkdir()
        store.patch_runtime({'auth': {'session_secret': 'preserve-private-secret'},
                             'recording': {'record_root': str(self.root / 'custom recordings')},
                             'cameras': [{'id': 'keep', 'path': 'keep', 'type': 'uvc', 'enabled': False}]})
        before = json.loads(runtime.read_text())
        (self.old / 'bin/mediamtx').unlink()
        recording = self.profile / 'recordings/keep.mp4'
        recording.write_bytes(b'existing recording')
        self.launch(self.new)
        after = json.loads(runtime.read_text())
        expected = json.loads(json.dumps(before))
        expected['mediamtx']['direct']['command'][0] = str(self.new / 'bin/mediamtx')
        self.assertEqual(after, expected)
        self.assertEqual(recording.read_bytes(), b'existing recording')
        unchanged = runtime.read_bytes()
        self.launch(self.new)
        self.assertEqual(runtime.read_bytes(), unchanged)

    def test_custom_commands_and_config_paths_are_preserved(self):
        runtime = self.launch(self.old)
        store = RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False)
        for command in ([str(self.root/'custom/bin/mediamtx'), str(self.profile/'mediamtx.yml')],
                        [str(self.old/'bin/mediamtx'), str(self.root/'custom.yml')],
                        [str(self.old/'bin/mediamtx'), str(self.profile/'mediamtx.yml'), '--custom']):
            with self.subTest(command=command):
                store.patch_runtime({'mediamtx': {'direct': {'command': command}}})
                before = runtime.read_bytes()
                self.launch(self.new)
                self.assertEqual(runtime.read_bytes(), before)

    def test_missing_bundled_media_never_silently_uses_a_system_binary(self):
        runtime = self.launch(self.old)
        before = runtime.read_bytes()
        (self.new/'bin/mediamtx').unlink()
        with self.assertRaisesRegex(FileNotFoundError, 'Bundled MediaMTX is missing'):
            self.launch(self.new)
        self.assertEqual(runtime.read_bytes(), before)

    def test_source_configuration_is_not_migrated(self):
        runtime = self.launch(self.old)
        before = runtime.read_bytes()
        with patch('sys.frozen', False, create=True):
            initialize(self.profile)
        self.assertEqual(runtime.read_bytes(), before)

    def test_upgrade_disables_unused_moq_without_overwriting_explicit_choices(self):
        runtime = self.launch(self.old)
        data = json.loads(runtime.read_text())
        self.assertIs(data['mediamtx']['managed']['global']['moq'], False)
        del data['mediamtx']['managed']['global']['moq']
        runtime.write_text(json.dumps(data))
        self.launch(self.new)
        upgraded = json.loads(runtime.read_text())
        self.assertIs(upgraded['mediamtx']['managed']['global']['moq'], False)
        upgraded['mediamtx']['managed']['global']['moq'] = True
        runtime.write_text(json.dumps(upgraded))
        self.launch(self.new)
        self.assertIs(json.loads(runtime.read_text())['mediamtx']['managed']['global']['moq'], True)

    def test_incomplete_new_bundle_can_be_reinstalled_without_resetting_profile(self):
        binary = self.new/'bin/mediamtx'
        binary.unlink()
        with self.assertRaisesRegex(FileNotFoundError, 'Bundled MediaMTX is missing'):
            self.launch(self.new)
        self.assertFalse((self.profile/'runtime.json').exists())
        self.assertFalse((self.profile/'recordings').exists())
        binary.write_bytes(b'restored executable')
        self.assertTrue(self.launch(self.new).is_file())

    def test_mac_autostart_does_not_persist_translocated_executable(self):
        with patch('sys.platform', 'darwin'), patch('sys.frozen', True, create=True), \
             patch('flinteye_app.cli.Path.home', return_value=self.root), \
             patch('sys.executable', str(self.old.parent/'MacOS/FlintEye')):
            enable_autostart()
        data = plistlib.loads((self.root/'Library/LaunchAgents/community.flinteye.plist').read_bytes())
        self.assertEqual(data['ProgramArguments'],
                         ['/usr/bin/open', '-b', 'community.flinteye', '--args', '--background'])
        self.assertTrue(data['RunAtLoad'])


class MediaFailureTests(unittest.TestCase):
    def test_spawn_failure_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor = OrchestratorSupervisor(workspace_dir=directory, env_file='',
                                                log_manager=LogManager(workspace_dir=directory))
            try:
                config = RuntimeConfig.model_validate({'mediamtx': {'control_mode': 'direct',
                    'direct': {'command': [str(Path(directory)/'missing-mediamtx')]}}})
                with self.assertLogs('orchestrator.supervisor', level='ERROR'):
                    result = supervisor.mediamtx_start(config)
                self.assertFalse(result['ok'])
                self.assertIn('missing-mediamtx', result['stderr'])
                status = supervisor.mediamtx_status(config)
                self.assertFalse(status['running'])
                self.assertIn('missing-mediamtx', status['detail'])
            finally:
                supervisor.shutdown()

    def test_media_errors_are_not_filtered_out_at_default_log_level(self):
        for line in ('ERR: invalid configuration', '2026/11/14 22:19:28 ERR listen tcp: address already in use'):
            self.assertEqual(infer_line_level(line), logging.ERROR)
        self.assertEqual(infer_line_level('2026/11/14 22:19:28 WRN warning'), logging.WARNING)
        self.assertEqual(infer_line_level('2026/11/14 22:19:28 INF started'), logging.INFO)
