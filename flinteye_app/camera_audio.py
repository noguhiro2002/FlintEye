"""Resolve camera microphones and keep archive and WebRTC audio formats separate."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from flinteye_app.flinteye_runtime import private_media_input_command
from flinteye_app.process_lifetime import run_background
from flinteye_app.subprocess_utils import background_process_options

LIVE_PREFIX = '__flinteye_audio'


def live_path(path: str) -> str:
    return f'{LIVE_PREFIX}/{hashlib.sha256(path.encode()).hexdigest()}'


def _usb_parent(path: Path) -> Path | None:
    real_path = path.resolve()
    return next((parent for parent in (real_path, *real_path.parents)
                 if (parent/'idVendor').is_file() and (parent/'idProduct').is_file()), None)


def _linux_microphone(device: str) -> tuple[str, str | None]:
    name = Path(device).name
    node = Path('/sys/class/video4linux')/name
    parent = _usb_parent(node/'device')
    if not node.exists() or parent is None:
        return 'unknown', None
    try:
        capture = Path('/proc/asound/pcm').read_text().splitlines()
    except OSError:
        return 'unknown', None
    matches = []
    for line in capture:
        indices = re.match(r'(\d+)-(\d+):.*\bcapture\s+[1-9]', line)
        if not indices:
            continue
        card, pcm = map(int, indices.groups())
        if _usb_parent(Path(f'/sys/class/sound/card{card}/device')) == parent:
            matches.append((card, pcm))
    if not matches:
        return 'no_input', None
    card, pcm = min(matches)
    capture_node = Path(f'/dev/snd/pcmC{card}D{pcm}c')
    if not os.access(capture_node, os.R_OK | os.W_OK):
        return 'permission', None
    if not shutil.which('arecord'):
        return 'capture_unavailable', None
    return 'available', f'plughw:{card},{pcm}'


def _windows_container_pairs() -> dict[str, set[str]]:
    """Associate unique labels only when PnP reports the same physical device."""
    script = """
    $items = Get-PnpDevice -PresentOnly -Class Camera,Image,AudioEndpoint
    foreach ($item in $items) {
      $id = (Get-PnpDeviceProperty -InstanceId $item.InstanceId -KeyName 'DEVPKEY_Device_ContainerId' -ErrorAction SilentlyContinue).Data
      if ($id -and $item.FriendlyName) { [PSCustomObject]@{Name=$item.FriendlyName; Container=[string]$id} }
    }
    """
    result = run_background(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         '@(& { ' + script + ' }) | ConvertTo-Json -Compress'],
        **background_process_options(), capture_output=True, text=True, timeout=6,
    )
    rows = json.loads(result.stdout or '[]')
    pairs: dict[str, set[str]] = {}
    for row in rows if isinstance(rows, list) else [rows]:
        container = row['Container'].strip('{}').lower()
        if container not in {'00000000-0000-0000-0000-000000000000',
                             '00000000-0000-0000-ffff-ffffffffffff'}:
            pairs.setdefault(row['Name'].casefold(), set()).add(container)
    return pairs


def _desktop_microphone(driver: str, device: str, ffmpeg_bin: str) -> tuple[str, str | None]:
    from flinteye_app.orchestrator_uvc_probe import _parse_avfoundation_devices, _run_capture

    mac = driver == 'avfoundation'
    probe = _run_capture([ffmpeg_bin, '-hide_banner', '-f', driver, '-list_devices', 'true',
                          '-i', '' if mac else 'dummy'], 5)
    output = (probe.stdout or '') + '\n' + (probe.stderr or '')
    if 'permission denied' in output.lower() or 'not authorized' in output.lower():
        return 'permission', None
    if mac:
        cameras = _parse_avfoundation_devices(output)
        name = next((item['display_name'] for item in cameras
                     if device in {item['ffmpeg_device'], item['ffmpeg_device_index']}), '')
        _, _, microphones = output.partition('AVFoundation audio devices')
        labels = re.findall(r'\[\d+\]\s+([^\r\n]+)', microphones)
        found = [label.strip() for label in labels if label.strip().casefold() == name.casefold()]
        if len(found) == 1 and sum(item['display_name'] == name for item in cameras) == 1:
            return 'available', found[0]
        return ('no_input' if name and not labels else 'unknown'), None

    name = device.removeprefix('video=').casefold()
    labels = re.findall(r'"([^"]+)"\s+\(audio\)', output)
    if not labels and 'DirectShow audio devices' in output:
        section = output.split('DirectShow audio devices', 1)[1]
        labels = [match[1] for line in section.splitlines() if 'Alternative name' not in line
                  if (match := re.search(r'"([^"]+)"', line))]
    pairs = _windows_container_pairs()
    identities = pairs.get(name, set())
    found = [label for label in labels if len(identities) == 1 and pairs.get(label.casefold()) == identities]
    if len(found) == 1:
        return 'available', found[0]
    return ('no_input' if identities and not found else 'unknown'), None


def microphone(driver: str, device: str, ffmpeg_bin: str) -> tuple[str, str | None]:
    try:
        if driver == 'v4l2':
            return _linux_microphone(device)
        return _desktop_microphone(driver, device, ffmpeg_bin)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return 'unknown', None


def probe_audio(ffprobe_bin: str, source: str | Path, *, rtsp=False) -> tuple[str, str | None]:
    cmd = [ffprobe_bin, '-v', 'error']
    if rtsp:
        cmd += ['-rtsp_transport', 'tcp', '-timeout', '3000000']
    cmd += ['-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'json',
            '-i', str(source)]
    try:
        with private_media_input_command(cmd, str(source), force=True) if rtsp else nullcontext(cmd) as safe:
            item = run_background(safe, **background_process_options(), check=True, capture_output=True,
                                  text=True, timeout=7)
        streams = json.loads(item.stdout).get('streams', [])
        return ('available', streams[0].get('codec_name')) if streams else ('no_input', None)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 'unknown', None


def add_capture_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--audio-codec', choices=['pcm_s16be', 'pcm_s24be', 'aac'])
    parser.add_argument('--audio-rate', type=int, default=16000)
    parser.add_argument('--audio-channels', type=int, default=1)
    parser.add_argument('--audio-bitrate', type=int, default=64)


def output_args(args) -> list[str]:
    codec = getattr(args, 'audio_codec', None)
    if not codec:
        return ['-an']
    options = ['-c:a', codec, '-ar', str(args.audio_rate), '-ac', str(args.audio_channels)]
    if codec == 'aac':
        options += ['-b:a', f'{args.audio_bitrate}k']
    return options
