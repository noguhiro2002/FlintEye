"""Pass setup ownership from the desktop launcher into its local browser."""
from __future__ import annotations

from html import escape
import logging
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit
import webbrowser

from flinteye_app.network_access import DESKTOP_CODE_SECONDS, private_write
from flinteye_app.orchestrator_auth import local_auth_is_configured

HANDOFF_PATH = '/api/v1/setup/handoff'
HANDOFF_COOKIE = 'flinteye_setup_grant'
HANDOFF_COOKIE_PATH = '/api/v1'
LOOPBACK_PEERS = {'127.0.0.1', '::1'}


def local_setup_origin(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'http' and parsed.hostname in LOOPBACK_PEERS | {'localhost'}
                and parsed.port is not None and parsed.username is None and parsed.password is None
                and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def local_setup_request(request, context) -> bool:
    url = (context.listener or {}).get('url') or ''
    return (getattr(context, 'desktop_setup', False) and local_setup_origin(url)
            and request.client is not None and request.client.host in LOOPBACK_PEERS
            and request.headers.get('host') == urlsplit(url).netloc and request.url.scheme == 'http'
            and not any(name == 'forwarded' or name.startswith('x-forwarded-') for name in request.headers))


class DesktopSetupBrowser:
    def __init__(self, context, url: str):
        self.context = context
        self.url = url
        self.lock = threading.Lock()
        self.page_directory: tempfile.TemporaryDirectory | None = None
        self.expiry: threading.Timer | None = None

    def close(self) -> None:
        with self.lock:
            self._clean_up()

    def _clean_up(self) -> None:
        if self.expiry is not None:
            self.expiry.cancel()
            self.expiry = None
        if self.page_directory is not None:
            self.page_directory.cleanup()
            self.page_directory = None

    def _expire(self, directory: tempfile.TemporaryDirectory) -> None:
        with self.lock:
            if self.page_directory is directory:
                self._clean_up()

    def _prepare_page(self, code: str) -> str:
        with self.lock:
            self._clean_up()
            directory = tempfile.TemporaryDirectory(prefix='flinteye-setup-', ignore_cleanup_errors=True)
            page = Path(directory.name) / 'setup.html'
            try:
                private_write(page, (
                    '<!doctype html><html lang="en"><meta charset="utf-8"><title>FlintEye Setup</title>'
                    f'<form method="post" action="{escape(self.url.rstrip("/") + HANDOFF_PATH)}">'
                    f'<input type="hidden" name="code" value="{escape(code)}">'
                    '<button type="submit">Continue to FlintEye setup</button></form>'
                    '<script>document.forms[0].submit()</script></html>'
                ).encode('utf-8'))
            except OSError:
                directory.cleanup()
                raise
            self.page_directory = directory
            self.expiry = threading.Timer(DESKTOP_CODE_SECONDS, self._expire, args=(directory,))
            self.expiry.daemon = True
            self.expiry.start()
            return page.as_uri()

    def open(self) -> bool:
        try:
            with self.context.lock:
                if local_setup_origin(self.url) and not local_auth_is_configured(self.context.store.get_effective().auth):
                    bootstrap = self.context.bootstrap
                    code = bootstrap.issue_desktop_code()
                    if code is None:
                        bootstrap.renew()
                        code = bootstrap.issue_desktop_code()
                    page = self._prepare_page(code) if code is not None else None
                else:
                    page = None
            if page and webbrowser.open(page):
                return True
        except (OSError, webbrowser.Error):
            logging.getLogger(__name__).warning('Could not open the local setup handoff. Use Address and setup assistance.')
        self.close()
        try:
            return webbrowser.open(self.url)
        except (OSError, webbrowser.Error):
            return False
