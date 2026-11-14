"""Owner-local shutdown requests; no network endpoint or global process names."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
import threading


class InstanceControl:
    def __init__(self, root: Path, stop):
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
                       'executable': str(Path(sys.executable).resolve())}, stream)
        temporary.replace(self.path)
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
                    self.stop()
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
        except (OSError, ValueError, AttributeError):
            pass
