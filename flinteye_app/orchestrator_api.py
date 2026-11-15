from __future__ import annotations

import argparse
import base64
import binascii
from collections import deque
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
from flinteye_app.process_lifetime import run_background
from flinteye_app.subprocess_utils import background_process_options
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flinteye_app.flinteye_runtime import application_dir

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from flinteye_app.orchestrator_auth import (
    AuthIdentity,
    authenticate_local_user,
    create_session_value,
    local_auth_is_configured,
    parse_session_value,
)
from flinteye_app.orchestrator_ip_camera_probe import inspect_ip_camera, probe_onvif
from flinteye_app.workers.multiview_input_to_rtsp import select_onvif_profile
from flinteye_app.orchestrator_models import CameraConfig, RuntimeConfig
from flinteye_app.orchestrator_mediamtx_yaml import MediamtxYamlApplyResult, apply_mediamtx_yaml, resolve_mediamtx_config_path
from flinteye_app.orchestrator_logging import LogManager, parse_duration_to_seconds
from flinteye_app.orchestrator_onvif_ptz import OnvifPtzController, PtzControlError
from flinteye_app.orchestrator_snapshot import SnapshotError, capture_snapshot_jpeg
from flinteye_app.orchestrator_store import RuntimeRevisionMismatch, RuntimeStore, load_env_file
from flinteye_app.orchestrator_supervisor import OrchestratorSupervisor
from flinteye_app.orchestrator_uvc_probe import UvcProbeCache, UvcProbeError, build_uvc_suggestion


APP_TITLE = "FlintEye API"
from flinteye_app._version import VERSION as APP_VERSION
DEFAULT_ENV_FILE = ".env"
DEFAULT_RUNTIME_FILE = "runtime.json"
RECORDING_STABLE_AGE_SEC = 30.0
RECORDING_PLAYBACK_CACHE_DIRNAME = ".playback_cache"
RECORDING_PLAYBACK_CACHE_CLEANUP_INTERVAL_SEC = 30.0


http_bearer = HTTPBearer(auto_error=False)
app = FastAPI(title=APP_TITLE, version=APP_VERSION)
logger = logging.getLogger("orchestrator.api")


class AppContext:
    def __init__(self, *, env_file: str, runtime_file: str, no_env: bool = False) -> None:
        workspace_dir = str(application_dir())
        self.workspace_dir = workspace_dir
        self.store = RuntimeStore(
            env_file=env_file,
            runtime_file=runtime_file,
            use_env=not no_env,
        )
        self.log_manager = LogManager(workspace_dir=workspace_dir)
        self.log_manager.configure(self.store.get_effective())
        self.supervisor = OrchestratorSupervisor(
            workspace_dir=workspace_dir,
            env_file=env_file,
            log_manager=self.log_manager,
        )
        self.uvc_probe_cache = UvcProbeCache()
        self.ptz_controller = OnvifPtzController()
        self.storage_problem = None
        self.started_at = time.time()
        self.listener: dict[str, Any] | None = None
        self.lock = threading.RLock()
        self._recording_cache_cleanup_stop = threading.Event()
        self._recording_cache_cleanup_thread: threading.Thread | None = None
        self._login_attempts: dict[str, deque[float]] = {}
        self._login_global_attempts: deque[float] = deque()
        self._login_lock = threading.Lock()
        self._login_workers = threading.BoundedSemaphore(4)
        self._playback_cache = tempfile.TemporaryDirectory(prefix="flinteye-playback-")
        self.playback_cache_dir = Path(self._playback_cache.name)
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._closing = threading.Event()

    def check_login_budget(self, client_host: str) -> None:
        now = time.monotonic()
        with self._login_lock:
            while self._login_global_attempts and self._login_global_attempts[0] <= now - 60:
                self._login_global_attempts.popleft()
            if len(self._login_global_attempts) >= 120:
                raise HTTPException(status_code=429, detail="Too many login attempts", headers={"Retry-After": "60"})
            attempts = self._login_attempts.setdefault(client_host, deque())
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= 10:
                raise HTTPException(status_code=429, detail="Too many login attempts", headers={"Retry-After": "60"})
            attempts.append(now)
            self._login_global_attempts.append(now)
            if len(self._login_attempts) > 2048:
                self._login_attempts = {
                    host: entries for host, entries in self._login_attempts.items()
                    if entries and entries[-1] > now - 60
                }
                if len(self._login_attempts) > 2048:
                    oldest = min(self._login_attempts, key=lambda host: self._login_attempts[host][-1])
                    del self._login_attempts[oldest]

    def shutdown(self) -> None:
        # Desktop shutdown must not depend on HTTP/WebRTC clients disconnecting.
        # The API lifespan and desktop finally block can reach here concurrently.
        self._closing.set()
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._recording_cache_cleanup_stop.set()
            try:
                self.supervisor.shutdown()
            finally:
                try:
                    self.ptz_controller.shutdown()
                finally:
                    cleanup_thread = self._recording_cache_cleanup_thread
                    if cleanup_thread is not None and cleanup_thread.is_alive():
                        cleanup_thread.join(timeout=2.0)
                    self._playback_cache.cleanup()
                    self._shutdown_complete = True

    def reconfigure_logging(self, config: RuntimeConfig) -> None:
        self.log_manager.configure(config)

    def cleanup_recording_playback_cache(self, config: RuntimeConfig | None = None) -> tuple[int, int]:
        effective = config or self.store.get_effective()
        retention_seconds = parse_duration_to_seconds(effective.recording.playback_cache_delete_after)
        with self.lock:
            if shutil.disk_usage(self.playback_cache_dir).free < _playback_cache_reserve(effective):
                _prune_private_playback_cache(self.playback_cache_dir, 0, self.playback_cache_dir)
            return _cleanup_recording_playback_cache(
                self.playback_cache_dir, retention_seconds=retention_seconds
            )

    def start_recording_cache_cleanup(self) -> None:
        with self._shutdown_lock:
            if self._closing.is_set():
                return
            cleanup_thread = self._recording_cache_cleanup_thread
            if cleanup_thread is not None and cleanup_thread.is_alive():
                return
            self._recording_cache_cleanup_stop.clear()
            self._recording_cache_cleanup_thread = threading.Thread(
                target=self._recording_cache_cleanup_loop,
                name="recording-playback-cache-cleanup",
                daemon=True,
            )
            self._recording_cache_cleanup_thread.start()

    def _recording_cache_cleanup_loop(self) -> None:
        while not self._recording_cache_cleanup_stop.is_set():
            try:
                self.cleanup_recording_playback_cache()
                from flinteye_app.flinteye_storage import cleanup
                config = self.store.get_effective()
                cleanup(Path(self.store.runtime_file).resolve().parent, config, self.workspace_dir)
                from flinteye_app.flinteye_storage import storage_problem
                problem = storage_problem(config)
                if problem != self.storage_problem:
                    self.storage_problem = problem
                    _apply_running_media_config(self, config)
            except (OSError, ValueError, ValidationError) as e:
                logger.warning("recording playback cache cleanup failed: %s", e)
            if self._recording_cache_cleanup_stop.wait(RECORDING_PLAYBACK_CACHE_CLEANUP_INTERVAL_SEC):
                break


def set_app_context(context: AppContext) -> None:
    app.state.context = context


def get_context(request: Request) -> AppContext:
    context = getattr(request.app.state, "context", None)
    if context is None:
        raise RuntimeError("Application context is not initialized")
    return context


def _legacy_auth_settings(context: AppContext) -> tuple[str, str, bool]:
    return _legacy_auth_settings_from_config(context.store.get_effective())


def _legacy_auth_settings_from_config(effective: RuntimeConfig) -> tuple[str, str, bool]:
    admin_token = (
        os.environ.get("API_ADMIN_TOKEN")
        or os.environ.get("API_BEARER_TOKEN")
        or effective.api.admin_token
        or effective.api.bearer_token
    )
    viewer_token = os.environ.get("API_VIEWER_TOKEN") or effective.api.viewer_token
    viewer_auth_required = effective.auth.viewer_auth_required
    return admin_token.strip(), viewer_token.strip(), bool(viewer_auth_required)


def _auth_config(context: AppContext):
    return context.store.get_effective().auth


def _session_signing_secret(context: AppContext) -> str:
    return _session_signing_secret_from_config(context.store.get_effective())


def _session_signing_secret_from_config(config: RuntimeConfig) -> str:
    if config.auth.session_secret:
        return config.auth.session_secret
    admin_token, viewer_token, _ = _legacy_auth_settings_from_config(config)
    return "|".join(part for part in [admin_token, viewer_token] if part)


def _validate_bearer_token(
    *,
    credentials: HTTPAuthorizationCredentials | None,
    accepted_tokens: list[str],
) -> str | None:
    accepted = [token for token in accepted_tokens if token]
    if not accepted:
        return None
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if credentials.credentials not in accepted:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return credentials.credentials


def _get_session_identity(request: Request, context: AppContext) -> AuthIdentity | None:
    config = context.store.get_effective()
    auth = config.auth
    cookie_value = request.cookies.get(auth.session_cookie_name)
    return parse_session_value(_session_signing_secret_from_config(config), cookie_value)


def _require_local_identity(request: Request, *, require_admin_role: bool) -> AuthIdentity | None:
    context = get_context(request)
    auth = _auth_config(context)
    if not auth.viewer_auth_required and not require_admin_role:
        return None
    if auth.provider == "oidc":
        raise HTTPException(status_code=501, detail="oidc auth provider is not implemented yet")
    if not local_auth_is_configured(auth):
        raise HTTPException(status_code=503, detail="local auth is not initialized")
    identity = _get_session_identity(request, context)
    if identity is None:
        raise HTTPException(status_code=401, detail="Login required")
    if require_admin_role and identity.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return identity


def _require_legacy_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    *,
    require_admin_role: bool,
) -> None:
    context = get_context(request)
    admin_token, viewer_token, viewer_auth_required = _legacy_auth_settings(context)
    if require_admin_role:
        if not admin_token:
            raise HTTPException(status_code=403, detail="admin token is not configured (set API_ADMIN_TOKEN)")
        _validate_bearer_token(credentials=credentials, accepted_tokens=[admin_token])
        return
    if not viewer_auth_required:
        return
    if not admin_token and not viewer_token:
        raise HTTPException(
            status_code=403,
            detail=(
                "viewer/admin token is not configured while viewer auth is required "
                "(set API_VIEWER_TOKEN or API_ADMIN_TOKEN)"
            ),
        )
    _validate_bearer_token(credentials=credentials, accepted_tokens=[admin_token, viewer_token])


def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
) -> None:
    context = get_context(request)
    provider = _auth_config(context).provider
    if provider == "local":
        _require_local_identity(request, require_admin_role=True)
        return
    _require_legacy_identity(request, credentials, require_admin_role=True)


def require_viewer(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
) -> None:
    context = get_context(request)
    provider = _auth_config(context).provider
    if provider == "local":
        _require_local_identity(request, require_admin_role=False)
        return
    _require_legacy_identity(request, credentials, require_admin_role=False)


