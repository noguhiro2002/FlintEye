"""Read-only RTSPS egress. The private media server never accepts its clients."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import secrets
from urllib.parse import quote

from flinteye_app.network_access import private_write

KEY = 'relay:rtsps'
PORT = 8322
USERNAME = 'flinteye-reader'


def rotate_password(root: Path) -> str:
    password = secrets.token_urlsafe(32)
    digest = base64.b64encode(hashlib.sha256(password.encode()).digest()).decode()
    private_write(root/'rtsps-password.sha256', ('sha256:' + digest).encode())
    return password


def relay_paths(config) -> set[str]:
    return {
        camera.path for camera in config.cameras if camera.enabled
        and re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', camera.path)
    }


def prepare_relay(root: Path, network, config) -> tuple[list[str], bool]:
    digest = (root/'rtsps-password.sha256').read_text().strip()
    if not re.fullmatch(r'sha256:[A-Za-z0-9+/]{43}=', digest):
        raise ValueError('Invalid RTSPS credential file')
    command = config.mediamtx.direct.command
    if not command or config.mediamtx.control_mode != 'direct' or not config.mediamtx.managed.enabled:
        raise ValueError('RTSPS requires the managed local MediaMTX')
    paths = sorted(relay_paths(config))
    if not paths:
        return [], False
    payload = {
        'logLevel': 'info', 'logDestinations': ['stdout'],
        'api': False, 'metrics': False, 'pprof': False, 'playback': False,
        'rtsp': True, 'rtspEncryption': 'strict', 'rtspsAddress': f'{network.address}:{PORT}',
        'rtspTransports': ['tcp'], 'rtspAuthMethods': ['basic'], 'rtspTrustedProxies': [],
        'rtspServerKey': str(root/'tls/server.key'), 'rtspServerCert': str(root/'tls/server.crt'),
        'rtmp': False, 'hls': False, 'webrtc': False, 'srt': False, 'moq': False,
        'authMethod': 'internal',
        'authInternalUsers': [{'user': USERNAME, 'pass': digest, 'ips': network.allowed_subnets,
                               'permissions': [{'action': 'read', 'path': name} for name in paths]}],
        'paths': {name: {'source': 'rtsp://127.0.0.1:8554/' + quote(name, safe='/'),
                         'rtspTransport': 'tcp', 'sourceOnDemand': True} for name in paths},
    }
    path = root/'rtsps-relay.yml'
    content = (json.dumps(payload, indent=2) + '\n').encode()
    changed = not path.exists() or path.read_bytes() != content
    if changed:
        private_write(path, content)
    return [command[0], str(path)], changed
