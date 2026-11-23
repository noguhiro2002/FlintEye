"""Event preservation with actual synthetic media and the managed retention index."""
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from flinteye_app.cli import initialize
from flinteye_app.flinteye_storage import cleanup, database
from flinteye_app.orchestrator_store import RuntimeStore
from flinteye_app.recording_archive import ArchiveError, ArchiveSettings, EventRequest, RecordingArchive
from flinteye_app.recording_events import file_evidence, record_event, recover_closed
import threading


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and FFprobe are required')
class RecordingArchiveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        runtime = initialize(self.root)
        self.store = RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False)
        self.store.patch_runtime({
            'cameras': [{'id': key, 'type': 'ip', 'path': key, 'display_name': f'Camera {key}',
                         'ip': {'source_url': 'rtsp://127.0.0.1/qa'}} for key in ('a', 'b')],
            'recording': {'record_delete_after': '1s', 'min_free_bytes': 0},
        })
        self.destination = self.root/'保全'
        self.destination.mkdir()
        self.archive = self.new_archive()
        self.token = self.archive.configure(ArchiveSettings(enabled=True, folder=str(self.destination)))['token']
        self.start = int(time.time()) - 100

    def new_archive(self):
        archive = RecordingArchive(self.root, str(self.root), self.store.get_effective, lambda: False)
        patcher = patch.object(archive, 'start')  # Tick deterministically while using the real disk and encoders.
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(archive.close)
        return archive

    def segment(self, camera, offset, color='red', *, audio=False, complete=True):
        date = datetime.fromtimestamp(self.start + offset, timezone.utc)
        path = self.root/'recordings'/camera/date.strftime('%Y-%m-%d')/(date.strftime('%H-%M-%S-%f_%z')+'.mp4')
        path.parent.mkdir(parents=True, exist_ok=True)
        command = ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi',
                   '-i', f'color={color}:size=96x64:rate=10:duration=2']
        if audio:
            command += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000:duration=2',
                        '-c:a', 'pcm_s16le', '-f', 'mov']
        subprocess.run([*command, '-c:v', 'libx264', '-threads', '1', str(path)], check=True, timeout=20)
        record_event(self.root, path, complete=False, session='fixture')
        if complete:
            with patch.dict('os.environ', {'MTX_SEGMENT_DURATION': '2'}):
                record_event(self.root, path, complete=True, session='fixture')
        return path

    def event(self, end, seconds, cameras=('a',), *, key='plc-error'):
        payload = EventRequest(camera_ids=list(cameras), lookback_sec=seconds,
                               occurred_at=datetime.fromtimestamp(self.start + end, timezone.utc).isoformat(),
                               label='設備エラー')
        return self.archive.submit(payload, self.token, key)

    def test_cuts_exact_window_across_segments_and_outlives_loop_cleanup(self):
        paths = [self.segment('a', 0, audio=True), self.segment('a', 2, 'blue', audio=True)]
        independent = self.segment('b', 0)
        accepted = self.event(4, 3)
        self.assertEqual(accepted['id'], self.event(4, 3)['id'])
        with self.assertRaisesRegex(ArchiveError, 'different event'):
            self.event(4, 2)
        rolling_config = self.store.get_effective()
        self.assertEqual(cleanup(self.root, rolling_config, str(self.root), now=time.time()+5), 1)
        self.assertFalse(independent.exists())
        self.assertTrue(all(path.is_file() for path in paths))

        self.archive.process_pending()
        event = self.archive.event_status(accepted['id'], self.token)
        self.assertEqual(event['status'], 'ready', event)
        clip, = event['clips']
        self.assertEqual((clip['started_at'], clip['ended_at']), (self.start+1, self.start+4))
        _, _, saved = self.archive.resolve(clip['file_id'])
        probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                         '-show_format', '-of', 'json', saved], timeout=10)
        info = json.loads(probe)
        self.assertAlmostEqual(float(info['format']['duration']), 3, delta=.1)
        audio = next(track for track in info['streams'] if track['codec_type']=='audio')
        self.assertEqual((audio['sample_rate'], audio['channels'], audio['bits_per_sample']), ('16000', 1, 16))
        for timestamp, expected_channel in [('0.2', 0), ('2.5', 2)]:
            pixels = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', timestamp, '-i', str(saved),
                '-frames:v', '1', '-vf', 'scale=2:2,format=rgb24', '-f', 'rawvideo', '-'], timeout=10)
            self.assertEqual(len(pixels), 12)
            self.assertGreater(pixels[expected_channel], 150)

        self.assertEqual(cleanup(self.root, rolling_config, str(self.root), now=time.time()+5), 2)
        reopened = self.new_archive()
        self.assertEqual(reopened.resolve(clip['file_id'])[2].read_bytes(), saved.read_bytes())

    def test_existing_event_can_be_listed_and_played_during_index_updates(self):
        self.segment('a', 0)
        accepted = self.event(2, 1)
        self.archive.process_pending()
        event = self.archive.event_status(accepted['id'], self.token)
        clip, = event['clips']
        reopened = self.new_archive()
        start = threading.Barrier(3, timeout=2)

        def read(operation, *args):
            start.wait()
            return operation(*args)

        with ThreadPoolExecutor(max_workers=2) as workers:
            with database(self.root) as index:
                index.execute('BEGIN EXCLUSIVE')
                listing = workers.submit(read, reopened.events)
                playback = workers.submit(read, reopened.resolve, clip['file_id'])
                start.wait()
                self.assertFalse(wait((listing, playback), timeout=.8).done)
            self.assertEqual(listing.result(timeout=3)[0]['id'], accepted['id'])
            self.assertTrue(playback.result(timeout=3)[2].is_file())

    def test_waits_for_open_tail_and_resumes_after_storage_returns(self):
        self.segment('a', 0)
        tail = self.segment('a', 2, complete=False)
        event = self.event(4, 3, cameras=('a', 'b'))
        with patch.object(self.archive, 'recording_running', return_value=True):
            self.archive.process_pending()
        self.assertEqual(self.archive.event_status(event['id'], self.token)['status'], 'waiting_recording')
        marker = self.destination/'.flinteye-event-archive'
        original = marker.read_bytes()
        marker.unlink()
        with patch.dict('os.environ', {'MTX_SEGMENT_DURATION': '2'}):
            record_event(self.root, tail, complete=True, session='fixture')
        future = time.time()+3
        with patch('flinteye_app.recording_archive.time.time', return_value=future):
            self.archive.process_pending()
            self.assertEqual(self.archive.event_status(event['id'], self.token)['status'], 'waiting_storage')
            marker.write_bytes(original)
            restarted = self.new_archive()
            restarted.process_pending()
        result = restarted.event_status(event['id'], self.token)
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual([clip['camera_id'] for clip in result['clips']], ['a'])

    def test_missing_hook_recovery_preserves_only_verified_segments(self):
        valid = self.segment('a', 0, complete=False)
        invalid = self.segment('b', 0, complete=False)
        invalid.write_bytes(b'not a recording')
        outcome = recover_closed(self.root, 'fixture', self.store.get_effective(),
                                 deadline=time.monotonic()+10, cancelled=threading.Event())
        self.assertEqual(outcome, {'recovered': 1, 'unreadable': 1, 'unavailable': 0})
        evidence = file_evidence(self.root, [valid, invalid])
        self.assertEqual(evidence[str(valid)]['completion_state'], 'recovered')
        self.assertEqual(evidence[str(valid)]['duration_sec'], 2)
        self.assertEqual(evidence[str(invalid)]['completion_state'], 'pending')