def require_ptz_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
) -> AuthIdentity:
    context = get_context(request)
    auth = _auth_config(context)
    if auth.provider == "local":
        if not local_auth_is_configured(auth):
            raise HTTPException(status_code=503, detail="local auth is not initialized")
        identity = _get_session_identity(request, context)
        if identity is None:
            raise HTTPException(status_code=401, detail="Authenticated login is required for PTZ control")
        return identity
    if auth.provider == "oidc":
        raise HTTPException(status_code=501, detail="oidc auth provider is not implemented yet")

    admin_token, viewer_token, _ = _legacy_auth_settings(context)
    if not admin_token and not viewer_token:
        raise HTTPException(status_code=403, detail="No authenticated PTZ identity is configured")
    token = _validate_bearer_token(credentials=credentials, accepted_tokens=[admin_token, viewer_token])
    if token and admin_token and token == admin_token:
        return AuthIdentity(username="admin", role="admin", provider="legacy_token")
    return AuthIdentity(username="viewer", role="viewer", provider="legacy_token")


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _publisher_rtsp_base_url(config: RuntimeConfig) -> str:
    return config.mediamtx.internal_rtsp_base_url or config.mediamtx.rtsp_base_url


def _deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _stream_addresses(config: RuntimeConfig, stream_path: str) -> dict[str, str]:
    clean = stream_path.strip().strip("/")
    return {
        "rtsp_url": _join_url(config.mediamtx.rtsp_base_url, clean),
        "webrtc_url": _join_url(config.mediamtx.webrtc_base_url, clean),
    }


def _build_ui_allowed_origins(*, env_file: str, api_host: str) -> list[str]:
    env = load_env_file(env_file)
    ui_host = (env.get("WEBUI_HOST") or api_host or "127.0.0.1").strip()
    ui_port = (env.get("WEBUI_PORT") or "5173").strip()
    if not ui_port:
        ui_port = "5173"

    hosts = {ui_host}
    if ui_host in {"0.0.0.0", "::"}:
        hosts.update({"127.0.0.1", "localhost"})

    origins: list[str] = []
    for host in hosts:
        origins.append(f"http://{host}:{ui_port}")
        origins.append(f"https://{host}:{ui_port}")
    return origins


def _configure_cors(*, env_file: str, api_host: str) -> None:
    app.user_middleware[:] = [
        middleware
        for middleware in app.user_middleware
        if middleware.cls is not CORSMiddleware
    ]
    app.middleware_stack = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_ui_allowed_origins(env_file=env_file, api_host=api_host),
        allow_credentials=True,
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["*"],
    )


def _find_camera(config: RuntimeConfig, camera_id: str) -> CameraConfig:
    normalized = camera_id.strip().strip("/").lower()
    for camera in config.cameras:
        if camera.id.lower() == normalized:
            return camera
    raise HTTPException(status_code=404, detail=f"camera not found: {camera_id}")


def _authorized_ptz_camera(context: AppContext, camera_id: str, identity: AuthIdentity) -> CameraConfig:
    camera = _find_camera(context.store.get_effective(), camera_id)
    if camera.type != "ip" or camera.ip is None:
        raise HTTPException(status_code=422, detail="PTZ is available only for IP cameras")
    if not camera.enabled:
        raise HTTPException(status_code=409, detail="Camera is disabled")
    if not camera.ip.ptz.enabled:
        raise HTTPException(status_code=409, detail="PTZ is disabled for this camera")
    if identity.role != "admin" and camera.ip.ptz.access != "viewer":
        raise HTTPException(status_code=403, detail="Viewer PTZ control is not enabled for this camera")
    return camera


def _raise_ptz_http_error(exc: PtzControlError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _effective_with_status(context: AppContext) -> tuple[RuntimeConfig, dict[str, Any], dict[str, Any]]:
    config = context.store.get_effective()
    process_status = _sanitized_process_status(context.supervisor.process_status())
    mediamtx_status = context.supervisor.mediamtx_status(config)
    return config, process_status, mediamtx_status


def _redact_text_secrets(value: str | None) -> str | None:
    if not value:
        return value
    return re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@\s]+)@", r"\1***:***@", value)


def _sanitize_process_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "status": item.get("status"),
        "desired": item.get("desired"),
        "pid": item.get("pid"),
        "started_at": item.get("started_at"),
        "restart_count": item.get("restart_count"),
        "last_exit_code": item.get("last_exit_code"),
        "last_error": _redact_text_secrets(item.get("last_error")),
        "health_state": item.get("health_state"),
        "healthcheck_failures": item.get("healthcheck_failures"),
        "last_healthcheck_at": item.get("last_healthcheck_at"),
        "last_healthcheck_error": _redact_text_secrets(item.get("last_healthcheck_error")),
        "manual_excluded": bool(item.get("manual_excluded")),
        "manual_excluded_since": item.get("manual_excluded_since"),
        "quarantined": bool(item.get("quarantined")),
        "quarantine_since": item.get("quarantine_since"),
        "quarantine_reason": _redact_text_secrets(item.get("quarantine_reason")),
        "command": "",
    }


def _sanitized_process_status(processes: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": [_sanitize_process_item(item) for item in processes.get("items", [])],
    }


def _camera_process_item(processes: dict[str, Any], camera_id: str) -> dict[str, Any] | None:
    key = f"camera:{camera_id.lower()}"
    for item in processes.get("items", []):
        if item.get("id") == key:
            return item
    return None


def _camera_health_item(camera: CameraConfig, process: dict[str, Any] | None) -> dict[str, Any]:
    if not camera.enabled:
        return {
            "state": "disabled",
            "healthy": False,
            "reason": "Camera disabled",
            "manual_excluded": False,
            "quarantined": False,
            "placeholder": True,
        }
    if process is None:
        return {
            "state": "unknown",
            "healthy": False,
            "reason": "Camera process not registered",
            "manual_excluded": False,
            "quarantined": False,
            "placeholder": True,
        }

    state = str(process.get("health_state") or "unknown")
    manual_excluded = bool(process.get("manual_excluded"))
    quarantined = bool(process.get("quarantined"))
    reason = (
        process.get("quarantine_reason")
        or process.get("last_healthcheck_error")
        or process.get("last_error")
        or ""
    )
    if not reason:
        if manual_excluded:
            reason = "Temporarily excluded from multiview"
        elif state == "healthy":
            reason = "OK"
        elif state == "starting":
            reason = "Starting"
        elif state == "degraded":
            reason = "Watchdog warning"
        elif state == "unhealthy":
            reason = "Camera process is not healthy"
        else:
            reason = state

    placeholder = state in {"excluded", "quarantined", "unhealthy", "disabled", "unknown", "starting"}
    return {
        "state": state,
        "healthy": state == "healthy",
        "reason": _redact_text_secrets(str(reason)),
        "manual_excluded": manual_excluded,
        "manual_excluded_since": process.get("manual_excluded_since"),
        "quarantined": quarantined,
        "quarantine_since": process.get("quarantine_since"),
        "healthcheck_failures": process.get("healthcheck_failures") or 0,
        "last_healthcheck_at": process.get("last_healthcheck_at"),
        "last_healthcheck_error": process.get("last_healthcheck_error"),
        "placeholder": placeholder,
    }


def _viewer_camera_item(config: RuntimeConfig, processes: dict[str, Any], camera: CameraConfig) -> dict[str, Any]:
    label = camera.display_name or camera.path or camera.id
    if not camera.display_name and camera.type == "uvc" and camera.uvc and camera.uvc.env:
        camera_name = camera.uvc.env.get("CAMERA_NAME")
        if isinstance(camera_name, str) and camera_name.strip():
            label = camera_name.strip()
    process = _camera_process_item(processes, camera.id)
    item = {
        "id": camera.id,
        "label": label,
        "type": camera.type,
        "enabled": camera.enabled,
        "path": camera.path,
        "addresses": _stream_addresses(config, camera.path),
        "process": process,
        "health": _camera_health_item(camera, process),
    }
    if camera.type == "ip" and camera.ip:
        item["ptz"] = {
            "enabled": camera.ip.ptz.enabled,
            "access": camera.ip.ptz.access,
        }
    return item


def _viewer_camera_settings(camera: CameraConfig) -> dict[str, Any]:
    if camera.type == "uvc" and camera.uvc:
        env = camera.uvc.env or {}
        return {
            "profile": camera.uvc.profile,
            "input_driver": env.get("INPUT_DRIVER"),
            "width": env.get("WIDTH"),
            "height": env.get("HEIGHT"),
            "fps": env.get("FPS"),
            "encoder": env.get("ENCODER"),
            "quality_preset": env.get("QUALITY_PRESET"),
            "latency_preset": env.get("LATENCY_PRESET"),
            "bitrate": env.get("BITRATE"),
            "maxrate": env.get("MAXRATE"),
            "bufsize": env.get("BUFSIZE"),
            "gop": env.get("GOP"),
        }

    if camera.type == "ip" and camera.ip:
        source_url = camera.ip.source_url or ""
        parsed = urlparse(source_url) if source_url else None
        return {
            "source_configured": bool(source_url),
            "source_host": parsed.hostname if parsed else None,
            "relay_mode": camera.ip.relay_mode,
            "bitrate": camera.ip.bitrate,
            "maxrate": camera.ip.maxrate,
            "bufsize": camera.ip.bufsize,
            "gop": camera.ip.gop,
            "x264_preset": camera.ip.x264_preset,
        }

    return {}


def _collect_multiview_sources(config: RuntimeConfig) -> list[str]:
    if config.multiview.source_paths:
        # preserve order while deduplicating
        out: list[str] = []
        seen: set[str] = set()
        for path in config.multiview.source_paths:
            normalized = path.strip().strip("/")
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized)
        return out

    out = []
    seen = set()
    for camera in config.cameras:
        key = camera.path.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(camera.path)
    return out


def _is_multiview_path(path: str, prefix: str) -> bool:
    p = path.lower()
    pref = prefix.lower()
    return p == pref or p.startswith(pref + "_")


def _camera_by_path(config: RuntimeConfig) -> dict[str, CameraConfig]:
    return {camera.path.strip().strip("/").lower(): camera for camera in config.cameras}


