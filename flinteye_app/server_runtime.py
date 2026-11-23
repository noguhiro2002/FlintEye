"""Two listeners, one application lifespan and one monitoring owner."""
from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
import errno
import logging
import signal
import socket
import ssl
import threading
import time
import uvicorn

from flinteye_app.network_access import ensure_certificates

logger = logging.getLogger(__name__)

def listener_bind_error(host: str, port: int, error: OSError) -> str:
    address = f'[{host}]' if ':' in host else host
    code = getattr(error, 'winerror', None) or error.errno
    endpoint = f'{address}:{port}'
    if code in {errno.EADDRINUSE, 10048}:
        return (f'{endpoint} is already in use ({code}). Quit any other FlintEye instance and check which process '
                'owns this address and port before changing the port.')
    if code in {errno.EADDRNOTAVAIL, 10049}:
        return f'The address {address} is unavailable ({code}). Select an IPv4 address assigned to this server.'
    return f'Could not listen at {endpoint} (error {code}). Check the server network and permissions.'


@contextmanager
def termination_signals(server):
    """Let the CLI finish its owner/process cleanup on an OS stop request.

    Uvicorn re-emits captured signals after its lifespan shutdown. A default
    SIGTERM handler would kill the process before the CLI's finally block.
    Desktop listeners also run off the main thread, where Uvicorn cannot own
    signals, so the same handler asks the native event loop to close normally.
    """
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def stop(signum, frame):
            server.should_exit = True
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


class ListenerGroup:
    def __init__(self, app, *, root, host, port, network):
        self.root, self.network = root, network
        self.on_ready = None
        self.lan_started = False
        group = self
        class OwnerServer(uvicorn.Server):
            async def shutdown(self, sockets=None):
                # Drain the secondary listener before the application lifespan ends.
                if group.lan_task is not None:
                    group.servers[1].should_exit = True
                    await asyncio.gather(group.lan_task, return_exceptions=True)
                await super().shutdown(sockets=sockets)
        self.lan_task = None
        self.servers = [OwnerServer(uvicorn.Config(app, host=host, port=port, log_config=None,
                       timeout_graceful_shutdown=5, proxy_headers=not network.enabled,
                       forwarded_allow_ips='127.0.0.1,::1'))]
        self.certificate = None
        self.certificate_change_pending = False
        self.lan_error = ''
        self.local_error = ''
        if network.enabled:
            if host != '127.0.0.1':
                raise ValueError('Built-in LAN access requires the local API host to be 127.0.0.1')
            try:
                from flinteye_app.orchestrator_store import RuntimeStore
                auth = RuntimeStore(env_file='', runtime_file=str(root/'runtime.json'), use_env=False).get_effective().auth
                if auth.provider != 'local' or not auth.viewer_auth_required:
                    raise ValueError('Built-in LAN access requires local authentication for administrator and viewer')
                self.certificate = ensure_certificates(root, network.address)
                config = uvicorn.Config(app, host=network.address, port=port, log_config=None,
                    lifespan='off', proxy_headers=False, timeout_graceful_shutdown=5,
                    ssl_certfile=self.certificate['certfile'], ssl_keyfile=self.certificate['keyfile'])
                config.load()
                config.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
                self.servers.append(uvicorn.Server(config))
            except (OSError, ValueError) as error:
                self.lan_error = 'LAN HTTPS unavailable: ' + str(error)
                logger.error('%s; local access remains available', self.lan_error)

    @property
    def started(self):
        return self.servers[0].started

    @property
    def should_exit(self):
        return self.servers[0].should_exit

    @should_exit.setter
    def should_exit(self, value):
        for server in self.servers:
            server.should_exit = value

    def run(self):
        asyncio.run(self._serve())

    async def _serve(self):
        sockets = []
        with ExitStack() as stack, self.servers[0].capture_signals():
            for index, server in enumerate(self.servers):
                try:
                    sock = socket.socket(socket.AF_INET6 if ':' in server.config.host else socket.AF_INET, socket.SOCK_STREAM)
                    stack.callback(sock.close)
                    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    else:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind((server.config.host, server.config.port))
                    sock.listen(128)
                    sock.setblocking(False)
                    sockets.append((server, sock))
                except OSError as error:
                    message = listener_bind_error(server.config.host, server.config.port, error)
                    if index == 0:
                        self.local_error = message
                        raise
                    self.lan_error = f'LAN HTTPS could not start. {message}'
                    logger.error('%s; local access remains available', self.lan_error)
            owner_task = asyncio.create_task(self.servers[0]._serve(sockets=[sockets[0][1]]))
            while not self.started and not owner_task.done():
                await asyncio.sleep(.05)
            if self.started and len(sockets) > 1:
                self.lan_task = asyncio.create_task(self.servers[1]._serve(sockets=[sockets[1][1]]))
                while not self.servers[1].started and not self.lan_task.done():
                    await asyncio.sleep(.05)
                self.lan_started = self.servers[1].started
            if self.started and self.on_ready is not None:
                self.on_ready()
            tasks = [owner_task] + ([self.lan_task] if self.lan_task else [])
            # Stop both listeners if either exits, without another application lifespan.
            async def supervise():
                renewed_at = time.monotonic()
                while not self.should_exit and not any(task.done() for task in tasks):
                    if (self.network.enabled and len(sockets) > 1 and not self.certificate_change_pending
                            and time.monotonic() - renewed_at >= 3600):
                        renewed_at = time.monotonic()
                        try:
                            metadata = ensure_certificates(self.root, self.network.address)
                            if metadata != self.certificate:
                                self.servers[1].config.ssl.load_cert_chain(metadata['certfile'], metadata['keyfile'])
                                self.certificate = metadata
                        except (OSError, ValueError):
                            logger.exception('LAN certificate renewal failed; check local connection settings')
                    await asyncio.sleep(1)
                self.should_exit = True
            watcher = asyncio.create_task(supervise())
            try:
                outcomes = await asyncio.gather(*tasks, return_exceptions=True)
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        raise outcome
            finally:
                self.should_exit = True
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
