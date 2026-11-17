"""Firewall changes require an explicit, owner-local request and UAC."""
from __future__ import annotations
from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path
import subprocess
import uuid
from flinteye_app.flinteye_runtime import application_dir, default_data_dir
from flinteye_app.network_access import installation_id, private_write
from flinteye_app.subprocess_utils import background_process_options


def _require_windows():
    if os.name != 'nt':
        raise ValueError('Automatic Firewall changes are available on Windows only. See the LAN guide for this OS.')


def _programs() -> tuple[Path, Path]:
    return ((application_dir().parent/'FlintEye.exe').resolve(),
            (application_dir()/'bin/mediamtx.exe').resolve())


def _maintenance_dir() -> Path:
    # Outside the default camera profile: explicitly deleting that profile must
    # not erase another profile/installation's outstanding Firewall ownership.
    return default_data_dir().parent/'FlintEyeMaintenance'


def _inventory(application: Path, identity: str) -> Path:
    key = hashlib.sha256((str(application).lower()+'\0'+str(uuid.UUID(identity))).encode()).hexdigest()
    return _maintenance_dir()/'firewall-installations'/(key+'.json')


@contextmanager
def _operation(application: Path):
    directory = _maintenance_dir()/'firewall-locks'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = hashlib.sha256(str(application).lower().encode()).hexdigest()+'.lock'
    with os.fdopen(os.open(directory/name, os.O_RDWR | os.O_CREAT, 0o600), 'r+b') as stream:
        if not os.fstat(stream.fileno()).st_size:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('Another Firewall change for this installation is in progress. Finish it and retry.') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _owned_inventory(application: Path) -> list[tuple[Path, dict]]:
    entries = []
    for file in (_maintenance_dir()/'firewall-installations').glob('*.json'):
        record = json.loads(file.read_text())
        if not Path(record['application']).is_absolute():
            raise ValueError('Invalid Firewall ownership record')
        if Path(record['application']).resolve() != application:
            continue
        if file != _inventory(application, record['id']) or not Path(record['profile']).is_absolute():
            raise ValueError('Invalid Firewall ownership record')
        entries.append((file, record))
    return entries


def _execute(root: Path, payload: dict):
    request = root/('firewall-request-'+uuid.uuid4().hex+'.json')
    private_write(request, json.dumps(payload).encode())
    script = application_dir()/'packaging/firewall_windows.ps1'
    launcher = application_dir()/'packaging/elevate_firewall.ps1'
    try:
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-File', str(launcher), '-Script', str(script), '-Request', str(request)],
                       check=True, timeout=180, **background_process_options())
    finally:
        request.unlink(missing_ok=True)


def manage_firewall(root: Path, config, action: str) -> dict:
    _require_windows()
    if action not in {'apply', 'remove'}:
        raise ValueError('Invalid Firewall action')
    if action == 'apply' and not config.network.enabled:
        raise ValueError('Enable LAN access before creating its Firewall rules')
    application, media = _programs()
    payload = {'action': action, 'id': installation_id(root), 'address': config.network.address,
               'subnets': config.network.allowed_subnets, 'port': config.api.port,
               'rtsp_enabled': config.network.rtsp_enabled,
               'application': str(application), 'media': str(media)}
    with _operation(application):
        index = _inventory(application, payload['id'])
        if action == 'apply':
            # Persist ownership before elevation: interrupted or failed applies
            # remain discoverable, including a stopped/deleted custom profile.
            private_write(index, json.dumps({'id': payload['id'], 'application': str(application),
                                            'profile': str(root.resolve())}).encode())
        _execute(root, payload)
        private_write(root/'firewall-owner.json', json.dumps({'id': payload['id'],
            'application': str(application), 'applied': action == 'apply'}).encode())
        if action == 'remove':
            index.unlink(missing_ok=True)
    return {'ok': True, 'message': 'Only the confirmed FlintEye installation rules were updated.'}


def remove_installation_firewall() -> dict:
    """No profile lock/configuration is needed after all API profiles stop."""
    _require_windows()
    application, media = _programs()
    with _operation(application):
        entries = _owned_inventory(application)
        _execute(_maintenance_dir(), {'action': 'remove-installation', 'id': str(uuid.UUID(int=0)),
            'application': str(application), 'media': str(media)})
        for file, record in entries:
            owner = Path(record['profile'])/'firewall-owner.json'
            try:
                receipt = json.loads(owner.read_text())
            except FileNotFoundError:
                receipt = None  # Do not recreate a deleted profile.
            if (receipt and receipt.get('id') == record['id']
                    and receipt.get('application') == str(application)):
                private_write(owner, json.dumps({**receipt, 'applied': False}).encode())
            file.unlink(missing_ok=True)
    return {'ok': True, 'message': 'Confirmed LAN rules for this installation and its saved profiles were removed.'}