def _multiview_views(config: RuntimeConfig, processes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    mv = config.multiview
    all_sources = _collect_multiview_sources(config)
    filtered_sources = [p for p in all_sources if not _is_multiview_path(p, mv.output_prefix)]
    if not filtered_sources or mv.tile_count <= 0:
        return []
    process_items = processes or {"items": []}
    cameras_by_path = _camera_by_path(config)

    def source_item(path: str) -> dict[str, Any]:
        camera = cameras_by_path.get(path.strip().strip("/").lower())
        if camera is None:
            return {
                "path": path,
                "label": path,
                "type": "external",
                "health": {
                    "state": "healthy",
                    "healthy": True,
                    "reason": "External source",
                    "manual_excluded": False,
                    "quarantined": False,
                    "placeholder": False,
                },
            }
        process = _camera_process_item(process_items, camera.id)
        return {
            "path": path,
            "label": _viewer_camera_item(config, process_items, camera)["label"],
            "type": camera.type,
            "camera_id": camera.id,
            "health": _camera_health_item(camera, process),
        }

    view_count = int(math.ceil(len(filtered_sources) / mv.tile_count))
    views: list[dict[str, Any]] = []
    for idx in range(view_count):
        sources = filtered_sources[idx * mv.tile_count : (idx + 1) * mv.tile_count]
        view_path = f"{mv.output_prefix}_{idx + 1}"
        views.append(
            {
                "id": view_path,
                "index": idx + 1,
                "sources": sources,
                "source_items": [source_item(path) for path in sources],
                **_stream_addresses(config, view_path),
            }
        )
    return views


def _resolve_record_root_path(config: RuntimeConfig, workspace_dir: str) -> Path:
    root = Path(config.recording.record_root)
    if root.is_absolute():
        return root
    return (Path(workspace_dir) / root).resolve()


def _to_recording_file_id(relative_path: str) -> str:
    return base64.urlsafe_b64encode(relative_path.encode("utf-8")).decode("ascii").rstrip("=")


def _recording_roots(config: RuntimeConfig, workspace: str):
    from flinteye_app.flinteye_storage import locations
    return [entry[0] for entry in locations(config, workspace, visible_only=True)]


def _all_recording_files(config: RuntimeConfig, workspace: str):
    files = []
    for root in _recording_roots(config, workspace):
        root_id = hashlib.sha256(str(root).encode()).hexdigest()[:24]
        for item in _list_recording_files(root):
            item["file_id"] = "v2." + root_id + "." + item["file_id"]
            item["record_root"] = str(root)
            files.append(item)
    return files


def _resolve_recording_file(config: RuntimeConfig, workspace: str, file_id: str):
    root = _resolve_record_root_path(config, workspace)
    if file_id.startswith("v2."):
        try:
            _, root_id, file_id = file_id.split(".", 2)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid recording ID") from error
        root = next((p for p in _recording_roots(config, workspace)
                     if hashlib.sha256(str(p).encode()).hexdigest()[:24] == root_id), None)
        if root is None:
            raise HTTPException(status_code=404, detail="Recording location is hidden or unavailable")
    relative = _from_recording_file_id(file_id)
    path = _safe_recording_path(root, relative)
    return root, path.relative_to(root.resolve()).as_posix(), path


def _from_recording_file_id(file_id: str) -> str:
    normalized = file_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="file_id must not be empty")
    padding = "=" * (-len(normalized) % 4)
    try:
        decoded = base64.urlsafe_b64decode(normalized + padding).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail="invalid file_id") from e
    relative = decoded.strip().lstrip("/\\")
    if not relative:
        raise HTTPException(status_code=400, detail="invalid file_id")
    return relative


