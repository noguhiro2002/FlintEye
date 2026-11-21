from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
import os
import tempfile
import re
import shlex
import threading
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from flinteye_app.orchestrator_models import RuntimeConfig


TRUTHY_VALUES = {"1", "true", "yes", "on"}
FALSY_VALUES = {"0", "false", "no", "off"}


def _parse_bool(value: str | bool | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in TRUTHY_VALUES:
        return True
    if normalized in FALSY_VALUES:
        return False
    return default


def _parse_int(value: str | int | None, default: int) -> int:
    if isinstance(value, int):
        return value
    if value is None or value == "":
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def _parse_float(value: str | float | int | None, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None or value == "":
        return default
    try:
        return float(str(value).strip())
    except ValueError:
        return default


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    items: list[str] = []
    for raw in re.split(r"[,\n;]", value):
        item = raw.strip().strip("/")
        if item:
            items.append(item)
    return items


def _to_env_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").upper()
    return token


def _parse_path_from_rtsp_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    path = (parsed.path or "").strip("/")
    return path or None


def _guess_rtsp_base_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


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


def _extract_uvc_profiles(env: dict[str, str]) -> list[str]:
    profiles = _parse_csv(env.get("UVC_PROFILES"))
    if profiles:
        return profiles

    if env.get("UVC_PROFILE"):
        return [env["UVC_PROFILE"].strip()]

    detected: list[str] = []
    for key in env.keys():
        m = re.match(r"^UVC_([A-Z0-9_]+)_(CAMERA_NAME|RTSP_URL|DEVICE)$", key)
        if not m:
            continue
        token = m.group(1)
        if token in {"PROFILE", "PROFILES"}:
            continue
        candidate = token.lower()
        if candidate not in detected:
            detected.append(candidate)
    return detected


def _build_camera_configs_from_env(env: dict[str, str]) -> list[dict[str, Any]]:
    cameras: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    profiles = _extract_uvc_profiles(env)
    shared_name = env.get("UVC_CAMERA_NAME")
    shared_rtsp_url = env.get("UVC_RTSP_URL")

    if not profiles and shared_rtsp_url:
        profiles = [env.get("UVC_PROFILE", "default").strip() or "default"]

    for profile in profiles:
        token = _to_env_token(profile)
        key_prefix = f"UVC_{token}_"
        camera_name = env.get(f"{key_prefix}CAMERA_NAME") or shared_name or profile
        rtsp_url = env.get(f"{key_prefix}RTSP_URL") or shared_rtsp_url
        path = env.get(f"{key_prefix}PATH") or _parse_path_from_rtsp_url(rtsp_url)
        if not path:
            path = f"uvc_{profile.lower()}"

        camera_id = path
        if camera_id.lower() in seen_ids:
            continue
        seen_ids.add(camera_id.lower())

        uvc_env: dict[str, Any] = {}
        for suffix in [
            "INPUT_DRIVER",
            "DEVICE",
            "FFMPEG_BIN",
            "LOGLEVEL",
            "ENCODER",
            "LATENCY_PRESET",
            "QUALITY_PRESET",
            "WIDTH",
            "HEIGHT",
            "FPS",
            "INPUT_FORMAT",
            "RTBUFSIZE",
            "BITRATE",
            "MAXRATE",
            "BUFSIZE",
            "GOP",
            "THREAD_QUEUE_SIZE",
            "BFRAMES",
            "FONT_SIZE",
            "FONTFILE",
            "X264_PRESET",
            "DRY_RUN",
        ]:
            value = env.get(f"{key_prefix}{suffix}")
            if value is None:
                value = env.get(f"UVC_{suffix}")
            if value is not None and value != "":
                uvc_env[suffix] = value
        uvc_env["CAMERA_NAME"] = camera_name
        if rtsp_url:
            uvc_env["RTSP_URL"] = rtsp_url

        cameras.append(
            {
                "id": camera_id,
                "type": "uvc",
                "enabled": _parse_bool(env.get(f"{key_prefix}ENABLED"), True),
                "path": path,
                "uvc": {"profile": profile, "env": uvc_env, "extra_args": []},
            }
        )

    ip_paths = _parse_csv(env.get("MTX_IP_PATHS"))
    for path in ip_paths:
        token = _to_env_token(path)
        source_key = f"MTX_IP_{token}_SOURCE"
        source_url = env.get(source_key)
        camera_id = path
        if camera_id.lower() in seen_ids:
            continue
        seen_ids.add(camera_id.lower())
        cameras.append(
            {
                "id": camera_id,
                "type": "ip",
                "enabled": _parse_bool(env.get(f"MTX_IP_{token}_ENABLED"), True),
                "path": path,
                "display_name": (env.get(f"MTX_IP_{token}_DISPLAY_NAME") or "").strip() or None,
                "ip": {
                    "source_url": source_url,
                    "relay_mode": env.get(f"MTX_IP_{token}_RELAY_MODE", "copy"),
                    "bitrate": (env.get(f"MTX_IP_{token}_BITRATE") or "").strip() or None,
                    "maxrate": (env.get(f"MTX_IP_{token}_MAXRATE") or "").strip() or None,
                    "bufsize": (env.get(f"MTX_IP_{token}_BUFSIZE") or "").strip() or None,
                    "gop": _parse_int(env.get(f"MTX_IP_{token}_GOP"), 40),
                    "x264_preset": env.get(f"MTX_IP_{token}_X264_PRESET", "veryfast"),
                    "periodic_restart_enabled": _parse_bool(
                        env.get(f"MTX_IP_{token}_PERIODIC_RESTART_ENABLED"),
                        True,
                    ),
                    "periodic_restart_interval_sec": _parse_float(
                        env.get(f"MTX_IP_{token}_PERIODIC_RESTART_INTERVAL_SEC"),
                        43200.0,
                    ),
                    "watchdog_enabled": _parse_bool(
                        env.get(f"MTX_IP_{token}_WATCHDOG_ENABLED"),
                        True,
                    ),
                    "watchdog_interval_sec": _parse_float(
                        env.get(f"MTX_IP_{token}_WATCHDOG_INTERVAL_SEC"),
                        300.0,
                    ),
                    "watchdog_timeout_sec": _parse_float(
                        env.get(f"MTX_IP_{token}_WATCHDOG_TIMEOUT_SEC"),
                        8.0,
                    ),
                    "watchdog_failure_threshold": _parse_int(
                        env.get(f"MTX_IP_{token}_WATCHDOG_FAILURE_THRESHOLD"),
                        3,
                    ),
                },
            }
        )

    return cameras


def env_to_runtime_defaults(env: dict[str, str]) -> dict[str, Any]:
    api_host = env.get("API_HOST", "127.0.0.1")
    api_port = _parse_int(env.get("API_PORT"), 18080)
    api_token = env.get("API_BEARER_TOKEN", "")
    admin_token = env.get("API_ADMIN_TOKEN", api_token)
    viewer_token = env.get("API_VIEWER_TOKEN", "")
    viewer_auth_required = _parse_bool(env.get("API_VIEWER_AUTH_REQUIRED"), True)
    auth_provider = env.get("AUTH_PROVIDER", "legacy_token").strip() or "legacy_token"

    first_uvc_rtsp = env.get("UVC_RTSP_URL")
    record_all_cameras_env = env.get("MTX_RECORD_ALL_CAMERAS")
    rtsp_base_guess = (
        env.get("MTX_RTSP_BASE_URL")
        or env.get("MV_INPUT_RTSP_BASE_URL")
        or env.get("MV_OUTPUT_RTSP_BASE_URL")
        or _guess_rtsp_base_url(first_uvc_rtsp)
        or "rtsp://127.0.0.1:8554"
    )

    runtime: dict[str, Any] = {
        "api": {
            "host": api_host,
            "port": api_port,
            "admin_token": admin_token,
            "viewer_token": viewer_token,
            "viewer_auth_required": viewer_auth_required,
            "bearer_token": api_token,
        },
        "auth": {
            "provider": auth_provider,
            "viewer_auth_required": _parse_bool(env.get("AUTH_VIEWER_AUTH_REQUIRED"), viewer_auth_required),
            "session_cookie_name": env.get("AUTH_SESSION_COOKIE_NAME", "orch_session"),
            "session_ttl_sec": _parse_int(env.get("AUTH_SESSION_TTL_SEC"), 43200),
            "session_secret": env.get("AUTH_SESSION_SECRET", ""),
            "oidc_issuer_url": (env.get("AUTH_OIDC_ISSUER_URL") or "").strip() or None,
            "oidc_client_id": (env.get("AUTH_OIDC_CLIENT_ID") or "").strip() or None,
            "oidc_client_secret": (env.get("AUTH_OIDC_CLIENT_SECRET") or "").strip() or None,
            "oidc_redirect_uri": (env.get("AUTH_OIDC_REDIRECT_URI") or "").strip() or None,
            "oidc_scopes": env.get("AUTH_OIDC_SCOPES", "openid profile email"),
            "local": {
                "admin": {
                    "username": env.get("AUTH_LOCAL_ADMIN_USERNAME", "admin"),
                    "password_hash": env.get("AUTH_LOCAL_ADMIN_PASSWORD_HASH", ""),
                },
                "viewer": {
                    "username": env.get("AUTH_LOCAL_VIEWER_USERNAME", "viewer"),
                    "password_hash": env.get("AUTH_LOCAL_VIEWER_PASSWORD_HASH", ""),
                },
            },
        },
        "ui": {
            "app_title": env.get("WEBAPP_TITLE", "FlintEye"),
            "sidebar_title": env.get("WEBAPP_SIDEBAR_TITLE", "FlintEye"),
            "footer_text": env.get(
                "WEBAPP_FOOTER_TEXT",
                "© 2026 Noguhiro. Sustainable Use License + additional permission.",
            ),
        },
        "logging": {
            "directory": env.get("LOG_DIR", "./logs"),
            "level": env.get("LOG_LEVEL", "ERROR").strip().upper(),
            "retention": (env.get("LOG_RETENTION") or "").strip() or None,
        },
        "snapshot": {
            "timeout_sec": _parse_float(env.get("SNAPSHOT_TIMEOUT_SEC"), 3.0),
            "thumbnail_refresh_interval_sec": _parse_float(
                env.get("SNAPSHOT_THUMBNAIL_REFRESH_INTERVAL_SEC"),
                10.0,
            ),
        },
        "mediamtx": {
            "control_mode": env.get("MTX_CONTROL_MODE", "systemd"),
            "service_name": env.get("MTX_SERVICE_NAME", "mediamtx"),
            "autostart_on_api_start": _parse_bool(env.get("MTX_AUTOSTART_ON_API_START"), True),
            "rtsp_base_url": rtsp_base_guess,
            "internal_rtsp_base_url": (env.get("MTX_INTERNAL_RTSP_BASE_URL") or "").strip() or None,
            "webrtc_base_url": env.get("MTX_WEBRTC_BASE_URL", "http://127.0.0.1:8889"),
            "direct": {
                "command": shlex.split(env.get("MTX_DIRECT_COMMAND", "")) if env.get("MTX_DIRECT_COMMAND") else [],
                "working_dir": env.get("MTX_DIRECT_WORKDIR") or None,
            },
            "managed": {
                "enabled": _parse_bool(env.get("MTX_MANAGED_ENABLED"), False),
                "global": {},
                "paths": {},
            },
        },
        "multiview": {
            "enabled": _parse_bool(env.get("MV_ENABLED"), False),
            "source_mode": env.get("MV_SOURCE_MODE", "hybrid"),
            "source_paths": _parse_csv(env.get("MV_SOURCE_PATHS")),
            "auto_placeholder_missing_sources": _parse_bool(env.get("MV_AUTO_PLACEHOLDER_MISSING_SOURCES"), True),
            "mtx_api_url": env.get("MV_MTX_API_URL", "http://127.0.0.1:9997/v3/paths/list"),
            "input_rtsp_base_url": env.get("MV_INPUT_RTSP_BASE_URL", rtsp_base_guess),
            "output_rtsp_base_url": env.get("MV_OUTPUT_RTSP_BASE_URL", rtsp_base_guess),
            "output_prefix": env.get("MV_OUTPUT_PREFIX", "multiview"),
            "max_sources": _parse_int(env.get("MV_MAX_SOURCES"), 32),
            "tile_count": _parse_int(env.get("MV_TILE_COUNT"), 4),
            "latency_preset": env.get("MV_LATENCY_PRESET", "low"),
            "restart_backoff_sec": _parse_float(env.get("MV_RESTART_BACKOFF_SEC"), 3.0),
            "input_stall_timeout_sec": _parse_float(env.get("MV_INPUT_STALL_TIMEOUT_SEC"), 15.0),
            "input_stall_timeout_option": env.get("MV_INPUT_STALL_TIMEOUT_OPTION", "auto"),
            "ffmpeg_bin": env.get("MV_FFMPEG_BIN", "ffmpeg"),
            "loglevel": env.get("MV_LOGLEVEL", "error"),
            "verbose": _parse_bool(env.get("MV_VERBOSE"), False),
            "quality": {
                "fps": _parse_int(env.get("MV_FPS"), 20),
                "encoder": env.get("MV_ENCODER", "auto"),
                "quality_preset": env.get("MV_QUALITY_PRESET", "standard"),
                "bitrate": env.get("MV_BITRATE") or None,
                "maxrate": env.get("MV_MAXRATE") or None,
                "bufsize": env.get("MV_BUFSIZE") or None,
                "gop": _parse_int(env.get("MV_GOP"), 40),
                "bframes": _parse_int(env.get("MV_BFRAMES"), 0),
                "x264_preset": env.get("MV_X264_PRESET", "veryfast"),
            },
            "layout": {
                "canvas_width": _parse_int(env.get("MV_CANVAS_WIDTH"), 1920),
                "canvas_height": _parse_int(env.get("MV_CANVAS_HEIGHT"), 1080),
                "grid_columns": (
                    _parse_int(env.get("MV_GRID_COLUMNS"), 0)
                    if env.get("MV_GRID_COLUMNS")
                    else None
                ),
                "global_slots": env.get("MV_SLOT_POSITIONS") or None,
                "per_view_slots": {
                    key[3:].lower(): value
                    for key, value in env.items()
                    if key.startswith("MV_VIEW_") and key.endswith("_SLOT_POSITIONS") and value
                },
            },
            "maintenance": {
                "enabled": _parse_bool(env.get("MV_MAINTENANCE_ENABLED"), True),
                "restart_interval_sec": _parse_float(env.get("MV_MAINTENANCE_RESTART_INTERVAL_SEC"), 43200.0),
                "align_with_record_segments": _parse_bool(
                    env.get("MV_MAINTENANCE_ALIGN_WITH_RECORD_SEGMENTS"),
                    True,
                ),
                "restart_offset_sec": _parse_float(env.get("MV_MAINTENANCE_RESTART_OFFSET_SEC"), 2.0),
            },
        },
        "recording": {
            "enabled": _parse_bool(env.get("MTX_RECORD_ENABLED"), True),
            "auto_apply": _parse_bool(
                env.get("MTX_RECORD_AUTO_APPLY", env.get("MTX_RECORD_APPLY_ON_START")),
                True,
            ),
            "config_path": env.get("MTX_CONFIG_PATH") or None,
            "record_root": env.get("MTX_RECORD_ROOT", "./recordings/mediamtx"),
            "record_format": env.get("MTX_RECORD_FORMAT", "fmp4"),
            "record_part_duration": env.get("MTX_RECORD_PART_DURATION", "1s"),
            "record_max_part_size": env.get("MTX_RECORD_MAX_PART_SIZE", "50M"),
            "record_segment_duration": env.get("MTX_RECORD_SEGMENT_DURATION", "10m"),
            "record_delete_after": env.get("MTX_RECORD_DELETE_AFTER", "168h"),
            "playback_cache_delete_after": env.get("PLAYBACK_CACHE_DELETE_AFTER", "24h"),
            "include_multiview": _parse_bool(env.get("MTX_RECORD_INCLUDE_MULTIVIEW"), True),
            "multiview_max_count": _parse_int(env.get("MTX_MULTI_VIEW_MAX_COUNT"), 16),
            "record_all_cameras": (
                _parse_bool(record_all_cameras_env, True)
                if record_all_cameras_env is not None
                else None
            ),
            "record_paths": _parse_csv(env.get("MTX_RECORD_PATHS")),
        },
        "cameras": _build_camera_configs_from_env(env),
    }
    return runtime


class RuntimeRevisionMismatch(ValueError):
    """The caller edited a configuration version that is no longer current."""


_RUNTIME_LOCKS: dict[str, threading.RLock] = {}
_RUNTIME_LOCKS_GUARD = threading.Lock()


@contextmanager
def runtime_file_lock(path: Path) -> Iterator[None]:
    """Serialize runtime read/modify/write operations in the API, installer and CLI."""
    runtime_path = path.expanduser().resolve()
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    with _RUNTIME_LOCKS_GUARD:
        local_lock = _RUNTIME_LOCKS.setdefault(str(runtime_path), threading.RLock())
    with local_lock:
        lock_path = runtime_path.with_name(f".{runtime_path.name}.lock")
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "r+b") as stream:
            if os.name == "nt":
                import msvcrt
                if os.fstat(stream.fileno()).st_size == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


_PROTECTED_CONFIG_PATHS = (
    ("auth", "session_secret"),
    ("auth", "oidc_client_secret"),
    ("auth", "local"),
    ("api", "admin_token"),
    ("api", "viewer_token"),
    ("api", "bearer_token"),
)


def _nested_value(source: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    node: Any = source
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
    return True, node


def _drop_nested(source: dict[str, Any], path: tuple[str, ...]) -> None:
    node: Any = source
    for key in path[:-1]:
        if not isinstance(node, dict) or key not in node:
            return
        node = node[key]
    if isinstance(node, dict):
        node.pop(path[-1], None)


def _put_nested(source: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = source
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = copy.deepcopy(value)


def write_private_runtime_json(
    path: Path, payload: dict[str, Any], *, sort_keys: bool = True, ensure_ascii: bool = False
) -> None:
    """Replace credential-bearing runtime JSON without a readable partial file."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=ensure_ascii, indent=2, sort_keys=sort_keys)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + 2.0
        while True:
            try:
                os.replace(temporary, path)
                break
            except PermissionError as error:
                # On Windows a recording hook can be reading runtime.json without
                # delete sharing. Keep the old file intact until that reader closes.
                if getattr(error, "winerror", None) not in {5, 32, 33} or time.monotonic() >= deadline:
                    raise
                time.sleep(.025)
    finally:
        temporary.unlink(missing_ok=True)


class RuntimeStore:
    def __init__(
        self,
        *,
        env_file: str = ".env",
        runtime_file: str = "runtime.json",
        use_env: bool = True,
    ) -> None:
        self.env_file = env_file
        self.runtime_file = runtime_file
        self.use_env = use_env
        self._lock = threading.RLock()
        self._runtime_raw: dict[str, Any] = self._load_runtime_file()

    def _load_runtime_file(self) -> dict[str, Any]:
        path = Path(self.runtime_file)
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Runtime configuration must be a JSON object")
        return data

    def _refresh_runtime_file(self) -> None:
        # manage_auth.py and the installer can update this file while the API runs.
        self._runtime_raw = self._load_runtime_file()

    def _save_runtime_file(self, payload: dict[str, Any]) -> None:
        write_private_runtime_json(Path(self.runtime_file), payload)

    def _load_env_values(self) -> dict[str, str]:
        if not self.use_env:
            return {}
        return load_env_file(self.env_file)

    def get_runtime(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_runtime_file()
            return copy.deepcopy(self._runtime_raw)

    def runtime_revision(self) -> str:
        with self._lock:
            self._refresh_runtime_file()
            serialized = json.dumps(self._runtime_raw, sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _assert_revision(self, expected_revision: str | None) -> None:
        self._refresh_runtime_file()
        if expected_revision is not None and expected_revision.strip('"') != self.runtime_revision():
            raise RuntimeRevisionMismatch("Configuration changed in another session. Reload settings before saving.")

    def _protect_credentials(self, incoming: dict[str, Any], *, replace: bool) -> dict[str, Any]:
        current = self.get_effective().model_dump()
        safe = copy.deepcopy(incoming)
        for path in _PROTECTED_CONFIG_PATHS:
            supplied, value = _nested_value(safe, path)
            _, effective_value = _nested_value(current, path)
            if supplied and value != effective_value:
                raise ValueError("Change credentials through the dedicated password or account tools.")
            _drop_nested(safe, path)
            if replace:
                stored, stored_value = _nested_value(self._runtime_raw, path)
                if stored:
                    _put_nested(safe, path, stored_value)
        return safe

    def get_effective(self) -> RuntimeConfig:
        with self._lock:
            self._refresh_runtime_file()
            env_values = self._load_env_values()
            env_defaults = env_to_runtime_defaults(env_values)
            merged = _deep_merge(env_defaults, self._runtime_raw)
            return RuntimeConfig.model_validate(merged)

    def _preserve_recording_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        old = self.get_effective().recording
        new = payload.get("recording", {})
        if old.managed_storage and new.get("record_root", old.record_root) != old.record_root:
            candidate = Path(new["record_root"]).expanduser()
            if not candidate.is_absolute() or not candidate.is_dir():
                raise ValueError("Recording folder must be an existing absolute directory")
            import tempfile
            with tempfile.TemporaryFile(dir=candidate):
                pass
            existing_paths = [Path(old.record_root).resolve()] + [Path(entry.path).resolve() for entry in old.previous_roots]
            for existing in existing_paths:
                if existing != candidate.resolve() and (existing.is_relative_to(candidate.resolve()) or candidate.resolve().is_relative_to(existing)):
                    raise ValueError("Recording folders must not contain one another")
            previous = [entry.model_dump() for entry in old.previous_roots]
            if not any(entry["path"] == old.record_root for entry in previous):
                previous.append({"path": old.record_root, "retention": old.record_delete_after, "max_bytes": old.max_bytes})
            new["previous_roots"] = [entry for entry in previous if Path(entry["path"]).resolve() != candidate.resolve()]
            new["record_root"] = str(candidate.resolve())
            payload["recording"] = new
        return payload

    def set_runtime(
        self,
        replacement: dict[str, Any],
        *,
        expected_revision: str | None = None,
        protect_credentials: bool = False,
    ) -> RuntimeConfig:
        with self._lock, runtime_file_lock(Path(self.runtime_file)):
            self._assert_revision(expected_revision)
            if protect_credentials:
                replacement = self._protect_credentials(replacement, replace=True)
            replacement = self._preserve_recording_history(copy.deepcopy(replacement))
            candidate = RuntimeConfig.model_validate(replacement)
            self._save_runtime_file(replacement)
            self._runtime_raw = copy.deepcopy(replacement)
            return self.get_effective()

    def patch_runtime(
        self,
        patch: dict[str, Any],
        *,
        expected_revision: str | None = None,
        protect_credentials: bool = False,
    ) -> RuntimeConfig:
        with self._lock, runtime_file_lock(Path(self.runtime_file)):
            self._assert_revision(expected_revision)
            if protect_credentials:
                patch = self._protect_credentials(patch, replace=False)
            merged_runtime = self._preserve_recording_history(_deep_merge(self._runtime_raw, patch))
            candidate = RuntimeConfig.model_validate(
                _deep_merge(env_to_runtime_defaults(self._load_env_values()), merged_runtime)
            )
            self._save_runtime_file(merged_runtime)
            self._runtime_raw = merged_runtime
            return self.get_effective()

    def replace_camera(self, camera_id: str, camera_payload: dict[str, Any]) -> RuntimeConfig:
        with self._lock, runtime_file_lock(Path(self.runtime_file)):
            current = self.get_effective().model_dump()
            cameras = current.get("cameras", [])
            normalized_id = camera_id.strip().strip("/")
            replaced = False
            for idx, item in enumerate(cameras):
                if str(item.get("id", "")).lower() == normalized_id.lower():
                    cameras[idx] = camera_payload
                    replaced = True
                    break
            if not replaced:
                cameras.append(camera_payload)
            self._runtime_raw = _deep_merge(self._runtime_raw, {"cameras": cameras})
            self._save_runtime_file(self._runtime_raw)
            return self.get_effective()

    def delete_camera(self, camera_id: str) -> RuntimeConfig:
        with self._lock, runtime_file_lock(Path(self.runtime_file)):
            current = self.get_effective().model_dump()
            normalized_id = camera_id.strip().strip("/")
            cameras = [
                cam
                for cam in current.get("cameras", [])
                if str(cam.get("id", "")).lower() != normalized_id.lower()
            ]
            self._runtime_raw = _deep_merge(self._runtime_raw, {"cameras": cameras})
            self._save_runtime_file(self._runtime_raw)
            return self.get_effective()
