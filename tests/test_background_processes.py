"""Keep Windows media subprocesses invisible while preserving their diagnostics."""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import Mock, patch

from flinteye_app.subprocess_utils import background_process_options, ensure_standard_streams
from flinteye_app.orchestrator_snapshot import SnapshotError, capture_snapshot_jpeg
from flinteye_app.orchestrator_uvc_probe import _run_capture
from flinteye_app.orchestrator_supervisor import ManagedProcess, OrchestratorSupervisor, _kill_process_tree_windows
from flinteye_app.orchestrator_logging import LogManager


class BackgroundProcessTests(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(patch('sys.platform', 'win32'))
        self.context.enter_context(patch.object(subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True))
        self.context.enter_context(patch.object(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200, create=True))

    def test_windows_flags_keep_group_termination_without_detaching_pipes(self):
        self.assertEqual(background_process_options(), {'creationflags': 0x08000000})
        self.assertEqual(background_process_options(new_process_group=True), {'creationflags': 0x08000200})
        for platform in ('darwin', 'linux'):
            with patch('sys.platform', platform):
                self.assertEqual(background_process_options(new_process_group=True), {})

    def test_usb_probe_and_periodic_snapshots_stay_hidden_and_keep_results(self):
        probe = subprocess.CompletedProcess(['ffmpeg'], 1, '', 'DirectShow device list')
        with patch('flinteye_app.orchestrator_uvc_probe.run_background', return_value=probe) as run:
            self.assertIs(_run_capture(['ffmpeg', '-list_devices', 'true'], 8), probe)
            self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)
            self.assertTrue(run.call_args.kwargs['capture_output'])
            self.assertEqual(run.call_args.kwargs['timeout'], 8)
        with patch('flinteye_app.orchestrator_snapshot.run_background', return_value=subprocess.CompletedProcess([], 0, b'jpeg', b'')) as run:
            self.assertEqual(capture_snapshot_jpeg(ffmpeg_bin='ffmpeg', rtsp_url='rtsp://127.0.0.1/test'), b'jpeg')
            self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)
        with patch('flinteye_app.orchestrator_snapshot.run_background', return_value=subprocess.CompletedProcess([], 1, b'', b'Connection refused')):
            with self.assertRaisesRegex(SnapshotError, 'Connection refused'):
                capture_snapshot_jpeg(ffmpeg_bin='ffmpeg', rtsp_url='rtsp://127.0.0.1/test')

    def test_managed_worker_keeps_credentials_in_stdin_and_output_in_log_pipe(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'logs').mkdir()
            supervisor = OrchestratorSupervisor(workspace_dir=directory, env_file='',
                                                 log_manager=LogManager(workspace_dir=directory))
            try:
                child = Mock(stdout=io.StringIO(''), stdin=io.StringIO())
                child.poll.return_value = None
                proc = ManagedProcess(key='camera:test', kind='camera',
                    command=['FlintEye.exe','--worker','ip_camera_to_rtsp',
                             '--source-url','rtsp://test:private-password@127.0.0.1/camera'])
                # Prevent the supervisor thread from racing with this isolated call.
                with patch('flinteye_app.orchestrator_supervisor.popen_background', return_value=child) as start:
                    supervisor._start_process(proc)
                kwargs = start.call_args.kwargs
                self.assertEqual(kwargs['creationflags'], 0x08000200)
                self.assertEqual(kwargs['stdout'], subprocess.PIPE)
                self.assertEqual(kwargs['stderr'], subprocess.STDOUT)
                self.assertEqual(kwargs['stdin'], subprocess.PIPE)
                self.assertNotIn('private-password', ' '.join(start.call_args.args[0]))
                self.assertIsNone(proc.last_error)
                if proc.output_thread:
                    proc.output_thread.join(timeout=2)
            finally:
                supervisor.shutdown()

    def test_stopping_windows_process_tree_does_not_open_a_console(self):
        with patch('flinteye_app.orchestrator_supervisor.run_background', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(_kill_process_tree_windows(123))
            self.assertEqual(run.call_args.args[0], ['taskkill','/PID','123','/T','/F'])
            self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)

    def test_windowed_worker_recovers_all_redirected_streams(self):
        streams = {name: io.StringIO() for name in ('stdin', 'stdout', 'stderr')}
        with patch('sys.stdin', None), patch('sys.stdout', None), patch('sys.stderr', None), \
             patch('flinteye_app.subprocess_utils._redirected_windows_stream', side_effect=streams.get) as recover:
            ensure_standard_streams()
            recovered = {name: getattr(sys, name) for name in streams}
            ensure_standard_streams()
        self.assertEqual(recovered, streams)
        self.assertEqual(recover.call_count, 3)

    def test_windowed_desktop_without_redirects_gets_safe_empty_streams(self):
        with patch('sys.stdin', None), patch('sys.stdout', None), patch('sys.stderr', None), \
             patch('flinteye_app.subprocess_utils._redirected_windows_stream', return_value=None):
            ensure_standard_streams()
            streams = [sys.stdin, sys.stdout, sys.stderr]
            try:
                self.assertEqual(sys.stdin.read(), '')
                sys.stdout.write('no console')
                sys.stderr.flush()
            finally:
                for stream in streams:
                    stream.close()


if __name__ == '__main__':
    unittest.main()