def _safe_recording_path(root: Path, relative_path: str) -> Path:
    if _is_recording_playback_cache_path(relative_path):
        raise HTTPException(status_code=404, detail="recording file not found")
    resolved_root = root.resolve()
    parts = relative_path.split("/")
    if not parts or any(part in {"", ".", ".."} or "\\" in part for part in parts):
        raise HTTPException(status_code=400, detail="invalid file path")
    current = resolved_root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise HTTPException(status_code=404, detail="recording file not found")
    candidate = (resolved_root / relative_path).resolve()
    try:
        normalized_relative = candidate.relative_to(resolved_root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid file path") from e
    if _is_recording_playback_cache_path(normalized_relative.as_posix()):
        raise HTTPException(status_code=404, detail="recording file not found")
    if candidate.suffix.lower() not in {".mp4", ".ts"} or not candidate.is_file():
        raise HTTPException(status_code=404, detail="recording file not found")
    return candidate


def _recording_stream_from_relative(relative_path: str) -> str:
    normalized = relative_path.strip().strip("/\\")
    if not normalized:
        return ""
    parts = Path(normalized).parts
    return parts[0] if parts else ""


def _build_recording_download_filename(relative_path: str, file_path: Path) -> str:
    stream_id = _recording_stream_from_relative(relative_path) or "recording"
    safe_stream_id = re.sub(r"[^A-Za-z0-9._-]+", "_", stream_id).strip("._-") or "recording"
    recorded_at = datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d_%H-%M-%S")
    return f"{safe_stream_id}_{recorded_at}.mp4"


def _is_recording_playback_cache_path(relative_path: str) -> bool:
    normalized = relative_path.strip().strip("/\\")
    if not normalized:
        return False
    parts = Path(normalized).parts
    return bool(parts) and parts[0].lower() == RECORDING_PLAYBACK_CACHE_DIRNAME.lower()


def _cleanup_recording_playback_cache(
    cache_dir: Path,
    *,
    retention_seconds: float | None,
    now: float | None = None,
) -> tuple[int, int]:
    if retention_seconds is None:
        return 0, 0
    if cache_dir.is_symlink() or not cache_dir.is_dir():
        return 0, 0

    cutoff = (time.time() if now is None else now) - retention_seconds
    deleted_count = 0
    deleted_bytes = 0
    for path in cache_dir.iterdir():
        try:
            if (
                path.is_symlink() or not path.is_file()
                or not re.fullmatch(r"[0-9a-f]{24}\.(?:mp4|jpg|tmp\.mp4|tmp\.jpg)", path.name)
            ):
                continue
            stat_result = path.stat()
            if float(stat_result.st_mtime) > cutoff:
                continue
            path.unlink()
            deleted_count += 1
            deleted_bytes += int(stat_result.st_size)
        except OSError:
            continue
    return deleted_count, deleted_bytes


def _list_recording_files(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    now = time.time()
    files: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if path.suffix.lower() not in {".mp4", ".ts"} or _is_recording_playback_cache_path(rel) or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            continue
        if any((root / Path(*Path(rel).parts[:index])).is_symlink() for index in range(1, len(Path(rel).parts))):
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        stream_id = _recording_stream_from_relative(rel)
        age_sec = max(0.0, now - float(stat.st_mtime))
        files.append(
            {
                "file_id": _to_recording_file_id(rel),
                "relative_path": rel,
                "stream_id": stream_id,
                "size_bytes": int(stat.st_size),
                "modified_at": float(stat.st_mtime),
                "age_sec": int(age_sec),
                "is_stable": age_sec >= RECORDING_STABLE_AGE_SEC,
            }
        )
    files.sort(key=lambda item: item["modified_at"], reverse=True)
    return files


def _recording_natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


def _select_recording_ffmpeg_bin(config: RuntimeConfig) -> str:
    ffmpeg_bin = config.multiview.ffmpeg_bin.strip()
    return ffmpeg_bin or "ffmpeg"


def _build_recording_playback_cache_path(
    cache_dir: Path, root: Path, relative_path: str, stat_result: os.stat_result
) -> Path:
    token = hashlib.sha1(
        f"{root.resolve()}|{relative_path}|{int(stat_result.st_size)}|{int(stat_result.st_mtime_ns)}".encode("utf-8")
    ).hexdigest()[:24]
    return cache_dir / f"{token}.mp4"


def _build_recording_thumbnail_cache_path(
    cache_dir: Path, root: Path, relative_path: str, stat_result: os.stat_result
) -> Path:
    return _build_recording_playback_cache_path(cache_dir, root, relative_path, stat_result).with_suffix(".jpg")


def _playback_cache_limit(config: RuntimeConfig) -> int:
    return config.recording.playback_cache_max_bytes


def _playback_cache_reserve(config: RuntimeConfig) -> int:
    return config.recording.min_free_bytes + 256_000_000


def _prune_private_playback_cache(cache_dir: Path, limit: int, preserve: Path) -> None:
    entries = sorted(
        (path for path in cache_dir.iterdir() if path.is_file() and not path.is_symlink()),
        key=lambda path: path.stat().st_mtime,
    )
    total = sum(path.stat().st_size for path in entries)
    for path in entries:
        if total <= limit:
            break
        if path == preserve:
            continue
        size = path.stat().st_size
        path.unlink()
        total -= size


def _prepare_recording_thumbnail_file(
    context: AppContext,
    config: RuntimeConfig,
    *,
    root: Path,
    relative_path: str,
    file_path: Path,
) -> Path:
    output_path = _build_recording_thumbnail_cache_path(context.playback_cache_dir, root, relative_path, file_path.stat())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.jpg")

    with context.lock:
        if output_path.is_file() and output_path.stat().st_size > 0:
            try:
                output_path.touch()
            except OSError:
                pass
            return output_path

        _prune_private_playback_cache(context.playback_cache_dir, _playback_cache_limit(config) - 1_000_000, tmp_path)
        if shutil.disk_usage(context.playback_cache_dir).free < _playback_cache_reserve(config) + 1_000_000:
            raise HTTPException(status_code=507, detail="Not enough free disk space for playback")
        ffmpeg_bin = _select_recording_ffmpeg_bin(config)
        last_detail = "ffmpeg thumbnail extraction failed"
        for seek_sec in ("1", "0"):
            if tmp_path.exists():
                tmp_path.unlink()
            cmd = [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
            if seek_sec != "0":
                cmd.extend(["-ss", seek_sec])
            cmd.extend(
                [
                    "-i",
                    str(file_path),
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
                    "-q:v",
                    "3",
                    str(tmp_path),
                ]
            )
            result = run_background(cmd, **background_process_options(), check=False, capture_output=True, text=True)
            if result.returncode == 0 and tmp_path.is_file() and tmp_path.stat().st_size > 0:
                tmp_path.replace(output_path)
                _prune_private_playback_cache(context.playback_cache_dir, _playback_cache_limit(config), output_path)
                return output_path
            last_detail = (result.stderr or result.stdout or last_detail).strip()

        if tmp_path.exists():
            tmp_path.unlink()
        raise HTTPException(status_code=502, detail=last_detail)


def _prepare_recording_playback_file(
    context: AppContext,
    config: RuntimeConfig,
    *,
    root: Path,
    relative_path: str,
    file_path: Path,
) -> Path:
    stat_result = file_path.stat()
    age_sec = max(0.0, time.time() - float(stat_result.st_mtime))
    if age_sec < RECORDING_STABLE_AGE_SEC:
        raise HTTPException(
            status_code=409,
            detail="recording file is still being written; wait until it becomes stable",
        )

    output_path = _build_recording_playback_cache_path(context.playback_cache_dir, root, relative_path, stat_result)
    cache_limit = _playback_cache_limit(config)
    if stat_result.st_size >= cache_limit:
        raise HTTPException(status_code=507, detail="Recording is too large for the playback cache")

    ffmpeg_bin = _select_recording_ffmpeg_bin(config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.mp4")

    with context.lock:
        if output_path.is_file() and output_path.stat().st_size > 0:
            try:
                output_path.touch()
            except OSError:
                pass
            return output_path
        if tmp_path.exists():
            tmp_path.unlink()
        _prune_private_playback_cache(context.playback_cache_dir, cache_limit - stat_result.st_size, tmp_path)
        output_limit = min(cache_limit, max(0, shutil.disk_usage(context.playback_cache_dir).free - _playback_cache_reserve(config)))
        if stat_result.st_size + 1_000_000 >= output_limit:
            raise HTTPException(status_code=507, detail="Not enough free disk space for playback")

        cmd = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(file_path),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-dn",
            "-sn",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-fs",
            str(output_limit),
            "-f",
            "mp4",
            str(tmp_path),
        ]
        result = run_background(cmd, **background_process_options(), check=False, capture_output=True, text=True)
        if result.returncode != 0 or not tmp_path.is_file() or tmp_path.stat().st_size <= 0:
            if tmp_path.exists():
                tmp_path.unlink()
            detail = (result.stderr or result.stdout or "ffmpeg remux failed").strip()
            raise HTTPException(status_code=502, detail=detail)
        if tmp_path.stat().st_size >= output_limit:
            tmp_path.unlink()
            raise HTTPException(status_code=507, detail="Recording is too large for the playback cache")
        tmp_path.replace(output_path)
        _prune_private_playback_cache(context.playback_cache_dir, cache_limit, output_path)

    return output_path


def _restart_affected(context: AppContext, old_cfg: RuntimeConfig, new_cfg: RuntimeConfig) -> None:
    old_cameras = {camera.id.lower(): camera for camera in old_cfg.cameras}
    new_cameras = {camera.id.lower(): camera for camera in new_cfg.cameras}
    for camera_id in old_cameras.keys() | new_cameras.keys():
        if old_cameras.get(camera_id) != new_cameras.get(camera_id):
            context.ptz_controller.invalidate(camera_id)
    context.reconfigure_logging(new_cfg)
    context.cleanup_recording_playback_cache(new_cfg)
    _apply_running_media_config(context, new_cfg, force_restart=old_cfg.mediamtx != new_cfg.mediamtx)


def _apply_running_media_config(context: AppContext, config: RuntimeConfig, *, force_restart=False) -> MediamtxYamlApplyResult:
    with context.supervisor.media_update(pause=False):
        try:
            callback = context.supervisor.pause_media_publishers if config.mediamtx.control_mode != 'external' else None
            result = _apply_mediamtx_config(context, config, before_write=callback)
            if force_restart or (result.ok and result.changed):
                context.supervisor.mediamtx_restart(config)
            return result
        finally:
            context.supervisor.reconcile(config)


def _apply_mediamtx_config(context: AppContext, config: RuntimeConfig, *, before_write=None) -> MediamtxYamlApplyResult:
    from flinteye_app.flinteye_storage import storage_problem
    context.storage_problem = storage_problem(config)
    if context.storage_problem:
        config = config.model_copy(update={"recording": config.recording.model_copy(update={"enabled": False})})
    result = apply_mediamtx_yaml(config, workspace_dir=context.workspace_dir, before_write=before_write)
    if not result.ok:
        logger.warning("mediamtx config apply failed: %s", result.message)
        return result

    if result.recording.changed:
        logger.info(
            "recording config updated: config=%s paths=%s root=%s",
            result.recording.config_path,
            len(result.recording.record_paths),
            result.recording.record_root,
        )

    if result.managed.changed:
        logger.info(
            "managed mediamtx config updated: config=%s actions=%s",
            result.managed.config_path,
            len(result.managed.actions),
        )
    return result


def _replace_camera_list(context: AppContext, cameras_payload: list[dict[str, Any]]) -> RuntimeConfig:
    patched = context.store.patch_runtime({"cameras": cameras_payload})
    return patched


def _device_keys_for_match(device: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for raw in [
        device.get("ffmpeg_device"),
        device.get("ffmpeg_device_index"),
        device.get("display_name"),
    ]:
        if not raw:
            continue
        text = str(raw).strip()
        if not text:
            continue
        keys.add(text.lower())
        if text.lower().startswith("video="):
            keys.add(text[6:].strip().lower())
        else:
            keys.add(f"video={text.lower()}")
    return keys


def _camera_keys_for_match(camera: CameraConfig) -> set[str]:
    if camera.type != "uvc" or not camera.uvc:
        return set()
    keys: set[str] = set()
    device = str(camera.uvc.env.get("DEVICE", "")).strip()
    if device:
        keys.add(device.lower())
        if device.lower().startswith("video="):
            keys.add(device[6:].strip().lower())
        else:
            keys.add(f"video={device.lower()}")
    return keys


def _ignored_keys_for_device(device: dict[str, Any]) -> set[str]:
    keys = _device_keys_for_match(device)
    device_id = str(device.get("device_id", "")).strip().lower()
    if device_id:
        keys.add(device_id)
    return keys


def _find_camera_by_device(config: RuntimeConfig, device: dict[str, Any]) -> CameraConfig | None:
    dkeys = _device_keys_for_match(device)
    if not dkeys:
        return None
    for camera in config.cameras:
        if camera.type != "uvc":
            continue
        if _camera_keys_for_match(camera) & dkeys:
            return camera
    return None


def _ignored_uvc_devices(config: RuntimeConfig) -> set[str]:
    return {item.strip().lower() for item in config.device_discovery.ignored_uvc_devices if item.strip()}


def _is_ignored_uvc_device(config: RuntimeConfig, device: dict[str, Any]) -> bool:
    return bool(_ignored_keys_for_device(device) & _ignored_uvc_devices(config))


def _next_cam_index(config: RuntimeConfig) -> int:
    used: set[int] = set()
    for camera in config.cameras:
        m = None
        if camera.uvc and camera.uvc.profile:
            m = camera.uvc.profile.lower().strip()
            mm = None
            if m.startswith("cam"):
                try:
                    mm = int(m[3:])
                except ValueError:
                    mm = None
            if mm:
                used.add(mm)
        path = camera.path.lower()
        pm = re.match(r"^uvc_cam(\d+)$", path)
        if pm:
            used.add(int(pm.group(1)))
    idx = 1
    while idx in used:
        idx += 1
    return idx


def _select_probe_ffmpeg_bin(config: RuntimeConfig) -> str:
    for camera in config.cameras:
        if camera.type != "uvc" or not camera.uvc:
            continue
        value = camera.uvc.env.get("FFMPEG_BIN")
        if value:
            return str(value)
    if config.multiview.ffmpeg_bin:
        return config.multiview.ffmpeg_bin
    return "ffmpeg"


def _get_uvc_probe_result(context: AppContext, *, refresh: bool = False) -> dict[str, Any]:
    config = context.store.get_effective()
    ffmpeg_bin = _select_probe_ffmpeg_bin(config)
    context.uvc_probe_cache.ffmpeg_bin = ffmpeg_bin
    try:
        return context.uvc_probe_cache.get(refresh=refresh)
    except UvcProbeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


def _suggest_for_device(
    *,
    config: RuntimeConfig,
    device: dict[str, Any],
    profile: str | None = None,
    path: str | None = None,
    camera_name: str | None = None,
    enabled: bool | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    bitrate: str | None = None,
    use_device_index: bool = False,
    fallback_index: int | None = None,
) -> dict[str, Any]:
    matched = _find_camera_by_device(config, device)
    if matched:
        default_profile = matched.uvc.profile if matched.uvc else matched.path
        default_path = matched.path
        default_name = (
            matched.uvc.env.get("CAMERA_NAME")
            if matched.uvc and matched.uvc.env.get("CAMERA_NAME")
            else matched.id
        )
        default_enabled = matched.enabled
        default_bitrate = (
            matched.uvc.env.get("BITRATE")
            if matched.uvc and matched.uvc.env.get("BITRATE")
            else None
        )
    else:
        idx = fallback_index or _next_cam_index(config)
        default_profile = f"cam{idx}"
        default_path = f"uvc_cam{idx}"
        default_name = f"UVC-CAM-{idx:02d}"
        default_enabled = True
        default_bitrate = None

    recommended = device.get("recommended", {})
    bitrate_value = default_bitrate if bitrate is None else str(bitrate).strip()
    suggestion = build_uvc_suggestion(
        driver=device["driver"],
        ffmpeg_device=(
            device.get("ffmpeg_device_index")
            if use_device_index and device.get("ffmpeg_device_index")
            else device.get("ffmpeg_device")
        ),
        display_name=device.get("display_name") or default_name,
        profile=(profile or default_profile),
        path=(path or default_path),
        rtsp_base_url=_publisher_rtsp_base_url(config),
        enabled=bool(default_enabled if enabled is None else enabled),
        width=int(width or recommended.get("width") or 1280),
        height=int(height or recommended.get("height") or 720),
        fps=int(fps or recommended.get("fps") or 30),
        bitrate=bitrate_value or None,
        camera_name=(camera_name or default_name),
    )
    suggestion["matched_camera_id"] = matched.id if matched else None
    return suggestion


def _validate_camera_payload(payload: dict[str, Any]) -> CameraConfig:
    try:
        return CameraConfig.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.on_event("startup")
def _on_startup() -> None:
    context = getattr(app.state, "context", None)
    if context is None:
        set_app_context(AppContext(env_file=DEFAULT_ENV_FILE, runtime_file=DEFAULT_RUNTIME_FILE))
        context = app.state.context
    if context._closing.is_set():
        return
    config = context.store.get_effective()
    if config.auth.provider == "local":
        if not local_auth_is_configured(config.auth):
            logger.warning("local auth provider is selected but not initialized; run manage_auth.py init-local")
    else:
        admin_token, _, viewer_auth_required = _legacy_auth_settings(context)
        if not viewer_auth_required and not admin_token:
            logger.warning(
                "insecure auth mode: viewer_auth_required=false and admin token is empty;"
                " viewer APIs are public and admin APIs are disabled until API_ADMIN_TOKEN is set"
            )
    if config.auth.provider == "local" and not local_auth_is_configured(config.auth):
        return
    enabled_camera_count = sum(1 for cam in config.cameras if cam.enabled)
    if enabled_camera_count == 0 and not config.multiview.enabled:
        logger.warning(
            "no enabled camera and multiview is disabled in effective config; only MediaMTX will run"
        )
    else:
        logger.info(
            "startup targets: cameras=%s/%s multiview=%s",
            enabled_camera_count,
            len(config.cameras),
            "enabled" if config.multiview.enabled else "disabled",
        )
    _apply_mediamtx_config(context, config)
    if config.mediamtx.autostart_on_api_start and config.mediamtx.control_mode != "external":
        start_result = context.supervisor.mediamtx_start(config)
        if not start_result.get("ok"):
            detail = start_result.get("stderr") or start_result.get("stdout") or "unknown error"
            logger.warning("mediamtx autostart failed: %s", detail)
    context.supervisor.reconcile(config)
    context.start_recording_cache_cleanup()


@app.on_event("shutdown")
def _on_shutdown() -> None:
    context = getattr(app.state, "context", None)
    if context is not None:
        context.shutdown()


@app.get("/api/v1/health")
def get_health(request: Request) -> dict[str, Any]:
    context = get_context(request)
    return {
        "ok": True,
        "service": APP_TITLE,
        "version": APP_VERSION,
        "uptime_sec": int(time.time() - context.started_at),
    }


def _build_auth_me_payload(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    auth = config.auth
    identity = _get_session_identity(request, context)
    return {
        "authenticated": identity is not None,
        "provider": auth.provider,
        "role": identity.role if identity else None,
        "username": identity.username if identity else None,
        "viewer_auth_required": auth.viewer_auth_required if auth.provider == "local" else config.api.viewer_auth_required,
        "setup_required": auth.provider == "local" and not local_auth_is_configured(auth),
        "local": {
            "admin_username": auth.local.admin.username,
            "viewer_username": auth.local.viewer.username,
        },
        "oidc": {
            "configured": bool(auth.oidc_issuer_url and auth.oidc_client_id and auth.oidc_redirect_uri),
        },
    }


@app.get("/api/v1/auth/me")
def get_auth_me(request: Request) -> dict[str, Any]:
    return _build_auth_me_payload(request)


@app.post("/api/v1/auth/login")
def post_auth_login(request: Request, payload: dict[str, Any], response: Response) -> dict[str, Any]:
    context = get_context(request)
    raw_username = payload.get("username", "")
    raw_password = payload.get("password", "")
    if (
        not isinstance(raw_username, str) or len(raw_username) > 256
        or not isinstance(raw_password, str) or len(raw_password) > 1024
    ):
        raise HTTPException(status_code=422, detail="Invalid login input")
    context.check_login_budget(request.client.host if request.client else "unknown")
    if not context._login_workers.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Login service is busy", headers={"Retry-After": "1"})
    try:
        return _post_auth_login_checked(request, payload, response, context)
    finally:
        context._login_workers.release()


def _post_auth_login_checked(request: Request, payload: dict[str, Any], response: Response, context: AppContext) -> dict[str, Any]:
    config = context.store.get_effective()
    auth = config.auth
    signing_secret = _session_signing_secret_from_config(config)
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    identity: AuthIdentity | None = None

    if auth.provider == "local":
        if not local_auth_is_configured(auth):
            raise HTTPException(status_code=503, detail="local auth is not initialized")
        identity = authenticate_local_user(auth, username=username, password=password)
    elif auth.provider == "legacy_token":
        admin_token, viewer_token, _ = _legacy_auth_settings_from_config(config)
        if username == "admin" and admin_token and password == admin_token:
            identity = AuthIdentity(username="admin", role="admin", provider="legacy_token")
        elif username == "viewer" and viewer_token and password == viewer_token:
            identity = AuthIdentity(username="viewer", role="viewer", provider="legacy_token")
    else:
        raise HTTPException(status_code=400, detail=f"login is not supported for auth provider '{auth.provider}'")

    if identity is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    cookie_value = create_session_value(signing_secret, identity, auth.session_ttl_sec)
    response.set_cookie(
        key=auth.session_cookie_name,
        value=cookie_value,
        max_age=auth.session_ttl_sec,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return {
        "ok": True,
        "authenticated": True,
        "role": identity.role,
        "username": identity.username,
        "provider": identity.provider,
    }


@app.post("/api/v1/auth/logout")
def post_auth_logout(request: Request, response: Response) -> dict[str, Any]:
    context = get_context(request)
    auth = context.store.get_effective().auth
    response.delete_cookie(key=auth.session_cookie_name, path="/")
    return {"ok": True}


@app.get("/api/v1/status")
def get_status(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config, processes, mediamtx = _effective_with_status(context)
    running_processes = sum(1 for item in processes.get("items", []) if item.get("status") == "running")
    return {
        "timestamp": time.time(),
        "mediamtx": mediamtx,
        "processes": processes,
        "cameras_total": len(config.cameras),
        "cameras_enabled": sum(1 for cam in config.cameras if cam.enabled),
        "multiview_enabled": config.multiview.enabled,
        "running_processes": running_processes,
    }


@app.get("/api/v1/status/listener", dependencies=[Depends(require_admin)])
def get_listener_status(request: Request) -> dict[str, Any]:
    context = get_context(request)
    if context.listener is not None:
        return context.listener
    # External ASGI runners own the binding. Report the actual connection, not
    # configuration defaults or an untrusted forwarded Host header.
    server = request.scope.get("server")
    return {"host": server[0], "port": server[1], "source": "ASGI connection"} if server else {}


@app.get("/api/v1/status/processes", dependencies=[Depends(require_viewer)])
def get_status_processes(request: Request) -> dict[str, Any]:
    context = get_context(request)
    return _sanitized_process_status(context.supervisor.process_status())


@app.get("/api/v1/status/mediamtx", dependencies=[Depends(require_viewer)])
def get_status_mediamtx(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    return context.supervisor.mediamtx_status(config)


@app.post("/api/v1/control/start", dependencies=[Depends(require_admin)])
def post_control_start(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    result = context.supervisor.start_all(config)
    return {"ok": True, "result": result}


@app.post("/api/v1/control/stop", dependencies=[Depends(require_admin)])
def post_control_stop(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    result = context.supervisor.stop_all(config)
    return {"ok": True, "result": result}


@app.post("/api/v1/control/restart", dependencies=[Depends(require_admin)])
def post_control_restart(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    result = context.supervisor.restart_all(config)
    return {"ok": True, "result": result}


@app.get("/api/v1/config/effective", dependencies=[Depends(require_admin)])
def get_config_effective(request: Request, response: Response) -> dict[str, Any]:
    context = get_context(request)
    response.headers["ETag"] = f'"{context.store.runtime_revision()}"'
    response.headers["Cache-Control"] = "no-store"
    return context.store.get_effective().model_dump()


@app.get("/api/v1/config/runtime", dependencies=[Depends(require_admin)])
def get_config_runtime(request: Request) -> dict[str, Any]:
    context = get_context(request)
    return context.store.get_runtime()


@app.put("/api/v1/config/runtime", dependencies=[Depends(require_admin)])
def put_config_runtime(request: Request, response: Response, payload: dict[str, Any]) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    try:
        new_cfg = context.store.set_runtime(
            payload, expected_revision=request.headers.get("if-match"), protect_credentials=True
        )
    except RuntimeRevisionMismatch as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _restart_affected(context, old_cfg, new_cfg)
    response.headers["ETag"] = f'"{context.store.runtime_revision()}"'
    return {"ok": True, "runtime": context.store.get_runtime(), "effective": new_cfg.model_dump()}


@app.patch("/api/v1/config/runtime", dependencies=[Depends(require_admin)])
def patch_config_runtime(request: Request, response: Response, payload: dict[str, Any]) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    try:
        new_cfg = context.store.patch_runtime(
            payload, expected_revision=request.headers.get("if-match"), protect_credentials=True
        )
    except RuntimeRevisionMismatch as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _restart_affected(context, old_cfg, new_cfg)
    response.headers["ETag"] = f'"{context.store.runtime_revision()}"'
    return {"ok": True, "runtime": context.store.get_runtime(), "effective": new_cfg.model_dump()}


@app.post("/api/v1/config/apply", dependencies=[Depends(require_admin)])
def post_config_apply(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    _apply_running_media_config(context, config)
    return {"ok": True, "applied": True}


def _find_probe_device_or_404(result: dict[str, Any], device_id: str) -> dict[str, Any]:
    normalized = device_id.strip().lower()
    for item in result.get("devices", []):
        if str(item.get("device_id", "")).lower() == normalized:
            return item
    raise HTTPException(status_code=404, detail=f"UVC device not found: {device_id}")


@app.get("/api/v1/uvc/devices", dependencies=[Depends(require_admin)])
def get_uvc_devices(request: Request, refresh: bool = False) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    result = _get_uvc_probe_result(context, refresh=refresh)
    next_idx = _next_cam_index(config)
    items: list[dict[str, Any]] = []
    for device in result.get("devices", []):
        matched = _find_camera_by_device(config, device)
        fallback_idx = None if matched else next_idx
        suggestion = _suggest_for_device(
            config=config,
            device=device,
            fallback_index=fallback_idx,
        )
        if matched is None:
            next_idx += 1
        item = dict(device)
        item["ignored"] = _is_ignored_uvc_device(config, device)
        item["suggestion"] = suggestion
        items.append(item)

    return {
        "driver": result.get("driver"),
        "ffmpeg_bin": result.get("ffmpeg_bin"),
        "warning": result.get("warning", ""),
        "count": len(items),
        "items": items,
    }


@app.get("/api/v1/uvc/devices/{device_id}", dependencies=[Depends(require_admin)])
def get_uvc_device(request: Request, device_id: str, refresh: bool = False) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    result = _get_uvc_probe_result(context, refresh=refresh)
    device = _find_probe_device_or_404(result, device_id)
    suggestion = _suggest_for_device(config=config, device=device)
    out = dict(device)
    out["ignored"] = _is_ignored_uvc_device(config, device)
    out["suggestion"] = suggestion
    return out


@app.post("/api/v1/uvc/devices/{device_id}/suggest", dependencies=[Depends(require_admin)])
def post_uvc_device_suggest(
    request: Request,
    device_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    result = _get_uvc_probe_result(context, refresh=False)
    device = _find_probe_device_or_404(result, device_id)
    body = payload or {}

    suggestion = _suggest_for_device(
        config=config,
        device=device,
        profile=body.get("profile"),
        path=body.get("path"),
        camera_name=body.get("camera_name"),
        enabled=body.get("enabled"),
        width=body.get("width"),
        height=body.get("height"),
        fps=body.get("fps"),
        bitrate=body.get("bitrate"),
        use_device_index=bool(body.get("use_device_index", False)),
    )
    return {
        "device_id": device["device_id"],
        "display_name": device["display_name"],
        "driver": device["driver"],
        "suggestion": suggestion,
    }


@app.post("/api/v1/uvc/devices/{device_id}/apply", dependencies=[Depends(require_admin)])
def post_uvc_device_apply(
    request: Request,
    device_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    result = _get_uvc_probe_result(context, refresh=False)
    device = _find_probe_device_or_404(result, device_id)
    body = payload or {}

    suggestion = _suggest_for_device(
        config=old_cfg,
        device=device,
        profile=body.get("profile"),
        path=body.get("path"),
        camera_name=body.get("camera_name"),
        enabled=body.get("enabled"),
        width=body.get("width"),
        height=body.get("height"),
        fps=body.get("fps"),
        bitrate=body.get("bitrate"),
        use_device_index=bool(body.get("use_device_index", False)),
    )

    runtime_camera = suggestion["runtime_camera"]
    new_path = runtime_camera["path"].lower()
    device_keys = _device_keys_for_match(device)

    cameras_payload: list[dict[str, Any]] = []
    for cam in old_cfg.cameras:
        if cam.type == "uvc":
            if cam.path.lower() == new_path:
                continue
            if _camera_keys_for_match(cam) & device_keys:
                continue
        cameras_payload.append(cam.model_dump())
    cameras_payload.append(runtime_camera)

    ignored_device_keys = _ignored_keys_for_device(device)
    ignored_devices = [
        item
        for item in old_cfg.device_discovery.ignored_uvc_devices
        if item.strip().lower() not in ignored_device_keys
    ]
    new_cfg = context.store.patch_runtime(
        {
            "cameras": cameras_payload,
            "device_discovery": {"ignored_uvc_devices": ignored_devices},
        }
    )
    _restart_affected(context, old_cfg, new_cfg)

    return {
        "ok": True,
        "camera": runtime_camera,
        "suggestion": suggestion,
    }


@app.get("/api/v1/mediamtx/config", dependencies=[Depends(require_admin)])
def get_mediamtx_config(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    config_path = resolve_mediamtx_config_path(config, context.workspace_dir)
    return {
        "config_path": str(config_path) if config_path else None,
        "managed": config.mediamtx.managed.model_dump(by_alias=True),
        "recording": config.recording.model_dump(),
    }


@app.patch("/api/v1/mediamtx/config", dependencies=[Depends(require_admin)])
def patch_mediamtx_config(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    patch: dict[str, Any] = {}

    if "managed" in payload:
        patch["mediamtx"] = {"managed": payload["managed"]}
    if "recording" in payload:
        patch["recording"] = payload["recording"]
    if "mediamtx" in payload:
        patch["mediamtx"] = _deep_merge_dict(patch.get("mediamtx", {}), payload["mediamtx"])

    if not patch:
        raise HTTPException(status_code=400, detail="payload must include one of: managed, recording, mediamtx")

    new_cfg = context.store.patch_runtime(patch)
    _restart_affected(context, old_cfg, new_cfg)
    config_path = resolve_mediamtx_config_path(new_cfg, context.workspace_dir)
    return {
        "ok": True,
        "config_path": str(config_path) if config_path else None,
        "managed": new_cfg.mediamtx.managed.model_dump(by_alias=True),
        "recording": new_cfg.recording.model_dump(),
    }


@app.post("/api/v1/mediamtx/config/apply", dependencies=[Depends(require_admin)])
def post_mediamtx_config_apply(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    result = _apply_running_media_config(context, config)
    return {
        "ok": result.ok,
        "changed": result.changed,
        "recording": {
            "ok": result.recording.ok,
            "changed": result.recording.changed,
            "message": result.recording.message,
        },
        "managed": {
            "ok": result.managed.ok,
            "changed": result.managed.changed,
            "message": result.managed.message,
        },
        "message": result.message,
    }


@app.get("/api/v1/cameras", dependencies=[Depends(require_admin)])
def get_cameras(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    processes = context.supervisor.process_status()
    sanitized_processes = _sanitized_process_status(processes)
    items: list[dict[str, Any]] = []
    for camera in config.cameras:
        camera_dump = camera.model_dump()
        health_process = _camera_process_item(sanitized_processes, camera.id)
        camera_dump["addresses"] = _stream_addresses(config, camera.path)
        camera_dump["process"] = health_process
        camera_dump["health"] = _camera_health_item(camera, health_process)
        items.append(camera_dump)
    return {"items": items}


@app.post("/api/v1/ip-cameras/probe", dependencies=[Depends(require_admin)])
def post_ip_camera_probe(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    source_url = str(payload.get("source_url") or "").strip()
    parsed_source = urlparse(source_url)
    if parsed_source.scheme.lower() not in {"rtsp", "rtsps"} or not parsed_source.hostname:
        raise HTTPException(status_code=422, detail="source_url must be a valid rtsp:// or rtsps:// URL")

    onvif_mode = str(payload.get("onvif_mode") or "auto").strip().lower()
    if onvif_mode not in {"auto", "manual", "disabled"}:
        raise HTTPException(status_code=422, detail="onvif_mode must be auto, manual, or disabled")
    onvif_address = str(payload.get("onvif_address") or "").strip() or None
    if onvif_mode == "manual" and not onvif_address:
        raise HTTPException(status_code=422, detail="onvif_address is required in manual mode")
    try:
        probe_duration_sec = float(payload.get("probe_duration_sec") or 6.0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="probe_duration_sec must be numeric") from exc
    if probe_duration_sec < 2.0 or probe_duration_sec > 15.0:
        raise HTTPException(status_code=422, detail="probe_duration_sec must be in range 2..15")

    camera_id = str(payload.get("camera_id") or "").strip()
    if bool(payload.get("force", True)):
        context = get_context(request)
        if camera_id:
            context.ptz_controller.invalidate(camera_id)
        else:
            context.ptz_controller.invalidate_by_source(source_url)

    return inspect_ip_camera(
        source_url,
        probe_duration_sec=probe_duration_sec,
        onvif_mode=onvif_mode,
        onvif_address=onvif_address,
        onvif_username=str(payload.get("onvif_username") or "").strip() or None,
        onvif_password=str(payload.get("onvif_password") or "") or None,
    )


@app.get("/api/v1/viewer/cameras", dependencies=[Depends(require_viewer)])
def get_viewer_cameras(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    processes = _sanitized_process_status(context.supervisor.process_status())
    items = [_viewer_camera_item(config, processes, camera) for camera in config.cameras]
    return {"items": items}


@app.get("/api/v1/viewer/info", dependencies=[Depends(require_viewer)])
def get_viewer_info(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    processes = _sanitized_process_status(context.supervisor.process_status())
    api_base_url = str(request.base_url).rstrip("/")
    cameras = []
    for camera in config.cameras:
        item = _viewer_camera_item(config, processes, camera)
        item["settings"] = _viewer_camera_settings(camera)
        cameras.append(item)

    mv = config.multiview
    multiview_summary = {
        "enabled": mv.enabled,
        "output_prefix": mv.output_prefix,
        "tile_count": mv.tile_count,
        "source_mode": mv.source_mode,
        "auto_placeholder_missing_sources": mv.auto_placeholder_missing_sources,
        "canvas_width": mv.layout.canvas_width,
        "canvas_height": mv.layout.canvas_height,
        "fps": mv.quality.fps,
        "encoder": mv.quality.encoder,
        "quality_preset": mv.quality.quality_preset,
        "bitrate": mv.quality.bitrate,
        "maxrate": mv.quality.maxrate,
        "bufsize": mv.quality.bufsize,
        "gop": mv.quality.gop,
        "input_stall_timeout_sec": mv.input_stall_timeout_sec,
        "input_stall_timeout_option": mv.input_stall_timeout_option,
        "views": _multiview_views(config, processes),
    }

    return {
        "generated_at": time.time(),
        "api": {
            "base_url": api_base_url,
            "swagger_url": api_base_url + "/docs",
            "redoc_url": api_base_url + "/redoc",
            "openapi_url": api_base_url + "/openapi.json",
        },
        "rtsp_base_url": config.mediamtx.rtsp_base_url,
        "webrtc_base_url": config.mediamtx.webrtc_base_url,
        "snapshot": {
            "timeout_sec": config.snapshot.timeout_sec,
            "thumbnail_refresh_interval_sec": config.snapshot.thumbnail_refresh_interval_sec,
        },
        "cameras": cameras,
        "multiview": multiview_summary,
    }


@app.post("/api/v1/cameras", dependencies=[Depends(require_admin)])
def post_cameras(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    camera = _validate_camera_payload(payload)
    existing = [cam.model_dump() for cam in old_cfg.cameras if cam.id.lower() != camera.id.lower()]
    existing.append(camera.model_dump())
    new_cfg = _replace_camera_list(context, existing)
    _restart_affected(context, old_cfg, new_cfg)
    return {"ok": True, "camera": camera.model_dump()}


@app.get("/api/v1/cameras/{camera_id}", dependencies=[Depends(require_admin)])
def get_camera(request: Request, camera_id: str) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    camera = _find_camera(config, camera_id)
    processes = context.supervisor.process_status()
    sanitized_processes = _sanitized_process_status(processes)
    health_process = _camera_process_item(sanitized_processes, camera.id)
    item = camera.model_dump()
    item["addresses"] = _stream_addresses(config, camera.path)
    item["process"] = health_process
    item["health"] = _camera_health_item(camera, health_process)
    return item


@app.get("/api/v1/cameras/{camera_id}/multiview-input/capabilities", dependencies=[Depends(require_admin)])
def get_camera_multiview_input_capabilities(
    request: Request,
    camera_id: str,
    refresh: bool = False,
) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    camera = _find_camera(config, camera_id)
    if camera.type != "ip" or not camera.ip or not camera.ip.source_url:
        raise HTTPException(status_code=422, detail="Multiview input profiles are available for IP cameras only")
    onvif = probe_onvif(
        camera.ip.source_url,
        mode=camera.ip.onvif_mode,
        address=camera.ip.onvif_address,
        username=camera.ip.onvif_username,
        password=camera.ip.onvif_password,
        timeout_sec=5.0,
    )
    columns = config.multiview.layout.grid_columns or max(1, math.ceil(math.sqrt(config.multiview.tile_count)))
    rows = max(1, math.ceil(config.multiview.tile_count / columns))
    width = max(2, config.multiview.layout.canvas_width // columns)
    height = max(2, config.multiview.layout.canvas_height // rows)
    profiles = list(onvif.get("profiles") or [])
    if not camera.ip.multiview_input.profile_token:
        main_path = urlparse(camera.ip.source_url).path.rstrip("/").lower()
        profiles = [
            profile
            for profile in profiles
            if urlparse(str(profile.get("stream_uri") or "")).path.rstrip("/").lower() != main_path
        ]
    recommended = select_onvif_profile(
        profiles,
        target_width=width,
        target_height=height,
        target_fps=config.multiview.input_defaults.target_fps,
        profile_token=camera.ip.multiview_input.profile_token,
    )
    safe_profiles = [
        {
            key: profile.get(key)
            for key in ("token", "name", "media_service", "encoding", "width", "height", "fps", "bitrate_kbps")
        }
        for profile in profiles
        if profile.get("stream_uri")
    ]
    mode = camera.ip.multiview_input.mode
    effective_mode = config.multiview.input_defaults.mode if mode == "inherit" else mode
    return {
        "camera_id": camera.id,
        "supported_modes": ["primary", "normalized_primary", "manual"]
        + (["onvif"] if safe_profiles else []),
        "onvif_status": onvif.get("status"),
        "onvif_message": onvif.get("message"),
        "profiles": safe_profiles,
        "recommended_profile_token": recommended.get("token") if recommended else None,
        "effective_mode": effective_mode,
        "target": {"width": width, "height": height, "fps": config.multiview.input_defaults.target_fps},
    }


@app.get("/api/v1/cameras/{camera_id}/ptz/capabilities")
def get_camera_ptz_capabilities(
    request: Request,
    camera_id: str,
    force: bool = False,
    identity: AuthIdentity = Depends(require_ptz_identity),
) -> dict[str, Any]:
    context = get_context(request)
    camera = _authorized_ptz_camera(context, camera_id, identity)
    try:
        return context.ptz_controller.capabilities(camera, force=force)
    except PtzControlError as exc:
        _raise_ptz_http_error(exc)


@app.post("/api/v1/cameras/{camera_id}/ptz/move")
def post_camera_ptz_move(
    request: Request,
    camera_id: str,
    payload: dict[str, Any],
    identity: AuthIdentity = Depends(require_ptz_identity),
) -> dict[str, Any]:
    context = get_context(request)
    camera = _authorized_ptz_camera(context, camera_id, identity)
    try:
        return context.ptz_controller.move(
            camera,
            identity,
            operation_id=str(payload.get("operation_id") or ""),
            pan=payload.get("pan", 0),
            tilt=payload.get("tilt", 0),
            zoom=payload.get("zoom", 0),
        )
    except PtzControlError as exc:
        _raise_ptz_http_error(exc)


@app.post("/api/v1/cameras/{camera_id}/ptz/position")
def post_camera_ptz_position(
    request: Request,
    camera_id: str,
    payload: dict[str, Any],
    identity: AuthIdentity = Depends(require_ptz_identity),
) -> dict[str, Any]:
    context = get_context(request)
    camera = _authorized_ptz_camera(context, camera_id, identity)
    try:
        return context.ptz_controller.position(
            camera,
            identity,
            zoom=payload.get("zoom"),
            operation_id=str(payload.get("operation_id") or ""),
        )
    except PtzControlError as exc:
        _raise_ptz_http_error(exc)


@app.post("/api/v1/cameras/{camera_id}/ptz/stop")
def post_camera_ptz_stop(
    request: Request,
    camera_id: str,
    payload: dict[str, Any] | None = None,
    identity: AuthIdentity = Depends(require_ptz_identity),
) -> dict[str, Any]:
    context = get_context(request)
    camera = _authorized_ptz_camera(context, camera_id, identity)
    body = payload or {}
    try:
        return context.ptz_controller.stop(
            camera,
            identity,
            operation_id=str(body.get("operation_id") or "") or None,
            pan_tilt=bool(body.get("pan_tilt", True)),
            zoom=bool(body.get("zoom", True)),
        )
    except PtzControlError as exc:
        _raise_ptz_http_error(exc)


@app.patch("/api/v1/cameras/{camera_id}", dependencies=[Depends(require_admin)])
def patch_camera(request: Request, camera_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    target = _find_camera(old_cfg, camera_id)

    merged = _deep_merge_dict(target.model_dump(), payload)
    merged["id"] = target.id
    merged["path"] = merged.get("path") or target.path
    camera = _validate_camera_payload(merged)

    cameras = [cam.model_dump() for cam in old_cfg.cameras if cam.id.lower() != target.id.lower()]
    cameras.append(camera.model_dump())
    new_cfg = _replace_camera_list(context, cameras)
    _restart_affected(context, old_cfg, new_cfg)
    return {"ok": True, "camera": camera.model_dump()}


@app.delete("/api/v1/cameras/{camera_id}", dependencies=[Depends(require_admin)])
def delete_camera(request: Request, camera_id: str) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    _ = _find_camera(old_cfg, camera_id)
    cameras = [cam.model_dump() for cam in old_cfg.cameras if cam.id.lower() != camera_id.lower()]
    new_cfg = _replace_camera_list(context, cameras)
    _restart_affected(context, old_cfg, new_cfg)
    return {"ok": True}


@app.post("/api/v1/cameras/{camera_id}/enable", dependencies=[Depends(require_admin)])
def post_camera_enable(request: Request, camera_id: str) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    target = _find_camera(old_cfg, camera_id)
    cameras: list[dict[str, Any]] = []
    for cam in old_cfg.cameras:
        item = cam.model_dump()
        if cam.id.lower() == target.id.lower():
            item["enabled"] = True
        cameras.append(item)
    new_cfg = _replace_camera_list(context, cameras)
    _restart_affected(context, old_cfg, new_cfg)
    return {"ok": True, "camera_id": target.id, "enabled": True}


@app.post("/api/v1/cameras/{camera_id}/disable", dependencies=[Depends(require_admin)])
def post_camera_disable(request: Request, camera_id: str) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    target = _find_camera(old_cfg, camera_id)
    cameras: list[dict[str, Any]] = []
    for cam in old_cfg.cameras:
        item = cam.model_dump()
        if cam.id.lower() == target.id.lower():
            item["enabled"] = False
        cameras.append(item)
    new_cfg = _replace_camera_list(context, cameras)
    _restart_affected(context, old_cfg, new_cfg)
    return {"ok": True, "camera_id": target.id, "enabled": False}


@app.post("/api/v1/cameras/{camera_id}/exclude", dependencies=[Depends(require_admin)])
def post_camera_exclude(request: Request, camera_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    target = _find_camera(config, camera_id)
    reason = None
    if payload and isinstance(payload.get("reason"), str):
        reason = payload["reason"].strip() or None
    ok = context.supervisor.exclude_camera_from_multiview(target.id, reason)
    if not ok:
        context.supervisor.reconcile(config)
        ok = context.supervisor.exclude_camera_from_multiview(target.id, reason)
    return {"ok": ok, "camera_id": target.id, "excluded": ok}


@app.post("/api/v1/cameras/{camera_id}/restore", dependencies=[Depends(require_admin)])
def post_camera_restore(request: Request, camera_id: str) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    target = _find_camera(config, camera_id)
    ok = context.supervisor.restore_camera_to_multiview(target.id)
    if not ok:
        context.supervisor.reconcile(config)
        ok = context.supervisor.restore_camera_to_multiview(target.id)
    return {"ok": ok, "camera_id": target.id, "excluded": False}


@app.get("/api/v1/cameras/{camera_id}/addresses", dependencies=[Depends(require_viewer)])
def get_camera_addresses(request: Request, camera_id: str) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    camera = _find_camera(config, camera_id)
    return {"id": camera.id, **_stream_addresses(config, camera.path)}


@app.get("/api/v1/cameras/{camera_id}/snapshot", dependencies=[Depends(require_viewer)])
def get_camera_snapshot(request: Request, camera_id: str) -> Response:
    context = get_context(request)
    config = context.store.get_effective()
    camera = _find_camera(config, camera_id)
    rtsp_url = _join_url(config.mediamtx.rtsp_base_url, camera.path)
    ffmpeg_bin = (
        camera.uvc.env.get("FFMPEG_BIN", "ffmpeg")
        if camera.type == "uvc" and camera.uvc and camera.uvc.env
        else config.multiview.ffmpeg_bin
    )
    try:
        image = capture_snapshot_jpeg(
            ffmpeg_bin=ffmpeg_bin,
            rtsp_url=rtsp_url,
            timeout_sec=config.snapshot.timeout_sec,
        )
    except SnapshotError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return Response(content=image, media_type="image/jpeg")


@app.get("/api/v1/multiview", dependencies=[Depends(require_admin)])
def get_multiview(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    processes = _sanitized_process_status(context.supervisor.process_status())
    data = config.multiview.model_dump()
    data["views"] = _multiview_views(config, processes)
    data["process"] = next(
        (item for item in processes.get("items", []) if item.get("id") == "multiview"),
        None,
    )
    return data


def _sanitize_multiview_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe_views: list[dict[str, Any]] = []
    raw_views = payload.get("views")
    if not isinstance(raw_views, list):
        raw_views = []
    for raw_view in raw_views:
        if not isinstance(raw_view, dict):
            continue
        safe_inputs: list[dict[str, Any]] = []
        raw_inputs = raw_view.get("inputs")
        if not isinstance(raw_inputs, list):
            raw_inputs = []
        for raw_input in raw_inputs:
            if not isinstance(raw_input, dict):
                continue
            safe_inputs.append(
                {
                    "path": str(raw_input.get("path") or "")[:256],
                    "state": str(raw_input.get("state") or "starting")[:32],
                    "last_progress_at": raw_input.get("last_progress_at"),
                    "failures": int(raw_input.get("failures") or 0),
                    "isolated": bool(raw_input.get("isolated")),
                    "reason": _redact_text_secrets(str(raw_input.get("reason")))[:500]
                    if raw_input.get("reason")
                    else None,
                    "buffer_delay_sec": raw_input.get("buffer_delay_sec"),
                    "buffered_frames": int(raw_input.get("buffered_frames") or 0),
                    "target_at": raw_input.get("target_at"),
                    "selected_frame_at": raw_input.get("selected_frame_at"),
                    "frames_received": int(raw_input.get("frames_received") or 0),
                }
            )
        safe_views.append(
            {
                "id": str(raw_view.get("id") or "")[:128],
                "state": str(raw_view.get("state") or "starting")[:32],
                "restart_count": int(raw_view.get("restart_count") or 0),
                "decode_error_count": int(raw_view.get("decode_error_count") or 0),
                "inputs": safe_inputs,
            }
        )
    return {"updated_at": payload.get("updated_at"), "views": safe_views}


def _merge_multiview_buffer_status(payload: dict[str, Any], status_path: Path) -> None:
    allowed = {"starting", "buffering", "healthy", "holding", "no_stream", "reconnecting"}
    statuses: dict[str, dict[str, Any]] = {}
    latest_updated_at: float | None = None
    for path in status_path.parent.glob("multiview_buffer_*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(item, dict):
            continue
        try:
            if time.time() - float(item.get("updated_at") or 0) > 10:
                continue
        except (TypeError, ValueError):
            continue
        if item.get("buffer_path"):
            statuses[str(item["buffer_path"])] = item
            try:
                item_updated_at = float(item.get("updated_at") or 0)
                latest_updated_at = max(latest_updated_at or item_updated_at, item_updated_at)
            except (TypeError, ValueError):
                pass
    for view in payload.get("views", []):
        for item in view.get("inputs", []):
            status = statuses.get(str(item.get("path") or ""))
            if not status:
                continue
            state = str(status.get("state") or "starting")
            item["path"] = str(status.get("source_path") or item["path"])[:256]
            item["state"] = state if state in allowed else "degraded"
            item["reason"] = _redact_text_secrets(str(status.get("reason")))[:500] if status.get("reason") else None
            item["buffer_delay_sec"] = status.get("buffer_delay_sec")
            item["buffered_frames"] = int(status.get("buffered_frames") or 0)
            item["target_at"] = status.get("target_at")
            item["selected_frame_at"] = status.get("selected_frame_at")
        input_states = [str(item.get("state") or "starting") for item in view.get("inputs", [])]
        if input_states and all(state == "healthy" for state in input_states):
            view["state"] = "healthy"
        elif input_states and all(state in {"starting", "buffering"} for state in input_states):
            view["state"] = "starting"
        elif input_states:
            view["state"] = "degraded"
    if latest_updated_at is not None:
        payload["updated_at"] = latest_updated_at


@app.get("/api/v1/multiview/status", dependencies=[Depends(require_viewer)])
def get_multiview_status(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    status_path = Path(config.multiview.status_file)
    if not status_path.is_absolute():
        status_path = Path(context.workspace_dir) / status_path
    try:
        if status_path.stat().st_size > 2_000_000:
            raise ValueError("status payload is too large")
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("status payload is not an object")
        payload = _sanitize_multiview_status_payload(payload)
        for camera in config.cameras:
            if camera.type != "ip" or not camera.ip:
                continue
            input_status_path = status_path.with_name(f"multiview_input_{camera.id}.json")
            try:
                input_status = json.loads(input_status_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            worker_state = str(input_status.get("state") or "")
            if worker_state not in {"fallback", "degraded"}:
                continue
            for view in payload.get("views", []):
                for item in view.get("inputs", []):
                    path = str(item.get("path") or "")
                    if path == f"__mv_input/{camera.path}":
                        item["state"] = worker_state
                        item["reason"] = (
                            _redact_text_secrets(str(input_status.get("reason")))[:500]
                            if input_status.get("reason")
                            else None
                        )
        # Raw synchronized mode writes input selection and final canvas health
        # atomically. Merging legacy __mv_buffer worker files here would
        # overwrite the real compositor state and recreate false health.
        return payload
    except (OSError, ValueError, json.JSONDecodeError):
        views = _multiview_views(config, _sanitized_process_status(context.supervisor.process_status()))
        return {
            "updated_at": None,
            "views": [
                {
                    "id": view["id"],
                    "state": "starting",
                    "restart_count": 0,
                    "decode_error_count": 0,
                    "inputs": [
                        {"path": source, "state": "starting", "failures": 0, "isolated": False, "reason": None}
                        for source in view.get("sources", [])
                    ],
                }
                for view in views
            ],
        }


@app.patch("/api/v1/multiview", dependencies=[Depends(require_admin)])
def patch_multiview(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    new_cfg = context.store.patch_runtime({"multiview": payload})
    _restart_affected(context, old_cfg, new_cfg)
    return {"ok": True, "multiview": new_cfg.multiview.model_dump()}


@app.post("/api/v1/multiview/enable", dependencies=[Depends(require_admin)])
def post_multiview_enable(request: Request) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    patch = {"multiview": old_cfg.multiview.model_dump()}
    patch["multiview"]["enabled"] = True
    new_cfg = context.store.patch_runtime(patch)
    _restart_affected(context, old_cfg, new_cfg)
    return {"ok": True, "enabled": True}


@app.post("/api/v1/multiview/disable", dependencies=[Depends(require_admin)])
def post_multiview_disable(request: Request) -> dict[str, Any]:
    context = get_context(request)
    old_cfg = context.store.get_effective()
    patch = {"multiview": old_cfg.multiview.model_dump()}
    patch["multiview"]["enabled"] = False
    new_cfg = context.store.patch_runtime(patch)
    _restart_affected(context, old_cfg, new_cfg)
    return {"ok": True, "enabled": False}


@app.get("/api/v1/multiview/views", dependencies=[Depends(require_viewer)])
def get_multiview_views(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    processes = _sanitized_process_status(context.supervisor.process_status())
    return {"items": _multiview_views(config, processes)}


@app.get("/api/v1/multiview/views/{view_id}/addresses", dependencies=[Depends(require_viewer)])
def get_multiview_view_addresses(request: Request, view_id: str) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    processes = _sanitized_process_status(context.supervisor.process_status())
    views = _multiview_views(config, processes)
    normalized = view_id.strip().strip("/")
    for view in views:
        if view["id"].lower() == normalized.lower():
            return {"id": view["id"], "rtsp_url": view["rtsp_url"], "webrtc_url": view["webrtc_url"]}
    raise HTTPException(status_code=404, detail=f"view not found: {view_id}")


@app.get("/api/v1/multiview/views/{view_id}/snapshot", dependencies=[Depends(require_viewer)])
def get_multiview_view_snapshot(request: Request, view_id: str) -> Response:
    context = get_context(request)
    config = context.store.get_effective()
    processes = _sanitized_process_status(context.supervisor.process_status())
    views = _multiview_views(config, processes)
    normalized = view_id.strip().strip("/")
    for view in views:
        if view["id"].lower() != normalized.lower():
            continue
        try:
            image = capture_snapshot_jpeg(
                ffmpeg_bin=config.multiview.ffmpeg_bin,
                rtsp_url=view["rtsp_url"],
                timeout_sec=config.snapshot.timeout_sec,
            )
        except SnapshotError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return Response(content=image, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail=f"view not found: {view_id}")


@app.get("/api/v1/streams/{stream_id}/addresses", dependencies=[Depends(require_viewer)])
def get_stream_addresses(request: Request, stream_id: str) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    clean = stream_id.strip().strip("/")
    if not clean:
        raise HTTPException(status_code=400, detail="stream_id must not be empty")
    return {"id": clean, **_stream_addresses(config, clean)}


@app.get("/api/v1/recordings/streams", dependencies=[Depends(require_viewer)])
def get_recording_streams(request: Request) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    root = _resolve_record_root_path(config, context.workspace_dir)
    files = _all_recording_files(config, context.workspace_dir)
    streams = sorted({item["stream_id"] for item in files if item["stream_id"]})
    return {
        "record_root": str(root),
        "count": len(streams),
        "items": streams,
    }


@app.get("/api/v1/recordings", dependencies=[Depends(require_viewer)])
def get_recordings(
    request: Request,
    stream_id: str | None = None,
    status: str = "all",
    recorded_from: float | None = None,
    recorded_to: float | None = None,
    sort_by: str = "recorded",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    if limit < 1 or limit > 5000:
        raise HTTPException(status_code=400, detail="limit must be in range 1..5000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    if status not in {"all", "stable", "recording"}:
        raise HTTPException(status_code=400, detail="status must be one of: all, stable, recording")
    if recorded_from is not None and recorded_to is not None and recorded_from > recorded_to:
        raise HTTPException(status_code=400, detail="recorded_from must be <= recorded_to")
    if sort_by not in {"stream", "recorded", "size"}:
        raise HTTPException(status_code=400, detail="sort_by must be one of: stream, recorded, size")
    if sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="sort_dir must be one of: asc, desc")

    root = _resolve_record_root_path(config, context.workspace_dir)
    # Also clean opportunistically so stale files are removed when this page is used,
    # even if the periodic maintenance thread was delayed or not started.
    context.cleanup_recording_playback_cache(config)
    files = _all_recording_files(config, context.workspace_dir)
    if stream_id:
        normalized = stream_id.strip().strip("/").lower()
        files = [item for item in files if str(item["stream_id"]).lower() == normalized]
    if status == "stable":
        files = [item for item in files if bool(item["is_stable"])]
    elif status == "recording":
        files = [item for item in files if not bool(item["is_stable"])]
    if recorded_from is not None:
        files = [item for item in files if float(item["modified_at"]) >= recorded_from]
    if recorded_to is not None:
        files = [item for item in files if float(item["modified_at"]) <= recorded_to]

    reverse_sort = sort_dir == "desc"
    if sort_by == "stream":
        files.sort(
            key=lambda item: _recording_natural_sort_key(str(item["stream_id"])),
            reverse=reverse_sort,
        )
    elif sort_by == "size":
        files.sort(key=lambda item: int(item["size_bytes"]), reverse=reverse_sort)
    else:
        files.sort(key=lambda item: float(item["modified_at"]), reverse=reverse_sort)

    total = len(files)
    page = files[offset : offset + limit]
    return {
        "record_root": str(root),
        "stream_id": stream_id or "",
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": page,
    }


@app.post("/api/v1/recordings/files/{file_id}/prepare", dependencies=[Depends(require_viewer)])
def post_prepare_recording_file(request: Request, file_id: str) -> dict[str, Any]:
    context = get_context(request)
    config = context.store.get_effective()
    root, relative_path, file_path = _resolve_recording_file(config, context.workspace_dir, file_id)
    playable_path = _prepare_recording_playback_file(
        context,
        config,
        root=root,
        relative_path=relative_path,
        file_path=file_path,
    )
    return {
        "ok": True,
        "file_id": file_id,
        "playable_path": f"/api/v1/recordings/files/{file_id}/playable",
        "cache_file": str(playable_path),
    }


@app.get("/api/v1/recordings/files/{file_id}/thumbnail", dependencies=[Depends(require_viewer)])
def get_recording_thumbnail_file(request: Request, file_id: str) -> Response:
    context = get_context(request)
    config = context.store.get_effective()
    root, relative_path, file_path = _resolve_recording_file(config, context.workspace_dir, file_id)
    thumbnail_path = _prepare_recording_thumbnail_file(
        context,
        config,
        root=root,
        relative_path=relative_path,
        file_path=file_path,
    )
    return FileResponse(path=thumbnail_path, media_type="image/jpeg")


@app.get("/api/v1/recordings/files/{file_id}/playable", dependencies=[Depends(require_viewer)])
def get_recording_playable_file(request: Request, file_id: str) -> Response:
    context = get_context(request)
    config = context.store.get_effective()
    root, relative_path, file_path = _resolve_recording_file(config, context.workspace_dir, file_id)
    playable_path = _prepare_recording_playback_file(
        context,
        config,
        root=root,
        relative_path=relative_path,
        file_path=file_path,
    )
    return FileResponse(path=playable_path, media_type="video/mp4")


@app.get("/api/v1/recordings/files/{file_id}", dependencies=[Depends(require_admin)])
def get_recording_file(request: Request, file_id: str) -> Response:
    context = get_context(request)
    config = context.store.get_effective()
    root, relative_path, file_path = _resolve_recording_file(config, context.workspace_dir, file_id)
    return FileResponse(
        path=file_path,
        filename=_build_recording_download_filename(relative_path, file_path),
        media_type="video/mp4",
    )


@app.exception_handler(Exception)
def _handle_exception(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    if isinstance(exc, ValidationError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(status_code=500, content={"detail": str(exc)})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE, help="Path to .env file")
    parser.add_argument("--runtime-file", default=DEFAULT_RUNTIME_FILE, help="Path to runtime JSON")
    parser.add_argument("--no-env", action="store_true", help="Ignore .env values")
    parser.add_argument("--host", help="Override API host")
    parser.add_argument("--port", type=int, help="Override API port")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload mode")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    context = AppContext(env_file=args.env_file, runtime_file=args.runtime_file, no_env=args.no_env)
    set_app_context(context)
    effective = context.store.get_effective()
    host = args.host or effective.api.host
    port = args.port or effective.api.port
    context.listener = {"host": host, "port": port, "source": "command line" if args.port or args.host else "saved configuration"}
    _configure_cors(env_file=args.env_file, api_host=host)

    import uvicorn

    uvicorn.run(app, host=host, port=port, reload=args.reload, log_config=None,
                proxy_headers=True, forwarded_allow_ips="127.0.0.1,::1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
