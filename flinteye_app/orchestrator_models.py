from __future__ import annotations

import re
import ipaddress
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ControlMode = Literal["windows_service", "systemd", "launchd", "direct", "external", "docker_compose"]
CameraType = Literal["uvc", "ip"]
SourceMode = Literal["env", "api", "hybrid"]
AuthProvider = Literal["legacy_token", "local", "oidc"]
IpRelayMode = Literal["copy", "libx264"]
IpTimestampMode = Literal["auto", "source", "wallclock", "cfr"]
OnvifMode = Literal["auto", "manual", "disabled"]
PtzAccess = Literal["admin", "viewer"]
MultiviewInputMode = Literal["inherit", "primary", "normalized_primary", "onvif", "manual"]


class NetworkAccessConfig(BaseModel):
    """Opt-in LAN access; absent in old profiles means local-only."""
    enabled: bool = False
    address: str = ""
    allowed_subnets: list[str] = Field(default_factory=list)
    rtsp_enabled: bool = False

    @model_validator(mode="after")
    def validate_lan(self):
        if self.address:
            address = ipaddress.IPv4Address(self.address)
            if not any(address in network for network in LAN_NETWORKS):
                raise ValueError("Choose a private IPv4 address assigned to this server")
        self.allowed_subnets = [str(ipaddress.IPv4Network(item, strict=False)) for item in self.allowed_subnets]
        if len(self.allowed_subnets) > 16:
            raise ValueError("Use at most 16 LAN source ranges")
        for item in self.allowed_subnets:
            network = ipaddress.IPv4Network(item)
            if not any(network.subnet_of(block) for block in LAN_NETWORKS):
                raise ValueError("Source ranges must be private IPv4 networks")
        if self.enabled and (not self.address or not self.allowed_subnets):
            raise ValueError("LAN access requires a server address and permitted source ranges")
        return self


# Shared-address VPNs are eligible when the owner selects the actual interface
# address and explicitly lists the sources. Do not infer a VPN allowlist.
LAN_NETWORKS = tuple(map(ipaddress.IPv4Network, (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
)))


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 18080
    admin_token: str = ""
    viewer_token: str = ""
    viewer_auth_required: bool = True
    bearer_token: str = ""

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError("port must be in range 1..65535")
        return value


class SnapshotConfig(BaseModel):
    timeout_sec: float = 3.0
    thumbnail_refresh_interval_sec: float = 10.0

    @field_validator("timeout_sec")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout_sec must be > 0")
        if value > 120:
            raise ValueError("timeout_sec must be <= 120")
        return value

    @field_validator("thumbnail_refresh_interval_sec")
    @classmethod
    def validate_thumbnail_refresh_interval(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("thumbnail_refresh_interval_sec must be > 0")
        if value > 3600:
            raise ValueError("thumbnail_refresh_interval_sec must be <= 3600")
        return value


class UiConfig(BaseModel):
    onboarding_done: bool = False
    app_title: str = "FlintEye"
    sidebar_title: str = "FlintEye"
    footer_text: str = "© 2026 Noguhiro. Sustainable Use License + additional permission."

    @field_validator("app_title", "sidebar_title")
    @classmethod
    def replace_legacy_product_label(cls, value: str) -> str:
        return "FlintEye" if value.strip() in {"Unified Camera Orchestrator", "Orchestrator UI"} else value

    @field_validator("app_title", "sidebar_title", "footer_text")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


class MediamtxDirectConfig(BaseModel):
    source: Literal['auto', 'bundled', 'external'] = 'auto'
    command: list[str] = Field(default_factory=list)
    working_dir: str | None = None


ScalarValue = str | int | float | bool


class MediamtxManagedConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool = False
    global_: dict[str, ScalarValue | list[ScalarValue]] = Field(default_factory=dict, alias="global")
    paths: dict[str, dict[str, ScalarValue | list[ScalarValue]]] = Field(default_factory=dict)

    @field_validator("global_")
    @classmethod
    def validate_global_map(cls, value: dict[str, ScalarValue | list[ScalarValue]]) -> dict[str, ScalarValue | list[ScalarValue]]:
        for key, item in value.items():
            if not key.strip():
                raise ValueError("global key must not be empty")
            cls._validate_scalar_or_list(item, f"global.{key}")
        return value

    @field_validator("paths")
    @classmethod
    def validate_paths_map(
        cls,
        value: dict[str, dict[str, ScalarValue | list[ScalarValue]]],
    ) -> dict[str, dict[str, ScalarValue | list[ScalarValue]]]:
        for path_name, settings in value.items():
            if not path_name.strip().strip("/"):
                raise ValueError("paths key must not be empty")
            if not isinstance(settings, dict):
                raise ValueError(f"paths.{path_name} must be an object")
            for key, item in settings.items():
                if not key.strip():
                    raise ValueError(f"paths.{path_name} contains empty key")
                cls._validate_scalar_or_list(item, f"paths.{path_name}.{key}")
        return value

    @staticmethod
    def _validate_scalar_or_list(item: object, path: str) -> None:
        if isinstance(item, (str, int, float, bool)):
            return
        if isinstance(item, list):
            for idx, entry in enumerate(item):
                if not isinstance(entry, (str, int, float, bool)):
                    raise ValueError(f"{path}[{idx}] must be scalar (str/int/float/bool)")
            return
        raise ValueError(f"{path} must be scalar or scalar list")


class MediamtxConfig(BaseModel):
    control_mode: ControlMode = "systemd"
    service_name: str = "mediamtx"
    autostart_on_api_start: bool = True
    rtsp_base_url: str = "rtsp://127.0.0.1:8554"
    internal_rtsp_base_url: str | None = None
    webrtc_base_url: str = "http://127.0.0.1:8889"
    direct: MediamtxDirectConfig = Field(default_factory=MediamtxDirectConfig)
    managed: MediamtxManagedConfig = Field(default_factory=MediamtxManagedConfig)

    @field_validator("internal_rtsp_base_url")
    @classmethod
    def normalize_optional_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UvcCameraConfig(BaseModel):
    profile: str = "cam1"
    env: dict[str, Any] = Field(default_factory=dict)
    extra_args: list[str] = Field(default_factory=list)


class IpCameraPtzConfig(BaseModel):
    enabled: bool = False
    access: PtzAccess = "admin"
    profile_token: str | None = None
    pan_tilt_speed: float = 0.5
    zoom_speed: float = 0.5
    relative_step: float = 0.15

    @field_validator("profile_token")
    @classmethod
    def normalize_profile_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("pan_tilt_speed", "zoom_speed", "relative_step")
    @classmethod
    def validate_normalized_value(cls, value: float) -> float:
        if value <= 0 or value > 1:
            raise ValueError("must be in range 0..1")
        return value


class IpCameraMultiviewInputConfig(BaseModel):
    mode: MultiviewInputMode = "inherit"
    profile_token: str | None = None
    manual_url: str | None = None
    target_fps: int | None = None
    resolution: str | None = None
    encoder: str | None = None
    quality_preset: Literal["high", "standard", "low"] | None = None
    bitrate: str | None = None
    maxrate: str | None = None
    bufsize: str | None = None
    x264_preset: str | None = None
    thread_queue_size: int | None = None
    stall_timeout_sec: float | None = None

    @field_validator("profile_token", "manual_url", "resolution", "encoder", "bitrate", "maxrate", "bufsize", "x264_preset")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("target_fps", "thread_queue_size")
    @classmethod
    def validate_optional_positive_int(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("stall_timeout_sec")
    @classmethod
    def validate_optional_timeout(cls, value: float | None) -> float | None:
        if value is not None and (value < 0 or value > 3600):
            raise ValueError("must be in range 0..3600")
        return value

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "IpCameraMultiviewInputConfig":
        if self.mode == "manual" and not self.manual_url:
            raise ValueError("manual_url is required when mode='manual'")
        return self


class IpCameraConfig(BaseModel):
    source_url: str | None = None
    relay_mode: IpRelayMode = "copy"
    timestamp_mode: IpTimestampMode = "auto"
    cfr_fps: float = 20.0
    onvif_mode: OnvifMode = "auto"
    onvif_address: str | None = None
    onvif_username: str | None = None
    onvif_password: str | None = None
    ptz: IpCameraPtzConfig = Field(default_factory=IpCameraPtzConfig)
    multiview_input: IpCameraMultiviewInputConfig = Field(default_factory=IpCameraMultiviewInputConfig)
    bitrate: str | None = None
    maxrate: str | None = None
    bufsize: str | None = None
    gop: int = 40
    x264_preset: str = "veryfast"
    periodic_restart_enabled: bool = True
    periodic_restart_interval_sec: float = 43200.0
    watchdog_enabled: bool = True
    watchdog_interval_sec: float = 300.0
    watchdog_timeout_sec: float = 8.0
    watchdog_failure_threshold: int = 3

    @field_validator(
        "source_url",
        "onvif_address",
        "onvif_username",
        "onvif_password",
        "bitrate",
        "maxrate",
        "bufsize",
    )
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("x264_preset")
    @classmethod
    def validate_preset(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("gop")
    @classmethod
    def validate_gop(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("cfr_fps")
    @classmethod
    def validate_cfr_fps(cls, value: float) -> float:
        if value <= 0 or value > 240:
            raise ValueError("must be in range 1..240")
        return value

    @model_validator(mode="after")
    def validate_onvif_settings(self) -> "IpCameraConfig":
        if self.onvif_mode == "manual" and not self.onvif_address:
            raise ValueError("onvif_address is required when onvif_mode='manual'")
        return self

    @field_validator("periodic_restart_interval_sec", "watchdog_interval_sec", "watchdog_timeout_sec")
    @classmethod
    def validate_positive_float(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be > 0")
        return value

    @field_validator("watchdog_failure_threshold")
    @classmethod
    def validate_watchdog_failure_threshold(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value


AUDIO_PRESETS = {
    "standard": (16000, 16), "high": (48000, 24),
    "middle": (12000, 16), "low": (8000, 16),
}


class CameraAudioConfig(BaseModel):
    enabled: bool = False
    preset: Literal["standard", "high", "middle", "low", "custom"] = "standard"
    codec: Literal["pcm", "aac"] = "pcm"
    sample_rate: Literal[8000, 12000, 16000, 22050, 24000, 32000, 44100, 48000] = 16000
    bit_depth: Literal[16, 24] = 16
    channels: Literal[1, 2] = 1
    bitrate_kbps: int = Field(default=64, ge=16, le=320)

    @model_validator(mode="after")
    def use_preset(self):
        if self.preset in AUDIO_PRESETS:
            self.sample_rate, self.bit_depth = AUDIO_PRESETS[self.preset]
            self.channels, self.codec = 1, "pcm"
        return self


class CameraConfig(BaseModel):
    id: str
    type: CameraType
    enabled: bool = True
    path: str
    display_name: str | None = None
    uvc: UvcCameraConfig | None = None
    ip: IpCameraConfig | None = None
    audio: CameraAudioConfig = Field(default_factory=CameraAudioConfig)

    @field_validator("id", "path")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_camera_shape(self) -> "CameraConfig":
        if self.id != self.path:
            raise ValueError("camera id must match path")
        if self.type == "uvc":
            if self.uvc is None:
                self.uvc = UvcCameraConfig(profile=self.id)
        if self.type == "ip":
            if self.ip is None or not self.ip.source_url:
                raise ValueError("ip.source_url is required when type='ip'")
        return self


class MultiviewQualityConfig(BaseModel):
    fps: int = 10
    encoder: str = "auto"
    quality_preset: Literal["high", "standard", "low"] = "standard"
    bitrate: str | None = None
    maxrate: str | None = None
    bufsize: str | None = None
    gop: int = 40
    bframes: int = 0
    x264_preset: str = "veryfast"

    @field_validator("fps", "gop")
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("bframes")
    @classmethod
    def validate_bframes(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be >= 0")
        return value


class MultiviewLayoutConfig(BaseModel):
    canvas_width: int = 1920
    canvas_height: int = 1080
    grid_columns: int | None = None
    global_slots: str | None = None
    per_view_slots: dict[str, str] = Field(default_factory=dict)
    source_slots: list[list[str | None]] | None = None

    @field_validator("canvas_width", "canvas_height")
    @classmethod
    def validate_canvas_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value


class MultiviewMaintenanceConfig(BaseModel):
    enabled: bool = True
    restart_interval_sec: float = 43200.0
    align_with_record_segments: bool = True
    restart_offset_sec: float = 2.0

    @field_validator("restart_interval_sec")
    @classmethod
    def validate_restart_interval(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be > 0")
        return value

    @field_validator("restart_offset_sec")
    @classmethod
    def validate_restart_offset(cls, value: float) -> float:
        if value < 0:
            raise ValueError("must be >= 0")
        return value


class MultiviewInputDefaultsConfig(BaseModel):
    mode: Literal["primary", "normalized_primary"] = "primary"
    target_fps: int = 10
    resolution: str = "auto"
    encoder: str = "libx264"
    quality_preset: Literal["high", "standard", "low"] = "standard"
    bitrate: str = "800k"
    maxrate: str = "1M"
    bufsize: str = "2M"
    x264_preset: str = "veryfast"
    fallback_to_primary: bool = True

    @field_validator("target_fps")
    @classmethod
    def validate_target_fps(cls, value: int) -> int:
        if value <= 0 or value > 120:
            raise ValueError("must be in range 1..120")
        return value


class MultiviewSyncBufferConfig(BaseModel):
    enabled: bool = False
    delay_sec: float = 3.0
    buffer_sec: float = 5.0
    fps: int = 10
    width: int = 640
    height: int = 360
    late_frame_policy: Literal["hold", "no_stream"] = "hold"
    max_hold_sec: float = 10.0
    memory_limit_mb_per_input: float = 64.0
    reconnect_sec: float = 2.0

    @model_validator(mode="after")
    def validate_values(self) -> "MultiviewSyncBufferConfig":
        if not 0 <= self.delay_sec <= self.buffer_sec <= 120:
            raise ValueError("must satisfy 0 <= delay_sec <= buffer_sec <= 120")
        if not 1 <= self.fps <= 60:
            raise ValueError("fps must be in range 1..60")
        if self.width <= 0 or self.height <= 0 or self.width % 2 or self.height % 2:
            raise ValueError("width and height must be positive even values")
        if self.max_hold_sec < 0 or self.memory_limit_mb_per_input <= 0 or self.reconnect_sec <= 0:
            raise ValueError("hold, memory, and reconnect values are invalid")
        minimum_mb = self.width * self.height * 3 * 2 / (1024 * 1024)
        if self.memory_limit_mb_per_input < minimum_mb:
            raise ValueError("memory limit must hold at least two RGB frames")
        return self


class MultiviewConfig(BaseModel):
    enabled: bool = False
    source_mode: SourceMode = "hybrid"
    source_paths: list[str] = Field(default_factory=list)
    auto_placeholder_missing_sources: bool = True
    mtx_api_url: str = "http://127.0.0.1:9997/v3/paths/list"
    input_rtsp_base_url: str = "rtsp://127.0.0.1:8554"
    output_rtsp_base_url: str = "rtsp://127.0.0.1:8554"
    output_prefix: str = "multiview"
    max_sources: int = 32
    tile_count: int = 4
    latency_preset: Literal["normal", "low"] = "low"
    restart_backoff_sec: float = 3.0
    input_stall_timeout_sec: float = 15.0
    input_stall_timeout_option: Literal["auto", "rw_timeout", "stimeout", "timeout", "none"] = "auto"
    input_healthcheck_enabled: bool = True
    input_healthcheck_interval_sec: float = 5.0
    input_isolation_threshold: int = 3
    input_retry_interval_sec: float = 30.0
    input_thread_queue_size: int = 128
    status_file: str = "./logs/runtime/multiview_status.json"
    ffmpeg_bin: str = "ffmpeg"
    loglevel: str = "error"
    verbose: bool = False
    quality: MultiviewQualityConfig = Field(default_factory=MultiviewQualityConfig)
    layout: MultiviewLayoutConfig = Field(default_factory=MultiviewLayoutConfig)
    maintenance: MultiviewMaintenanceConfig = Field(default_factory=MultiviewMaintenanceConfig)
    input_defaults: MultiviewInputDefaultsConfig = Field(default_factory=MultiviewInputDefaultsConfig)
    sync_buffer: MultiviewSyncBufferConfig = Field(default_factory=MultiviewSyncBufferConfig)

    @model_validator(mode="after")
    def validate_source_slots(self):
        from flinteye_app.multiview_layout import is_public_source

        pages = self.layout.source_slots
        if pages is None:
            return self
        if len(pages) > 32 or any(len(page) != self.tile_count for page in pages):
            raise ValueError("Each Multiview page must contain Tile Count slots")
        sources: set[str] = set()
        for page in pages:
            for index, path in enumerate(page):
                if path is None:
                    continue
                path = path.strip().strip("/")
                if (not is_public_source(path, self.output_prefix) or len(path) > 256
                        or any(ch in path for ch in "\r\n,;\\?#") or ".." in path.split("/")):
                    raise ValueError("Multiview slots require public MediaMTX paths")
                if path.casefold() in sources:
                    raise ValueError("Assign each Multiview source to one slot")
                sources.add(path.casefold())
                page[index] = path
        if len(sources) > self.max_sources:
            raise ValueError("Multiview assignments exceed Max Sources")
        return self

    @field_validator("max_sources", "tile_count")
    @classmethod
    def validate_tile_settings(cls, value: int) -> int:
        if value < 2 or value > 32:
            raise ValueError("must be in range 2..32")
        return value

    @field_validator("restart_backoff_sec")
    @classmethod
    def validate_backoff(cls, value: float) -> float:
        if value < 0:
            raise ValueError("must be >= 0")
        return value

    @field_validator("input_stall_timeout_sec")
    @classmethod
    def validate_input_stall_timeout(cls, value: float) -> float:
        if value < 0:
            raise ValueError("must be >= 0")
        if value > 3600:
            raise ValueError("must be <= 3600")
        return value

    @field_validator("input_healthcheck_interval_sec", "input_retry_interval_sec")
    @classmethod
    def validate_health_intervals(cls, value: float) -> float:
        if value <= 0 or value > 3600:
            raise ValueError("must be in range 0..3600")
        return value

    @field_validator("input_isolation_threshold", "input_thread_queue_size")
    @classmethod
    def validate_positive_settings(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value


class PreviousRecordingRoot(BaseModel):
    path: str
    retention: str = "168h"
    max_bytes: int | None = Field(default=None, gt=0)


class RecordingConfig(BaseModel):
    max_bytes: int | None = Field(default=None, gt=0)
    min_free_bytes: int = Field(default=1_000_000_000, ge=0)
    managed_storage: bool = False
    previous_roots: list[PreviousRecordingRoot] = Field(default_factory=list)
    show_previous: bool = True
    enabled: bool = True
    auto_apply: bool = True
    config_path: str | None = None
    record_root: str = "./recordings/mediamtx"
    record_format: Literal["fmp4", "mpegts"] = "fmp4"
    record_part_duration: str = "1s"
    record_max_part_size: str = "50M"
    record_segment_duration: str = "10m"
    record_delete_after: str = "168h"
    playback_cache_delete_after: str = "24h"
    playback_cache_max_bytes: int = Field(default=2_000_000_000, ge=1_000_000)
    include_multiview: bool = True
    multiview_max_count: int = 16
    record_all_cameras: bool | None = None
    record_paths: list[str] = Field(default_factory=list)

    @field_validator("multiview_max_count")
    @classmethod
    def validate_multiview_max_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value

    @field_validator(
        "record_root",
        "record_part_duration",
        "record_max_part_size",
        "record_segment_duration",
        "record_delete_after",
    )
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("record_delete_after")
    @classmethod
    def validate_record_retention(cls, value: str, info) -> str:
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:ms|s|m|h|d)", value) or (info.data.get("managed_storage") and float(re.match(r"[0-9.]+", value).group()) <= 0):
            raise ValueError("Recording retention must be a positive duration, e.g. 168h")
        return value

    @field_validator("playback_cache_delete_after")
    @classmethod
    def validate_playback_cache_delete_after(cls, value: str) -> str:
        normalized = value.strip().lower()
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(ms|s|m|h|d)", normalized)
        if not match or float(match.group(1)) <= 0:
            raise ValueError("must be a duration greater than 0 (for example, 24h)")
        return normalized

    @field_validator("config_path")
    @classmethod
    def validate_config_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LoggingConfig(BaseModel):
    directory: str = "./logs"
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "ERROR"
    retention: str | None = None

    @field_validator("directory")
    @classmethod
    def validate_directory(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("retention")
    @classmethod
    def validate_retention(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LocalAuthUserConfig(BaseModel):
    username: str
    password_hash: str = ""

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


class LocalAuthConfig(BaseModel):
    admin: LocalAuthUserConfig = Field(default_factory=lambda: LocalAuthUserConfig(username="admin"))
    viewer: LocalAuthUserConfig = Field(default_factory=lambda: LocalAuthUserConfig(username="viewer"))


class AuthConfig(BaseModel):
    provider: AuthProvider = "legacy_token"
    viewer_auth_required: bool = True
    session_cookie_name: str = "orch_session"
    session_ttl_sec: int = 43200
    session_secret: str = ""
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_scopes: str = "openid profile email"
    local: LocalAuthConfig = Field(default_factory=LocalAuthConfig)

    @field_validator("session_cookie_name")
    @classmethod
    def validate_cookie_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("session_ttl_sec")
    @classmethod
    def validate_session_ttl(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be > 0")
        return value

    @field_validator("session_secret", "oidc_issuer_url", "oidc_client_id", "oidc_client_secret", "oidc_redirect_uri")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized

    @field_validator("oidc_scopes")
    @classmethod
    def validate_scopes(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


class DeviceDiscoveryConfig(BaseModel):
    ignored_uvc_devices: list[str] = Field(default_factory=list)

    @field_validator("ignored_uvc_devices")
    @classmethod
    def validate_ignored_uvc_devices(cls, value: list[str]) -> list[str]:
        normalized_items: list[str] = []
        seen: set[str] = set()
        for raw in value:
            normalized = str(raw).strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_items.append(normalized)
        return normalized_items


class RuntimeConfig(BaseModel):
    network: NetworkAccessConfig = Field(default_factory=NetworkAccessConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    snapshot: SnapshotConfig = Field(default_factory=SnapshotConfig)
    mediamtx: MediamtxConfig = Field(default_factory=MediamtxConfig)
    cameras: list[CameraConfig] = Field(default_factory=list)
    multiview: MultiviewConfig = Field(default_factory=MultiviewConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    device_discovery: DeviceDiscoveryConfig = Field(default_factory=DeviceDiscoveryConfig)

    @model_validator(mode='after')
    def require_lan_authentication(self):
        if self.network.enabled and (self.auth.provider != 'local' or not self.auth.viewer_auth_required):
            raise ValueError('Built-in LAN access requires local administrator and viewer authentication')
        return self
