from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from flinteye_app.orchestrator_auth import AuthIdentity
from flinteye_app.orchestrator_ip_camera_probe import (
    _pick,
    _safe_error,
    _serialized,
    find_onvif_camera,
)
from flinteye_app.orchestrator_models import CameraConfig


PTZ_CACHE_TTL_SEC = 300.0
PTZ_LEASE_SEC = 2.0
PTZ_RATE_LIMIT_PER_SEC = 10
PTZ_MOVE_TIMEOUT = "PT1S"


class PtzControlError(RuntimeError):
    status_code = 502


class PtzConfigurationError(PtzControlError):
    status_code = 409


class PtzUnsupportedError(PtzControlError):
    status_code = 422


class PtzBusyError(PtzControlError):
    status_code = 409


class PtzRateLimitError(PtzControlError):
    status_code = 429


@dataclass
class PtzCacheEntry:
    signature: str
    client: Any
    service: Any
    profiles: list[dict[str, Any]]
    ptz: dict[str, Any]
    connection: dict[str, Any]
    expires_at: float


@dataclass
class PtzLease:
    username: str
    role: str
    operation_id: str
    expires_at: float


@dataclass
class CameraRateWindow:
    calls: deque[float] = field(default_factory=deque)


class OnvifPtzController:
    def __init__(
        self,
        *,
        cache_ttl_sec: float = PTZ_CACHE_TTL_SEC,
        clock: Callable[[], float] = time.monotonic,
        inspector: Callable[[CameraConfig], PtzCacheEntry] | None = None,
    ) -> None:
        self.cache_ttl_sec = cache_ttl_sec
        self.clock = clock
        self._inspector = inspector
        self._lock = threading.RLock()
        self._cache: dict[str, PtzCacheEntry] = {}
        self._leases: dict[str, PtzLease] = {}
        self._rates: dict[str, CameraRateWindow] = {}

    def shutdown(self) -> None:
        with self._lock:
            camera_ids = list(self._cache)
        for camera_id in camera_ids:
            self.invalidate(camera_id)

    def invalidate(self, camera_id: str) -> None:
        with self._lock:
            entry = self._cache.pop(camera_id.lower(), None)
            self._leases.pop(camera_id.lower(), None)
            self._rates.pop(camera_id.lower(), None)
        if entry is not None:
            try:
                selected = self._select_profile(entry, None, None)
                self._stop_entry(entry, selected, pan_tilt=True, zoom=True)
            except Exception:
                pass

    def invalidate_by_source(self, source_url: str) -> None:
        with self._lock:
            matches = [
                camera_id
                for camera_id, entry in self._cache.items()
                if json.loads(entry.signature).get("source_url") == source_url
            ]
        for camera_id in matches:
            self.invalidate(camera_id)

    def capabilities(self, camera: CameraConfig, *, force: bool = False) -> dict[str, Any]:
        entry = self._entry(camera, force=force)
        selected = self._select_profile(entry, camera.ip.ptz.profile_token if camera.ip else None, camera)
        selected_ptz = selected.get("ptz") if selected else None
        current: dict[str, float | None] = {"pan": None, "tilt": None, "zoom": None}
        if selected and selected_ptz and selected_ptz.get("supported"):
            current = self._current_position(entry, selected, tolerate_errors=True)
        return {
            "camera_id": camera.id,
            "enabled": bool(camera.ip and camera.ip.ptz.enabled),
            "access": camera.ip.ptz.access if camera.ip else "admin",
            "supported": bool(entry.ptz.get("supported")),
            "service_available": bool(entry.ptz.get("service_available")),
            "message": entry.ptz.get("message"),
            "pan_tilt": bool(selected_ptz and selected_ptz.get("pan_tilt")),
            "zoom": bool(selected_ptz and selected_ptz.get("zoom")),
            "modes": (selected_ptz or {}).get("modes") or {
                "pan_tilt": {"continuous": False, "relative": False, "absolute": False},
                "zoom": {"continuous": False, "relative": False, "absolute": False},
            },
            "spaces": (selected_ptz or {}).get("spaces") or {},
            "selected_profile_token": selected.get("token") if selected else None,
            "selected_profile_name": selected.get("name") if selected else None,
            "profiles": [
                {
                    "token": profile.get("token"),
                    "name": profile.get("name"),
                    "media_service": profile.get("media_service"),
                    "stream_uri": profile.get("stream_uri"),
                    "ptz": profile.get("ptz"),
                }
                for profile in entry.profiles
                if (profile.get("ptz") or {}).get("supported")
            ],
            "current": current,
            "cache_ttl_sec": self.cache_ttl_sec,
        }

    def move(
        self,
        camera: CameraConfig,
        identity: AuthIdentity,
        *,
        operation_id: str,
        pan: float = 0.0,
        tilt: float = 0.0,
        zoom: float = 0.0,
    ) -> dict[str, Any]:
        if not operation_id.strip():
            raise PtzConfigurationError("operation_id is required")
        pan = self._normalized_signed(pan, "pan")
        tilt = self._normalized_signed(tilt, "tilt")
        zoom = self._normalized_signed(zoom, "zoom")
        if pan == 0 and tilt == 0 and zoom == 0:
            raise PtzConfigurationError("At least one PTZ direction must be non-zero")

        entry = self._entry(camera)
        selected = self._select_profile(entry, camera.ip.ptz.profile_token if camera.ip else None, camera)
        support = selected.get("ptz") if selected else None
        if not selected or not support or not support.get("supported"):
            raise PtzUnsupportedError("No PTZ-capable ONVIF media profile is available")
        if (pan or tilt) and not support.get("pan_tilt"):
            raise PtzUnsupportedError("This ONVIF profile does not support Pan/Tilt")
        if zoom and not support.get("zoom"):
            raise PtzUnsupportedError("This ONVIF profile does not support Zoom")

        try:
            self._acquire_lease(camera.id, identity, operation_id, entry, selected)
        except PtzControlError:
            raise
        except Exception as exc:
            raise PtzControlError(_safe_error(exc, camera.ip.source_url or "")) from exc
        self._check_rate(camera.id)
        try:
            self._move_supported(entry, selected, camera, pan=pan, tilt=tilt, zoom=zoom)
        except PtzControlError:
            with self._lock:
                lease = self._leases.get(camera.id.lower())
                if lease and lease.operation_id == operation_id:
                    self._leases.pop(camera.id.lower(), None)
            raise
        except Exception as exc:
            with self._lock:
                lease = self._leases.get(camera.id.lower())
                if lease and lease.operation_id == operation_id:
                    self._leases.pop(camera.id.lower(), None)
            raise PtzControlError(_safe_error(exc, camera.ip.source_url or "")) from exc
        return {"ok": True, "camera_id": camera.id, "operation_id": operation_id}

    def position(
        self,
        camera: CameraConfig,
        identity: AuthIdentity,
        *,
        zoom: float,
        operation_id: str,
    ) -> dict[str, Any]:
        if not operation_id.strip():
            raise PtzConfigurationError("operation_id is required")
        zoom = self._normalized_unit(zoom, "zoom")
        entry = self._entry(camera)
        selected = self._select_profile(entry, camera.ip.ptz.profile_token if camera.ip else None, camera)
        support = selected.get("ptz") if selected else None
        if not selected or not support or not (support.get("modes") or {}).get("zoom", {}).get("absolute"):
            raise PtzUnsupportedError("Absolute Zoom is not supported by this ONVIF profile")
        try:
            self._acquire_lease(camera.id, identity, operation_id, entry, selected)
        except PtzControlError:
            raise
        except Exception as exc:
            raise PtzControlError(_safe_error(exc, camera.ip.source_url or "")) from exc
        self._check_rate(camera.id)
        zoom_range = self._space_axis_range(support, "absolute_zoom", "x")
        target = self._from_unit(zoom, zoom_range)
        try:
            entry.service.AbsoluteMove(
                ProfileToken=selected.get("token"),
                Position={"Zoom": {"x": target}},
            )
        except Exception as exc:
            raise PtzControlError(_safe_error(exc, camera.ip.source_url or "")) from exc
        return {"ok": True, "camera_id": camera.id, "operation_id": operation_id, "zoom": zoom}

    def stop(
        self,
        camera: CameraConfig,
        identity: AuthIdentity,
        *,
        operation_id: str | None = None,
        pan_tilt: bool = True,
        zoom: bool = True,
    ) -> dict[str, Any]:
        key = camera.id.lower()
        with self._lock:
            lease = self._leases.get(key)
            if lease and lease.expires_at > self.clock():
                same_operation = bool(operation_id and operation_id == lease.operation_id)
                same_user = lease.username == identity.username and lease.role == identity.role
                if not same_operation and not same_user and identity.role != "admin":
                    raise PtzBusyError("Camera PTZ is controlled by another user")
            self._leases.pop(key, None)
            entry = self._cache.get(key)
        if entry is None:
            entry = self._entry(camera)
        selected = self._select_profile(entry, camera.ip.ptz.profile_token if camera.ip else None, camera)
        if selected:
            try:
                self._stop_entry(entry, selected, pan_tilt=pan_tilt, zoom=zoom)
            except Exception as exc:
                raise PtzControlError(_safe_error(exc, camera.ip.source_url or "")) from exc
        return {"ok": True, "camera_id": camera.id, "stopped": {"pan_tilt": pan_tilt, "zoom": zoom}}

    def _entry(self, camera: CameraConfig, *, force: bool = False) -> PtzCacheEntry:
        self._validate_camera(camera)
        signature = self._signature(camera)
        key = camera.id.lower()
        now = self.clock()
        with self._lock:
            cached = self._cache.get(key)
            if not force and cached and cached.signature == signature and cached.expires_at > now:
                return cached
        entry = self._inspector(camera) if self._inspector else self._inspect_camera(camera)
        entry.signature = signature
        entry.expires_at = now + self.cache_ttl_sec
        with self._lock:
            self._cache[key] = entry
        return entry

    def _inspect_camera(self, camera: CameraConfig) -> PtzCacheEntry:
        assert camera.ip and camera.ip.source_url
        result, client, connection = find_onvif_camera(
            camera.ip.source_url, mode=camera.ip.onvif_mode, address=camera.ip.onvif_address,
            username=camera.ip.onvif_username, password=camera.ip.onvif_password,
            profile_token=camera.ip.ptz.profile_token,
        )
        if result["status"] == "unavailable":
            raise PtzConfigurationError(result["message"])
        if client is None:
            raise PtzControlError(result["message"])
        ptz = result["ptz"]
        try:
            service = client.ptz() if ptz["service_available"] else None
        except Exception as exc:
            raise PtzControlError(_safe_error(exc, camera.ip.source_url)) from exc
        return PtzCacheEntry("", client, service, result["profiles"], ptz, connection, 0.0)

    @staticmethod
    def _validate_camera(camera: CameraConfig) -> None:
        if camera.type != "ip" or camera.ip is None or not camera.ip.source_url:
            raise PtzConfigurationError("PTZ is available only for configured IP cameras")
        if camera.ip.onvif_mode == "disabled":
            raise PtzConfigurationError("ONVIF is disabled for this camera")

    @staticmethod
    def _signature(camera: CameraConfig) -> str:
        assert camera.ip
        return json.dumps(
            {
                "source_url": camera.ip.source_url,
                "onvif_mode": camera.ip.onvif_mode,
                "onvif_address": camera.ip.onvif_address,
                "onvif_username": camera.ip.onvif_username,
                "onvif_password": camera.ip.onvif_password,
                "profile_token": camera.ip.ptz.profile_token,
            },
            sort_keys=True,
        )

    def _select_profile(
        self,
        entry: PtzCacheEntry,
        configured_token: str | None,
        camera: CameraConfig | None,
    ) -> dict[str, Any] | None:
        supported = [profile for profile in entry.profiles if (profile.get("ptz") or {}).get("supported")]
        if not supported:
            return None
        if configured_token:
            selected = next((item for item in supported if str(item.get("token")) == configured_token), None)
            if selected is None:
                raise PtzConfigurationError("Configured ONVIF PTZ profile is not available")
            return selected
        if camera and camera.ip and camera.ip.source_url:
            return max(supported, key=lambda item: self._stream_match_score(camera.ip.source_url or "", item.get("stream_uri")))
        return supported[0]

    @staticmethod
    def _stream_match_score(source_url: str, stream_uri: Any) -> int:
        if not stream_uri:
            return 0
        try:
            source = urlparse(source_url)
            candidate = urlparse(str(stream_uri))
        except ValueError:
            return 0
        score = 0
        if source.path.rstrip("/") == candidate.path.rstrip("/"):
            score += 20
        if source.query == candidate.query:
            score += 5
        if source.hostname and candidate.hostname and source.hostname.lower() == candidate.hostname.lower():
            score += 3
        if (source.port or 554) == (candidate.port or 554):
            score += 1
        return score

    def _acquire_lease(
        self,
        camera_id: str,
        identity: AuthIdentity,
        operation_id: str,
        entry: PtzCacheEntry,
        selected: dict[str, Any],
    ) -> None:
        key = camera_id.lower()
        now = self.clock()
        preempt = False
        with self._lock:
            lease = self._leases.get(key)
            if lease and lease.expires_at > now:
                same_operation = lease.operation_id == operation_id and lease.username == identity.username
                if not same_operation:
                    if identity.role == "admin" and lease.role == "viewer":
                        preempt = True
                    else:
                        raise PtzBusyError("Camera PTZ is currently controlled by another user")
            self._leases[key] = PtzLease(
                username=identity.username,
                role=identity.role,
                operation_id=operation_id,
                expires_at=now + PTZ_LEASE_SEC,
            )
        if preempt:
            self._stop_entry(entry, selected, pan_tilt=True, zoom=True)

    def _check_rate(self, camera_id: str) -> None:
        key = camera_id.lower()
        now = self.clock()
        with self._lock:
            window = self._rates.setdefault(key, CameraRateWindow())
            while window.calls and now - window.calls[0] >= 1.0:
                window.calls.popleft()
            if len(window.calls) >= PTZ_RATE_LIMIT_PER_SEC:
                raise PtzRateLimitError("PTZ command rate exceeded 10 commands per second")
            window.calls.append(now)

    def _move_supported(
        self,
        entry: PtzCacheEntry,
        selected: dict[str, Any],
        camera: CameraConfig,
        *,
        pan: float,
        tilt: float,
        zoom: float,
    ) -> None:
        assert camera.ip
        support = selected["ptz"]
        modes = support.get("modes") or {}
        token = selected.get("token")
        pt_modes = modes.get("pan_tilt") or {}
        zoom_modes = modes.get("zoom") or {}

        continuous_velocity: dict[str, Any] = {}
        if (pan or tilt) and pt_modes.get("continuous"):
            x_range = self._space_axis_range(support, "continuous_pan_tilt", "x")
            y_range = self._space_axis_range(support, "continuous_pan_tilt", "y")
            continuous_velocity["PanTilt"] = {
                "x": self._signed_value(pan * camera.ip.ptz.pan_tilt_speed, x_range),
                "y": self._signed_value(tilt * camera.ip.ptz.pan_tilt_speed, y_range),
            }
        if zoom and zoom_modes.get("continuous"):
            z_range = self._space_axis_range(support, "continuous_zoom", "x")
            continuous_velocity["Zoom"] = {
                "x": self._signed_value(zoom * camera.ip.ptz.zoom_speed, z_range)
            }
        if continuous_velocity:
            entry.service.ContinuousMove(
                ProfileToken=token,
                Velocity=continuous_velocity,
                Timeout=PTZ_MOVE_TIMEOUT,
            )

        if (pan or tilt) and not pt_modes.get("continuous"):
            if pt_modes.get("relative"):
                x_range = self._space_axis_range(support, "relative_pan_tilt", "x")
                y_range = self._space_axis_range(support, "relative_pan_tilt", "y")
                entry.service.RelativeMove(
                    ProfileToken=token,
                    Translation={
                        "PanTilt": {
                            "x": self._relative_value(pan, camera.ip.ptz.relative_step, x_range),
                            "y": self._relative_value(tilt, camera.ip.ptz.relative_step, y_range),
                        }
                    },
                )
            elif pt_modes.get("absolute"):
                current = self._current_position(entry, selected)
                x_range = self._space_axis_range(support, "absolute_pan_tilt", "x")
                y_range = self._space_axis_range(support, "absolute_pan_tilt", "y")
                current_pan = current.get("pan") if current.get("pan") is not None else 0.5
                current_tilt = current.get("tilt") if current.get("tilt") is not None else 0.5
                entry.service.AbsoluteMove(
                    ProfileToken=token,
                    Position={
                        "PanTilt": {
                            "x": self._from_unit(
                                self._clamp(current_pan + pan * camera.ip.ptz.relative_step, 0, 1),
                                x_range,
                            ),
                            "y": self._from_unit(
                                self._clamp(current_tilt + tilt * camera.ip.ptz.relative_step, 0, 1),
                                y_range,
                            ),
                        }
                    },
                )
            else:
                raise PtzUnsupportedError("Pan/Tilt has no supported ONVIF move mode")

        if zoom and not zoom_modes.get("continuous"):
            if zoom_modes.get("relative"):
                z_range = self._space_axis_range(support, "relative_zoom", "x")
                entry.service.RelativeMove(
                    ProfileToken=token,
                    Translation={
                        "Zoom": {"x": self._relative_value(zoom, camera.ip.ptz.relative_step, z_range)}
                    },
                )
            elif zoom_modes.get("absolute"):
                current = self._current_position(entry, selected)
                z_range = self._space_axis_range(support, "absolute_zoom", "x")
                current_zoom = current.get("zoom") if current.get("zoom") is not None else 0.0
                target = self._clamp(current_zoom + zoom * camera.ip.ptz.relative_step, 0, 1)
                entry.service.AbsoluteMove(
                    ProfileToken=token,
                    Position={"Zoom": {"x": self._from_unit(target, z_range)}},
                )
            else:
                raise PtzUnsupportedError("Zoom has no supported ONVIF move mode")

    @staticmethod
    def _stop_entry(
        entry: PtzCacheEntry,
        selected: dict[str, Any],
        *,
        pan_tilt: bool,
        zoom: bool,
    ) -> None:
        entry.service.Stop(
            ProfileToken=selected.get("token"),
            PanTilt=bool(pan_tilt),
            Zoom=bool(zoom),
        )

    def _current_position(
        self,
        entry: PtzCacheEntry,
        selected: dict[str, Any],
        *,
        tolerate_errors: bool = False,
    ) -> dict[str, float | None]:
        try:
            status = _serialized(entry.service.GetStatus(ProfileToken=selected.get("token")))
            position = _pick(status, "Position", "position") or {}
            pan_tilt = _pick(position, "PanTilt", "panTilt") or {}
            zoom = _pick(position, "Zoom", "zoom") or {}
            support = selected.get("ptz") or {}
            return {
                "pan": self._to_unit(_pick(pan_tilt, "x", "X"), self._space_axis_range(support, "absolute_pan_tilt", "x")),
                "tilt": self._to_unit(_pick(pan_tilt, "y", "Y"), self._space_axis_range(support, "absolute_pan_tilt", "y")),
                "zoom": self._to_unit(_pick(zoom, "x", "X"), self._space_axis_range(support, "absolute_zoom", "x")),
            }
        except Exception:
            if tolerate_errors:
                return {"pan": None, "tilt": None, "zoom": None}
            raise

    @staticmethod
    def _space_axis_range(support: dict[str, Any], key: str, axis: str) -> dict[str, float]:
        spaces = (support.get("spaces") or {}).get(key) or []
        if spaces and isinstance(spaces[0], dict) and isinstance(spaces[0].get(axis), dict):
            return spaces[0][axis]
        return {"min": -1.0, "max": 1.0}

    @staticmethod
    def _signed_value(value: float, axis_range: dict[str, float]) -> float:
        if value < 0:
            return abs(value) * float(axis_range.get("min", -1.0))
        return value * float(axis_range.get("max", 1.0))

    @staticmethod
    def _relative_value(direction: float, step: float, axis_range: dict[str, float]) -> float:
        span = float(axis_range.get("max", 1.0)) - float(axis_range.get("min", -1.0))
        return direction * step * span

    @staticmethod
    def _from_unit(value: float, axis_range: dict[str, float]) -> float:
        minimum = float(axis_range.get("min", -1.0))
        maximum = float(axis_range.get("max", 1.0))
        return minimum + value * (maximum - minimum)

    @staticmethod
    def _to_unit(value: Any, axis_range: dict[str, float]) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        minimum = float(axis_range.get("min", -1.0))
        maximum = float(axis_range.get("max", 1.0))
        if maximum == minimum:
            return 0.0
        return OnvifPtzController._clamp((numeric - minimum) / (maximum - minimum), 0.0, 1.0)

    @staticmethod
    def _normalized_signed(value: Any, name: str) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise PtzConfigurationError(f"{name} must be numeric") from exc
        if not -1 <= numeric <= 1:
            raise PtzConfigurationError(f"{name} must be in range -1..1")
        return numeric

    @staticmethod
    def _normalized_unit(value: Any, name: str) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise PtzConfigurationError(f"{name} must be numeric") from exc
        if not 0 <= numeric <= 1:
            raise PtzConfigurationError(f"{name} must be in range 0..1")
        return numeric

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
