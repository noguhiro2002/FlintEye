"""Durable recording lifecycle evidence, separate from the retention index."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import time


@contextmanager
def database(root: Path, *, timeout=5):
    db = sqlite3.connect(root / 'recording-events.sqlite3', timeout=timeout)
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS events (
            session TEXT, path TEXT, stream TEXT, created REAL, completed REAL,
            indexed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session, path))''')
        db.execute('''CREATE TABLE IF NOT EXISTS completed_files (
            path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, started REAL, ended REAL, duration REAL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS recovered_files (
            path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER)''')
        with db:
            yield db
    finally:
        db.close()


def segment_started_at(path: Path) -> float | None:
    # New names retain the recorder's UTC offset. Legacy names use local time.
    name = path.parent.name + '_' + path.stem
    for pattern in ('%Y-%m-%d_%H-%M-%S-%f_%z', '%Y-%m-%d_%H-%M-%S-%f'):
        try:
            return datetime.strptime(name, pattern).timestamp()
        except ValueError:
            continue
    return None


def media_bins(config) -> tuple[str, str]:
    ffmpeg = config.multiview.ffmpeg_bin.strip() or 'ffmpeg'
    resolved = shutil.which(ffmpeg)
    probe_name = 'ffprobe.exe' if os.name == 'nt' else 'ffprobe'
    ffprobe = Path(resolved).with_name(probe_name) if resolved else None
    return ffmpeg, str(ffprobe) if ffprobe and ffprobe.is_file() else probe_name


def record_event(root: Path, segment: Path, *, complete: bool, session: str | None = None) -> None:
    from flinteye_app.flinteye_storage import locations, register_segment
    from flinteye_app.orchestrator_models import RuntimeConfig
    session = session or os.environ.get('FLINTEYE_RECORDING_SESSION')
    if not session:
        # Old/external configurations can still index completion hooks.
        if complete:
            register_segment(root, segment)
        return
    config = RuntimeConfig.model_validate(json.loads((root / 'runtime.json').read_text(encoding='utf-8')))
    path = segment.resolve()
    if segment.is_symlink():
        return
    for location, _, _ in locations(config, str(root)):
        try:
            relative = path.relative_to(location)
        except ValueError:
            continue
        if len(relative.parts) != 3 or path.suffix not in {'.mp4', '.ts'}:
            return
        stat = path.stat() if complete else None
        now = time.time()
        with database(root) as db:
            # Create and completion hooks are separate processes and may arrive
            # out of order. A late create must never undo completed evidence.
            db.execute('''INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session, path) DO UPDATE SET
                created = COALESCE(events.created, excluded.created),
                completed = COALESCE(excluded.completed, events.completed),
                indexed = MAX(events.indexed, excluded.indexed)''',
                (session, str(path), relative.parts[0], None if complete else now,
                 now if complete else None, 0))
            if stat is not None:
                try:
                    duration = float(os.environ.get('MTX_SEGMENT_DURATION', 'nan'))
                    if not math.isfinite(duration) or duration <= 0: duration = None
                except ValueError: duration = None
                started = segment_started_at(path)
                db.execute('INSERT OR REPLACE INTO completed_files VALUES (?, ?, ?, ?, ?, ?)',
                           (str(path), stat.st_size, stat.st_mtime_ns, started,
                            started + duration if started is not None and duration is not None else None, duration))
                db.execute('DELETE FROM recovered_files WHERE path=?', (str(path),))
        if stat is not None:
            # Preserve the recorder's completion evidence even if the index is
            # temporarily locked or the volume disappears before registration.
            _index_completed(root, session, path, (stat.st_size, stat.st_mtime_ns), timeout=5)
        return


def _index_completed(root: Path, session: str, path: Path, fingerprint: tuple[int, int], *, timeout: float) -> None:
    from flinteye_app.flinteye_storage import register_segment

    if register_segment(root, path, expected=fingerprint, timeout=timeout):
        with database(root, timeout=timeout) as db:
            db.execute('UPDATE events SET indexed=1 WHERE session=? AND path=? AND completed IS NOT NULL',
                       (session, str(path)))


def retry_completed(root: Path, session: str, deadline: float) -> None:
    """Recover only files with a completion callback and matching file identity."""
    with database(root, timeout=max(0, min(.2, deadline - time.monotonic()))) as db:
        pending = db.execute('''SELECT events.path, size, mtime FROM events JOIN completed_files USING(path)
            WHERE session=? AND indexed=0 AND completed IS NOT NULL''', (session,)).fetchall()
    for path, size, mtime in pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        _index_completed(root, session, Path(path), (size, mtime), timeout=min(.2, remaining))


def recover_closed(root: Path, session: str, config, *, deadline: float, cancelled) -> dict[str, int]:
    """Inspect tracked files after the owner has stopped the recorder and publishers."""
    import subprocess
    from flinteye_app.flinteye_storage import locations, register_segment
    from flinteye_app.process_lifetime import run_background
    from flinteye_app.subprocess_utils import background_process_options

    results = {'recovered': 0, 'unreadable': 0, 'unavailable': 0}
    with database(root, timeout=.2) as db:
        paths = [Path(row[0]) for row in db.execute(
            'SELECT path FROM events WHERE session=? AND completed IS NULL', (session,))]
    roots = [location for location, _, _ in locations(config, str(root))]
    ffmpeg, ffprobe = media_bins(config)
    for path in paths:
        if cancelled.is_set() or time.monotonic() >= deadline:
            break
        if (path.suffix not in {'.mp4', '.ts'} or path.resolve() != path
                or not any(path.is_relative_to(location) for location in roots)):
            results['unavailable'] += 1
            continue
        try:
            before = path.stat()
            fingerprint = before.st_size, before.st_mtime_ns
            if not before.st_size:
                results['unreadable'] += 1
                continue
            probe = run_background(
                [ffprobe, '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                 '-of', 'json', str(path)], capture_output=True, check=True, text=True,
                timeout=max(.1, deadline - time.monotonic()), **background_process_options())
            details = json.loads(probe.stdout)
            duration = float(details.get('format', {}).get('duration', 0))
            if (not math.isfinite(duration) or duration <= 0
                    or not any(track.get('codec_type') == 'video' for track in details.get('streams', []))):
                raise ValueError('Recording has no complete video')
            decode = run_background(
                [ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(path), '-map', '0:v:0',
                 '-map', '0:a?', '-fps_mode:v', 'passthrough', '-enc_time_base:v', 'demux',
                 '-f', 'null', '-'], capture_output=True, check=True,
                timeout=max(.1, deadline - time.monotonic()), **background_process_options())
            if probe.stderr or decode.stderr:
                raise ValueError('Recording reported a decode error')
            after = path.stat()
            if cancelled.is_set() or (after.st_size, after.st_mtime_ns) != fingerprint:
                continue
            if not register_segment(root, path, expected=fingerprint, timeout=.2):
                continue
            started = segment_started_at(path)
            with database(root, timeout=.2) as db:
                updated = db.execute('UPDATE events SET completed=?, indexed=1 '
                                     'WHERE session=? AND path=? AND completed IS NULL',
                                     (time.time(), session, str(path)))
                if not updated.rowcount:
                    continue  # A delayed completion hook already supplied better evidence.
                db.execute('INSERT OR REPLACE INTO completed_files VALUES (?, ?, ?, ?, ?, ?)',
                           (str(path), *fingerprint, started,
                            started + duration if started is not None else None, duration))
                db.execute('INSERT OR REPLACE INTO recovered_files VALUES (?, ?, ?)',
                           (str(path), *fingerprint))
            results['recovered'] += 1
        except OSError:
            results['unavailable'] += 1
        except (ValueError, subprocess.SubprocessError):
            results['unreadable'] += 1
    return results


def file_evidence(root: Path, paths: list[Path]) -> dict:
    """Read once per list. An unfinished tracked file never becomes stable by age."""
    if not (root/'recording-events.sqlite3').is_file(): return {}
    with database(root, timeout=.5) as db:
        events = {row[0]: (row[1], row[2]) for row in db.execute('SELECT path, MAX(completed), MAX(indexed) FROM events GROUP BY path')}
        completed = {row[0]: row[1:] for row in db.execute('SELECT path,size,mtime,started,ended,duration FROM completed_files')}
        recovered = {row[0]: row[1:] for row in db.execute('SELECT path,size,mtime FROM recovered_files')}
    result = {}
    for path in paths:
        key = str(path.resolve())
        if key not in events: continue
        try:
            stat = path.stat()
        except OSError:
            result[key] = {'is_stable': False, 'completion_state': 'unavailable'}
            continue
        record = completed.get(key)
        matches = bool(events[key][1] and record and record[0] == stat.st_size and record[1] == stat.st_mtime_ns)
        state = 'pending'
        if matches:
            state = 'recovered' if recovered.get(key) == (stat.st_size, stat.st_mtime_ns) else 'complete'
        result[key] = {'is_stable': matches, 'completion_state': state,
                       'started_at': record[2] if matches else None, 'ended_at': record[3] if matches else None,
                       'duration_sec': record[4] if matches else None}
    return result


def summary(root: Path, session: str, *, timeout=5) -> dict:
    with database(root, timeout=timeout) as db:
        pending = db.execute('SELECT COUNT(*) FROM events WHERE session=? AND indexed=0', (session,)).fetchone()[0]
        streams = [row[0] for row in db.execute(
            'SELECT DISTINCT stream FROM events WHERE session=? AND completed IS NULL', (session,))]
        previous = db.execute('SELECT COUNT(*) FROM events WHERE session<>? AND indexed=0', (session,)).fetchone()[0]
        total = db.execute('SELECT COUNT(*) FROM events WHERE session=?', (session,)).fetchone()[0]
    return {'pending_segments': pending, 'active_streams': streams,
            'previous_incomplete_segments': previous, 'observed_segments': total}


def write_stop_result(root: Path, *, ok: bool, pending: int, forced: bool, reason: str) -> None:
    """The uninstaller and diagnostics can distinguish exit from completed recording."""
    target = root / 'last-monitoring-stop.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'at': time.time(), 'ok': ok, 'pending_segments': pending,
                                    'forced': forced, 'reason': reason}) + '\n', encoding='utf-8')
    temporary.replace(target)
