"""Small shared release contract; no application imports or network access."""
from __future__ import annotations

import ast
import hashlib
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'noguhiro2002/FlintEye'
ARCHES = ('amd64', 'arm64')
IMAGE = 'ghcr.io/' + REPOSITORY.lower()


def version() -> str:
    for node in ast.parse((ROOT / 'flinteye_app/_version.py').read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in node.targets):
            value = ast.literal_eval(node.value)
            if not re.fullmatch(r'\d+\.\d+\.\d+', value):
                raise ValueError('VERSION must be a stable X.Y.Z version')
            return value
    raise ValueError('VERSION not found')


def release_identity() -> tuple[str, str]:
    values = {}
    for node in ast.parse((ROOT / 'flinteye_app/_version.py').read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            values[node.targets[0].id] = ast.literal_eval(node.value)
    value, channel = values['RELEASE_VERSION'], values['RELEASE_CHANNEL']
    if channel not in {'source', 'preview', 'stable'} or not re.fullmatch(r'\d+\.\d+\.\d+(?:-preview\.[1-9][0-9]{0,5})?', value):
        raise ValueError('Invalid embedded release identity')
    if value.split('-')[0] != version() or (channel == 'preview') != ('-preview.' in value):
        raise ValueError('Release identity does not match application version/channel')
    return value, channel


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package_names(v: str | None = None) -> list[str]:
    v = v or version()
    return [f'FlintEye-{v}-{os_name}-{arch}{suffix}'
            for arch in ARCHES
            for os_name, suffix in [('windows', '-setup.exe'), ('macos', '.dmg'),
                                    ('linux', '.deb'), ('linux', '.rpm')]]


def binary_architecture(path: Path) -> str:
    """Identify native executable headers without executing an emulated binary."""
    with path.open('rb') as stream:
        header = stream.read(64)
        if header[:4] == b'\x7fELF' and header[4] == 2:
            endian = '<' if header[5] == 1 else '>'
            machine = struct.unpack_from(endian + 'H', header, 18)[0]
            return {62: 'amd64', 183: 'arm64'}[machine]
        if header[:2] == b'MZ':
            stream.seek(struct.unpack_from('<I', header, 60)[0])
            signature = stream.read(6)
            if signature[:4] == b'PE\0\0':
                return {0x8664: 'amd64', 0xAA64: 'arm64'}[struct.unpack_from('<H', signature, 4)[0]]
        if header[:4] == b'\xcf\xfa\xed\xfe':
            return {0x01000007: 'amd64', 0x0100000C: 'arm64'}[struct.unpack_from('<I', header, 4)[0]]
    raise ValueError(f'Unsupported native executable: {path}')
