#!/usr/bin/env python3
"""Compose multiple MediaMTX RTSP streams into multi-view RTSP outputs."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import subprocess
from flinteye_app.process_lifetime import popen_background, run_background
from flinteye_app.subprocess_utils import background_process_options
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


WINDOWS_ENCODERS = [
    "h264_qsv",
    "h264_amf",
    "h264_nvenc",
    "libx264",
]

MACOS_ENCODERS = [
    "h264_videotoolbox",
    "libx264",
]

LINUX_ENCODERS = [
    "h264_v4l2m2m",
    "h264_nvenc",
    "h264_qsv",
    "h264_amf",
    "libx264",
]

QUALITY_PRESETS = {
    "high": {"bitrate": "4M", "maxrate": "4M", "bufsize": "8M"},
    "standard": {"bitrate": "2M", "maxrate": "2M", "bufsize": "4M"},
    "low": {"bitrate": "1M", "maxrate": "1M", "bufsize": "2M"},
}

LATENCY_PRESETS = {"normal", "low"}

TRUTHY_VALUES = {"1", "true", "yes", "on"}
FALSY_VALUES = {"0", "false", "no", "off"}
FFMPEG_OPTION_ERROR_PATTERNS = (
    "Option not found",
    "Unrecognized option",
    "Error parsing options",
)
FFMPEG_DECODE_ERROR_PATTERNS = (
    "error while decoding",
    "decode_slice_header error",
    "invalid nal unit",
    "corrupt decoded frame",
    "missing picture in access unit",
)
RTSP_STARTUP_BUDGET_PER_REMAINING_INPUT_SEC = 5.0


@dataclass
class ViewSpec:
    index: int
    sources: list[str]
    slots: list[tuple[int, int, int, int]]


@dataclass
class ViewRuntime:
    spec: ViewSpec
    encoder_idx: int = 0
    process: subprocess.Popen[str] | None = None
    next_restart_at: float = 0.0
    started_at: float | None = None
    restart_count: int = 0
    decode_error_count: int = 0


@dataclass
class InputHealth:
    source: str
    state: str = "starting"
    last_bytes_received: int | None = None
    last_progress_at: float = field(default_factory=time.time)
    stable_since: float | None = None
    unhealthy_since: float | None = None
    recovery_since: float | None = None
    failures: int = 0
    isolated: bool = False
    retry_at: float = 0.0
    reason: str | None = None


def load_env_file(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path or not os.path.isfile(path):
        return env

    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and (
                (value[0] == "'" and value[-1] == "'")
                or (value[0] == '"' and value[-1] == '"')
            ):
                value = value[1:-1]
            env[key] = value
    return env


def parse_env_int(value: str, key: str) -> int:
    try:
        return int(value)
    except ValueError as e:
        raise ValueError(f"{key} must be an integer: '{value}'") from e


def parse_env_float(value: str, key: str) -> float:
    try:
        return float(value)
    except ValueError as e:
        raise ValueError(f"{key} must be a number: '{value}'") from e


def parse_env_bool(value: str, key: str) -> bool:
    lowered = value.strip().lower()
    if lowered in TRUTHY_VALUES:
        return True
    if lowered in FALSY_VALUES:
        return False
    raise ValueError(f"{key} must be one of {sorted(TRUTHY_VALUES | FALSY_VALUES)}: '{value}'")


def run_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return run_background(cmd, **background_process_options(), capture_output=True, text=True, check=False)


def has_drawtext_filter(ffmpeg_bin: str) -> bool:
    result = run_capture([ffmpeg_bin, "-hide_banner", "-filters"])
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    return re.search(r"\bdrawtext\b", text) is not None


def auto_default_font_path() -> str | None:
    candidates: list[str] = []
    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
        candidates = [
            os.path.join(windir, "Fonts", "arial.ttf"),
            os.path.join(windir, "Fonts", "meiryo.ttc"),
            os.path.join(windir, "Fonts", "msgothic.ttc"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
        ]
    elif sys.platform.startswith("linux"):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def normalize_fontfile_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if not sys.platform.startswith("win"):
        return normalized

    m = re.match(r"^([A-Za-z]):/(.*)$", normalized)
    if not m:
        return normalized

    sys_root = (os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows").replace("\\", "/")
    sys_drive = re.match(r"^([A-Za-z]):/", sys_root)
    if sys_drive and m.group(1).lower() == sys_drive.group(1).lower():
        return "/" + m.group(2)
    return normalized


def escape_drawtext_text(value: str) -> str:
    return (
        value.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def escape_filter_value(value: str) -> str:
    value = normalize_fontfile_path(value)
    return (
        value.replace("\\", r"\\")
        .replace(":", r"\\:")
        .replace(",", r"\\,")
        .replace("'", r"\'")
    )


def parse_path_list(value: str | None) -> list[str]:
    if not value:
        return []
    out: list[str] = []
    for part in re.split(r"[,\n;]", value):
        normalized = normalize_path_name(part)
        if normalized:
            out.append(normalized)
    return out


def normalize_path_name(path: str) -> str:
    return path.strip().strip("/")


def parse_source_label_map(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"source label map must be valid JSON: {e}") from e
    if not isinstance(payload, dict):
        raise ValueError("source label map must be a JSON object")

    out: dict[str, str] = {}
    for raw_key, raw_value in payload.items():
        normalized_key = normalize_path_name(str(raw_key))
        text = str(raw_value).strip()
        if normalized_key and text:
            out[normalized_key] = text
    return out


def parse_source_placeholder_map(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"source placeholder map must be valid JSON: {e}") from e
    if not isinstance(payload, dict):
        raise ValueError("source placeholder map must be a JSON object")

    out: dict[str, str] = {}
    for raw_key, raw_value in payload.items():
        normalized_key = normalize_path_name(str(raw_key))
        text = str(raw_value).strip()
        if normalized_key:
            out[normalized_key] = text or "No stream"
    return out


def get_source_placeholder_reason(args: argparse.Namespace, source_path: str) -> str:
    normalized = normalize_path_name(source_path)
    return (
        args.source_placeholder_map.get(normalized)
        or args.health_placeholder_map.get(normalized)
        or args.dynamic_source_placeholder_map.get(normalized, "")
    )


def normalize_unique(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        normalized = normalize_path_name(path)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def is_multiview_output_path(path_name: str, prefix: str) -> bool:
    if not prefix:
        return False
    path_lower = path_name.lower()
    prefix_lower = prefix.lower()
    return path_lower == prefix_lower or path_lower.startswith(prefix_lower + "_")


def join_rtsp_url(base_url: str, path_name: str) -> str:
    return base_url.rstrip("/") + "/" + path_name.lstrip("/")


def run_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return run_background(cmd, **background_process_options(), capture_output=True, text=True, check=False)


def preferred_encoders_for_platform() -> list[str]:
    if sys.platform.startswith("win"):
        return WINDOWS_ENCODERS
    if sys.platform == "darwin":
        return MACOS_ENCODERS
    if sys.platform.startswith("linux"):
        return LINUX_ENCODERS
    return LINUX_ENCODERS


def get_available_encoders(ffmpeg_bin: str) -> set[str]:
    result = run_capture([ffmpeg_bin, "-hide_banner", "-encoders"])
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    encoders: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        m = re.match(r"^[A-Z\.]{6}\s+([^\s]+)\s+", line)
        if m:
            encoders.add(m.group(1))
    return encoders


def ffmpeg_help_contains_option(ffmpeg_bin: str, help_target: str, option_name: str) -> bool:
    result = run_capture([ffmpeg_bin, "-hide_banner", "-h", help_target])
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    return re.search(rf"(^|\n)\s*-{re.escape(option_name)}\b", text) is not None


def output_has_option_error(text: str) -> bool:
    return any(pattern in text for pattern in FFMPEG_OPTION_ERROR_PATTERNS)


def probe_input_stall_timeout_option(ffmpeg_bin: str, option_name: str) -> bool:
    try:
        return ffmpeg_help_contains_option(ffmpeg_bin, "demuxer=rtsp", option_name)
    except FileNotFoundError:
        return False


def detect_input_stall_timeout_option(ffmpeg_bin: str) -> str | None:
    # Only use options advertised by the RTSP demuxer. A generic AVIO option
    # may appear in `-h full` but still fail with "Option not found" on RTSP.
    for option_name in ("timeout", "stimeout", "rw_timeout"):
        if probe_input_stall_timeout_option(ffmpeg_bin, option_name):
            return option_name
    return None


def resolve_input_stall_timeout_option(args: argparse.Namespace) -> None:
    requested = args.input_stall_timeout_option
    if args.input_stall_timeout_sec <= 0 or requested == "none":
        args.input_stall_timeout_arg = None
        return

    if requested != "auto":
        if probe_input_stall_timeout_option(args.ffmpeg_bin, requested):
            args.input_stall_timeout_arg = requested
        else:
            args.input_stall_timeout_arg = None
            print(
                f"[warn] FFmpeg rejected -{requested}; input stall timeout is disabled",
                file=sys.stderr,
            )
        return

    args.input_stall_timeout_arg = detect_input_stall_timeout_option(args.ffmpeg_bin)
    if args.input_stall_timeout_arg is None:
        print(
            "[warn] no supported FFmpeg RTSP timeout option found; input stall timeout is disabled",
            file=sys.stderr,
        )


def build_encoder_candidates(available: set[str], requested: str) -> list[str]:
    if requested != "auto":
        if requested not in available:
            raise ValueError(
                f"Requested encoder '{requested}' is not available in this ffmpeg build."
            )
        return [requested]

    candidates = [enc for enc in preferred_encoders_for_platform() if enc in available]
    if not candidates:
        raise ValueError("No supported H.264 encoder found in this ffmpeg build.")
    return candidates


def preferred_pix_fmt_for_encoder(encoder: str) -> str:
    if encoder in {"h264_qsv", "h264_amf"}:
        return "nv12"
    return "yuv420p"


def resolve_rate_control(args: argparse.Namespace) -> None:
    values = QUALITY_PRESETS[args.quality_preset].copy()
    if args.bitrate is not None:
        values["bitrate"] = args.bitrate
    if args.maxrate is not None:
        values["maxrate"] = args.maxrate
    if args.bufsize is not None:
        values["bufsize"] = args.bufsize
    args.bitrate = values["bitrate"]
    args.maxrate = values["maxrate"]
    args.bufsize = values["bufsize"]


def extract_paths_from_api_payload(payload: object) -> list[str]:
    out: list[str] = []

    def add_name(value: object) -> None:
        if isinstance(value, str):
            normalized = normalize_path_name(value)
            if normalized:
                out.append(normalized)

    def is_ready_item(value: object) -> bool:
        if not isinstance(value, dict):
            return True
        if "ready" in value:
            return bool(value.get("ready"))
        return True

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                if not is_ready_item(item):
                    continue
                add_name(item.get("name"))
                add_name(item.get("path"))
            else:
                add_name(item)
        return out

    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            out += extract_paths_from_api_payload(items)

        paths = payload.get("paths")
        if isinstance(paths, list):
            out += extract_paths_from_api_payload(paths)
        elif isinstance(paths, dict):
            for key, value in paths.items():
                if not is_ready_item(value):
                    continue
                add_name(key)

        if not out:
            # Fallback for unknown schema that still stores path names as keys.
            for key, value in payload.items():
                if key in {"itemCount", "page", "itemsPerPage"}:
                    continue
                if isinstance(value, dict):
                    add_name(key)

    return out


def fetch_paths_from_api(api_url: str) -> list[str]:
    request = urllib.request.Request(api_url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return normalize_unique(extract_paths_from_api_payload(payload))


def _fetch_json(api_url: str) -> dict[str, object]:
    request = urllib.request.Request(api_url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def fetch_input_metrics(api_url: str) -> tuple[dict[str, dict[str, object]], set[str]]:
    paths_payload = _fetch_json(api_url)
    paths: dict[str, dict[str, object]] = {}
    for item in paths_payload.get("items", []) if isinstance(paths_payload.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        name = normalize_path_name(str(item.get("name") or item.get("path") or ""))
        if name:
            paths[name] = item

    sessions_url = api_url.replace("/paths/list", "/rtspsessions/list")
    sessions_payload = _fetch_json(sessions_url)
    readers: set[str] = set()
    for item in sessions_payload.get("items", []) if isinstance(sessions_payload.get("items"), list) else []:
        if not isinstance(item, dict) or str(item.get("state") or "").lower() != "read":
            continue
        path = normalize_path_name(str(item.get("path") or ""))
        if path:
            readers.add(path)
    return paths, readers


def write_status_file(
    args: argparse.Namespace,
    views: list[ViewRuntime],
    states: dict[str, InputHealth],
) -> None:
    if not args.status_file:
        return
    path = Path(args.status_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": time.time(),
        "views": [
            {
                "id": f"{args.output_prefix}_{runtime.spec.index}",
                "state": (
                    "degraded"
                    if any(states[source].state != "healthy" for source in runtime.spec.sources)
                    else "healthy"
                ),
                "restart_count": runtime.restart_count,
                "decode_error_count": runtime.decode_error_count,
                "inputs": [
                    {
                        "path": source,
                        "state": states[source].state,
                        "last_progress_at": states[source].last_progress_at,
                        "failures": states[source].failures,
                        "isolated": states[source].isolated,
                        "reason": states[source].reason,
                    }
                    for source in runtime.spec.sources
                ],
            }
            for runtime in views
        ],
    }
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temp_path, path)


def view_startup_grace_sec(args: argparse.Namespace, runtime: ViewRuntime) -> float:
    base_timeout = args.input_stall_timeout_sec if args.input_stall_timeout_sec > 0 else 15.0
    network_input_count = sum(
        1
        for source in runtime.spec.sources
        if not args.health_placeholder_map.get(source)
    )
    return (
        base_timeout
        + max(0, network_input_count - 1) * RTSP_STARTUP_BUDGET_PER_REMAINING_INPUT_SEC
    )


def poll_input_health(
    args: argparse.Namespace,
    runtimes: list[ViewRuntime],
    states: dict[str, InputHealth],
    *,
    now: float,
) -> set[int]:
    affected_views: set[int] = set()
    health_stall_timeout = args.input_stall_timeout_sec if args.input_stall_timeout_sec > 0 else 15.0
    try:
        paths, readers = fetch_input_metrics(args.mtx_api_url)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
        for state in states.values():
            state.state = "degraded"
            state.reason = f"MediaMTX health API unavailable: {exc}"
        write_status_file(args, runtimes, states)
        return affected_views

    source_to_runtime = {
        source: runtime
        for runtime in runtimes
        for source in runtime.spec.sources
    }
    for source, state in states.items():
        item = paths.get(source)
        ready = bool(item and item.get("ready"))
        try:
            received = int((item or {}).get("bytesReceived") or 0)
        except (TypeError, ValueError):
            received = 0
        progressed = state.last_bytes_received is None or received != state.last_bytes_received
        if progressed:
            state.last_progress_at = now
        state.last_bytes_received = received
        has_reader = source in readers
        runtime = source_to_runtime[source]

        if state.isolated:
            state.state = "isolated"
            state.reason = state.reason or "Input isolated after repeated recovery failures"
            if now >= state.retry_at and ready and progressed:
                state.recovery_since = state.recovery_since or now
                if now - state.recovery_since >= 10:
                    state.isolated = False
                    state.unhealthy_since = None
                    state.reason = None
                    state.state = "starting"
                    state.retry_at = 0
                    args.health_placeholder_map.pop(source, None)
                    affected_views.add(runtime.spec.index)
            elif now >= state.retry_at:
                state.recovery_since = None
                state.retry_at = now + args.input_retry_interval_sec
            continue

        view_running = runtime.process is not None and runtime.process.poll() is None
        startup_grace = view_startup_grace_sec(args, runtime)
        within_startup_grace = runtime.started_at is not None and now - runtime.started_at < startup_grace
        if not view_running or within_startup_grace:
            state.state = "starting"
            state.reason = "Multiview process is restarting" if not view_running else "Waiting for Multiview reader"
            state.unhealthy_since = None
            continue

        publisher_healthy = ready and now - state.last_progress_at < health_stall_timeout
        if publisher_healthy and has_reader:
            state.state = "healthy"
            state.reason = None
            state.unhealthy_since = None
            state.stable_since = state.stable_since or now
            if now - state.stable_since >= 60:
                state.failures = 0
            continue

        state.stable_since = None
        state.unhealthy_since = state.unhealthy_since or now
        reasons = []
        if not ready:
            reasons.append("MediaMTX path is not ready")
        if not has_reader:
            reasons.append("Multiview RTSP reader is missing")
        if now - state.last_progress_at >= health_stall_timeout:
            reasons.append("Input bytes are not progressing")
        state.state = "degraded"
        state.reason = "; ".join(reasons) or "Input is starting"

        if now - state.unhealthy_since < health_stall_timeout:
            continue

        # A missing reader is a View-level fault. It must restart the View, but
        # must not be counted while the whole View is down. When the View output
        # is ready and only this reader is missing, however, the fault is local
        # to this input and repeated recovery failures should isolate it.
        if publisher_healthy:
            state.unhealthy_since = now
            output_path = f"{args.output_prefix}_{runtime.spec.index}"
            output_item = paths.get(output_path)
            output_ready = bool(output_item and output_item.get("ready"))
            if not has_reader and output_ready:
                state.failures += 1
                if state.failures >= args.input_isolation_threshold:
                    state.isolated = True
                    state.state = "isolated"
                    state.retry_at = now + args.input_retry_interval_sec
                    state.reason = "Input isolated after repeated Multiview reader failures"
                    args.health_placeholder_map[source] = state.reason
                    affected_views.add(runtime.spec.index)
            else:
                # The complete View is unavailable rather than one reader being
                # absent from a still-publishing View. Restart it without
                # charging the failure to this otherwise healthy input.
                affected_views.add(runtime.spec.index)
            continue

        state.failures += 1
        state.unhealthy_since = now
        affected_views.add(runtime.spec.index)
        if state.failures >= args.input_isolation_threshold:
            state.isolated = True
            state.state = "isolated"
            state.retry_at = now + args.input_retry_interval_sec
            state.reason = "Input isolated after repeated recovery failures"
            args.health_placeholder_map[source] = state.reason

    write_status_file(args, runtimes, states)
    return affected_views


def refresh_missing_source_placeholders(
    args: argparse.Namespace,
    source_paths: list[str],
) -> bool:
    if not args.auto_placeholder_missing_sources:
        return False

    try:
        ready_sources = set(fetch_paths_from_api(args.mtx_api_url))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as e:
        now = time.time()
        last_warn_at = getattr(args, "last_placeholder_api_warn_at", 0.0)
        if now - last_warn_at >= 30:
            print(
                f"[warn] failed to refresh MediaMTX path readiness for placeholders: {e}",
                file=sys.stderr,
            )
            args.last_placeholder_api_warn_at = now
        return False

    static_placeholders = set(args.source_placeholder_map)
    next_dynamic: dict[str, str] = {}
    for source_path in source_paths:
        normalized = normalize_path_name(source_path)
        if not normalized or normalized in static_placeholders:
            continue
        if normalized not in ready_sources:
            next_dynamic[normalized] = "MediaMTX path is not ready"

    changed = next_dynamic != args.dynamic_source_placeholder_map
    if changed:
        missing = ", ".join(next_dynamic) if next_dynamic else "none"
        print(
            f"[warn] missing MediaMTX paths rendered as No Stream placeholders: {missing}",
            file=sys.stderr,
        )
    args.dynamic_source_placeholder_map = next_dynamic
    return changed


def parse_slot_positions(value: str, key: str) -> list[tuple[int, int, int, int]]:
    slots: list[tuple[int, int, int, int]] = []
    raw_items = [item.strip() for item in value.split(";") if item.strip()]
    if not raw_items:
        raise ValueError(f"{key} must contain at least one slot definition")

    for idx, item in enumerate(raw_items):
        parts = [p.strip() for p in item.split(",")]
        if len(parts) != 4:
            raise ValueError(
                f"{key} slot#{idx + 1} must be 'x,y,w,h', got '{item}'"
            )
        try:
            x, y, w, h = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        except ValueError as e:
            raise ValueError(
                f"{key} slot#{idx + 1} has non-integer values: '{item}'"
            ) from e
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            raise ValueError(
                f"{key} slot#{idx + 1} must satisfy x>=0,y>=0,w>0,h>0: '{item}'"
            )
        slots.append((x, y, w, h))
    return slots


def build_auto_slots(
    tile_count: int,
    canvas_width: int,
    canvas_height: int,
    grid_columns: int | None,
) -> list[tuple[int, int, int, int]]:
    cols = grid_columns if grid_columns and grid_columns > 0 else math.ceil(math.sqrt(tile_count))
    rows = math.ceil(tile_count / cols)

    slots: list[tuple[int, int, int, int]] = []
    for idx in range(tile_count):
        row = idx // cols
        col = idx % cols
        x0 = (canvas_width * col) // cols
        x1 = (canvas_width * (col + 1)) // cols
        y0 = (canvas_height * row) // rows
        y1 = (canvas_height * (row + 1)) // rows
        slots.append((x0, y0, max(1, x1 - x0), max(1, y1 - y0)))
    return slots


def select_slots_for_view(
    args: argparse.Namespace,
    view_index: int,
) -> list[tuple[int, int, int, int]]:
    view_key = f"MV_VIEW_{view_index}_SLOT_POSITIONS"
    view_value = args.env_values.get(view_key)
    if view_value:
        slots = parse_slot_positions(view_value, view_key)
    elif args.slot_positions:
        slots = parse_slot_positions(args.slot_positions, "MV_SLOT_POSITIONS")
    else:
        slots = build_auto_slots(
            tile_count=args.tile_count,
            canvas_width=args.canvas_width,
            canvas_height=args.canvas_height,
            grid_columns=args.grid_columns,
        )

    if len(slots) < args.tile_count:
        raise ValueError(
            f"View {view_index}: slot definitions are fewer than MV_TILE_COUNT "
            f"({len(slots)} < {args.tile_count})"
        )
    return slots[: args.tile_count]


def build_views(
    args: argparse.Namespace,
    source_paths: list[str],
) -> list[ViewSpec]:
    views: list[ViewSpec] = []
    for index, start in enumerate(range(0, len(source_paths), args.tile_count), start=1):
        view_sources = source_paths[start : start + args.tile_count]
        slots = select_slots_for_view(args, index)
        views.append(ViewSpec(index=index, sources=view_sources, slots=slots))
    return views


def build_page_command(
    args: argparse.Namespace,
    view: ViewSpec,
    encoder: str,
) -> list[str]:
    cmd = [args.ffmpeg_bin, "-hide_banner", "-loglevel", args.loglevel]

    network_input_indexes = [
        index
        for index, source in enumerate(view.sources)
        if not get_source_placeholder_reason(args, source)
    ]
    for source_idx, source_path in enumerate(view.sources):
        placeholder_reason = get_source_placeholder_reason(args, source_path)
        if placeholder_reason:
            slot = view.slots[source_idx]
            cmd += [
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={slot[2]}x{slot[3]}:r={args.fps}",
            ]
            continue

        input_timeout_arg = getattr(args, "input_stall_timeout_arg", None)
        if args.input_stall_timeout_sec > 0 and input_timeout_arg:
            remaining_network_inputs = sum(index > source_idx for index in network_input_indexes)
            # FFmpeg opens RTSP inputs serially. Earlier sockets otherwise spend
            # most of their timeout waiting for later inputs to open. Preserve
            # the configured steady-state health threshold in the supervisor,
            # while giving the demuxer enough startup time for the remaining
            # inputs.
            effective_timeout_sec = (
                args.input_stall_timeout_sec
                + remaining_network_inputs * RTSP_STARTUP_BUDGET_PER_REMAINING_INPUT_SEC
            )
            cmd += [
                f"-{input_timeout_arg}",
                str(int(effective_timeout_sec * 1_000_000)),
            ]
        queue_size = min(args.input_thread_queue_size, 32) if args.latency_preset == "low" else args.input_thread_queue_size
        cmd += ["-thread_queue_size", str(queue_size)]
        if args.latency_preset == "low":
            # Reduce RTSP demux buffering and normalize timestamp source.
            cmd += [
                "-fflags",
                "+genpts+nobuffer",
                "-flags",
                "low_delay",
                "-use_wallclock_as_timestamps",
                "1",
                "-analyzeduration",
                "0",
                "-probesize",
                "32k",
                "-max_delay",
                "0",
            ]
        cmd += [
            "-rtsp_transport",
            "tcp",
            "-i",
            join_rtsp_url(args.input_rtsp_base_url, source_path),
        ]

    for slot_idx in range(len(view.sources), args.tile_count):
        slot = view.slots[slot_idx]
        cmd += [
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={slot[2]}x{slot[3]}:r={args.fps}",
        ]

    chains: list[str] = []
    labels: list[str] = []
    for idx, slot in enumerate(view.slots):
        x, y, width, height = slot
        if args.latency_preset == "low":
            timing_chain = (
                f"fps={args.fps}:round=down,"
                f"settb=AVTB,setpts=N/({args.fps}*TB)"
            )
        else:
            timing_chain = f"fps={args.fps},setpts=PTS-STARTPTS"
        chain = (
            f"[{idx}:v]{timing_chain},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
        source_label = ""
        placeholder_reason = ""
        if idx < len(view.sources):
            normalized_source = normalize_path_name(view.sources[idx])
            source_label = args.source_label_map.get(normalized_source, "")
            placeholder_reason = get_source_placeholder_reason(args, normalized_source)
        if placeholder_reason and args.text_overlay_enabled:
            fontopt: list[str] = []
            if args.label_fontfile:
                fontopt.append(f"fontfile='{escape_filter_value(args.label_fontfile)}'")
            chain += ",drawtext=" + ":".join(
                fontopt
                + [
                    "text='No Stream'",
                    "expansion=none",
                    "x=24",
                    "y=24",
                    f"fontsize={max(args.label_font_size + 6, 24)}",
                    "fontcolor=white",
                    "shadowcolor=black",
                    "shadowx=2",
                    "shadowy=2",
                ]
            )
            reason_text = placeholder_reason
            if len(reason_text) > 72:
                reason_text = reason_text[:69] + "..."
            chain += ",drawtext=" + ":".join(
                fontopt
                + [
                    f"text='{escape_drawtext_text(reason_text)}'",
                    "expansion=none",
                    "x=24",
                    "y=64",
                    f"fontsize={max(args.label_font_size - 2, 14)}",
                    "fontcolor=white",
                    "shadowcolor=black",
                    "shadowx=1",
                    "shadowy=1",
                ]
            )
        if source_label and args.text_overlay_enabled:
            fontopt: list[str] = []
            if args.label_fontfile:
                fontopt.append(f"fontfile='{escape_filter_value(args.label_fontfile)}'")
            label_band_height = max(28, args.label_font_size + 14)
            drawtext_common = [
                f"fontsize={args.label_font_size}",
                "fontcolor=white",
                "shadowcolor=black",
                "shadowx=2",
                "shadowy=2",
            ]
            chain += (
                f",drawbox=x=0:y=ih-{label_band_height}:w=iw:h={label_band_height}:"
                "color=black@0.45:t=fill"
            )
            chain += ",drawtext=" + ":".join(
                fontopt
                + [
                    f"text='{escape_drawtext_text(source_label)}'",
                    "expansion=none",
                    "x=12",
                    "y=h-th-8",
                ]
                + drawtext_common
            )
        chain += f"[v{idx}]"
        chains.append(chain)
        labels.append(f"[v{idx}]")

    layout = "|".join(f"{slot[0]}_{slot[1]}" for slot in view.slots)
    chains.append(
        "".join(labels)
        + f"xstack=inputs={args.tile_count}:layout={layout}:fill=black[outv]"
    )
    filter_complex = ";".join(chains)

    pix_fmt = preferred_pix_fmt_for_encoder(encoder)
    output_path = f"{args.output_prefix}_{view.index}"
    output_url = join_rtsp_url(args.output_rtsp_base_url, output_path)

    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-an",
        "-pix_fmt",
        pix_fmt,
        "-c:v",
        encoder,
        "-bf",
        str(args.bframes),
    ]
    if encoder == "libx264":
        cmd += ["-preset", args.x264_preset, "-tune", "zerolatency"]
    cmd += [
        "-b:v",
        args.bitrate,
        "-maxrate",
        args.maxrate,
        "-bufsize",
        args.bufsize,
        "-g",
        str(args.gop),
        "-flush_packets",
        "1",
        "-muxdelay",
        "0",
        "-muxpreload",
        "0",
        "-rtsp_transport",
        "tcp",
        "-f",
        "rtsp",
        output_url,
    ]
    return cmd


def resolve_sources(args: argparse.Namespace) -> list[str]:
    env_sources = normalize_unique(parse_path_list(args.source_paths))
    env_source_set = {source.lower() for source in env_sources}
    shadowed_sources = {
        source.lower() for source in normalize_unique(parse_path_list(args.shadowed_source_paths))
    }
    api_sources: list[str] = []
    if args.source_mode in {"api", "hybrid"}:
        try:
            api_sources = fetch_paths_from_api(args.mtx_api_url)
            api_sources = [
                source
                for source in api_sources
                if source.lower() not in shadowed_sources
                and (
                    not source.lower().startswith(("__mv_input/", "__mv_buffer/"))
                    or source.lower() in env_source_set
                )
            ]
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            if args.source_mode == "api":
                raise ValueError(f"Failed to fetch sources from API: {e}") from e
            print(f"[warn] API source fetch failed, using env sources only: {e}", file=sys.stderr)

    if args.source_mode == "env":
        merged = env_sources
    elif args.source_mode == "api":
        merged = api_sources
    else:
        merged = normalize_unique(env_sources + api_sources)

    filtered = [
        src
        for src in merged
        if not is_multiview_output_path(src, args.output_prefix)
    ]
    filtered = filtered[: args.max_sources]

    if len(filtered) < 2:
        raise ValueError(
            "Need at least 2 source paths after filtering. "
            "Set MV_SOURCE_PATHS and/or MV_SOURCE_MODE=api."
        )
    return filtered


def format_cmd_for_display(cmd: list[str]) -> str:
    if sys.platform.startswith("win"):
        return subprocess.list2cmdline(cmd)
    return " ".join(shlex.quote(part) for part in cmd)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file", default=".env")
    pre.add_argument("--no-env", action="store_true")
    pre_args, _ = pre.parse_known_args(argv)

    env_values: dict[str, str] = {}
    env_path = pre_args.env_file
    env_loaded_path: str | None = None
    if not pre_args.no_env and env_path:
        if os.path.isfile(env_path):
            env_values = load_env_file(env_path)
            env_loaded_path = env_path
        elif env_path != ".env":
            raise SystemExit(f"env file not found: {env_path}")

    p = argparse.ArgumentParser(
        description="Compose multiple MediaMTX camera streams into multi-view RTSP streams."
    )
    p.add_argument("--env-file", default=env_path, help="Path to .env file (default: .env)")
    p.add_argument("--no-env", action="store_true", help="Ignore .env values")
    p.add_argument("--source-mode", choices=["env", "api", "hybrid"], default="hybrid")
    p.add_argument("--source-paths", help="Comma-separated source paths in MediaMTX")
    p.add_argument("--shadowed-source-paths", help="Public paths replaced by internal Multiview inputs")
    p.add_argument("--mtx-api-url", default="http://127.0.0.1:9997/v3/paths/list")
    p.add_argument("--input-rtsp-base-url", default="rtsp://127.0.0.1:8554")
    p.add_argument("--output-rtsp-base-url", default="rtsp://127.0.0.1:8554")
    p.add_argument("--output-prefix", default="multiview")
    p.add_argument("--max-sources", type=int, default=32)
    p.add_argument("--tile-count", type=int, default=4)
    p.add_argument("--canvas-width", type=int, default=1920)
    p.add_argument("--canvas-height", type=int, default=1080)
    p.add_argument("--grid-columns", type=int, help="Grid columns for auto layout")
    p.add_argument(
        "--slot-positions",
        help="Global slot positions: x,y,w,h;x,y,w,h;... (used for all views)",
    )
    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--latency-preset", choices=sorted(LATENCY_PRESETS), default="low")
    p.add_argument("--encoder", default="auto")
    p.add_argument("--quality-preset", choices=["high", "standard", "low"], default="standard")
    p.add_argument("--bitrate")
    p.add_argument("--maxrate")
    p.add_argument("--bufsize")
    p.add_argument("--source-label-map-json", help="JSON object mapping source path -> display label")
    p.add_argument("--source-placeholder-map-json", help="JSON object mapping source path -> no-stream reason")
    p.add_argument(
        "--auto-placeholder-missing-sources",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Render configured sources missing from MediaMTX as No Stream tiles.",
    )
    p.add_argument("--label-font-size", type=int, default=20)
    p.add_argument("--label-fontfile")
    p.add_argument("--gop", type=int, default=40)
    p.add_argument("--bframes", type=int, default=0)
    p.add_argument("--x264-preset", default="veryfast")
    p.add_argument("--restart-backoff-sec", type=float, default=3.0)
    p.add_argument(
        "--input-stall-timeout-sec",
        type=float,
        default=15.0,
        help="Per-RTSP-input network read/write timeout. 0 disables it.",
    )
    p.add_argument(
        "--input-stall-timeout-option",
        choices=["auto", "rw_timeout", "stimeout", "timeout", "none"],
        default="auto",
        help="FFmpeg option used for RTSP input stall timeout.",
    )
    p.add_argument("--input-thread-queue-size", type=int, default=128)
    p.add_argument("--input-healthcheck-enabled", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--input-healthcheck-interval-sec", type=float, default=5.0)
    p.add_argument("--input-isolation-threshold", type=int, default=3)
    p.add_argument("--input-retry-interval-sec", type=float, default=30.0)
    p.add_argument("--status-file", default="./logs/runtime/multiview_status.json")
    p.add_argument("--ffmpeg-bin", default="ffmpeg")
    p.add_argument("--loglevel", default="error")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--verbose", action="store_true")

    env_defaults: dict[str, object] = {}
    env_errors: list[str] = []

    def env_str(dest: str, key: str) -> None:
        if key in env_values:
            env_defaults[dest] = env_values[key]

    def env_int(dest: str, key: str) -> None:
        if key in env_values:
            try:
                env_defaults[dest] = parse_env_int(env_values[key], key)
            except ValueError as e:
                env_errors.append(str(e))

    def env_float(dest: str, key: str) -> None:
        if key in env_values:
            try:
                env_defaults[dest] = parse_env_float(env_values[key], key)
            except ValueError as e:
                env_errors.append(str(e))

    def env_bool(dest: str, key: str) -> None:
        if key in env_values:
            try:
                env_defaults[dest] = parse_env_bool(env_values[key], key)
            except ValueError as e:
                env_errors.append(str(e))

    env_str("source_mode", "MV_SOURCE_MODE")
    env_str("source_paths", "MV_SOURCE_PATHS")
    env_str("mtx_api_url", "MV_MTX_API_URL")
    env_str("input_rtsp_base_url", "MV_INPUT_RTSP_BASE_URL")
    env_str("output_rtsp_base_url", "MV_OUTPUT_RTSP_BASE_URL")
    env_str("output_prefix", "MV_OUTPUT_PREFIX")
    env_int("max_sources", "MV_MAX_SOURCES")
    env_int("tile_count", "MV_TILE_COUNT")
    env_int("canvas_width", "MV_CANVAS_WIDTH")
    env_int("canvas_height", "MV_CANVAS_HEIGHT")
    env_int("grid_columns", "MV_GRID_COLUMNS")
    env_str("slot_positions", "MV_SLOT_POSITIONS")
    env_int("fps", "MV_FPS")
    env_str("latency_preset", "MV_LATENCY_PRESET")
    env_str("encoder", "MV_ENCODER")
    env_str("quality_preset", "MV_QUALITY_PRESET")
    env_str("bitrate", "MV_BITRATE")
    env_str("maxrate", "MV_MAXRATE")
    env_str("bufsize", "MV_BUFSIZE")
    env_str("source_label_map_json", "MV_SOURCE_LABEL_MAP_JSON")
    env_str("source_placeholder_map_json", "MV_SOURCE_PLACEHOLDER_MAP_JSON")
    env_bool("auto_placeholder_missing_sources", "MV_AUTO_PLACEHOLDER_MISSING_SOURCES")
    env_int("label_font_size", "MV_LABEL_FONT_SIZE")
    env_str("label_fontfile", "MV_LABEL_FONTFILE")
    env_int("gop", "MV_GOP")
    env_int("bframes", "MV_BFRAMES")
    env_str("x264_preset", "MV_X264_PRESET")
    env_float("restart_backoff_sec", "MV_RESTART_BACKOFF_SEC")
    env_float("input_stall_timeout_sec", "MV_INPUT_STALL_TIMEOUT_SEC")
    env_str("input_stall_timeout_option", "MV_INPUT_STALL_TIMEOUT_OPTION")
    env_int("input_thread_queue_size", "MV_INPUT_THREAD_QUEUE_SIZE")
    env_bool("input_healthcheck_enabled", "MV_INPUT_HEALTHCHECK_ENABLED")
    env_float("input_healthcheck_interval_sec", "MV_INPUT_HEALTHCHECK_INTERVAL_SEC")
    env_int("input_isolation_threshold", "MV_INPUT_ISOLATION_THRESHOLD")
    env_float("input_retry_interval_sec", "MV_INPUT_RETRY_INTERVAL_SEC")
    env_str("status_file", "MV_STATUS_FILE")
    env_str("ffmpeg_bin", "MV_FFMPEG_BIN")
    env_str("loglevel", "MV_LOGLEVEL")
    env_bool("dry_run", "MV_DRY_RUN")
    env_bool("once", "MV_ONCE")
    env_bool("verbose", "MV_VERBOSE")

    if env_errors:
        p.error("; ".join(env_errors))
    if env_defaults:
        p.set_defaults(**env_defaults)

    args = p.parse_args(argv)
    args.env_loaded_path = None if args.no_env else env_loaded_path
    args.env_values = env_values

    if args.tile_count < 2 or args.tile_count > 32:
        p.error("--tile-count must be in range 2..32")
    if args.max_sources < 2 or args.max_sources > 32:
        p.error("--max-sources must be in range 2..32")
    if args.canvas_width <= 0 or args.canvas_height <= 0:
        p.error("canvas size must be positive")
    if args.fps <= 0:
        p.error("--fps must be positive")
    if args.label_font_size <= 0:
        p.error("--label-font-size must be positive")
    if args.gop <= 0:
        p.error("--gop must be positive")
    if args.bframes < 0:
        p.error("--bframes must be >= 0")
    if args.restart_backoff_sec < 0:
        p.error("--restart-backoff-sec must be >= 0")
    if args.input_stall_timeout_sec < 0:
        p.error("--input-stall-timeout-sec must be >= 0")
    if args.input_thread_queue_size <= 0:
        p.error("--input-thread-queue-size must be positive")
    if args.input_healthcheck_interval_sec <= 0 or args.input_retry_interval_sec <= 0:
        p.error("input healthcheck and retry intervals must be positive")
    if args.input_isolation_threshold <= 0:
        p.error("--input-isolation-threshold must be positive")
    if not args.output_prefix:
        p.error("--output-prefix must not be empty")
    try:
        args.source_label_map = parse_source_label_map(args.source_label_map_json)
    except ValueError as e:
        p.error(str(e))
    try:
        args.source_placeholder_map = parse_source_placeholder_map(args.source_placeholder_map_json)
    except ValueError as e:
        p.error(str(e))
    args.dynamic_source_placeholder_map = {}
    args.health_placeholder_map = {}
    args.last_placeholder_api_warn_at = 0.0
    args.text_overlay_enabled = bool(
        args.source_label_map
        or args.source_placeholder_map
        or args.auto_placeholder_missing_sources
        or args.input_healthcheck_enabled
    )
    return args


def terminate_processes(runtimes: list[ViewRuntime]) -> None:
    for runtime in runtimes:
        proc = runtime.process
        if proc is None:
            continue
        if proc.poll() is None:
            proc.terminate()
    time.sleep(0.5)
    for runtime in runtimes:
        proc = runtime.process
        if proc is None:
            continue
        if proc.poll() is None:
            proc.kill()


def stop_runtime_process(runtime: ViewRuntime) -> None:
    proc = runtime.process
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        runtime.process = None
        runtime.started_at = None


def start_runtime_process(
    args: argparse.Namespace,
    runtime: ViewRuntime,
    encoder_candidates: list[str],
    *,
    reason: str,
) -> None:
    encoder = encoder_candidates[runtime.encoder_idx]
    refresh_missing_source_placeholders(args, args.all_source_paths)
    cmd = build_page_command(args, runtime.spec, encoder)
    output_path = f"{args.output_prefix}_{runtime.spec.index}"
    if args.verbose:
        print(
            f"[info] starting {output_path} with encoder={encoder} reason={reason}",
            file=sys.stderr,
        )
        print(format_cmd_for_display(cmd), file=sys.stderr)
    runtime.process = popen_background(
        cmd, **background_process_options(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    runtime.started_at = time.time()
    if runtime.process.stderr is not None:
        stderr = runtime.process.stderr

        def forward_stderr() -> None:
            for line in stderr:
                normalized = line.lower()
                if any(pattern in normalized for pattern in FFMPEG_DECODE_ERROR_PATTERNS):
                    runtime.decode_error_count += 1
                print(line.rstrip(), file=sys.stderr)

        threading.Thread(
            target=forward_stderr,
            name=f"multiview-{runtime.spec.index}-stderr",
            daemon=True,
        ).start()
    if reason != "initial":
        runtime.restart_count += 1


def run_once(
    args: argparse.Namespace,
    views: list[ViewSpec],
    encoder_candidates: list[str],
) -> int:
    runtimes: list[ViewRuntime] = []
    for view in views:
        runtime = ViewRuntime(spec=view, encoder_idx=0)
        runtimes.append(runtime)
        start_runtime_process(args, runtime, encoder_candidates, reason="once")

    worst_code = 0
    try:
        for runtime in runtimes:
            proc = runtime.process
            if proc is None:
                continue
            return_code = proc.wait()
            if return_code != 0:
                worst_code = return_code
    except KeyboardInterrupt:
        terminate_processes(runtimes)
        return 130
    return worst_code


def run_supervisor(
    args: argparse.Namespace,
    views: list[ViewSpec],
    encoder_candidates: list[str],
) -> int:
    runtimes = [ViewRuntime(spec=view) for view in views]
    input_states = {
        source: InputHealth(source=source)
        for view in views
        for source in view.sources
    }
    for runtime in runtimes:
        start_runtime_process(args, runtime, encoder_candidates, reason="initial")

    next_placeholder_refresh_at = time.time() + 5.0
    next_healthcheck_at = time.time() + args.input_healthcheck_interval_sec
    next_status_at = time.time() + 1.0
    write_status_file(args, runtimes, input_states)
    try:
        while True:
            now = time.time()
            if args.input_healthcheck_enabled and now >= next_healthcheck_at:
                next_healthcheck_at = now + args.input_healthcheck_interval_sec
                affected = poll_input_health(args, runtimes, input_states, now=now)
                for runtime in runtimes:
                    if runtime.spec.index not in affected:
                        continue
                    print(
                        f"[warn] {args.output_prefix}_{runtime.spec.index} restarting after input health failure",
                        file=sys.stderr,
                    )
                    stop_runtime_process(runtime)
                    runtime.next_restart_at = now
            if args.auto_placeholder_missing_sources and now >= next_placeholder_refresh_at:
                next_placeholder_refresh_at = now + 5.0
                previous_missing = set(args.dynamic_source_placeholder_map)
                if refresh_missing_source_placeholders(args, args.all_source_paths):
                    changed_sources = previous_missing ^ set(args.dynamic_source_placeholder_map)
                    for runtime in runtimes:
                        if not changed_sources.intersection(runtime.spec.sources):
                            continue
                        output_path = f"{args.output_prefix}_{runtime.spec.index}"
                        print(
                            f"[warn] {output_path} restarting after MediaMTX path readiness changed",
                            file=sys.stderr,
                        )
                        stop_runtime_process(runtime)
                        runtime.next_restart_at = now

            for runtime in runtimes:
                output_path = f"{args.output_prefix}_{runtime.spec.index}"
                proc = runtime.process

                if proc is None:
                    if now >= runtime.next_restart_at:
                        start_runtime_process(
                            args,
                            runtime,
                            encoder_candidates,
                            reason="restart",
                        )
                    continue

                return_code = proc.poll()
                if return_code is None:
                    continue

                runtime.process = None
                if return_code == 0:
                    print(
                        f"[warn] {output_path} ended normally, restarting in "
                        f"{args.restart_backoff_sec:.1f}s",
                        file=sys.stderr,
                    )
                    runtime.next_restart_at = now + args.restart_backoff_sec
                    continue

                current_encoder = encoder_candidates[runtime.encoder_idx]
                print(
                    f"[warn] {output_path} ffmpeg process with encoder '{current_encoder}' exited with code {return_code}",
                    file=sys.stderr,
                )
                if refresh_missing_source_placeholders(args, args.all_source_paths):
                    print(
                        f"[warn] {output_path} retrying after MediaMTX path readiness changed",
                        file=sys.stderr,
                    )
                    runtime.next_restart_at = now
                    continue

                if args.latency_preset == "low":
                    print(
                        f"[warn] {output_path} failed in low latency mode; "
                        "falling back to normal latency mode and retrying",
                        file=sys.stderr,
                    )
                    args.latency_preset = "normal"
                    runtime.next_restart_at = now
                    continue

                if args.encoder == "auto" and runtime.encoder_idx + 1 < len(encoder_candidates):
                    runtime.encoder_idx += 1
                    next_encoder = encoder_candidates[runtime.encoder_idx]
                    print(
                        f"[warn] {output_path} retrying with fallback encoder '{next_encoder}'",
                        file=sys.stderr,
                    )
                    runtime.next_restart_at = now
                    continue

                if args.encoder == "auto" and runtime.encoder_idx + 1 >= len(encoder_candidates):
                    print(
                        f"[warn] {output_path} all encoders failed; retrying from first in "
                        f"{args.restart_backoff_sec:.1f}s",
                        file=sys.stderr,
                    )
                    runtime.encoder_idx = 0
                runtime.next_restart_at = now + args.restart_backoff_sec

            # Input health is delegated to the wall-clock workers when their
            # feature is enabled, but process/decode status must still advance.
            if now >= next_status_at:
                write_status_file(args, runtimes, input_states)
                next_status_at = now + 1.0

            time.sleep(0.5)
    except KeyboardInterrupt:
        terminate_processes(runtimes)
        return 130


def main() -> int:
    args = parse_args()
    resolve_rate_control(args)
    resolve_input_stall_timeout_option(args)

    try:
        sources = resolve_sources(args)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    views = build_views(args, sources)
    args.all_source_paths = normalize_unique([source for view in views for source in view.sources])

    try:
        available = get_available_encoders(args.ffmpeg_bin)
    except FileNotFoundError:
        print(f"ffmpeg binary not found: {args.ffmpeg_bin}", file=sys.stderr)
        return 127

    try:
        encoder_candidates = build_encoder_candidates(available, args.encoder)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    if args.text_overlay_enabled:
        if not has_drawtext_filter(args.ffmpeg_bin):
            print("[warn] drawtext filter is unavailable; multiview text overlays are disabled", file=sys.stderr)
            args.source_label_map = {}
            args.text_overlay_enabled = False
        elif not args.label_fontfile:
            auto_font = auto_default_font_path()
            if auto_font:
                args.label_fontfile = auto_font
                print(f"[info] using multiview label fontfile: {auto_font}", file=sys.stderr)

    if args.env_loaded_path:
        print(f"[info] loaded env file: {args.env_loaded_path}", file=sys.stderr)
    print(f"[info] source mode: {args.source_mode}", file=sys.stderr)
    print(f"[info] source count: {len(sources)}", file=sys.stderr)
    print(
        f"[info] tile count: {args.tile_count} -> view count: {len(views)}",
        file=sys.stderr,
    )
    print(
        f"[info] output prefix: {args.output_prefix} (base: {args.output_rtsp_base_url})",
        file=sys.stderr,
    )
    print(
        f"[info] rate control: bitrate={args.bitrate} maxrate={args.maxrate} bufsize={args.bufsize}",
        file=sys.stderr,
    )
    print(
        f"[info] latency preset: {args.latency_preset}",
        file=sys.stderr,
    )
    print(
        f"[info] input stall timeout: {args.input_stall_timeout_sec:.1f}s"
        + (f" via -{args.input_stall_timeout_arg}" if args.input_stall_timeout_arg else " disabled"),
        file=sys.stderr,
    )
    print(
        f"[info] encoder candidates: {', '.join(encoder_candidates)}",
        file=sys.stderr,
    )
    if args.source_label_map:
        print(f"[info] multiview label overlays: {len(args.source_label_map)} mapped sources", file=sys.stderr)
    if args.source_placeholder_map:
        print(f"[info] multiview placeholders: {len(args.source_placeholder_map)} mapped sources", file=sys.stderr)
    if args.verbose:
        for view in views:
            print(
                f"[info] {args.output_prefix}_{view.index} sources: {', '.join(view.sources)}",
                file=sys.stderr,
            )

    if args.dry_run:
        for view in views:
            cmd = build_page_command(args, view, encoder_candidates[0])
            print(
                f"[dry-run] {args.output_prefix}_{view.index} command:",
                file=sys.stderr,
            )
            print(format_cmd_for_display(cmd), file=sys.stderr)
        return 0

    if args.once:
        return run_once(args, views, encoder_candidates)
    return run_supervisor(args, views, encoder_candidates)


if __name__ == "__main__":
    raise SystemExit(main())
