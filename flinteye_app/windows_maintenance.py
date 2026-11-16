"""Firewall changes require an explicit, owner-local request and UAC."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
from flinteye_app.flinteye_runtime import application_dir
from flinteye_app.network_access import installation_id, private_write
from flinteye_app.subprocess_utils import background_process_options


def manage_firewall(root: Path, config, action: str) -> dict:
    if os.name != 'nt':
        raise ValueError('Automatic Firewall changes are available on Windows only. See the LAN guide for this OS.')
    if action == 'apply' and not config.network.enabled:
        raise ValueError('Enable LAN access before creating its Firewall rules')
    request = root / 'firewall-request.json'
    payload = {'action': action, 'id': installation_id(root), 'address': config.network.address,
               'subnets': config.network.allowed_subnets, 'port': config.api.port,
               'application': str(application_dir().parent / 'FlintEye.exe'),
               'media': str(application_dir() / 'bin/mediamtx.exe')}
    private_write(request, json.dumps(payload).encode())
    script = application_dir() / 'packaging/firewall_windows.ps1'
    # Arguments are supplied as arguments, never interpolated into PowerShell source.
    launcher = application_dir() / 'packaging/elevate_firewall.ps1'
    try:
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-File', str(launcher), '-Script', str(script), '-Request', str(request)],
                       check=True, timeout=180, **background_process_options())
        outcome = {'ok': True, 'message': 'Only the confirmed FlintEye installation rules were updated.'}
        private_write(root/'firewall-owner.json', json.dumps({'id': payload['id'], 'applied': action == 'apply'}).encode())
        return outcome
    finally:
        request.unlink(missing_ok=True)

