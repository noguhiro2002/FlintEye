"""Durable recording lifecycle evidence, separate from the retention index."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
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
        with db:
            yield db
    finally:
        db.close()


def record_event(root: Path, segment: Path, *, complete: bool, session: str | None = None) -> None:
    from flinteye_app.flinteye_storage import locations, register_segment
    from flinteye_app.orchestrator_models import RuntimeConfig
    session = session or os.environ.get('FLINTEYE_RECORDING_SESSION')
    # Old/external MediaMTX configurations can still register completed files.
    if complete:
        indexed = register_segment(root, segment)
    else:
        indexed = False
    if not session:
        return
    config = RuntimeConfig.model_validate(json.loads((root / 'runtime.json').read_text()))
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
                 now if complete else None, int(indexed)))
            if complete and indexed:
                stat = path.stat()
                try:
                    duration = float(os.environ.get('MTX_SEGMENT_DURATION', 'nan'))
                    import math
                    if not math.isfinite(duration) or duration <= 0: duration = None
                except ValueError: duration = None
                started = None
                # The filename is created by our managed recorder in local time.
                try:
                    from datetime import datetime
                    started = datetime.strptime(path.parent.name + '_' + path.stem, '%Y-%m-%d_%H-%M-%S-%f').timestamp()
                except ValueError: pass
                db.execute('INSERT OR REPLACE INTO completed_files VALUES (?, ?, ?, ?, ?, ?)',
                           (str(path), stat.st_size, stat.st_mtime_ns, started,
                            started + duration if started is not None and duration is not None else None, duration))
        return


def file_evidence(root: Path, paths: list[Path]) -> dict:
    """Read once per list. An unfinished tracked file never becomes stable by age."""
    if not (root/'recording-events.sqlite3').is_file(): return {}
    with database(root, timeout=.5) as db:
        events = {row[0]: (row[1], row[2]) for row in db.execute('SELECT path, MAX(completed), MAX(indexed) FROM events GROUP BY path')}
        completed = {row[0]: row[1:] for row in db.execute('SELECT path,size,mtime,started,ended,duration FROM completed_files')}
    result = {}
    for path in paths:
        key = str(path.resolve())
        if key not in events: continue
        stat = path.stat()
        record = completed.get(key)
        matches = bool(record and record[0] == stat.st_size and record[1] == stat.st_mtime_ns)
        result[key] = {'is_stable': matches, 'completion_state': 'complete' if matches else 'pending',
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
