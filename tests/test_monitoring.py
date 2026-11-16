"""Monitoring intent, health evidence, finalization and desktop boundaries."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from flinteye_app import cli, recording_events
from flinteye_app.monitoring import MonitoringConflict
from flinteye_app.orchestrator_api import AppContext, _apply_running_media_config
from flinteye_app.orchestrator_auth import hash_password
from flinteye_app.orchestrator_models import RuntimeConfig
from flinteye_app.orchestrator_supervisor import ManagedProcess


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cli.initialize(self.root)
        self.context = AppContext(env_file='', runtime_file=str(self.root/'runtime.json'), no_env=True)
        self.controller = self.context.monitoring
        self.context.store.patch_runtime({'auth': {'session_secret': 'a' * 64, 'local': {'admin': {'username': 'admin', 'password_hash': hash_password('example-password')}}},
            'cameras': [{'id': 'cam', 'type': 'uvc', 'path': 'cam', 'enabled': True}],
            'recording': {'min_free_bytes': 0}})
        self.stack = ExitStack()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.context.shutdown)
        self.addCleanup(self.stack.close)
        # Exercise real supervisor gating but never launch a real camera in a unit test.
        self.spawn = self.stack.enter_context(patch.object(self.context.supervisor, '_start_process'))
        self.stack.enter_context(patch('flinteye_app.monitoring.FINALIZE_SECONDS', .06))

    def complete_file(self, name='00-00-00-000000', *, complete=True):
        file = self.root/'recordings/cam/2026-11-15'/f'{name}.mp4'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'completed-media-placeholder')
        recording_events.record_event(self.root, file, complete=False, session=self.controller.session)
        if complete:
            recording_events.record_event(self.root, file, complete=True, session=self.controller.session)
        return file

    def test_stop_survives_config_save_reconcile_and_recovery(self):
        self.assertTrue(self.controller.perform('stop')['ok'])
        self.spawn.reset_mock()
        config = self.context.store.get_effective()
        self.context.supervisor.reconcile(config, force_restart=True)
        self.context.supervisor.mediamtx_restart(config)
        self.context.supervisor.restart_camera(config, 'cam')
        self.context.supervisor.restart_multiview(config)
        _apply_running_media_config(self.context, config, force_restart=True)
        self.spawn.assert_not_called()
        saved = json.loads((self.root/'monitoring.json').read_text())
        self.assertFalse(saved['desired_running'])
        self.assertFalse(saved['resume_on_startup'])

    def test_restart_while_stopped_requires_explicit_start(self):
        self.controller.perform('stop')
        with self.assertRaises(MonitoringConflict):
            self.controller.perform('restart')
        self.assertFalse(self.controller.desired)

    def test_preferences_survive_restart_and_resume_is_optional(self):
        self.controller.perform('stop')
        from flinteye_app.monitoring import MonitoringController
        restored = MonitoringController(self.context)
        self.assertFalse(restored.desired)
        restored.set_resume_on_startup(True)
        restarted = MonitoringController(self.context)
        self.assertTrue(restarted.desired)
        self.assertTrue(restarted.resume_on_startup)

    def test_corrupt_saved_stop_does_not_start_cameras(self):
        (self.root/'monitoring.json').write_text('{broken')
        from flinteye_app.monitoring import MonitoringController
        restored = MonitoringController(self.context)
        self.assertFalse(restored.desired)
        self.assertIn('Could not read', restored.error)

    def test_quit_does_not_change_monitoring_preference(self):
        self.controller._save()
        self.controller.perform('quit')
        self.assertTrue(json.loads((self.root/'monitoring.json').read_text())['desired_running'])
        self.assertFalse(self.context.supervisor._monitoring_enabled)

    def test_overlapping_actions_do_not_queue_a_surprise_restart(self):
        with self.controller.operation:
            for action in ('start', 'stop', 'restart'):
                with self.assertRaises(MonitoringConflict):
                    self.controller.perform(action)

    def test_health_requires_progress_and_stall_turns_red(self):
        start = time.monotonic()
        self.controller.started_mono = start - 20
        self.controller.phase = 'running'
        self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': 10}], now=start)
        self.assertNotEqual(self.controller.status()['color'], 'green')
        self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': 100}], now=start+2)
        self.assertEqual(self.controller.status()['color'], 'green')
        self.assertEqual(self.controller.status()['counts']['recording'], 0)
        self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': 100}], now=start+18)
        self.assertEqual(self.controller.status()['color'], 'red')
        self.assertEqual(self.controller.status()['counts']['receiving'], 0)
        self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': 5}], now=start+19)
        self.assertNotEqual(self.controller.status()['color'], 'green')
        self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': 500}], now=start+21)
        self.assertEqual(self.controller.status()['color'], 'green')

    def test_partial_camera_failure_and_missing_media_api(self):
        config = self.context.store.get_effective()
        other = config.cameras[0].model_copy(update={'id': 'other', 'path': 'other'})
        self.context.store.patch_runtime({'cameras': [c.model_dump() for c in [config.cameras[0], other]]})
        self.controller.started_mono = time.monotonic()-30
        for count in (1, 10):
            self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': count}])
        self.assertEqual(self.controller.status()['state'], 'warning')
        self.assertEqual(self.controller.status()['counts']['receiving'], 1)
        with patch('flinteye_app.monitoring.media_paths', side_effect=OSError), patch.object(self.context.supervisor, 'mediamtx_status', return_value={'running': True}):
            self.controller.refresh()
        self.assertEqual(self.controller.status()['state'], 'unknown')
        self.assertEqual(self.controller.status()['counts']['receiving'], 0)

    def test_recovered_path_requires_new_counter_progress(self):
        for count in (1, 10):
            self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': count}])
        self.assertEqual(self.controller.status()['counts']['receiving'], 1)
        self.controller.refresh(items=[{'name': 'cam', 'ready': False}])
        for _ in range(2):
            self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': 100}])
            self.assertEqual(self.controller.status()['counts']['receiving'], 0)
        self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': 101}])
        self.assertEqual(self.controller.status()['counts']['receiving'], 1)

    def test_stop_status_does_not_reuse_last_running_snapshot(self):
        self.controller.phase = 'running'
        for count in (1, 10):
            self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': count}])
        self.assertEqual(self.controller.status()['color'], 'green')
        self.assertTrue(self.controller.perform('stop')['ok'])
        status = self.controller.status()
        self.assertEqual(status['state'], 'stopped')
        self.assertEqual(status['counts']['receiving'], 0)
        self.assertFalse(status['cameras'][0]['receiving'])

    def test_restart_waits_for_fresh_reception_evidence(self):
        self.controller.phase = 'running'
        for count in (1, 10):
            self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': count}])
        self.assertEqual(self.controller.status()['color'], 'green')
        with patch.object(self.context.supervisor, 'mediamtx_start', return_value={'ok': True}):
            self.assertTrue(self.controller.perform('restart')['ok'])
        self.assertEqual(self.controller.status()['state'], 'starting')
        self.assertEqual(self.controller.status()['counts']['receiving'], 0)
        self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': 100}])
        self.assertNotEqual(self.controller.status()['color'], 'green')
        self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': 101}])
        self.assertEqual(self.controller.status()['color'], 'green')

    def test_storage_warning_does_not_hide_a_media_server_failure(self):
        self.context.storage_problem = 'Recording storage is unavailable'
        with patch('flinteye_app.monitoring.media_paths', side_effect=OSError), patch.object(self.context.supervisor, 'mediamtx_status', return_value={'running': False}):
            self.controller.refresh()
        self.assertEqual(self.controller.status()['state'], 'error')
        self.assertEqual(self.controller.status()['color'], 'red')

    def test_no_camera_and_intentional_stop_are_distinct(self):
        self.controller.perform('stop')
        self.controller.refresh(items=[])
        self.assertEqual(self.controller.status()['state'], 'stopped')
        self.context.store.patch_runtime({'cameras': []})
        self.controller.refresh(items=[])
        self.assertEqual(self.controller.status()['color'], 'gray')

    def test_quit_after_relaunching_a_stopped_profile_never_waits_for_old_writers(self):
        self.controller.perform('stop')
        self.context.store.patch_runtime({'recording': {'record_paths': ['cam']}})
        from flinteye_app.monitoring import MonitoringController
        restored = MonitoringController(self.context)
        self.addCleanup(restored.close)
        restored.startup()
        self.assertTrue(restored.started)
        self.assertFalse(restored.tracking_configured)
        self.assertFalse(restored.desired)
        self.assertTrue(restored.perform('quit')['ok'])
        receipt = json.loads((self.root/'last-monitoring-stop.json').read_text())
        self.assertTrue(receipt['ok'])
        self.assertFalse(receipt['forced'])

    def test_interrupted_stop_is_not_promoted_to_a_clean_stop_on_relaunch(self):
        self.controller.perform('stop')
        saved = json.loads((self.root/'monitoring.json').read_text())
        saved['clean_stop'] = False
        (self.root/'monitoring.json').write_text(json.dumps(saved))
        from flinteye_app.monitoring import MonitoringController
        restored = MonitoringController(self.context)
        self.addCleanup(restored.close)
        restored.startup()
        self.assertFalse(restored.perform('quit')['ok'])
        receipt = json.loads((self.root/'last-monitoring-stop.json').read_text())
        self.assertFalse(receipt['ok'])
        self.assertTrue(restored.status()['previous_stop_unknown'])
        self.assertFalse(restored.perform('quit', force=True)['ok'])
        receipt = json.loads((self.root/'last-monitoring-stop.json').read_text())
        self.assertTrue(receipt['forced'])
        self.assertFalse(receipt['ok'])

    def test_delayed_complete_must_be_indexed_before_media_stops(self):
        file = self.complete_file(complete=False)
        events = []
        def complete(*, deadline=None):
            events.append('publishers-stopped')
            recording_events.record_event(self.root, file, complete=True, session=self.controller.session)
        with patch.object(self.context.supervisor, 'pause_media_publishers', side_effect=complete), \
             patch.object(self.context.supervisor, 'mediamtx_stop', side_effect=lambda config: events.append('media-stopped') or {'ok': True}):
            self.assertTrue(self.controller.perform('stop')['ok'])
        self.assertEqual(events, ['publishers-stopped', 'media-stopped'])
        self.assertEqual(recording_events.summary(self.root, self.controller.session)['pending_segments'], 0)

    def test_missing_callback_timeout_keeps_recorder_and_retry_completes(self):
        file = self.complete_file(complete=False)
        with patch.object(self.context.supervisor, 'mediamtx_stop', return_value={'ok': True}) as stop:
            result = self.controller.perform('stop')
            self.assertFalse(result['ok'])
            stop.assert_not_called()
            self.assertEqual(self.controller.phase, 'finalizing')
            with self.assertRaises(MonitoringConflict):
                self.controller.perform('start')
            recording_events.record_event(self.root, file, complete=True, session=self.controller.session)
            self.assertTrue(self.controller.perform('stop')['ok'])
            stop.assert_called_once()
        self.assertFalse(self.controller.desired)

    def test_missing_create_hook_still_detects_unindexed_file(self):
        file = self.root/'recordings/cam/2026-11-15/00-00-00-000000.mp4'
        file.parent.mkdir(parents=True)
        file.write_bytes(b'incomplete')
        result = self.controller.perform('stop')
        self.assertFalse(result['ok'])
        self.assertEqual(result['pending_segments'], 1)

    def test_force_quit_receipt_does_not_claim_finalized(self):
        self.complete_file(complete=False)
        with patch.object(self.context.supervisor, 'mediamtx_stop', return_value={'ok': True}):
            result = self.controller.perform('quit', force=True)
        self.assertFalse(result['ok'])
        receipt = json.loads((self.root/'last-monitoring-stop.json').read_text())
        self.assertTrue(receipt['forced'])
        self.assertFalse(receipt['ok'])
        self.assertTrue(self.controller.quitting)

    def test_create_after_complete_cannot_reopen_segment(self):
        file = self.complete_file()
        recording_events.record_event(self.root, file, complete=False, session=self.controller.session)
        state = recording_events.summary(self.root, self.controller.session)
        self.assertEqual(state['pending_segments'], 0)
        self.assertEqual(state['active_streams'], [])

    def test_recording_count_uses_events_and_reception_not_enabled_flag(self):
        self.complete_file(complete=False)
        for count in (1, 10):
            self.controller.refresh(items=[{'name': 'cam', 'ready': True, 'bytesReceived': count}])
        self.assertEqual(self.controller.status()['counts']['recording'], 1)
        self.controller.desired = False
        self.controller.refresh(items=[])
        self.assertEqual(self.controller.status()['counts']['recording'], 0)

    def test_headless_detection_and_explicit_override(self):
        with patch('sys.platform', 'linux'), patch.dict(os.environ, {}, clear=True):
            self.assertFalse(cli.desktop_available())
            os.environ['DISPLAY'] = ':99'
            self.assertTrue(cli.desktop_available())
            os.environ['FLINTEYE_HEADLESS'] = '1'
            self.assertFalse(cli.desktop_available())


if __name__ == '__main__':
    unittest.main()
