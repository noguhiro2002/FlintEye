"""Owner-local shutdown requests; no network endpoint or global process names."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import secrets
import sys
import threading


def active_listener_port(root: Path, fallback: int) -> int:
    """Read only while another process holds this profile's instance lock."""
    try:
        port = json.loads((root/'instance-control.json').read_text(encoding='utf-8')).get('port')
        if type(port) is int and 1 <= port <= 65535:
            return port
    except (OSError, ValueError, AttributeError):
        pass
    return fallback


class InstanceControl:
    def __init__(self, root: Path, stop, *, port: int | None = None, renew_setup=None):
        self.renew_setup = renew_setup
        self.path = root / 'instance-control.json'
        self.request = root / 'stop-request.json'
        self.token = secrets.token_hex(32)
        self.stop = stop
        self.closed = threading.Event()
        self.request.unlink(missing_ok=True)
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'token': self.token, 'pid': os.getpid(),
                       'executable': str(Path(sys.executable).resolve()), 'port':port}, stream)
        temporary.replace(self.path)
        self.index = None
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            from flinteye_app.flinteye_runtime import default_data_dir
            try:
                self.index = default_data_dir()/'running'/f'{os.getpid()}.json'
                self.index.parent.mkdir(parents=True, exist_ok=True)
                index_temp = self.index.with_suffix('.tmp')
                index_temp.write_text(json.dumps({'pid':os.getpid(), 'profile':str(root.resolve()),
                                                 'executable':str(Path(sys.executable).resolve())}), encoding='utf-8')
                index_temp.replace(self.index)
            except OSError:
                self.index = None
                logging.getLogger(__name__).warning('Could not register the running profile. Use an explicit -DataDir when stopping this instance with the Windows helper.')
        self.thread = threading.Thread(target=self._watch, name='flinteye-stop-request', daemon=True)
        self.thread.start()

    def _watch(self):
        while not self.closed.wait(.2):
            try:
                if self.request.stat().st_size > 1024:
                    continue
                data = json.loads(self.request.read_text(encoding='utf-8-sig'))
                token = data.get('token')
                if isinstance(token, str) and secrets.compare_digest(token, self.token):
                    self.request.unlink(missing_ok=True)
                    if data.get('action') == 'renew-setup':
                        if self.renew_setup is not None: self.renew_setup()
                        continue
                    if data.get('action', 'stop') != 'stop': continue
                    if self.stop() is False:
                        continue  # A failed normal finalization stays available for retry.
                    return
            except (OSError, ValueError, AttributeError):
                continue

    def close(self):
        self.closed.set()
        self.thread.join(timeout=1)
        try:
            if json.loads(self.path.read_text(encoding='utf-8')).get('token') == self.token:
                self.path.unlink(missing_ok=True)
                self.request.unlink(missing_ok=True)
                if self.index is not None:
                    self.index.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass
