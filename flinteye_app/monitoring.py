"""One monitoring state machine shared by HTTP, native menus and shutdown."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import httpx

from flinteye_app.orchestrator_auth import local_auth_is_configured
from flinteye_app import recording_events

logger = logging.getLogger(__name__)
STALL_SECONDS = 15.0
FINALIZE_SECONDS = 30.0


class MonitoringConflict(Exception):
    pass


def media_paths(config) -> list[dict]:
    """Read health only; never enable or reconfigure an external media API."""
    url = config.multiview.mtx_api_url
    if config.mediamtx.control_mode == 'direct' and config.mediamtx.managed.enabled:
        options = config.mediamtx.managed.global_
        address = str(options.get('apiAddress', '127.0.0.1:9997'))
        host = urlsplit('//' + address)
        hostname = host.hostname or '127.0.0.1'
        if hostname in {'0.0.0.0', '::'}:
            hostname = '127.0.0.1' if hostname == '0.0.0.0' else '::1'
        if ':' in hostname:
            hostname = '[' + hostname + ']'
        url = ('https' if options.get('apiEncryption') else 'http') + f'://{hostname}:{host.port or 9997}/v3/paths/list'
    parts = urlsplit(url)
    if parts.scheme not in {'http', 'https'} or not parts.hostname:
        raise ValueError('Media health API is not configured')
    items = []
    with httpx.Client(timeout=1.5, trust_env=False, follow_redirects=False) as client:
        for page in range(100):
            query = dict(parse_qsl(parts.query))
            query.update(page=str(page), itemsPerPage='100')
            response = client.get(urlunsplit(parts._replace(query=urlencode(query))))
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get('items'), list):
                raise ValueError('Invalid media health response')
            items.extend(item for item in data['items'] if isinstance(item, dict))
            if page + 1 >= int(data.get('pageCount', 1)):
                return items
    raise ValueError('Media health response exceeds the supported page count')


class MonitoringController:
    def __init__(self, context):
        self.context = context
        self.root = Path(context.store.runtime_file).resolve().parent
        self.path = self.root / 'monitoring.json'
        self.session = secrets.token_hex(16)
        self.session_started = time.time()
        self.operation = threading.Lock()
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.thread = None
        self.desired = True
        self.resume_on_startup = False
        self.preference_error = ''
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if type(saved.get('desired_running')) is not bool or type(saved.get('resume_on_startup')) is not bool:
                raise ValueError('Invalid monitoring preferences')
            self.desired = saved['desired_running']
            self.resume_on_startup = saved['resume_on_startup']
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            # Never start cameras because a saved Stop could not be read.
            self.desired = False
            self.preference_error = 'Could not read monitoring preferences. Monitoring remains stopped; choose Start to resume.'
        if self.resume_on_startup:
            self.desired = True
        self.phase = 'starting' if self.desired else 'stopped'
        self.error = self.preference_error
        self.busy = False
        self.active_action = None
        self.quitting = False
        self.started = False
        self.tracking_configured = False
        self.started_mono = time.monotonic()
        self.samples: dict[str, tuple[int, float, float | None]] = {}
        self._snapshot: dict = {}
        self.last_poll = 0.0
        context.supervisor.set_monitoring_enabled(self.desired)
        context.supervisor.media_environment['FLINTEYE_RECORDING_SESSION'] = self.session

    def _save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'desired_running': self.desired, 'resume_on_startup': self.resume_on_startup}, stream)
        temporary.replace(self.path)

    def preferences(self) -> dict:
        with self.lock:
            return {'resume_on_startup': self.resume_on_startup, 'desired_running': self.desired}

    def set_resume_on_startup(self, value: bool):
        with self.lock:
            previous = self.resume_on_startup
            self.resume_on_startup = value
            try:
                self._save()
            except OSError:
                self.resume_on_startup = previous
                raise

    def startup(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._poll_loop, name='monitoring-health', daemon=True)
            self.thread.start()
        if self.started:
            return
        config = self.context.store.get_effective()
        if config.auth.provider == 'local' and not local_auth_is_configured(config.auth):
            return
        self.started = True
        if self.desired:
            self.perform('start', startup=True)
        else:
            self.refresh()

    @contextmanager
    def configuration_change(self):
        # Saving configuration while Stop is finalizing must not rewrite a live
        # recorder or bring publishers back. The saved config applies on Start.
        with self.operation:
            yield self.phase != 'finalizing' and not self.quitting

    def perform(self, action: str, *, startup=False, force=False) -> dict:
        if action not in {'start', 'stop', 'restart', 'quit'}:
            raise ValueError('Unknown monitoring action')
        if not self.operation.acquire(blocking=False):
            raise MonitoringConflict('A monitoring operation is already in progress')
        try:
            with self.lock:
                if self.quitting and action != 'quit':
                    raise MonitoringConflict('FlintEye is shutting down')
                if action == 'restart' and not self.desired:
                    raise MonitoringConflict('Monitoring is stopped. Choose Start to resume.')
                if action in {'start', 'restart'} and self.phase == 'finalizing':
                    raise MonitoringConflict('Finish or retry the pending recording stop first')
                self.busy = True
                self.active_action = action
                self.error = ''
                if action in {'start', 'stop'}:
                    previous = self.desired
                    self.desired = action == 'start'
                    try:
                        self._save()
                    except OSError:
                        self.desired = previous
                        raise
                self.phase = 'starting' if action == 'start' else 'stopping'
            if action in {'stop', 'restart', 'quit'}:
                result = self._stop(force=force)
                if not result['ok'] and not force:
                    return result
                if action == 'quit':
                    self.quitting = True
            if action in {'start', 'restart'}:
                from flinteye_app.orchestrator_api import _apply_mediamtx_config
                config = self.context.store.get_effective()
                if config.auth.provider == 'local' and not local_auth_is_configured(config.auth):
                    raise MonitoringConflict('Complete administrator setup before starting monitoring')
                applied = _apply_mediamtx_config(self.context, config)
                self.started = True
                self.context.supervisor.set_monitoring_enabled(True)
                with self.lock:
                    self.started_mono = time.monotonic()
                    self.samples.clear()
                    # A completed Start/Restart is not yet proof of reception.
                    # Do not reuse the previous session's green health snapshot.
                    self._snapshot = {
                        'state': 'starting', 'color': 'amber', 'label': 'Starting',
                        'message': 'Waiting for fresh camera video',
                        'counts': {'configured': len(config.cameras),
                                   'targets': sum(camera.enabled for camera in config.cameras),
                                   'receiving': 0, 'recording': 0}, 'cameras': []}
                    self.last_poll = self.started_mono
                mtx = {'ok': True}
                if not startup or config.mediamtx.autostart_on_api_start:
                    mtx = self.context.supervisor.mediamtx_start(config)
                self.context.supervisor.reconcile(config)
                self.phase = 'running'
                if not mtx.get('ok'):
                    self.error = 'Media server could not start. Open logs for details.'
                elif not applied.ok:
                    self.error = 'Media configuration could not be applied. Open logs for details.'
                return {'ok': not bool(self.error), 'message': self.error or 'Monitoring started'}
            return result
        except (OSError, ValueError) as exc:
            logger.exception('Monitoring operation failed')
            self.error = 'Could not complete the monitoring operation. Open logs and retry.'
            return {'ok': False, 'message': self.error}
        finally:
            self.busy = False
            self.active_action = None
            self.operation.release()

    def _stop(self, *, force=False) -> dict:
        config = self.context.store.get_effective()
        deadline = time.monotonic() + FINALIZE_SECONDS
        self.context.supervisor.set_monitoring_enabled(False)
        self.context.supervisor.pause_media_publishers(deadline=deadline)
        self.phase = 'finalizing'
        # Allow separately launched hook processes to enter the ledger. File
        # evidence also covers a callback that is delayed or could not start.
        quiet_until = time.monotonic() + (2.0 if self.started else 0)
        pending = 0
        error = ''
        while True:
            try:
                evidence = recording_events.summary(self.root, self.session, timeout=max(0, min(.2, deadline-time.monotonic())))
                pending = max(evidence['pending_segments'], self._unindexed_files(config, deadline=deadline))
                expects_recording = config.recording.enabled and (
                    any(camera.enabled for camera in config.cameras) or config.multiview.enabled
                    or config.recording.record_paths or evidence['observed_segments'])
                if expects_recording and self.started and (
                    not self.tracking_configured or config.mediamtx.control_mode == 'external'):
                    raise ValueError('External recording lifecycle cannot be verified')
                error = ''
            except (OSError, ValueError, sqlite3.Error):
                # SQLite/disk failures must not be reported as completed writes.
                error = 'Recording completion could not be verified. Reconnect storage and retry.'
                pending = max(pending, 1)
            if not pending and time.monotonic() >= quiet_until:
                break
            if time.monotonic() >= deadline or force:
                break
            time.sleep(.2)
        ok = pending == 0 and not error
        message = 'Monitoring stopped' if ok else error or f'{pending} recording segment(s) have not finished. Retry Stop, or explicitly force quit.'
        if ok or force:
            result = self.context.supervisor.mediamtx_stop(config)
            ok = ok and bool(result.get('ok'))
            if not result.get('ok'):
                message = 'Media server did not stop. Open logs and retry.'
            self.phase = 'stopped' if ok or force else 'finalizing'
        self.error = '' if ok else message
        recording_events.write_stop_result(self.root, ok=ok, pending=pending, forced=force and not ok, reason=message)
        return {'ok': ok, 'message': message, 'pending_segments': pending}

    def _unindexed_files(self, config, *, deadline=None) -> int:
        if not config.recording.managed_storage:
            return 0
        from flinteye_app.flinteye_storage import locations, database
        roots = locations(config, self.context.workspace_dir)
        if config.recording.enabled and self.started and not roots[0][0].is_dir():
            raise OSError('Recording volume is unavailable')
        with database(self.root, timeout=.2) as db:
            known = {(r, p): (size, mtime) for r, p, size, mtime in db.execute('SELECT root, relative, size, mtime FROM segments')}
        count = 0
        for root, _, _ in roots:
            if not root.is_dir():
                continue
            for file in root.glob('*/*/*'):
                if deadline is not None and time.monotonic() >= deadline:
                    raise OSError('Recording inventory verification timed out')
                if file.suffix not in {'.mp4', '.ts'} or file.is_symlink() or not file.is_file():
                    continue
                stat = file.stat()
                if stat.st_mtime >= self.session_started and known.get((str(root), file.relative_to(root).as_posix())) != (stat.st_size, stat.st_mtime_ns):
                    count += 1
        return count

    def close(self):
        # OS signals/uninstallation cannot leave an invisible service behind.
        # Try the same bounded finalization first and persist any forced outcome.
        self.quitting = True
        if not self.started:
            self.context.supervisor.set_monitoring_enabled(False)
            recording_events.write_stop_result(self.root, ok=True, pending=0, forced=False,
                                              reason='Monitoring was not started; no recording publishers were launched.')
            self.done.set()
            if self.thread:
                self.thread.join(timeout=2)
            return
        with self.operation:
            if self.phase != 'stopped':
                result = self._stop()
                if not result['ok']:
                    self._stop(force=True)
            elif not self.error:
                recording_events.write_stop_result(self.root, ok=True, pending=0, forced=False, reason='Monitoring was already stopped')
        self.done.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def _poll_loop(self):
        while not self.done.is_set():
            try:
                self.refresh()
            except Exception:
                logger.exception('Could not refresh monitoring health')
            self.done.wait(2)

    def refresh(self, *, items=None, now=None):
        config = self.context.store.get_effective()
        now = time.monotonic() if now is None else now
        configured = len(config.cameras)
        targets = [camera for camera in config.cameras if camera.enabled]
        setup = config.auth.provider == 'local' and not local_auth_is_configured(config.auth)
        media_running = None
        available = False
        if self.desired and not setup:
            try:
                if items is None:
                    items = media_paths(config)
                available = True
                media_running = True
            except (httpx.HTTPError, ValueError, OSError):
                if config.mediamtx.control_mode == 'direct':
                    media_running = self.context.supervisor.mediamtx_status(config).get('running', False)
        paths = {item.get('name'): item for item in (items or [])}
        cameras = []
        with self.lock:
            for camera in targets:
                path = paths.get(camera.path, {})
                count = path.get('bytesReceived')
                previous = self.samples.get(camera.path)
                ready = path.get('ready') is True and isinstance(count, (int, float))
                last_reception = previous[2] if previous else None
                progress = previous[1] if previous else now
                if ready and previous and count > previous[0]:
                    progress, last_reception = now, time.time()
                elif ready and (not previous or count < previous[0]):
                    progress, last_reception = now, None
                receiving = bool(available and ready and last_reception and now - progress < STALL_SECONDS)
                if available and ready:
                    self.samples[camera.path] = (count, progress, last_reception)
                else:
                    # A recovered path/API needs two fresh readings. Treating
                    # its old counter as zero would falsely certify reception.
                    self.samples.pop(camera.path, None)
                reason = ('Receiving' if receiving else 'Stopped' if not self.desired else
                          'Media status unavailable' if not available else
                          'Waiting for camera' if not ready else 'Waiting for video data' if not last_reception else 'No new video data for 15 seconds')
                cameras.append({'id': camera.id, 'receiving': receiving, 'last_received_at': last_reception, 'reason': reason})
            receiving = sum(item['receiving'] for item in cameras)
            evidence = recording_events.summary(self.root, self.session)
            active = set(evidence.pop('active_streams'))
            recording = sum(camera.path in active and item['receiving'] for camera, item in zip(targets, cameras))
            counts = {'configured': configured, 'targets': len(targets), 'receiving': receiving, 'recording': recording}
            color, state, label, reason = 'green', 'running', 'Running', 'Receiving camera video'
            if setup:
                color, state, label, reason = 'gray', 'idle', 'Setup needed', 'Complete setup and add a camera to begin.'
            elif not self.desired:
                color, state, label, reason = 'gray', 'stopped', 'Stopped', 'Monitoring is stopped. Settings remain available.'
            elif not targets:
                color, state, label, reason = 'gray', 'idle', 'No cameras', 'Monitoring is enabled; add a camera to begin.'
            elif media_running is False:
                color, state, label, reason = 'red', 'error', 'Media server unavailable', 'Open logs and restart monitoring.'
            elif not available:
                color, state, label, reason = 'amber', 'unknown', 'Status unavailable', 'The media health API could not be reached.'
            elif receiving < len(targets):
                color, state, label, reason = ('amber', 'starting', 'Starting', 'Waiting for camera video') if now - self.started_mono < STALL_SECONDS else (
                    ('amber', 'warning', 'Some cameras unavailable', 'Check camera connections.') if receiving else ('red', 'error', 'No camera video', 'Check camera connections and logs.'))
            if self.context.storage_problem and self.desired and state != 'error':
                color, state, label, reason = 'amber', 'warning', 'Recording paused', self.context.storage_problem
            if self.phase == 'finalizing' or self.busy:
                color, state, label, reason = 'amber', self.phase, 'Finishing recordings' if self.phase == 'finalizing' else 'Starting' if self.phase == 'starting' else 'Stopping', self.error or 'Please wait for the operation to finish.'
            elif self.error and state != 'error':
                color, state, label, reason = 'amber', 'warning', 'Action needed', self.error
            self._snapshot = {'state': state, 'color': color, 'label': label, 'message': reason,
                              'counts': counts, 'cameras': cameras, **evidence}
            self.last_poll = now

    def status(self) -> dict:
        with self.lock:
            result = copy.deepcopy(self._snapshot) or {
                'state': 'unknown', 'color': 'amber', 'label': 'Checking status', 'message': '',
                'counts': {'configured': 0, 'targets': 0, 'receiving': 0, 'recording': 0}, 'cameras': []}
            result['active_action'] = self.active_action
            if self.last_poll and time.monotonic() - self.last_poll > 6 and self.desired:
                result.update(state='unknown', color='amber', label='Status unavailable', message='Waiting for a fresh health check.')
            if self.busy or self.phase == 'finalizing':
                result.update(state=self.phase, color='amber', label='Finishing recordings' if self.phase == 'finalizing' else 'Starting' if self.phase == 'starting' else 'Stopping', message=self.error or 'Please wait.')
            elif self.phase == 'stopped':
                # Stop takes effect immediately, even between health polls.
                result['counts'].update(receiving=0, recording=0)
                for camera in result['cameras']:
                    camera.update(receiving=False, reason='Stopped')
                if self.error:
                    result.update(state='warning', color='amber', label='Action needed', message=self.error)
                else:
                    result.update(state='stopped', color='gray', label='Stopped', message='Monitoring is stopped. Settings remain available.' + (' No cameras are configured.' if not result['counts']['configured'] else ''))
            result.update(desired_running=self.desired, busy=self.busy, phase=self.phase,
                          resume_on_startup=self.resume_on_startup)
            return result
