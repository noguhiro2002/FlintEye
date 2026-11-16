"""Allowlisted, secret-free diagnostic export. No raw configuration or footage."""
import io
import json
from pathlib import Path
import platform
import re
import zipfile
from flinteye_app._version import RELEASE_VERSION


def diagnostic_archive(context) -> bytes:
    config = context.store.get_effective()
    # Raw logs/configuration/commands can contain unknown custom secrets. Do not
    # attempt to make them shareable with a best-effort URL regular expression.
    processes = context.supervisor.process_status().get('items', [])
    summaries = []
    for item in processes:
        error = str(item.get('last_error') or '')
        match = re.search(r'(?:WinError|Errno) (\d+)', error)
        summaries.append({'component': 'media' if str(item.get('id', '')).startswith('mediamtx') else 'worker',
                          'state': item.get('status'), 'os_error_number': match.group(1) if match else None,
                          'has_error': bool(error), 'exit_code': item.get('exit_code')})
    root = Path(context.store.runtime_file).resolve().parent
    receipt = {}
    try:
        raw = json.loads((root/'last-monitoring-stop.json').read_text())
        receipt = {key: raw.get(key) for key in ('at', 'ok', 'pending_segments', 'forced')}
    except (OSError, ValueError):
        pass
    result = {'release': RELEASE_VERSION, 'os': platform.system(), 'cpu': platform.machine(),
              'cameras_configured': len(config.cameras), 'cameras_enabled': sum(c.enabled for c in config.cameras),
              'lan_enabled': config.network.enabled, 'processes': summaries, 'last_stop': receipt,
              'media_executable_exists': bool(config.mediamtx.direct.command and Path(config.mediamtx.direct.command[0]).is_file()),
              'media_working_directory_exists': bool(config.mediamtx.direct.working_dir and Path(config.mediamtx.direct.working_dir).is_dir())}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('diagnostics.json', json.dumps(result, indent=2))
        archive.writestr('README.txt', 'Contains allowlisted status only. No raw logs, camera URLs, paths, passwords, tokens, hashes, private keys or video.\n')
    return stream.getvalue()
