"""Retention only deletes registered, completed segments, never arbitrary media files."""
from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from flinteye_app.orchestrator_logging import parse_duration_to_seconds

GB = 1_000_000_000


def suggested_quota(path: Path) -> int:
    return min(50 * GB, shutil.disk_usage(path).free // 2)


@contextmanager
def database(root: Path, *, timeout=30):
    db = sqlite3.connect(root / 'recordings.sqlite3', timeout=timeout)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS segments (root TEXT, relative TEXT, size INTEGER, mtime INTEGER, PRIMARY KEY(root, relative))')
        with db:
            yield db
    finally:
        db.close()


def locations(config, workspace: str, visible_only: bool = False):
    recording = config.recording
    entries = [(recording.record_root, recording.record_delete_after, recording.max_bytes)]
    entries += [(old.path, old.retention, old.max_bytes) for old in recording.previous_roots
                if not visible_only or recording.show_previous]
    result = []
    seen = set()
    for path, retention, quota in entries:
        root = Path(path).expanduser()
        if not root.is_absolute(): root = Path(workspace) / root
        root = root.resolve()
        if str(root) not in seen:
            seen.add(str(root)); result.append((root, retention, quota))
    return result


def register_segment(data: Path, segment: Path, *, expected: tuple[int, int] | None = None, timeout=30) -> bool:
    from flinteye_app.orchestrator_models import RuntimeConfig
    config = RuntimeConfig.model_validate(json.loads((data / 'runtime.json').read_text()))
    if segment.is_symlink() or not segment.is_file(): return False
    path = segment.resolve()
    for root, _, _ in locations(config, str(data)):
        try: relative = path.relative_to(root)
        except ValueError: continue
        if len(relative.parts) != 3 or path.suffix not in {'.mp4', '.ts'}: return False
        stat = path.stat()
        if expected is not None and (stat.st_size, stat.st_mtime_ns) != expected:
            return False
        with database(data, timeout=timeout) as db:
            db.execute('INSERT OR REPLACE INTO segments VALUES (?, ?, ?, ?)',
                       (str(root), relative.as_posix(), stat.st_size, stat.st_mtime_ns))
        return True
    return False


def cleanup(data: Path, config, workspace: str, now: float | None = None) -> int:
    if not config.recording.managed_storage: return 0
    now = time.time() if now is None else now
    count = 0
    with database(data) as db:
        for root, retention, quota in locations(config, workspace):
            if not root.is_dir(): continue  # Disconnected volumes are never recreated here.
            seconds = parse_duration_to_seconds(retention)
            rows = db.execute('SELECT relative, size, mtime FROM segments WHERE root=? ORDER BY mtime', (str(root),)).fetchall()
            # Include active recordings/cache in disk accounting, but never delete them here.
            total = 0
            for file in root.rglob('*'):
                try:
                    if file.relative_to(root).parts[0].lower() == '.playback_cache':
                        continue
                    if file.is_file() and not file.is_symlink(): total += file.stat().st_size
                except FileNotFoundError:
                    continue
            free = shutil.disk_usage(root).free
            for relative, size, mtime in rows:
                path = root / relative
                if path.is_symlink() or not path.resolve().is_relative_to(root): continue
                if not path.exists():
                    db.execute('DELETE FROM segments WHERE root=? AND relative=?', (str(root), relative)); continue
                stat = path.stat()
                if stat.st_size != size or stat.st_mtime_ns != mtime: continue
                expired = seconds is not None and now - mtime / 1e9 >= seconds
                over_quota = quota is not None and total > quota
                low_space = free < config.recording.min_free_bytes
                if not (expired or over_quota or low_space): continue
                try: path.unlink()
                except OSError: continue
                db.execute('DELETE FROM segments WHERE root=? AND relative=?', (str(root), relative))
                total -= size; free += size; count += 1
    return count


def storage_problem(config) -> str | None:
    if not config.recording.managed_storage or not config.recording.enabled:
        return None
    root = Path(config.recording.record_root)
    if not root.is_dir():
        return "Recording folder is unavailable. Reconnect the disk or choose another folder."
    try:
        if shutil.disk_usage(root).free < config.recording.min_free_bytes:
            return "Recording paused: not enough free disk space. Free space or choose another folder."
    except OSError:
        return "Recording folder cannot be accessed."
    return None
