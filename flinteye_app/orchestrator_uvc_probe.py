from __future__ import annotations

import re
import subprocess
from flinteye_app.process_lifetime import run_background
from flinteye_app.subprocess_utils import background_process_options
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_PROBE_TIMEOUT_SEC = 8.0
DEFAULT_CACHE_TTL_SEC = 10.0


class UvcProbeError(RuntimeError):
    pass


def _run_capture(cmd: list[str], timeout_sec: float) -> subprocess.CompletedProcess[str]:
    return run_background(
        cmd, **background_process_options(),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )


def _infer_driver(platform_name: str | None = None) -> str:
    plat = platform_name or sys.platform
    if plat.startswith("linux"):
        return "v4l2"
    if plat == "darwin":
        return "avfoundation"
    if plat.startswith("win"):
        return "dshow"
    raise UvcProbeError(f"unsupported platform for UVC probe: {plat}")


def _slug(value: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return out or "camera"


def _normalize_capture_fps(value: float | int | None, fallback: int = 30) -> int:
    if value is None:
        return fallback
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    if numeric <= 0:
        return fallback
    return max(1, int(round(numeric)))


def _pick_recommended_mode(
    modes: list[dict[str, Any]],
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default = fallback or {"width": 1280, "height": 720, "fps": 30}
    if not modes:
        return default

    normalized: list[dict[str, int]] = []
    for item in modes:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        fps = _normalize_capture_fps(item.get("fps"), fallback=int(default.get("fps") or 30))
        if width <= 0 or height <= 0:
            continue
        normalized.append({"width": width, "height": height, "fps": fps})

    if not normalized:
        return default

    pool = [item for item in normalized if item["fps"] >= 20]
    if not pool:
        pool = [item for item in normalized if item["fps"] >= 15]
    if not pool:
        pool = normalized

    best = max(pool, key=lambda item: (item["width"] * item["height"], item["fps"], item["width"]))
    return {"width": best["width"], "height": best["height"], "fps": best["fps"]}


def _parse_avfoundation_devices(text: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    in_video = False
    for raw in text.splitlines():
        line = raw.strip()
        if "AVFoundation video devices" in line:
            in_video = True
            continue
        if "AVFoundation audio devices" in line:
            in_video = False
            continue
        if not in_video:
            continue
        m = re.search(r"\[(\d+)\]\s+(.+)$", line)
        if not m:
            continue
        idx = m.group(1).strip()
        name = m.group(2).strip()
        device_id = f"avfoundation-{idx}-{_slug(name)}"
        devices.append(
            {
                "device_id": device_id,
                "driver": "avfoundation",
                "display_name": name,
                "index": idx,
                "ffmpeg_device": f"{name}:none",
                "ffmpeg_device_index": f"{idx}:none",
                "modes": [],
                "recommended": {"width": 1280, "height": 720, "fps": 30},
            }
        )
    return devices


def _parse_avfoundation_modes(text: str) -> list[dict[str, Any]]:
    modes: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int]] = set()
    for raw in text.splitlines():
        m = re.search(
            r"(\d{2,5})x(\d{2,5})@\[\s*(\d+(?:\.\d+)?)",
            raw,
            flags=re.IGNORECASE,
        )
        if not m:
            continue
        width = int(m.group(1))
        height = int(m.group(2))
        fps = _normalize_capture_fps(float(m.group(3)))
        key = (width, height, fps)
        if key in seen:
            continue
        seen.add(key)
        modes.append({"width": width, "height": height, "fps": fps})
    return modes


def _parse_dshow_devices(text: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    in_video = False
    seen: set[str] = set()

    def add_device(name: str) -> None:
        clean_name = name.strip()
        if not clean_name:
            return
        key = clean_name.lower()
        if key in seen:
            return
        seen.add(key)
        device_id = f"dshow-{_slug(clean_name)}"
        ffmpeg_device = f"video={clean_name}"
        devices.append(
            {
                "device_id": device_id,
                "driver": "dshow",
                "display_name": clean_name,
                "index": None,
                "ffmpeg_device": ffmpeg_device,
                "ffmpeg_device_index": ffmpeg_device,
                "modes": [],
                "recommended": {"width": 1280, "height": 720, "fps": 30},
            }
        )

    for raw in text.splitlines():
        line = raw.strip()
        if "DirectShow video devices" in line:
            in_video = True
            continue
        if "DirectShow audio devices" in line:
            in_video = False
            continue
        if not in_video:
            # Newer ffmpeg builds sometimes omit section headers and annotate each
            # device inline as "(video)" / "(audio)" / "(none)".
            inline = re.search(r'"([^"]+)"\s+\((video|audio|none)\)', line, flags=re.IGNORECASE)
            if not inline:
                continue
            kind = inline.group(2).strip().lower()
            if kind != "video":
                continue
            add_device(inline.group(1))
            continue
        if "Alternative name" in line:
            continue
        m = re.search(r'"([^"]+)"', line)
        if not m:
            continue
        add_device(m.group(1))
    return devices


def _empty_probe_warning(driver: str, stderr: str) -> str:
    detail = stderr.strip()
    lowered = detail.lower()

    if "unknown input format" in lowered and driver == "dshow":
        return (
            "ffmpeg does not support DirectShow (dshow) on this machine. "
            "Use a Windows ffmpeg build with dshow support or set UVC_FFMPEG_BIN accordingly."
        )
    if driver == "dshow" and ("could not enumerate video devices" in lowered or "none found" in lowered):
        return (
            "ffmpeg/dshow could not enumerate Windows camera devices. "
            "Check Windows 11 privacy settings and enable camera access for desktop apps."
        )
    if driver == "dshow" and detail:
        return f"ffmpeg/dshow probe did not find devices: {detail}"
    if detail:
        return detail
    return "no UVC video devices detected"


def _parse_v4l2_modes(text: str) -> list[dict[str, Any]]:
    modes: list[dict[str, Any]] = []
    seen: set[tuple[int, int, float | None]] = set()
    for raw in text.splitlines():
        m = re.search(r"(\d{2,5})x(\d{2,5})(?:[^0-9]+(\d+(?:\.\d+)?))?", raw)
        if not m:
            continue
        width = int(m.group(1))
        height = int(m.group(2))
        fps = float(m.group(3)) if m.group(3) else None
        key = (width, height, fps)
        if key in seen:
            continue
        seen.add(key)
        item: dict[str, Any] = {"width": width, "height": height}
        if fps is not None:
            item["fps"] = fps
        modes.append(item)
    return modes


def _probe_v4l2_devices(ffmpeg_bin: str, timeout_sec: float) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for path in sorted(Path("/dev").glob("video*")):
        try:
            result = _run_capture(
                [
                    ffmpeg_bin,
                    "-hide_banner",
                    "-f",
                    "v4l2",
                    "-list_formats",
                    "all",
                    "-i",
                    str(path),
                ],
                timeout_sec=timeout_sec,
            )
            text = (result.stdout or "") + "\n" + (result.stderr or "")
            modes = _parse_v4l2_modes(text)
        except (subprocess.TimeoutExpired, OSError):
            modes = []

        name = path.name
        recommended = _pick_recommended_mode(modes)
        devices.append(
            {
                "device_id": f"v4l2-{_slug(name)}",
                "driver": "v4l2",
                "display_name": name,
                "index": None,
                "ffmpeg_device": str(path),
                "ffmpeg_device_index": str(path),
                "modes": modes,
                "recommended": recommended,
            }
        )
    return devices


def _probe_avfoundation_modes(ffmpeg_bin: str, device_index: str, timeout_sec: float) -> list[dict[str, Any]]:
    result = _run_capture(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "avfoundation",
            "-framerate",
            "999",
            "-video_size",
            "999x999",
            "-i",
            f"{device_index}:none",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        timeout_sec=timeout_sec,
    )
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    return _parse_avfoundation_modes(text)


def probe_uvc_devices(
    *,
    ffmpeg_bin: str = "ffmpeg",
    timeout_sec: float = DEFAULT_PROBE_TIMEOUT_SEC,
    platform_name: str | None = None,
) -> dict[str, Any]:
    driver = _infer_driver(platform_name)
    started_at = time.time()

    if driver == "avfoundation":
        cmd = [ffmpeg_bin, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
        result = _run_capture(cmd, timeout_sec=timeout_sec)
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        devices = _parse_avfoundation_devices(text)
        mode_timeout_sec = max(1.0, min(timeout_sec, 3.0))
        for device in devices:
            index = str(device.get("index") or "").strip()
            if not index:
                continue
            try:
                modes = _probe_avfoundation_modes(ffmpeg_bin, index, mode_timeout_sec)
            except (subprocess.TimeoutExpired, OSError):
                modes = []
            if modes:
                device["modes"] = modes
                device["recommended"] = _pick_recommended_mode(
                    modes,
                    fallback=device.get("recommended"),
                )
        warning = ""
    elif driver == "dshow":
        cmd = [ffmpeg_bin, "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"]
        result = _run_capture(cmd, timeout_sec=timeout_sec)
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        devices = _parse_dshow_devices(text)
        warning = ""
    else:
        cmd = [ffmpeg_bin, "-hide_banner", "-f", "v4l2", "-list_formats", "all", "-i", "/dev/video0"]
        try:
            devices = _probe_v4l2_devices(ffmpeg_bin, timeout_sec)
            warning = ""
            text = ""
        except Exception as e:  # noqa: BLE001
            raise UvcProbeError(str(e)) from e

    if not devices:
        stderr = (result.stderr or "").strip() if driver in {"avfoundation", "dshow"} else ""
        if stderr and ("No such file" in stderr or "not found" in stderr):
            raise UvcProbeError(f"ffmpeg probe failed: {stderr}")
        warning = _empty_probe_warning(driver, stderr)

    return {
        "driver": driver,
        "ffmpeg_bin": ffmpeg_bin,
        "probed_at": started_at,
        "duration_ms": int((time.time() - started_at) * 1000),
        "devices": devices,
        "warning": warning,
        "raw_output": text[:12000] if driver in {"avfoundation", "dshow"} else "",
    }


def build_uvc_suggestion(
    *,
    driver: str,
    ffmpeg_device: str,
    display_name: str,
    profile: str,
    path: str,
    rtsp_base_url: str,
    enabled: bool = True,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    bitrate: str | None = None,
    camera_name: str | None = None,
) -> dict[str, Any]:
    profile_clean = profile.strip()
    if not profile_clean:
        raise ValueError("profile must not be empty")
    path_clean = path.strip().strip("/")
    if not path_clean:
        raise ValueError("path must not be empty")
    camera_name_value = (camera_name or display_name or profile_clean).strip()
    bitrate_value = (bitrate or "").strip()

    token = re.sub(r"[^A-Za-z0-9]+", "_", profile_clean).strip("_").upper()
    rtsp_url = rtsp_base_url.rstrip("/") + "/" + path_clean

    env_lines = [
        f"UVC_{token}_ENABLED={'true' if enabled else 'false'}",
        f"UVC_{token}_DEVICE={ffmpeg_device}",
        f"UVC_{token}_CAMERA_NAME={camera_name_value}",
        f"UVC_{token}_RTSP_URL={rtsp_url}",
        f"UVC_{token}_INPUT_DRIVER={driver}",
        f"UVC_{token}_WIDTH={width}",
        f"UVC_{token}_HEIGHT={height}",
        f"UVC_{token}_FPS={fps}",
    ]
    if bitrate_value:
        env_lines.append(f"UVC_{token}_BITRATE={bitrate_value}")

    runtime_camera = {
        "id": path_clean,
        "type": "uvc",
        "enabled": bool(enabled),
        "path": path_clean,
        "uvc": {
            "profile": profile_clean,
            "env": {
                "INPUT_DRIVER": driver,
                "DEVICE": ffmpeg_device,
                "CAMERA_NAME": camera_name_value,
                "RTSP_URL": rtsp_url,
                "WIDTH": str(width),
                "HEIGHT": str(height),
                "FPS": str(fps),
            },
            "extra_args": [],
        },
    }
    if bitrate_value:
        runtime_camera["uvc"]["env"]["BITRATE"] = bitrate_value

    return {
        "profile": profile_clean,
        "path": path_clean,
        "rtsp_url": rtsp_url,
        "camera_name": camera_name_value,
        "env_lines": env_lines,
        "runtime_camera": runtime_camera,
    }


@dataclass
class UvcProbeCache:
    ffmpeg_bin: str = "ffmpeg"
    timeout_sec: float = DEFAULT_PROBE_TIMEOUT_SEC
    cache_ttl_sec: float = DEFAULT_CACHE_TTL_SEC
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _last_result: dict[str, Any] | None = None
    _last_time: float = 0.0

    def get(self, *, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            if (
                not refresh
                and self._last_result is not None
                and (now - self._last_time) <= self.cache_ttl_sec
            ):
                return self._last_result

            result = probe_uvc_devices(ffmpeg_bin=self.ffmpeg_bin, timeout_sec=self.timeout_sec)
            self._last_result = result
            self._last_time = now
            return result
