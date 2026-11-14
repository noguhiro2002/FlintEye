"""Paths and worker commands shared by source and packaged installations."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import argparse
from contextlib import contextmanager
import tempfile
from typing import Iterator
from urllib.parse import urlparse


def application_dir() -> Path:
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def data_dir() -> Path:
    if os.environ.get('FLINTEYE_DATA_DIR'):
        return Path(os.environ['FLINTEYE_DATA_DIR']).expanduser().resolve()
    if sys.platform == 'win32':
        return Path(os.environ['LOCALAPPDATA']) / 'FlintEye'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'FlintEye'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'flinteye'


def worker_command(name: str, python_bin: str | None = None) -> list[str]:
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--worker', name]
    return [python_bin or sys.executable, str(application_dir() / 'flinteye.py'), '--worker', name]


def load_worker_secrets(args: argparse.Namespace) -> argparse.Namespace:
    if not getattr(args, 'secret_stdin', False):
        return args
    raw = sys.stdin.read(65537)
    if len(raw) > 65536:
        raise ValueError('Worker secret input is too large')
    secrets = json.loads(raw)
    if not isinstance(secrets, dict):
        raise ValueError('Worker secret input must be an object')
    for key, value in secrets.items():
        if not isinstance(key, str) or not isinstance(value, str) or not hasattr(args, key):
            raise ValueError('Invalid worker secret input')
        setattr(args, key, value)
    return args


@contextmanager
def private_media_input_command(command: list[str], input_url: str, *, force: bool = False) -> Iterator[list[str]]:
    """Keep camera URLs out of argv using a private, single-input concat manifest.

    FFmpeg's argument-file syntax does not apply to its special ``-i`` option.
    The concat demuxer opens the original stream without decoding/re-encoding it;
    protocol options must be attached to that stream, not the outer demuxer.
    """
    if any(ord(character) < 32 for character in input_url):
        raise ValueError('Media URLs must not contain control characters')
    parsed = urlparse(input_url)
    if not force and parsed.username is None and parsed.password is None and not parsed.query:
        yield command
        return
    if parsed.scheme not in {'rtsp', 'rtsps', 'http', 'https'}:
        raise ValueError('Unsupported credential-bearing media URL')
    if '-i' in command and command[command.index('-i') + 1] == input_url:
        index = command.index('-i')
        suffix = command[index + 2:]
    elif command and command[-1] == input_url:
        index = len(command) - 1
        suffix = []
    else:
        raise ValueError('Media input URL was not found in the command')
    prefix = command[:1]
    options: list[tuple[str, str]] = []
    cursor = 1
    protocol_options = {'-rtsp_transport', '-rw_timeout', '-stimeout', '-timeout'}
    probe_options = {'-analyzeduration', '-probesize', '-fpsprobesize'}
    while cursor < index:
        option = command[cursor]
        if option in protocol_options | probe_options:
            if cursor + 1 >= index:
                raise ValueError('Missing media input option value')
            options.append((option[1:], command[cursor + 1]))
            if option in probe_options:
                prefix.extend(command[cursor:cursor + 2])
            cursor += 2
        else:
            prefix.append(option)
            cursor += 1

    def quote(value: str) -> str:
        if any(ord(character) < 32 for character in value):
            raise ValueError('Invalid media input option')
        return "'" + value.replace("'", "'\\''") + "'"

    # Restrict nested media protocols: a remote playlist must not open local files.
    protocols = 'http,https,tcp,tls,crypto' if parsed.scheme in {'http', 'https'} else 'rtsp,rtsps,tcp,tls,udp,rtp'
    manifest = 'ffconcat version 1.0\nfile ' + quote(input_url) + '\n'
    manifest += 'option protocol_whitelist ' + quote(protocols) + '\n'
    manifest += ''.join('option ' + key + ' ' + quote(value) + '\n' for key, value in options)
    with tempfile.TemporaryDirectory(prefix='flinteye-media-input-') as directory:
        option_file = Path(directory) / 'input.ffconcat'
        descriptor = os.open(option_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(manifest)
        safe = prefix + ['-f', 'concat', '-safe', '0', '-i', str(option_file)] + suffix
        yield safe


def launch_command() -> list[str]:
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    return [sys.executable, str(application_dir() / 'flinteye.py')]
