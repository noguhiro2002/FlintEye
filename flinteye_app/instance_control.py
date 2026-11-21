"""Owner-local shutdown requests; no network endpoint or global process names."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import urlsplit


def browser_url(host: str, port: int) -> str:
    address = '127.0.0.1' if host == '0.0.0.0' else '::1' if host == '::' else host
    if ':' in address and not address.startswith('['): address = '[' + address + ']'
    return f'http://{address}:{port}'


def active_listener_url(root: Path, fallback: str) -> str:
    try:
        url = json.loads((root/'instance-control.json').read_text(encoding='utf-8')).get('url', '')
        parsed = urlsplit(url)
        if parsed.scheme in {'http', 'https'} and parsed.hostname and parsed.hostname not in {'0.0.0.0', '::'} and not (parsed.username or parsed.password or parsed.query or parsed.fragment) and parsed.path in {'', '/'}:
            return url
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return fallback


def active_listener_port(root: Path, fallback: int) -> int:
    """Read only while another process holds this profile's instance lock."""
    try:
        port = json.loads((root/'instance-control.json').read_text(encoding='utf-8')).get('port')
        if type(port) is int and 1 <= port <= 65535:
            return port
    except (OSError, ValueError, AttributeError):
        pass
    return fallback


def request_local_browser(root: Path) -> bool:
    """Ask the already running desktop to open its browser on behalf of this profile."""
    from flinteye_app.orchestrator_store import write_private_runtime_json

    try:
        owner = json.loads((root / 'instance-control.json').read_text(encoding='utf-8'))
        if owner.get('browser_requests') is not True or not isinstance(owner.get('token'), str):
            return False
        write_private_runtime_json(root / 'open-browser-request.json', {'token': owner['token']})
        return True
    except (OSError, ValueError, AttributeError):
        return False


class InstanceControl:
    def __init__(self, root: Path, stop, *, port: int | None = None, renew_setup=None,
                 open_browser=None, url: str | None = None):
        self.renew_setup = renew_setup
        self.open_browser = open_browser
        self.path = root / 'instance-control.json'
        self.request = root / 'stop-request.json'
        self.browser_request = root / 'open-browser-request.json'
        self.token = secrets.token_hex(32)
        self.stop = stop
        self.closed = threading.Event()
        self.request.unlink(missing_ok=True)
        self.browser_request.unlink(missing_ok=True)
        self.metadata = {'token': self.token, 'pid': os.getpid(),
                         'executable': str(Path(sys.executable).resolve()), 'port': port, 'url': url,
                         'browser_requests': open_browser is not None}
        self.write_connection()
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

    def write_connection(self, **values):
        from flinteye_app.network_access import private_write

        self.metadata.update(values)
        private_write(self.path, json.dumps(self.metadata).encode())

    def _take_request(self, path: Path) -> dict | None:
        try:
            if path.stat().st_size <= 1024:
                data = json.loads(path.read_text(encoding='utf-8-sig'))
                token = data.get('token')
                if isinstance(token, str) and token.isascii() and secrets.compare_digest(token, self.token):
                    path.unlink(missing_ok=True)
                    return data
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def _watch(self):
        while not self.closed.wait(.2):
            try:
                data = self._take_request(self.request)
                if data is not None:
                    if data.get('action') == 'renew-setup':
                        if self.renew_setup is not None: self.renew_setup()
                        continue
                    if data.get('action', 'stop') != 'stop': continue
                    if self.stop() is False:
                        continue  # A failed normal finalization stays available for retry.
                    return
                if self.open_browser is not None and self.metadata.get('ready') and self._take_request(self.browser_request) is not None:
                    self.open_browser()
            except (OSError, ValueError, AttributeError):
                continue

    def close(self):
        self.closed.set()
        self.thread.join(timeout=1)
        try:
            if json.loads(self.path.read_text(encoding='utf-8')).get('token') == self.token:
                self.path.unlink(missing_ok=True)
                self.request.unlink(missing_ok=True)
                self.browser_request.unlink(missing_ok=True)
                if self.index is not None:
                    self.index.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass
