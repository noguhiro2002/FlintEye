"""Preserve an incident interval from FlintEye-managed recording segments."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator

from flinteye_app import recording_events
from flinteye_app.flinteye_storage import database, locations
from flinteye_app.orchestrator_logging import parse_duration_to_seconds
from flinteye_app.process_lifetime import popen_background
from flinteye_app.subprocess_utils import background_process_options

logger = logging.getLogger(__name__)
ACTIVE = ('waiting_recording', 'waiting_storage', 'processing')
ARCHIVE_MARKER = '.flinteye-event-archive'
EVENT_ID = re.compile(r'[0-9a-f]{32}')
MAX_PENDING = 32


class ArchiveError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class ArchiveSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    folder: str = Field(max_length=4096)
    max_lookback_sec: StrictInt = Field(default=600, ge=1, le=3600)
    rotate_token: bool = False


class EventRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    camera_ids: list[str] = Field(min_length=1, max_length=32)
    lookback_sec: StrictInt = Field(ge=1, le=3600)
    occurred_at: AwareDatetime | None = None
    label: str = Field(default='', max_length=200)

    @field_validator('occurred_at', mode='before')
    @classmethod
    def timestamp_string(cls, value):
        if value is not None and not isinstance(value, str):
            raise ValueError('Use an ISO 8601 timestamp with a UTC offset')
        return value


@dataclass(frozen=True)
class Span:
    path: Path
    source_start: float
    start: float
    end: float
    fingerprint: tuple[int, int]


def _create_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS archive_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER, folder TEXT, marker TEXT,
        token_hash TEXT, max_lookback INTEGER)''')
    db.execute('CREATE TABLE IF NOT EXISTS archive_folders (folder TEXT PRIMARY KEY, marker TEXT)')
    db.execute('''CREATE TABLE IF NOT EXISTS archive_events (
        id TEXT PRIMARY KEY, token_hash TEXT, request_key TEXT, request_hash TEXT,
        received REAL, start REAL, end REAL, wait_until REAL, label TEXT, folder TEXT,
        marker TEXT, roots TEXT, cameras TEXT, status TEXT, detail TEXT, clips TEXT,
        UNIQUE(token_hash, request_key))''')


def _has_table(db, name):
    return db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', name)).fetchone() is not None


def _read_index(data: Path):
    # Retention and segment completion can briefly hold the index during startup.
    return database(data, timeout=3, initialize=False)


def configured_folders(data: Path) -> set[Path]:
    if not (data/'recordings.sqlite3').is_file():
        return set()
    with _read_index(data) as db:
        if not _has_table(db, 'archive_settings'):
            return set()
        return {Path(row[0]) for row in db.execute(
            "SELECT folder FROM archive_settings WHERE folder<>'' UNION SELECT folder FROM archive_events")}


def source_reservations(db, directory: Path):
    """Read reservations while the retention deletion transaction owns the index."""
    if not _has_table(db, 'archive_events'):
        return []
    rows = db.execute("SELECT start, end, roots, cameras FROM archive_events "
                      "WHERE status IN (?, ?, ?)", ACTIVE)
    return [(start, end, {camera['stream'] for camera in json.loads(cameras)})
            for start, end, roots, cameras in rows if str(directory) in json.loads(roots)]


def _safe_directory(folder: str, marker: str) -> Path:
    root = Path(folder)
    identity = root/ARCHIVE_MARKER
    if (root.resolve() != root or not root.is_dir() or identity.is_symlink()
            or identity.read_text(encoding='ascii').strip() != marker):
        raise OSError('The configured event recording volume is unavailable')
    return root


def _stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _public_event(row: sqlite3.Row) -> dict:
    return {'id': row['id'], 'label': row['label'], 'occurred_at': row['end'],
            'received_at': row['received'], 'requested_from': row['start'],
            'lookback_sec': round(row['end'] - row['start']), 'status': row['status'],
            'detail': row['detail'], 'cameras': json.loads(row['cameras']),
            'clips': json.loads(row['clips'])}


class RecordingArchive:
    def __init__(self, root: Path, workspace: str, config, recording_running):
        self.root = root
        self.workspace = workspace
        self.config = config
        self.recording_running = recording_running
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.thread is None and not self.stopping.is_set():
                self.thread = threading.Thread(target=self._loop, name='event-recordings', daemon=True)
                self.thread.start()

    def close(self):
        self.stopping.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout=3)

    def _settings(self, db):
        if not _has_table(db, 'archive_settings'):
            return None
        return db.execute('SELECT * FROM archive_settings WHERE id=1').fetchone()

    def settings(self) -> dict:
        if not (self.root/'recordings.sqlite3').exists():
            return {'enabled': False, 'folder': '', 'token_configured': False, 'max_lookback_sec': 600}
        with _read_index(self.root) as db:
            db.row_factory = sqlite3.Row
            row = self._settings(db)
        if row is None:
            return {'enabled': False, 'folder': '', 'token_configured': False, 'max_lookback_sec': 600}
        return {'enabled': bool(row['enabled']), 'folder': row['folder'],
                'token_configured': bool(row['token_hash']), 'max_lookback_sec': row['max_lookback']}

    def configure(self, requested: ArchiveSettings) -> dict:
        config = self.config()
        folder = requested.folder.strip()
        if requested.enabled and not folder:
            raise ArchiveError(422, 'Choose an existing event recording folder')
        marker = ''
        if folder:
            destination = Path(folder).expanduser()
            if not destination.is_absolute() or not destination.is_dir():
                raise ArchiveError(422, 'Choose an existing absolute folder on the FlintEye server')
            destination = destination.resolve()
            folder = str(destination)
            for loop_root, _, _ in locations(config, self.workspace):
                if destination.is_relative_to(loop_root) or loop_root.is_relative_to(destination):
                    raise ArchiveError(422, 'The event recording folder and loop recording folders must be separate')
            executable = Path(os.sys.executable).resolve()
            program = next((parent for parent in executable.parents if parent.suffix == '.app'), executable.parent)
            if destination.is_relative_to(program) or program.is_relative_to(destination):
                # Python installations and frozen program folders are disposable.
                raise ArchiveError(422, 'Choose an event folder outside the program directory')
        with database(self.root, timeout=1) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            _create_tables(db)
            previous = self._settings(db)
            if folder:
                known = db.execute('SELECT marker FROM archive_folders WHERE folder=?', (folder,)).fetchone()
                if known:
                    marker = known['marker']
                if marker:
                    try:
                        _safe_directory(folder, marker)
                    except OSError as error:
                        raise ArchiveError(422, 'Reconnect the original event recording volume') from error
                else:
                    marker = uuid4().hex
                    try:
                        with (Path(folder)/ARCHIVE_MARKER).open('x', encoding='ascii') as stream:
                            stream.write(marker+'\n')
                        db.execute('INSERT INTO archive_folders VALUES (?, ?)', (folder, marker))
                    except OSError as error:
                        raise ArchiveError(422, 'The event folder is not writable or belongs to another profile') from error
            token_hash = previous['token_hash'] if previous else ''
            token = None
            if requested.rotate_token or (requested.enabled and not token_hash):
                token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(token.encode()).hexdigest()
            db.execute('INSERT OR REPLACE INTO archive_settings VALUES (1, ?, ?, ?, ?, ?)',
                       (int(requested.enabled), folder, marker, token_hash, requested.max_lookback_sec))
        self.start()
        self.wake.set()
        response = self.settings()
        if token is not None:
            response['token'] = token
        return response

    def _authenticate(self, db, token: str) -> sqlite3.Row:
        row = self._settings(db)
        supplied = hashlib.sha256(token.encode()).hexdigest()
        if not row or not row['token_hash'] or not secrets.compare_digest(row['token_hash'], supplied):
            raise ArchiveError(401, 'An event recording token is required')
        return row

    def submit(self, payload: EventRequest, token: str, request_key: str | None) -> dict:
        if request_key is not None and not re.fullmatch(r'[a-zA-Z0-9._:-]{1,128}', request_key):
            raise ArchiveError(422, 'Invalid Idempotency-Key')
        now = time.time()
        try:
            end = payload.occurred_at.timestamp() if payload.occurred_at is not None else now
        except (OSError, OverflowError, ValueError) as error:
            raise ArchiveError(422, 'The event time is out of range') from error
        if end > now:
            raise ArchiveError(422, 'The event time must be at or before receipt')
        signature = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        config = self.config()
        with database(self.root, timeout=.5) as db:
            db.row_factory = sqlite3.Row
            row = self._authenticate(db, token)
            db.execute('BEGIN IMMEDIATE')
            # Recheck inside the transaction in case settings changed concurrently.
            row = self._authenticate(db, token)
            owner = row['token_hash']
            if request_key is not None:
                event = db.execute('SELECT * FROM archive_events WHERE token_hash=? AND request_key=?',
                                   (owner, request_key)).fetchone()
                if event:
                    if signature != event['request_hash']:
                        raise ArchiveError(409, 'The idempotency key belongs to a different event')
                    return _public_event(event)
            if not row['enabled'] or not config.recording.managed_storage or not config.recording.auto_apply:
                raise ArchiveError(409, 'Enable event recordings on a FlintEye-managed recorder')
            if config.mediamtx.control_mode == 'external':
                raise ArchiveError(409, 'Event recordings require a FlintEye-managed media server')
            if payload.lookback_sec > row['max_lookback']:
                raise ArchiveError(422, 'The requested interval exceeds the event recording limit')
            known = {camera.id.casefold(): camera for camera in config.cameras}
            selected = [known.get(key.casefold()) for key in payload.camera_ids]
            if any(camera is None for camera in selected) or len(set(key.casefold() for key in payload.camera_ids)) != len(selected):
                raise ArchiveError(422, 'Choose distinct configured camera IDs')
            cameras = [{'id': camera.id, 'stream': camera.path.strip('/'),
                        'label': camera.display_name or camera.id} for camera in selected]
            pending, = db.execute('SELECT COUNT(*) FROM archive_events WHERE status IN (?, ?, ?)', ACTIVE).fetchone()
            if pending >= MAX_PENDING:
                raise ArchiveError(429, 'The event recording queue is full')
            roots = [str(root) for root, _, _ in locations(config, self.workspace)]
            event_id = uuid4().hex
            segment_seconds = parse_duration_to_seconds(config.recording.record_segment_duration) or 600
            wait_until = now + max(60, 2*segment_seconds + 15)
            db.execute('INSERT INTO archive_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (event_id, owner, request_key, signature, now, end - payload.lookback_sec, end, wait_until,
                        payload.label, row['folder'], row['marker'], json.dumps(roots), json.dumps(cameras),
                        'waiting_recording', 'Waiting for the relevant recording segments to close.', '[]'))
            event = db.execute('SELECT * FROM archive_events WHERE id=?', (event_id,)).fetchone()
        self.start()
        self.wake.set()
        return _public_event(event)

    def event_status(self, event_id: str, token: str) -> dict:
        if not (self.root/'recordings.sqlite3').is_file():
            raise ArchiveError(401, 'An event recording token is required')
        with _read_index(self.root) as db:
            db.row_factory = sqlite3.Row
            owner = self._authenticate(db, token)['token_hash']
            row = db.execute('SELECT * FROM archive_events WHERE id=? AND token_hash=?',
                             (event_id, owner)).fetchone()
        if row is None:
            raise ArchiveError(404, 'Event recording not found')
        return _public_event(row)

    def events(self, *, limit=100, offset=0) -> list[dict]:
        if not (self.root/'recordings.sqlite3').is_file():
            return []
        with _read_index(self.root) as db:
            if not _has_table(db, 'archive_events'):
                return []
            db.row_factory = sqlite3.Row
            return [_public_event(row) for row in db.execute(
                'SELECT * FROM archive_events ORDER BY end DESC, id LIMIT ? OFFSET ?', (limit, offset))]

    def cancel(self, event_id: str):
        with database(self.root, timeout=.5) as db:
            if not _has_table(db, 'archive_events'):
                raise ArchiveError(404, 'Event recording not found')
            found = db.execute("UPDATE archive_events SET status='cancelled', detail='Event cancelled.' "
                               "WHERE id=? AND status IN ('waiting_recording', 'waiting_storage')", (event_id,))
            if not found.rowcount:
                raise ArchiveError(409, 'Only waiting event recordings can be cancelled')
        return {'ok': True}

    def resolve(self, file_id: str) -> tuple[Path, str, Path]:
        match = re.fullmatch(r'event\.([0-9a-f]{32})\.([0-9]{1,4})', file_id)
        if not match or not (self.root/'recordings.sqlite3').is_file():
            raise ArchiveError(404, 'Event recording file not found')
        event_id, index = match[1], int(match[2])
        with _read_index(self.root) as db:
            if not _has_table(db, 'archive_events'):
                raise ArchiveError(404, 'Event recording file not found')
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM archive_events WHERE id=?', (event_id,)).fetchone()
        if row is None or row['status'] not in ('ready', 'partial'):
            raise ArchiveError(404, 'Event recording file not found')
        clips = json.loads(row['clips'])
        if index >= len(clips):
            raise ArchiveError(404, 'Event recording file not found')
        relative = f'{event_id}/{index}.mp4'
        try:
            root = _safe_directory(row['folder'], row['marker'])
            path = root/relative
            if (path.resolve() != path or not path.is_file()
                    or _stamp(path) != (clips[index]['size_bytes'], clips[index]['mtime_ns'])):
                raise OSError
        except OSError as error:
            raise ArchiveError(404, 'The archived file or its storage volume is unavailable') from error
        return root, relative, path

    def _loop(self):
        while not self.stopping.is_set():
            try:
                self.process_pending()
            except (OSError, ValueError, sqlite3.Error):
                logger.exception('Could not process event recordings')
            self.wake.wait(1)
            self.wake.clear()

    def _update(self, event_id, status, detail, clips=()):
        with database(self.root, timeout=.5) as db:
            result = db.execute("UPDATE archive_events SET status=?, detail=?, clips=? "
                                "WHERE id=? AND status IN (?, ?, ?)",
                                (status, detail, json.dumps(clips), event_id, *ACTIVE))
            return bool(result.rowcount)

    def process_pending(self):
        if not (self.root/'recordings.sqlite3').is_file():
            return
        with _read_index(self.root) as db:
            if not _has_table(db, 'archive_events'):
                return
            db.row_factory = sqlite3.Row
            events = list(db.execute('SELECT * FROM archive_events WHERE status IN (?, ?, ?) ORDER BY received, id', ACTIVE))
        for event in events:
            if self.stopping.is_set():
                break
            self._process_event(event)

    def _sources(self, event):
        if not (self.root/'recording-events.sqlite3').is_file():
            return {}
        with recording_events.database(self.root, timeout=.5) as db:
            rows = db.execute('SELECT path,size,mtime,started,ended FROM completed_files WHERE started < ? AND ended > ? '
                              'AND EXISTS(SELECT 1 FROM events WHERE events.path=completed_files.path AND indexed=1)',
                              (event['end'], event['start'])).fetchall()
        roots = [Path(path) for path in json.loads(event['roots'])]
        by_stream = defaultdict(list)
        for name, size, mtime, start, end in rows:
            path = Path(name)
            parent = next((root for root in roots if path.is_relative_to(root)), None)
            if parent is None or path.suffix not in {'.mp4', '.ts'}:
                continue
            try:
                if path.resolve() != path or not path.is_file() or _stamp(path) != (size, mtime):
                    continue
            except OSError:
                continue
            stream = path.relative_to(parent).parts[0]
            by_stream[stream].append(Span(path, start, max(start, event['start']), min(end, event['end']), (size, mtime)))
        return by_stream

    def _process_event(self, event):
        config = self.config()
        cameras = json.loads(event['cameras'])
        sources = self._sources(event)
        # Preserve every completed overlap now. Wait for the currently open
        # tail while recording is active, including when the hook is delayed.
        now = time.time()
        missing_tails = {camera['stream'] for camera in cameras
                         if max((span.end for span in sources.get(camera['stream'], ())), default=0) < event['end'] - .001}
        enabled_streams = {camera.path.strip('/') for camera in config.cameras if camera.enabled}
        recorder_active = config.recording.enabled and self.recording_running()
        if missing_tails and (now < event['received'] + 2 or
                              (recorder_active and missing_tails & enabled_streams and now < event['wait_until'])):
            self._update(event['id'], 'waiting_recording', 'Waiting for the relevant recording segments to close.')
            return
        minimum_free = config.recording.min_free_bytes + 8_000_000
        try:
            destination = _safe_directory(event['folder'], event['marker'])
            for loop_root, _, _ in locations(config, self.workspace):
                if destination.is_relative_to(loop_root) or loop_root.is_relative_to(destination):
                    raise OSError('The recording folders overlap')
            if shutil.disk_usage(destination).free < minimum_free:
                raise OSError('Not enough space for event recordings')
            if not self._update(event['id'], 'processing', 'Preparing event recordings.'):
                return
            complete = destination/event['id']
            if complete.exists():
                if complete.resolve() != complete or (complete/'manifest.json').is_symlink():
                    raise OSError('Invalid event recording folder')
                receipt = json.loads((complete/'manifest.json').read_text(encoding='utf-8'))
                if receipt['id'] != event['id'] or not EVENT_ID.fullmatch(receipt['id']):
                    raise OSError('Event recording receipt does not match')
                clips = receipt['clips']
                if any((complete/f'{index}.mp4').is_symlink() or
                       _stamp(complete/f'{index}.mp4') != (clip['size_bytes'], clip['mtime_ns'])
                       for index, clip in enumerate(clips)):
                    raise OSError('Archived files no longer match their receipt')
            else:
                clips = self._render(event, config, destination, cameras, sources)
            complete_coverage = all(_covers([clip for clip in clips if clip['camera_id'] == camera['id']],
                                           event['start'], event['end']) for camera in cameras)
            if complete_coverage:
                self._update(event['id'], 'ready', 'Event recordings saved.', clips)
            elif clips:
                self._update(event['id'], 'partial', 'Only the available recording intervals were saved.', clips)
            else:
                self._update(event['id'], 'unavailable', 'No completed recording covers the requested interval.')
        except OSError:
            if not self.stopping.is_set():
                self._update(event['id'], 'waiting_storage', 'Reconnect the event folder or free space to resume.')
        except (KeyError, TypeError, ValueError, subprocess.SubprocessError):
            # Media errors and shutdown are distinct from a vanished volume.
            if not self.stopping.is_set():
                try:
                    _safe_directory(event['folder'], event['marker'])
                    needs_space = shutil.disk_usage(Path(event['folder'])).free < minimum_free
                except OSError:
                    needs_space = True
                if needs_space:
                    self._update(event['id'], 'waiting_storage', 'Reconnect the event folder or free space to resume.')
                else:
                    logger.exception('Could not prepare event recording %s', event['id'])
                    self._update(event['id'], 'failed', 'An event recording could not be decoded or saved.')

    def _render(self, event, config, destination, cameras, sources):
        ffmpeg, ffprobe = recording_events.media_bins(config)
        clips = []
        prefix = f".{event['id']}-"
        for old in destination.glob(prefix+'*'):
            owner = old/'.event-owner'
            if old.resolve() == old and old.is_dir() and owner.is_file() and not owner.is_symlink():
                if owner.read_text(encoding='ascii') == event['id']:
                    shutil.rmtree(old)
        with tempfile.TemporaryDirectory(dir=destination, prefix=prefix) as directory:
            stage = Path(directory)
            (stage/'.event-owner').write_text(event['id'], encoding='ascii')
            for camera in cameras:
                previous_end = event['start']
                slices = []
                for span in sorted(sources.get(camera['stream'], ()), key=lambda item: (item.start, -item.end)):
                    start = max(span.start, previous_end)
                    if start >= span.end:
                        continue
                    if self.stopping.is_set():
                        raise InterruptedError
                    if _stamp(span.path) != span.fingerprint:
                        continue
                    name = f'part-{len(slices)}.mp4'
                    output = stage/name
                    media = _probe(ffprobe, span.path, self.stopping)
                    signature, audio = _encoding(media)
                    _media([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(span.path),
                            '-ss', f'{start-span.source_start:.6f}', '-t', f'{span.end-start:.6f}',
                            '-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'libx264', '-preset', 'veryfast',
                            '-pix_fmt', 'yuv420p', '-threads', '2', '-fps_mode:v', 'passthrough',
                            '-enc_time_base:v', '1:90000', '-video_track_timescale', '90000',
                            *audio, str(output)], self.stopping)
                    if _stamp(span.path) != span.fingerprint:
                        output.unlink()
                        continue
                    part = _probe(ffprobe, output, self.stopping)
                    if not any(track.get('codec_type') == 'video' for track in part['streams']):
                        output.unlink()
                        continue
                    slices.append((name, start, span.end, signature))
                    previous_end = span.end
                for group in _groups(slices):
                    index = len(clips)
                    result = stage/f'{index}.mp4'
                    if len(group) == 1:
                        (stage/group[0][0]).replace(result)
                    else:
                        listing = stage/'parts.txt'
                        listing.write_text(''.join(f"file '{part[0]}'\n" for part in group), encoding='ascii')
                        _media([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-f', 'concat', '-safe', '1',
                                '-i', str(listing), '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy', str(result)], self.stopping)
                        listing.unlink()
                        for part in group:
                            (stage/part[0]).unlink()
                    size, mtime_ns = _stamp(result)
                    _media([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(result), '-map', '0:v:0',
                            '-map', '0:a?', '-fps_mode:v', 'passthrough', '-enc_time_base:v', 'demux',
                            '-f', 'null', '-'], self.stopping)
                    clips.append({'file_id': f"event.{event['id']}.{index}", 'camera_id': camera['id'],
                                  'stream_id': camera['stream'], 'started_at': group[0][1], 'ended_at': group[-1][2],
                                  'size_bytes': size, 'modified_at': mtime_ns / 1e9, 'mtime_ns': mtime_ns})
            if clips and not self.stopping.is_set():
                (stage/'manifest.json').write_text(json.dumps({'id': event['id'], 'clips': clips}), encoding='utf-8')
                for path in stage.iterdir():
                    with path.open('rb+') as file:
                        os.fsync(file.fileno())
                _safe_directory(event['folder'], event['marker'])
                stage.replace(destination/event['id'])
            elif self.stopping.is_set():
                raise InterruptedError
        return clips


def _media(command, stopping):
    deadline = time.monotonic() + 180
    with popen_background(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          **background_process_options()) as process:
        try:
            while not stopping.is_set() and time.monotonic() < deadline:
                try:
                    stdout, stderr = process.communicate(timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    continue
            else:
                if stopping.is_set():
                    raise InterruptedError('Event worker is shutting down')
                raise subprocess.TimeoutExpired(command, 180)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, stderr=stderr)
    if stderr:
        raise ValueError('Media tool reported an error')
    return stdout


def _probe(ffprobe, path, stopping):
    return json.loads(_media([ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(path)], stopping))


def _encoding(media):
    video = next((track for track in media['streams'] if track.get('codec_type') == 'video'), None)
    if video is None:
        raise ValueError('The source segment has no video')
    audio = next((track for track in media['streams'] if track.get('codec_type') == 'audio'), None)
    signature = (video['width'], video['height'])
    if audio is None:
        return signature, ['-an']
    codec = 'pcm_s16le' if audio['codec_name'] in ('pcm_s16be', 'pcm_s16le') else 'pcm_s24le'
    return (*signature, codec, audio['sample_rate'], audio['channels'], audio.get('channel_layout')), ['-c:a', codec]


def _groups(slices):
    groups = []
    for part in slices:
        if groups and abs(groups[-1][-1][2] - part[1]) < .001 and groups[-1][-1][3] == part[3]:
            groups[-1].append(part)
        else:
            groups.append([part])
    return groups


def _covers(clips, start, end):
    boundary = start
    for clip in clips:
        if clip['started_at'] > boundary + .001:
            return False
        boundary = max(boundary, clip['ended_at'])
    return bool(clips) and boundary >= end - .001
