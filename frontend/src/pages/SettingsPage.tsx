import { StartupSettings } from "../components/StartupSettings";
import { useConfirmChanges } from "../components/ConfirmChanges";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowPathIcon,
  ArrowsPointingOutIcon,
  BoltIcon,
  CameraIcon,
  CheckCircleIcon,
  ChevronRightIcon,
  CodeBracketIcon,
  Cog6ToothIcon,
  DocumentTextIcon,
  ExclamationTriangleIcon,
  MagnifyingGlassIcon,
  MinusIcon,
  PlusIcon,
  ShieldCheckIcon,
  SignalIcon,
  Squares2X2Icon,
  TrashIcon,
  VideoCameraIcon,
} from "@heroicons/react/24/outline";
import { ApiClient, ApiError } from "../api/client";
import type { IpCameraProbeResult, MultiviewStatus, RuntimeConfigResponse, UvcDeviceItem, UvcSuggestion } from "../types";
import { SettingsHelp } from "../components/SettingsHelp";

type ConfiguredCamera = NonNullable<RuntimeConfigResponse["cameras"]>[number];

interface SettingsPageProps {
  api: ApiClient;
  onUiConfigChanged?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}

interface IpCameraDraft {
  id: string;
  type: "ip";
  enabled: boolean;
  path: string;
  display_name: string;
  ip: {
    source_url: string;
    relay_mode: "copy" | "libx264";
    timestamp_mode: "auto" | "source" | "wallclock" | "cfr";
    cfr_fps: number;
    onvif_mode: "auto" | "manual" | "disabled";
    onvif_address: string;
    onvif_username: string;
    onvif_password: string;
    ptz: {
      enabled: boolean;
      access: "admin" | "viewer";
      profile_token: string;
      pan_tilt_speed: number;
      zoom_speed: number;
      relative_step: number;
    };
    multiview_input: {
      mode: "inherit" | "primary" | "normalized_primary" | "onvif" | "manual";
      profile_token: string;
      manual_url: string;
      target_fps: number | null;
      resolution: string;
      encoder: string;
      quality_preset: "" | "high" | "standard" | "low";
      bitrate: string;
      maxrate: string;
      bufsize: string;
      x264_preset: string;
      thread_queue_size: number | null;
      stall_timeout_sec: number | null;
    };
    bitrate: string;
    maxrate: string;
    bufsize: string;
    gop: number;
    x264_preset: string;
    periodic_restart_enabled: boolean;
    periodic_restart_interval_sec: number;
    watchdog_enabled: boolean;
    watchdog_interval_sec: number;
    watchdog_timeout_sec: number;
    watchdog_failure_threshold: number;
  };
}

const DEFAULT_IP_CAMERA_SETTINGS: IpCameraDraft["ip"] = {
  source_url: "",
  relay_mode: "copy",
  timestamp_mode: "auto",
  cfr_fps: 20,
  onvif_mode: "auto",
  onvif_address: "",
  onvif_username: "",
  onvif_password: "",
  ptz: {
    enabled: false,
    access: "admin",
    profile_token: "",
    pan_tilt_speed: 0.5,
    zoom_speed: 0.5,
    relative_step: 0.15,
  },
  multiview_input: {
    mode: "inherit",
    profile_token: "",
    manual_url: "",
    target_fps: null,
    resolution: "",
    encoder: "",
    quality_preset: "",
    bitrate: "",
    maxrate: "",
    bufsize: "",
    x264_preset: "",
    thread_queue_size: null,
    stall_timeout_sec: null,
  },
  bitrate: "",
  maxrate: "",
  bufsize: "",
  gop: 40,
  x264_preset: "veryfast",
  periodic_restart_enabled: true,
  periodic_restart_interval_sec: 43200,
  watchdog_enabled: true,
  watchdog_interval_sec: 300,
  watchdog_timeout_sec: 8,
  watchdog_failure_threshold: 3,
};

interface IpCameraProbeState {
  requestKey: string;
  loading: boolean;
  error: string;
  result: IpCameraProbeResult | null;
}

interface SourceOption {
  path: string;
  label: string;
  type: "uvc" | "ip";
  enabled: boolean;
}

interface UvcModeOption {
  key: string;
  width: number;
  height: number;
  fps: number;
  label: string;
}

type SettingsMode =
  | "quick"
  | "general"
  | "runtime"
  | "logging"
  | "mediamtx"
  | "recording"
  | "multiview"
  | "cameras"
  | "advanced";

const SETTINGS_NAV_ITEMS = [
  { key: "quick", label: "Quick settings", icon: BoltIcon },
  { key: "general", label: "General", icon: Cog6ToothIcon },
  { key: "runtime", label: "Runtime & access", icon: ShieldCheckIcon },
  { key: "mediamtx", label: "MediaMTX", icon: SignalIcon },
  { key: "recording", label: "Recording", icon: VideoCameraIcon },
  { key: "logging", label: "Logging", icon: DocumentTextIcon },
  { key: "multiview", label: "Multiview", icon: Squares2X2Icon },
  { key: "cameras", label: "Cameras", icon: CameraIcon },
  { key: "advanced", label: "Advanced", icon: CodeBracketIcon },
] as const;

const SETTINGS_SEARCH_INDEX: Array<{
  label: string;
  description: string;
  section: SettingsMode;
  terms: string;
}> = [
  { label: "Application branding", description: "App, sidebar, and footer titles", section: "general", terms: "app title sidebar title footer text branding web app" },
  { label: "Software updates", description: "Check and download releases", section: "general", terms: "update upgrade version release download" },
  { label: "API endpoint", description: "API host and port", section: "runtime", terms: "api host port server endpoint" },
  { label: "Viewer access", description: "Authentication provider and viewer requirement", section: "runtime", terms: "auth provider authentication viewer username password access" },
  { label: "Session settings", description: "TTL and cookie name", section: "runtime", terms: "session ttl cookie timeout" },
  { label: "Thumbnail refresh", description: "Snapshot timeout and refresh interval", section: "runtime", terms: "snapshot thumbnail refresh interval timeout" },
  { label: "MediaMTX endpoints", description: "RTSP, internal RTSP, and WebRTC URLs", section: "mediamtx", terms: "mediamtx rtsp webrtc url service control mode" },
  { label: "Recording behavior", description: "Enablement, cameras, format, and segment duration", section: "recording", terms: "recording enabled cameras format segment path" },
  { label: "Storage & retention", description: "Recording folder, capacity, retention, and previous locations", section: "recording", terms: "storage retention record root folder browse capacity quota GB days previous locations delete playback cache" },
  { label: "Logging", description: "Log level, directory, and retention", section: "logging", terms: "logging log level directory retention error debug" },
  { label: "Multiview", description: "Sources, layout, encoder, quality, and synchronization", section: "multiview", terms: "multiview sources layout tile sync buffer quality encoder bitrate fps resolution canvas width height hardware gpu preset watchdog restart" },
  { label: "Camera discovery", description: "UVC devices and IP cameras", section: "cameras", terms: "camera uvc discovery ip onvif ptz" },
  { label: "Full runtime JSON", description: "Expert-level configuration editor", section: "advanced", terms: "advanced json runtime expert raw" },
];

const DEFAULT_RUNTIME: RuntimeConfigResponse = {
  api: {
    host: "127.0.0.1",
    port: 18080,
  },
  auth: {
    provider: "legacy_token",
    viewer_auth_required: true,
    session_cookie_name: "orch_session",
    session_ttl_sec: 43200,
    session_secret: "",
    oidc_issuer_url: null,
    oidc_client_id: null,
    oidc_client_secret: null,
    oidc_redirect_uri: null,
    oidc_scopes: "openid profile email",
    local: {
      admin: { username: "admin", password_hash: "" },
      viewer: { username: "viewer", password_hash: "" },
    },
  },
  ui: {
    app_title: "FlintEye",
    sidebar_title: "FlintEye",
    footer_text: "© 2026 Noguhiro. Sustainable Use License + additional permission.",
  },
  logging: {
    directory: "./logs",
    level: "ERROR",
    retention: null,
  },
  snapshot: { timeout_sec: 3.0, thumbnail_refresh_interval_sec: 10.0 },
  mediamtx: {
    control_mode: "systemd",
    service_name: "mediamtx",
    autostart_on_api_start: true,
    rtsp_base_url: "rtsp://127.0.0.1:8554",
    internal_rtsp_base_url: null,
    webrtc_base_url: "http://127.0.0.1:8889",
    direct: {
      command: [],
      working_dir: null,
    },
    managed: {
      enabled: false,
      global: {},
      paths: {},
    },
  },
  recording: {
    enabled: true,
    auto_apply: true,
    config_path: null,
    record_root: "./recordings/mediamtx",
    record_format: "fmp4",
    record_part_duration: "1s",
    record_max_part_size: "50M",
    record_segment_duration: "10m",
    record_delete_after: "168h",
    playback_cache_delete_after: "24h",
    include_multiview: true,
    multiview_max_count: 16,
    record_all_cameras: true,
    record_paths: [],
  },
  device_discovery: {
    ignored_uvc_devices: [],
  },
  multiview: {
    enabled: false,
    source_mode: "hybrid",
    source_paths: [],
    auto_placeholder_missing_sources: true,
    mtx_api_url: "http://127.0.0.1:9997/v3/paths/list",
    input_rtsp_base_url: "rtsp://127.0.0.1:8554",
    output_rtsp_base_url: "rtsp://127.0.0.1:8554",
    output_prefix: "multiview",
    max_sources: 32,
    tile_count: 4,
    latency_preset: "low",
    restart_backoff_sec: 3,
    input_stall_timeout_sec: 15,
    input_stall_timeout_option: "auto",
    input_healthcheck_enabled: true,
    input_healthcheck_interval_sec: 5,
    input_isolation_threshold: 3,
    input_retry_interval_sec: 30,
    input_thread_queue_size: 128,
    status_file: "./logs/runtime/multiview_status.json",
    input_defaults: {
      mode: "primary",
      target_fps: 10,
      resolution: "auto",
      encoder: "libx264",
      quality_preset: "standard",
      bitrate: "800k",
      maxrate: "1M",
      bufsize: "2M",
      x264_preset: "veryfast",
      fallback_to_primary: true,
    },
    sync_buffer: {
      enabled: false,
      delay_sec: 3,
      buffer_sec: 5,
      fps: 10,
      width: 640,
      height: 360,
      late_frame_policy: "hold",
      max_hold_sec: 10,
      memory_limit_mb_per_input: 64,
      reconnect_sec: 2,
    },
    ffmpeg_bin: "ffmpeg",
    loglevel: "error",
    verbose: false,
    quality: {
      fps: 10,
      encoder: "auto",
      quality_preset: "standard",
      bitrate: "2M",
      maxrate: "2M",
      bufsize: "4M",
      gop: 40,
      bframes: 0,
      x264_preset: "veryfast",
    },
    layout: {
      canvas_width: 1920,
      canvas_height: 1080,
      grid_columns: null,
      global_slots: null,
      per_view_slots: {},
    },
    maintenance: {
      enabled: true,
      restart_interval_sec: 43200,
      align_with_record_segments: true,
      restart_offset_sec: 2,
    },
  },
  cameras: [],
};

function splitList(value: string): string[] {
  return value
    .split(/[,\n;]+/)
    .map((item) => item.trim().replace(/^\/+|\/+$/g, ""))
    .filter(Boolean);
}

function uniqueStrings(values: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  values.forEach((value) => {
    const normalized = value.trim().replace(/^\/+|\/+$/g, "");
    if (!normalized) {
      return;
    }
    const key = normalized.toLowerCase();
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    out.push(normalized);
  });
  return out;
}

function uniqueIdentifiers(values: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  values.forEach((value) => {
    const normalized = value.trim().toLowerCase();
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    out.push(normalized);
  });
  return out;
}

function formatFps(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.?0+$/, "");
}

function buildModeKey(width: number, height: number, fps: number): string {
  return `${width}x${height}@${fps}`;
}

function toModeOptions(device: UvcDeviceItem | null): UvcModeOption[] {
  if (!device || device.modes.length === 0) {
    return [];
  }

  const out: UvcModeOption[] = [];
  const seen = new Set<string>();
  device.modes.forEach((mode) => {
    const fps = Math.max(1, Math.round(mode.fps ?? device.recommended.fps));
    const key = buildModeKey(mode.width, mode.height, fps);
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    out.push({
      key,
      width: mode.width,
      height: mode.height,
      fps,
      label: `${mode.width}x${mode.height} @ ${formatFps(fps)} fps`,
    });
  });

  return out.sort((left, right) => {
    const areaDiff = right.width * right.height - left.width * left.height;
    if (areaDiff !== 0) {
      return areaDiff;
    }
    return right.fps - left.fps;
  });
}

function findExactModeOption(
  options: UvcModeOption[],
  width: number,
  height: number,
  fps: number,
): UvcModeOption | null {
  const key = buildModeKey(width, height, fps);
  return options.find((item) => item.key === key) ?? null;
}

function pickInitialModeOption(
  options: UvcModeOption[],
  width: number,
  height: number,
  fps: number,
  recommended: { width: number; height: number; fps: number },
): UvcModeOption | null {
  return (
    findExactModeOption(options, width, height, fps) ??
    findExactModeOption(options, recommended.width, recommended.height, recommended.fps) ??
    options[0] ??
    null
  );
}

function getCameraLabel(camera: ConfiguredCamera): string {
  if (camera.display_name?.trim()) {
    return camera.display_name.trim();
  }
  if (camera.type === "uvc") {
    return camera.uvc?.env?.CAMERA_NAME?.trim() || camera.path || camera.id;
  }
  return camera.path || camera.id;
}

function parsePositiveInt(value: unknown, fallback: number): number {
  const numeric =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim()
        ? Number(value)
        : Number.NaN;
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return fallback;
  }
  return Math.round(numeric);
}

function getUvcDeviceMatchKeys(device: UvcDeviceItem): string[] {
  const out: string[] = [];
  const add = (raw: string | null | undefined): void => {
    const text = raw?.trim();
    if (!text) {
      return;
    }
    out.push(text.toLowerCase());
    if (text.toLowerCase().startsWith("video=")) {
      out.push(text.slice(6).trim().toLowerCase());
    } else {
      out.push(`video=${text.toLowerCase()}`);
    }
  };

  add(device.device_id);
  add(device.ffmpeg_device);
  add(device.ffmpeg_device_index);
  add(device.display_name);
  return uniqueIdentifiers(out);
}

function getManagedUvcCameraMatchKeys(camera: ConfiguredCamera): string[] {
  if (camera.type !== "uvc") {
    return [];
  }
  const deviceValue = camera.uvc?.env?.DEVICE?.trim();
  if (!deviceValue) {
    return [];
  }
  return uniqueIdentifiers(
    deviceValue.toLowerCase().startsWith("video=")
      ? [deviceValue, deviceValue.slice(6).trim()]
      : [deviceValue, `video=${deviceValue}`],
  );
}

function serializeCamera(camera: ConfiguredCamera): Record<string, unknown> {
  return {
    id: camera.id,
    type: camera.type,
    enabled: camera.enabled,
    path: camera.path,
    display_name: camera.display_name,
    uvc: camera.uvc,
    ip: camera.ip,
  };
}

function multiviewHealthClass(state: string | undefined): string {
  if (state === "healthy" || state === "preferred") {
    return "ok";
  }
  if (state === "starting" || state === "buffering" || state === "holding" || state === "reconnecting" || state === "degraded" || state === "fallback") {
    return "warn";
  }
  if (state === "disabled") {
    return "muted";
  }
  return "ng";
}

function withDefaults(runtime: RuntimeConfigResponse): RuntimeConfigResponse {
  const mergedRecording = { ...DEFAULT_RUNTIME.recording, ...(runtime.recording ?? {}) };
  const recordAllCameras =
    runtime.recording?.record_all_cameras ?? (mergedRecording.record_paths?.length ?? 0) === 0;

  return {
    ...DEFAULT_RUNTIME,
    ...runtime,
    api: { ...DEFAULT_RUNTIME.api, ...(runtime.api ?? {}) },
    auth: {
      ...DEFAULT_RUNTIME.auth,
      ...(runtime.auth ?? {}),
      local: {
        ...DEFAULT_RUNTIME.auth?.local,
        ...(runtime.auth?.local ?? {}),
        admin: {
          ...DEFAULT_RUNTIME.auth?.local?.admin,
          ...(runtime.auth?.local?.admin ?? {}),
        },
        viewer: {
          ...DEFAULT_RUNTIME.auth?.local?.viewer,
          ...(runtime.auth?.local?.viewer ?? {}),
        },
      },
    },
    ui: { ...DEFAULT_RUNTIME.ui, ...(runtime.ui ?? {}) },
    logging: { ...DEFAULT_RUNTIME.logging, ...(runtime.logging ?? {}) },
    snapshot: { ...DEFAULT_RUNTIME.snapshot, ...(runtime.snapshot ?? {}) },
    mediamtx: {
      ...DEFAULT_RUNTIME.mediamtx,
      ...(runtime.mediamtx ?? {}),
      direct: {
        ...DEFAULT_RUNTIME.mediamtx?.direct,
        ...(runtime.mediamtx?.direct ?? {}),
      },
      managed: {
        ...DEFAULT_RUNTIME.mediamtx?.managed,
        ...(runtime.mediamtx?.managed ?? {}),
      },
    },
    device_discovery: {
      ...DEFAULT_RUNTIME.device_discovery,
      ...(runtime.device_discovery ?? {}),
    },
    recording: {
      ...mergedRecording,
      record_all_cameras: recordAllCameras,
    },
    multiview: {
      ...DEFAULT_RUNTIME.multiview,
      ...(runtime.multiview ?? {}),
      input_defaults: {
        ...DEFAULT_RUNTIME.multiview?.input_defaults,
        ...(runtime.multiview?.input_defaults ?? {}),
      },
      sync_buffer: {
        ...DEFAULT_RUNTIME.multiview?.sync_buffer,
        ...(runtime.multiview?.sync_buffer ?? {}),
      },
      quality: {
        ...DEFAULT_RUNTIME.multiview?.quality,
        ...(runtime.multiview?.quality ?? {}),
      },
      layout: {
        ...DEFAULT_RUNTIME.multiview?.layout,
        ...(runtime.multiview?.layout ?? {}),
      },
      maintenance: {
        ...DEFAULT_RUNTIME.multiview?.maintenance,
        ...(runtime.multiview?.maintenance ?? {}),
      },
    },
    cameras: runtime.cameras ?? [],
  };
}

function retentionDays(value: string): number {
  const match = /^(\d+(?:\.\d+)?)(ms|s|m|h|d)$/.exec(value);
  if (!match) return NaN;
  const seconds: Record<string, number> = { ms: .001, s: 1, m: 60, h: 3600, d: 86400 };
  return Number(match[1]) * seconds[match[2]] / 86400;
}

export function SettingsPage({ api: sharedApi, onUiConfigChanged, onDirtyChange }: SettingsPageProps): JSX.Element {
  const { ask, confirmation } = useConfirmChanges();
  // Keep this editor's revision separate from onboarding and branding requests.
  const api = useMemo(() => sharedApi.configSession(), [sharedApi]);
  const [mode, setMode] = useState<SettingsMode>("quick");
  const [settingsSearch, setSettingsSearch] = useState("");
  const [cameras, setCameras] = useState<ConfiguredCamera[]>([]);
  const [runtime, setRuntime] = useState<RuntimeConfigResponse>(DEFAULT_RUNTIME);
  const [runtimeJsonText, setRuntimeJsonText] = useState("");
  const [savedJsonText, setSavedJsonText] = useState("");
  const [savedRuntimeText, setSavedRuntimeText] = useState("");
  const [savedRuntimeSnapshot, setSavedRuntimeSnapshot] = useState<RuntimeConfigResponse | null>(null);
  const [savedIpDraftsText, setSavedIpDraftsText] = useState("");
  const [lastRefreshedAt, setLastRefreshedAt] = useState("");
  const [uvcDevices, setUvcDevices] = useState<UvcDeviceItem[]>([]);
  const [uvcWarning, setUvcWarning] = useState("");
  const [loading, setLoading] = useState(true);
  const [configReady, setConfigReady] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [installation, setInstallation] = useState<{ folder_picker: boolean } | null>(null);
  const [viewerPassword, setViewerPassword] = useState("");
  const [updateMessage, setUpdateMessage] = useState("");
  const [listener, setListener] = useState<{ host?: string; port?: number; source?: string }>({});

  useEffect(() => {
    let active = true;
    void api.desktopCapabilities().then(result => { if (active) setInstallation(result); }).catch(() => undefined);
    return () => { active = false; };
  }, [api]);

  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [suggestProfile, setSuggestProfile] = useState("cam1");
  const [suggestPath, setSuggestPath] = useState("uvc_cam1");
  const [suggestName, setSuggestName] = useState("UVC-CAM-01");
  const [suggestWidth, setSuggestWidth] = useState(1280);
  const [suggestHeight, setSuggestHeight] = useState(720);
  const [suggestFps, setSuggestFps] = useState(30);
  const [suggestBitrate, setSuggestBitrate] = useState("");
  const [selectedModeKey, setSelectedModeKey] = useState("");
  const [suggestion, setSuggestion] = useState<UvcSuggestion | null>(null);

  const [ipDrafts, setIpDrafts] = useState<IpCameraDraft[]>([]);
  const [ipProbeStates, setIpProbeStates] = useState<Record<string, IpCameraProbeState>>({});
  const probeRequests = useRef(new Map<string, symbol>());
  const loadRequest = useRef(0);
  const [multiviewStatus, setMultiviewStatus] = useState<MultiviewStatus>({ updated_at: null, views: [] });
  const settingsSearchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent): void => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        settingsSearchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);

  const selectedDevice = useMemo(
    () => uvcDevices.find((item) => item.device_id === selectedDeviceId) ?? null,
    [uvcDevices, selectedDeviceId],
  );
  const selectedModeOptions = useMemo(() => toModeOptions(selectedDevice), [selectedDevice]);
  const selectedMatchedCamera = useMemo(() => {
    const matchedCameraId = selectedDevice?.suggestion?.matched_camera_id;
    if (!matchedCameraId) {
      return null;
    }
    return cameras.find((camera) => camera.id === matchedCameraId) ?? null;
  }, [cameras, selectedDevice]);
  const activeUvcDevices = useMemo(
    () => uvcDevices.filter((item) => !item.ignored),
    [uvcDevices],
  );
  const ignoredUvcDevices = useMemo(
    () => uvcDevices.filter((item) => item.ignored),
    [uvcDevices],
  );
  const managedUvcCameras = useMemo(
    () => cameras.filter((camera) => camera.type === "uvc"),
    [cameras],
  );
  const managedUvcCameraStates = useMemo(
    () =>
      managedUvcCameras.map((camera) => {
        const cameraKeys = new Set(getManagedUvcCameraMatchKeys(camera));
        const detectedDevice =
          uvcDevices.find((device) =>
            getUvcDeviceMatchKeys(device).some((key) => cameraKeys.has(key)),
          ) ?? null;
        return { camera, detectedDevice };
      }),
    [managedUvcCameras, uvcDevices],
  );
  const sourceOptions = useMemo((): SourceOption[] => {
    const out: SourceOption[] = [];
    const seen = new Set<string>();

    cameras
      .filter((camera) => camera.type === "uvc")
      .forEach((camera) => {
        const path = camera.path.trim().replace(/^\/+|\/+$/g, "");
        if (!path) {
          return;
        }
        const key = path.toLowerCase();
        if (seen.has(key)) {
          return;
        }
        seen.add(key);
        out.push({
          path,
          label: getCameraLabel(camera),
          type: "uvc",
          enabled: camera.enabled,
        });
      });

    ipDrafts.forEach((draft) => {
      const path = draft.path.trim().replace(/^\/+|\/+$/g, "");
      if (!path) {
        return;
      }
      const key = path.toLowerCase();
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      out.push({
        path,
        label: draft.display_name.trim() || path,
        type: "ip",
        enabled: draft.enabled,
      });
    });

    return out.sort((left, right) => {
      if (left.enabled !== right.enabled) {
        return left.enabled ? -1 : 1;
      }
      return left.label.localeCompare(right.label);
    });
  }, [cameras, ipDrafts]);
  const knownSourcePathSet = useMemo(
    () => new Set(sourceOptions.map((item) => item.path.toLowerCase())),
    [sourceOptions],
  );
  const multiviewSourcePaths = runtime.multiview?.source_paths ?? [];
  const selectedSourcePathSet = useMemo(
    () => new Set(multiviewSourcePaths.map((item) => item.trim().toLowerCase())),
    [multiviewSourcePaths],
  );
  const extraMultiviewSourcePaths = useMemo(
    () => multiviewSourcePaths.filter((item) => !knownSourcePathSet.has(item.trim().toLowerCase())),
    [knownSourcePathSet, multiviewSourcePaths],
  );
  const recordingSourcePaths = runtime.recording?.record_paths ?? [];
  const recordAllCameras = runtime.recording?.record_all_cameras !== false;
  const selectedRecordingPathSet = useMemo(
    () => new Set(recordingSourcePaths.map((item) => item.trim().toLowerCase())),
    [recordingSourcePaths],
  );
  const extraRecordingSourcePaths = useMemo(
    () => recordingSourcePaths.filter((item) => !knownSourcePathSet.has(item.trim().toLowerCase())),
    [knownSourcePathSet, recordingSourcePaths],
  );
  const currentRuntimeText = useMemo(() => JSON.stringify(runtime), [runtime]);
  const currentIpDraftsText = useMemo(() => JSON.stringify(ipDrafts), [ipDrafts]);
  const formDirty =
    Boolean(savedRuntimeText) &&
    (currentRuntimeText !== savedRuntimeText || currentIpDraftsText !== savedIpDraftsText);
  const jsonDirty = Boolean(savedJsonText) && runtimeJsonText !== savedJsonText;
  const hasUnsavedChanges = formDirty || jsonDirty;
  useEffect(() => {
    onDirtyChange?.(hasUnsavedChanges);
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (hasUnsavedChanges) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [hasUnsavedChanges, onDirtyChange]);
  useEffect(() => () => { onDirtyChange?.(false); loadRequest.current++; probeRequests.current.clear(); }, [onDirtyChange]);
  const confirmDiscard = async (): Promise<boolean> => !hasUnsavedChanges || await ask("Discard all unsaved settings, including Advanced JSON edits, and reload the saved configuration?");
  const requireSavedDraft = (): boolean => {
    if (!hasUnsavedChanges) return true;
    setError("Save or discard your unsaved settings before changing devices or account access.");
    return false;
  };
  const saveError = (error: unknown, fallback: string): void => {
    setError(error instanceof ApiError && [409, 412].includes(error.status)
      ? "Settings changed in another session. Your edits are still here. Copy any changes you need before using Refresh to reload the latest settings; refreshing will ask before discarding them."
      : error instanceof Error ? error.message : fallback);
  };
  const normalizedSettingsSearch = settingsSearch.trim().toLowerCase();
  const settingsSearchResults = useMemo(
    () =>
      normalizedSettingsSearch
        ? SETTINGS_SEARCH_INDEX.filter((item) =>
            `${item.label} ${item.description} ${item.terms}`.toLowerCase().includes(normalizedSettingsSearch),
          )
        : [],
    [normalizedSettingsSearch],
  );
  const quickChangeItems = useMemo(() => {
    if (!savedRuntimeSnapshot) {
      return [] as Array<{ label: string; value: string }>;
    }
    const items: Array<{ label: string; value: string }> = [];
    if (runtime.auth?.viewer_auth_required !== savedRuntimeSnapshot.auth?.viewer_auth_required) {
      items.push({
        label: "Viewer access",
        value: runtime.auth?.viewer_auth_required ? "Authentication required" : "Public viewing allowed",
      });
    }
    if (
      runtime.recording?.enabled !== savedRuntimeSnapshot.recording?.enabled ||
      runtime.recording?.record_all_cameras !== savedRuntimeSnapshot.recording?.record_all_cameras ||
      runtime.recording?.record_format !== savedRuntimeSnapshot.recording?.record_format
    ) {
      items.push({
        label: "Recording",
        value: runtime.recording?.enabled
          ? `${runtime.recording?.record_all_cameras !== false ? "All cameras" : "Selected cameras"} · ${runtime.recording?.record_format ?? "fmp4"}`
          : "Disabled",
      });
    }
    if (runtime.logging?.level !== savedRuntimeSnapshot.logging?.level) {
      items.push({ label: "Log level", value: runtime.logging?.level ?? "ERROR" });
    }
    if (
      runtime.snapshot?.thumbnail_refresh_interval_sec !==
      savedRuntimeSnapshot.snapshot?.thumbnail_refresh_interval_sec
    ) {
      items.push({
        label: "Thumbnail refresh",
        value: `${runtime.snapshot?.thumbnail_refresh_interval_sec ?? 10} seconds`,
      });
    }
    if (formDirty) {
      items.push({ label: "Configuration", value: "Unsaved form changes; saving applies all edited fields." });
    }
    if (jsonDirty) items.push({ label: "Advanced JSON", value: "Unsaved JSON edits; use Replace Runtime & Apply in Advanced." });
    return items;
  }, [formDirty, jsonDirty, runtime, savedRuntimeSnapshot]);

  const selectSettingsSection = (section: SettingsMode): void => {
    setMode(section);
    setSettingsSearch("");
  };

  const applySelectedDeviceDraft = (
    deviceId: string,
    nextDevices: UvcDeviceItem[],
    nextCameras: ConfiguredCamera[],
  ): void => {
    setSelectedDeviceId(deviceId);
    const device = nextDevices.find((item) => item.device_id === deviceId) ?? null;
    if (!device) {
      setSuggestBitrate("");
      setSuggestion(null);
      setSelectedModeKey("");
      return;
    }

    const matchedCameraId = device.suggestion?.matched_camera_id;
    const matchedCamera = matchedCameraId
      ? nextCameras.find((camera) => camera.id === matchedCameraId) ?? null
      : null;
    const env = matchedCamera?.uvc?.env ?? {};
    const configuredWidth = parsePositiveInt(env.WIDTH, device.recommended.width);
    const configuredHeight = parsePositiveInt(env.HEIGHT, device.recommended.height);
    const configuredFps = parsePositiveInt(env.FPS, device.recommended.fps);
    const modeOptions = toModeOptions(device);
    const selectedMode = pickInitialModeOption(
      modeOptions,
      configuredWidth,
      configuredHeight,
      configuredFps,
      device.recommended,
    );
    const width = selectedMode?.width ?? configuredWidth;
    const height = selectedMode?.height ?? configuredHeight;
    const fps = selectedMode?.fps ?? configuredFps;

    setSuggestProfile(matchedCamera?.uvc?.profile?.trim() || device.suggestion?.profile || "cam1");
    setSuggestPath(matchedCamera?.path?.trim() || device.suggestion?.path || "uvc_cam1");
    setSuggestName(
      (typeof env.CAMERA_NAME === "string" && env.CAMERA_NAME.trim()) ||
        device.suggestion?.camera_name ||
        device.display_name,
    );
    setSuggestWidth(width);
    setSuggestHeight(height);
    setSuggestFps(fps);
    setSuggestBitrate(typeof env.BITRATE === "string" ? env.BITRATE.trim() : "");
    setSelectedModeKey(selectedMode?.key ?? "");
    setSuggestion(device.suggestion ?? null);
  };

  const setMultiviewSourcePaths = (paths: string[]): void => {
    setRuntime((prev) => ({
      ...prev,
      multiview: {
        ...(prev.multiview ?? {}),
        source_paths: uniqueStrings(paths),
      },
    }));
  };

  const onToggleKnownSource = (path: string, checked: boolean): void => {
    const pathKey = path.trim().toLowerCase();
    const currentExtras = multiviewSourcePaths.filter(
      (item) => !knownSourcePathSet.has(item.trim().toLowerCase()),
    );
    const nextKnownPaths = sourceOptions
      .filter((item) => {
        const key = item.path.toLowerCase();
        if (key === pathKey) {
          return checked;
        }
        return selectedSourcePathSet.has(key);
      })
      .map((item) => item.path);
    setMultiviewSourcePaths([...nextKnownPaths, ...currentExtras]);
  };

  const onChangeExtraSourcePaths = (value: string): void => {
    const nextKnownPaths = sourceOptions
      .filter((item) => selectedSourcePathSet.has(item.path.toLowerCase()))
      .map((item) => item.path);
    setMultiviewSourcePaths([...nextKnownPaths, ...splitList(value)]);
  };

  const setRecordingSourcePaths = (paths: string[]): void => {
    setRuntime((prev) => ({
      ...prev,
      recording: {
        ...(prev.recording ?? {}),
        record_paths: uniqueStrings(paths),
      },
    }));
  };

  const onToggleRecordingKnownSource = (path: string, checked: boolean): void => {
    const pathKey = path.trim().toLowerCase();
    const currentExtras = recordingSourcePaths.filter(
      (item) => !knownSourcePathSet.has(item.trim().toLowerCase()),
    );
    const nextKnownPaths = sourceOptions
      .filter((item) => {
        const key = item.path.toLowerCase();
        if (key === pathKey) {
          return checked;
        }
        return selectedRecordingPathSet.has(key);
      })
      .map((item) => item.path);
    setRecordingSourcePaths([...nextKnownPaths, ...currentExtras]);
  };

  const onChangeExtraRecordingSourcePaths = (value: string): void => {
    const nextKnownPaths = sourceOptions
      .filter((item) => selectedRecordingPathSet.has(item.path.toLowerCase()))
      .map((item) => item.path);
    setRecordingSourcePaths([...nextKnownPaths, ...splitList(value)]);
  };

  const onToggleIgnoredDevice = async (device: UvcDeviceItem): Promise<void> => {
    if (!requireSavedDraft() || loading) return;
    setLoading(true);
    const ignoredIds = runtime.device_discovery?.ignored_uvc_devices ?? [];
    const shouldIgnore = !device.ignored;
    const nextIgnoredIds = shouldIgnore
      ? uniqueIdentifiers([...ignoredIds, ...getUvcDeviceMatchKeys(device)])
      : ignoredIds.filter((item) => !getUvcDeviceMatchKeys(device).includes(item.trim().toLowerCase()));

    const payload: Record<string, unknown> = {
      device_discovery: { ignored_uvc_devices: nextIgnoredIds },
    };

    if (shouldIgnore && device.suggestion?.matched_camera_id) {
      payload.cameras = cameras
        .filter((camera) => camera.id !== device.suggestion?.matched_camera_id)
        .map((camera) => serializeCamera(camera));
    }

    try {
      await api.patchRuntimeConfig(payload);
      await api.applyConfig();
      setNotice(
        shouldIgnore
          ? device.suggestion?.matched_camera_id
            ? "Device ignored. Matching managed camera was removed from the system."
            : "Device ignored and excluded from future discovery suggestions."
          : "Device restored to UVC discovery.",
      );
      setError("");
      onUiConfigChanged?.();
      await loadAll(true);
    } catch (e) {
      saveError(e, "Failed to update ignored device list");
    } finally { setLoading(false); }
  };

  const onIgnoreManagedUvcCamera = async (camera: ConfiguredCamera): Promise<void> => {
    if (!requireSavedDraft() || loading) return;
    setLoading(true);
    const ignoredIds = runtime.device_discovery?.ignored_uvc_devices ?? [];
    const cameraKeys = getManagedUvcCameraMatchKeys(camera);
    try {
      await api.patchRuntimeConfig({
        cameras: cameras.filter((item) => item.id !== camera.id).map((item) => serializeCamera(item)),
        device_discovery: { ignored_uvc_devices: uniqueIdentifiers([...ignoredIds, ...cameraKeys]) },
      });
      await api.applyConfig();
      setNotice("Managed UVC camera removed and its device signature was added to the ignore list.");
      setError("");
      onUiConfigChanged?.();
      await loadAll(true);
    } catch (e) {
      saveError(e, "Failed to remove managed UVC camera");
    } finally { setLoading(false); }
  };

  const loadAll = async (refreshDevices = false): Promise<void> => {
    const request = ++loadRequest.current;
    probeRequests.current.clear();
    setIpProbeStates({});
    setLoading(true);
    setConfigReady(false);
    try {
      let deviceError = "";
      const [runtimeRes, uvcRes, multiviewStatusRes, listenerRes] = await Promise.all([
        api.getRuntimeConfig(),
        api.getUvcDevices(refreshDevices).catch((e) => {
          deviceError = `USB discovery unavailable: ${e instanceof Error ? e.message : "Request failed"}. Other settings are available; Refresh to retry.`;
          return { items: [], warning: deviceError };
        }),
        api.getMultiviewStatus().catch(() => ({ updated_at: null, views: [] } as MultiviewStatus)),
        api.getListener().catch(() => ({})),
      ]);
      if (request !== loadRequest.current) return;
      setListener(listenerRes);

      // Editable cameras must come from the same response as the configuration ETag.
      // A separate status request may observe a different administrator's revision.
      if (!Array.isArray(runtimeRes.cameras)) throw new Error("Camera configuration is unavailable. Refresh to retry.");
      const configuredCameras = runtimeRes.cameras;
      const mergedRuntime = withDefaults(runtimeRes);
      setRuntime(mergedRuntime);
      setRuntimeJsonText(JSON.stringify(mergedRuntime, null, 2));
      setSavedJsonText(JSON.stringify(mergedRuntime, null, 2));
      setSavedRuntimeText(JSON.stringify(mergedRuntime));
      setSavedRuntimeSnapshot(mergedRuntime);

      setCameras(configuredCameras);
      setMultiviewStatus(multiviewStatusRes);
      setUvcDevices(uvcRes.items);
      setUvcWarning(uvcRes.warning ?? "");
      if (uvcRes.items.length > 0) {
        const nextSelectedId =
          uvcRes.items.find((item) => item.device_id === selectedDeviceId)?.device_id ??
          uvcRes.items.find((item) => !item.ignored)?.device_id ??
          uvcRes.items[0]?.device_id ??
          "";
        if (nextSelectedId) {
          applySelectedDeviceDraft(nextSelectedId, uvcRes.items, configuredCameras);
        }
      } else {
        setSelectedDeviceId("");
        setSuggestBitrate("");
        setSuggestion(null);
        setSelectedModeKey("");
      }

      const nextIpDrafts = configuredCameras
        .filter((camera) => camera.type === "ip")
        .map(
          (camera): IpCameraDraft => ({
            id: camera.id,
            type: "ip",
            enabled: camera.enabled,
            path: camera.path,
            display_name: camera.display_name ?? "",
            ip: {
              source_url: camera.ip?.source_url ?? "",
              relay_mode: camera.ip?.relay_mode ?? DEFAULT_IP_CAMERA_SETTINGS.relay_mode,
              timestamp_mode: camera.ip?.timestamp_mode ?? DEFAULT_IP_CAMERA_SETTINGS.timestamp_mode,
              cfr_fps: camera.ip?.cfr_fps ?? DEFAULT_IP_CAMERA_SETTINGS.cfr_fps,
              onvif_mode: camera.ip?.onvif_mode ?? DEFAULT_IP_CAMERA_SETTINGS.onvif_mode,
              onvif_address: camera.ip?.onvif_address ?? DEFAULT_IP_CAMERA_SETTINGS.onvif_address,
              onvif_username: camera.ip?.onvif_username ?? DEFAULT_IP_CAMERA_SETTINGS.onvif_username,
              onvif_password: camera.ip?.onvif_password ?? DEFAULT_IP_CAMERA_SETTINGS.onvif_password,
              ptz: {
                ...DEFAULT_IP_CAMERA_SETTINGS.ptz,
                ...(camera.ip?.ptz ?? {}),
                profile_token: camera.ip?.ptz?.profile_token ?? "",
              },
              multiview_input: {
                ...DEFAULT_IP_CAMERA_SETTINGS.multiview_input,
                ...(camera.ip?.multiview_input ?? {}),
                profile_token: camera.ip?.multiview_input?.profile_token ?? "",
                manual_url: camera.ip?.multiview_input?.manual_url ?? "",
                resolution: camera.ip?.multiview_input?.resolution ?? "",
                encoder: camera.ip?.multiview_input?.encoder ?? "",
                quality_preset: camera.ip?.multiview_input?.quality_preset ?? "",
                bitrate: camera.ip?.multiview_input?.bitrate ?? "",
                maxrate: camera.ip?.multiview_input?.maxrate ?? "",
                bufsize: camera.ip?.multiview_input?.bufsize ?? "",
                x264_preset: camera.ip?.multiview_input?.x264_preset ?? "",
              },
              bitrate: camera.ip?.bitrate ?? DEFAULT_IP_CAMERA_SETTINGS.bitrate,
              maxrate: camera.ip?.maxrate ?? DEFAULT_IP_CAMERA_SETTINGS.maxrate,
              bufsize: camera.ip?.bufsize ?? DEFAULT_IP_CAMERA_SETTINGS.bufsize,
              gop: camera.ip?.gop ?? DEFAULT_IP_CAMERA_SETTINGS.gop,
              x264_preset: camera.ip?.x264_preset ?? DEFAULT_IP_CAMERA_SETTINGS.x264_preset,
              periodic_restart_enabled:
                camera.ip?.periodic_restart_enabled ?? DEFAULT_IP_CAMERA_SETTINGS.periodic_restart_enabled,
              periodic_restart_interval_sec:
                camera.ip?.periodic_restart_interval_sec ?? DEFAULT_IP_CAMERA_SETTINGS.periodic_restart_interval_sec,
              watchdog_enabled: camera.ip?.watchdog_enabled ?? DEFAULT_IP_CAMERA_SETTINGS.watchdog_enabled,
              watchdog_interval_sec:
                camera.ip?.watchdog_interval_sec ?? DEFAULT_IP_CAMERA_SETTINGS.watchdog_interval_sec,
              watchdog_timeout_sec:
                camera.ip?.watchdog_timeout_sec ?? DEFAULT_IP_CAMERA_SETTINGS.watchdog_timeout_sec,
              watchdog_failure_threshold:
                camera.ip?.watchdog_failure_threshold ?? DEFAULT_IP_CAMERA_SETTINGS.watchdog_failure_threshold,
            },
          }),
        );
      setIpDrafts(nextIpDrafts);
      setSavedIpDraftsText(JSON.stringify(nextIpDrafts));
      setConfigReady(true);
      setLastRefreshedAt(
        new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date()),
      );
      setError("");
    } catch (e) {
      if (request !== loadRequest.current) return;
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      if (request === loadRequest.current) setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSelectDevice = (deviceId: string): void => {
    applySelectedDeviceDraft(deviceId, uvcDevices, cameras);
  };

  const onPreviewSuggestion = async (): Promise<void> => {
    if (!selectedDeviceId) {
      return;
    }
    try {
      const response = await api.suggestUvcDevice(selectedDeviceId, {
        profile: suggestProfile,
        path: suggestPath,
        camera_name: suggestName,
        width: suggestWidth,
        height: suggestHeight,
        fps: suggestFps,
        bitrate: suggestBitrate,
      });
      setSuggestion(response.suggestion as UvcSuggestion);
      setNotice("Suggestion updated.");
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to preview suggestion");
    }
  };

  const onApplyUvc = async (): Promise<void> => {
    if (!requireSavedDraft() || loading) return;
    if (!selectedDeviceId) {
      return;
    }
    setLoading(true);
    try {
      await api.applyUvcDevice(selectedDeviceId, {
        profile: suggestProfile,
        path: suggestPath,
        camera_name: suggestName,
        width: suggestWidth,
        height: suggestHeight,
        fps: suggestFps,
        bitrate: suggestBitrate,
      });
      setNotice("UVC device applied.");
      await loadAll(true);
    } catch (e) {
      saveError(e, "Failed to apply UVC device");
    } finally { setLoading(false); }
  };

  const onAddIpDraft = (): void => {
    const used = new Set([...cameras.flatMap(c => [c.id, c.path]), ...ipDrafts.flatMap(c => [c.id, c.path])].map(value => value.toLowerCase()));
    let idx = 1;
    while (used.has(`ipcam${idx}`)) idx++;
    setIpDrafts((prev) => [
      ...prev,
      {
        id: `ipcam${idx}`,
        type: "ip",
        enabled: true,
        path: `ipcam${idx}`,
        display_name: "",
        ip: { ...DEFAULT_IP_CAMERA_SETTINGS },
      },
    ]);
  };

  const onUpdateIpDraft = (
    idx: number,
    patch: Partial<Omit<IpCameraDraft, "ip">> & { ip?: Partial<IpCameraDraft["ip"]> },
  ): void => {
    const id = ipDrafts[idx]?.id;
    if (id) {
      probeRequests.current.delete(id);
      setIpProbeStates(prev => { const next = { ...prev }; delete next[id]; return next; });
    }
    setIpDrafts((prev) =>
      prev.map((item, i) => {
        if (i !== idx) {
          return item;
        }
        return {
          ...item,
          ...patch,
          ip: { ...item.ip, ...(patch.ip ?? {}) },
        };
      }),
    );
  };

  const onInspectIpCamera = async (idx: number, force = true): Promise<void> => {
    const draft = ipDrafts[idx];
    if (!draft) {
      return;
    }
    const sourceUrl = draft.ip.source_url.trim();
    if (!sourceUrl) {
      setIpProbeStates((prev) => ({
        ...prev,
        [draft.id]: { requestKey: "", loading: false, error: "Enter a Source URL first.", result: null },
      }));
      return;
    }
    const requestKey = JSON.stringify({
      sourceUrl,
      onvifMode: draft.ip.onvif_mode,
      onvifAddress: draft.ip.onvif_address.trim(),
      onvifUsername: draft.ip.onvif_username.trim(),
    });
    const existing = ipProbeStates[draft.id];
    if (!force && existing?.requestKey === requestKey && existing.result) {
      return;
    }
    const request = Symbol();
    probeRequests.current.set(draft.id, request);
    setIpProbeStates((prev) => ({
      ...prev,
      [draft.id]: { requestKey, loading: true, error: "", result: null },
    }));
    try {
      const result = await api.probeIpCamera({
        camera_id: draft.id,
        force,
        source_url: sourceUrl,
        probe_duration_sec: 6,
        onvif_mode: draft.ip.onvif_mode,
        onvif_address: draft.ip.onvif_address.trim() || null,
        onvif_username: draft.ip.onvif_username.trim() || null,
        onvif_password: draft.ip.onvif_password || null,
      });
      if (probeRequests.current.get(draft.id) !== request) return;
      setIpProbeStates((prev) => ({
        ...prev,
        [draft.id]: { requestKey, loading: false, error: "", result },
      }));
    } catch (e) {
      if (probeRequests.current.get(draft.id) !== request) return;
      setIpProbeStates((prev) => ({
        ...prev,
        [draft.id]: {
          requestKey,
          loading: false,
          error: e instanceof Error ? e.message : "Camera inspection failed",
          result: null,
        },
      }));
    }
  };

  const onRemoveIpDraft = (idx: number): void => {
    const removedId = ipDrafts[idx]?.id;
    setIpDrafts((prev) => prev.filter((_, i) => i !== idx));
    if (removedId) {
      probeRequests.current.delete(removedId);
      setIpProbeStates((prev) => {
        const next = { ...prev };
        delete next[removedId];
        return next;
      });
    }
  };

  const onInstallationAction = async (action: () => Promise<void>): Promise<void> => {
    setLoading(true);
    setError("");
    setNotice("");
    try { await action(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not complete this action"); }
    finally { setLoading(false); }
  };

  const onBrowseRecordingFolder = (): void => {
    void onInstallationAction(async () => {
      const result = await api.pickFolder();
      if (result.path) setRuntime(prev => ({ ...prev, recording: { ...prev.recording, record_root: result.path } }));
    });
  };

  const onSuggestRecordingCapacity = (): void => {
    void onInstallationAction(async () => {
      const result = await api.suggestStorage(runtime.recording?.record_root ?? "");
      setRuntime(prev => ({ ...prev, recording: { ...prev.recording, record_root: result.path,
        max_bytes: Math.floor(result.max_bytes / 1e8) * 1e8 } }));
      setNotice("Suggested capacity added to your changes. Choose Save changes to apply it.");
    });
  };

  const onSaveBasic = async (restart = false): Promise<void> => {
    if (loading || !configReady) return;
    if (jsonDirty) { setError("Advanced JSON has unsaved edits. Apply them in Advanced, or discard those edits before saving the form."); return; }
    if (
      restart &&
      !window.confirm(
        "Restart the entire stack? All individual RTSP/WebRTC camera streams will disconnect temporarily. Normal setting changes do not require this.",
      )
    ) {
      return;
    }
    setLoading(true);
    try {
      const paths = [...cameras.filter(c => c.type !== "ip").map(c => c.path.trim()), ...ipDrafts.map(c => c.path.trim())];
      if (paths.some(path => !path)) throw new Error("Every camera needs a nonempty path.");
      if (new Set(paths.map(path => path.toLowerCase())).size !== paths.length) throw new Error("Camera paths must be unique. Change the duplicate path before saving.");
      const recording = { ...runtime.recording };
      if (recording.managed_storage) {
        if (recording.max_bytes != null && (!Number.isFinite(recording.max_bytes) || recording.max_bytes <= 0)) {
          throw new Error("Enter a positive recording capacity.");
        }
        if (!(retentionDays(recording.record_delete_after ?? "") > 0)) {
          throw new Error("Enter a positive recording retention period.");
        }
        if (recording.record_root !== savedRuntimeSnapshot?.recording?.record_root) {
          const result = await api.suggestStorage(recording.record_root ?? "");
          recording.record_root = result.path;
        }
      }
      const nonIpCameras = cameras.filter((camera) => camera.type !== "ip").map((camera) => serializeCamera(camera));

      const payload = {
        api: runtime.api,
        auth: {
          provider: runtime.auth?.provider,
          viewer_auth_required: runtime.auth?.viewer_auth_required,
          session_cookie_name: runtime.auth?.session_cookie_name,
          session_ttl_sec: runtime.auth?.session_ttl_sec,
          oidc_issuer_url: runtime.auth?.oidc_issuer_url,
          oidc_client_id: runtime.auth?.oidc_client_id,
          oidc_redirect_uri: runtime.auth?.oidc_redirect_uri,
          oidc_scopes: runtime.auth?.oidc_scopes,
        },
        ui: runtime.ui,
        logging: runtime.logging,
        snapshot: runtime.snapshot,
        mediamtx: runtime.mediamtx,
        device_discovery: runtime.device_discovery,
        recording,
        multiview: runtime.multiview,
        cameras: [
          ...nonIpCameras,
          ...ipDrafts.map((draft) => ({
            id: draft.path.trim(),
            type: "ip" as const,
            enabled: draft.enabled,
            path: draft.path.trim(),
            display_name: draft.display_name.trim() || null,
            ip: {
              source_url: draft.ip.source_url.trim(),
              relay_mode: draft.ip.relay_mode,
              timestamp_mode: draft.ip.timestamp_mode,
              cfr_fps:
                Number.isFinite(draft.ip.cfr_fps) && draft.ip.cfr_fps > 0
                  ? draft.ip.cfr_fps
                  : DEFAULT_IP_CAMERA_SETTINGS.cfr_fps,
              onvif_mode: draft.ip.onvif_mode,
              onvif_address: draft.ip.onvif_address.trim() || null,
              onvif_username: draft.ip.onvif_username.trim() || null,
              onvif_password: draft.ip.onvif_password || null,
              ptz: {
                enabled: draft.ip.ptz.enabled,
                access: draft.ip.ptz.access,
                profile_token: draft.ip.ptz.profile_token.trim() || null,
                pan_tilt_speed: draft.ip.ptz.pan_tilt_speed,
                zoom_speed: draft.ip.ptz.zoom_speed,
                relative_step: draft.ip.ptz.relative_step,
              },
              multiview_input: {
                mode: draft.ip.multiview_input.mode,
                profile_token: draft.ip.multiview_input.profile_token.trim() || null,
                manual_url: draft.ip.multiview_input.manual_url.trim() || null,
                target_fps: draft.ip.multiview_input.target_fps,
                resolution: draft.ip.multiview_input.resolution.trim() || null,
                encoder: draft.ip.multiview_input.encoder.trim() || null,
                quality_preset: draft.ip.multiview_input.quality_preset || null,
                bitrate: draft.ip.multiview_input.bitrate.trim() || null,
                maxrate: draft.ip.multiview_input.maxrate.trim() || null,
                bufsize: draft.ip.multiview_input.bufsize.trim() || null,
                x264_preset: draft.ip.multiview_input.x264_preset.trim() || null,
                thread_queue_size: draft.ip.multiview_input.thread_queue_size,
                stall_timeout_sec: draft.ip.multiview_input.stall_timeout_sec,
              },
              bitrate: draft.ip.bitrate.trim() || null,
              maxrate: draft.ip.maxrate.trim() || null,
              bufsize: draft.ip.bufsize.trim() || null,
              gop:
                Number.isFinite(draft.ip.gop) && draft.ip.gop > 0
                  ? Math.round(draft.ip.gop)
                  : DEFAULT_IP_CAMERA_SETTINGS.gop,
              x264_preset: draft.ip.x264_preset.trim() || DEFAULT_IP_CAMERA_SETTINGS.x264_preset,
              periodic_restart_enabled: draft.ip.periodic_restart_enabled,
              periodic_restart_interval_sec:
                Number.isFinite(draft.ip.periodic_restart_interval_sec) && draft.ip.periodic_restart_interval_sec > 0
                  ? draft.ip.periodic_restart_interval_sec
                  : DEFAULT_IP_CAMERA_SETTINGS.periodic_restart_interval_sec,
              watchdog_enabled: draft.ip.watchdog_enabled,
              watchdog_interval_sec:
                Number.isFinite(draft.ip.watchdog_interval_sec) && draft.ip.watchdog_interval_sec > 0
                  ? draft.ip.watchdog_interval_sec
                  : DEFAULT_IP_CAMERA_SETTINGS.watchdog_interval_sec,
              watchdog_timeout_sec:
                Number.isFinite(draft.ip.watchdog_timeout_sec) && draft.ip.watchdog_timeout_sec > 0
                  ? draft.ip.watchdog_timeout_sec
                  : DEFAULT_IP_CAMERA_SETTINGS.watchdog_timeout_sec,
              watchdog_failure_threshold:
                Number.isFinite(draft.ip.watchdog_failure_threshold) && draft.ip.watchdog_failure_threshold > 0
                  ? Math.round(draft.ip.watchdog_failure_threshold)
                  : DEFAULT_IP_CAMERA_SETTINGS.watchdog_failure_threshold,
            },
          })),
        ],
      };

      await api.patchRuntimeConfig(payload);
      if (restart) {
        await api.restartControl();
      }
      setNotice(restart ? "Basic settings saved and all processes restarted." : "Basic settings saved and applied.");
      setError("");
      onUiConfigChanged?.();
      await loadAll(true);
    } catch (e) {
      saveError(e, "Failed to save settings");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (selectedModeOptions.length === 0) {
      if (selectedModeKey !== "") {
        setSelectedModeKey("");
      }
      return;
    }
    const nextModeOption = findExactModeOption(selectedModeOptions, suggestWidth, suggestHeight, suggestFps) ?? selectedModeOptions[0];
    if (selectedModeKey !== nextModeOption.key) {
      setSelectedModeKey(nextModeOption.key);
    }
    if (suggestWidth !== nextModeOption.width) {
      setSuggestWidth(nextModeOption.width);
    }
    if (suggestHeight !== nextModeOption.height) {
      setSuggestHeight(nextModeOption.height);
    }
    if (suggestFps !== nextModeOption.fps) {
      setSuggestFps(nextModeOption.fps);
    }
  }, [selectedModeKey, selectedModeOptions, suggestFps, suggestHeight, suggestWidth]);

  const onReplaceRuntime = async (restart = false): Promise<void> => {
    if (loading || !configReady) return;
    if (formDirty && !await ask("Replacing runtime JSON will discard unsaved form changes. Continue?")) return;
    if (
      restart &&
      !window.confirm(
        "Restart the entire stack? All individual RTSP/WebRTC camera streams will disconnect temporarily.",
      )
    ) {
      return;
    }
    setLoading(true);
    try {
      const parsed = JSON.parse(runtimeJsonText) as Record<string, unknown>;
      await api.putRuntimeConfig(parsed);
      if (restart) {
        await api.restartControl();
      }
      setNotice(
        restart
          ? "Advanced runtime JSON replaced and all processes restarted."
          : "Advanced runtime JSON replaced and applied.",
      );
      setError("");
      onUiConfigChanged?.();
      await loadAll(true);
    } catch (e) {
      saveError(e, "Failed to apply runtime JSON");
    } finally { setLoading(false); }
  };

  return (
    <SettingsHelp>
    {confirmation}
    <div className="page settings-page">
      <div className="settings-page-header">
        <div>
          <span className="settings-eyebrow">System preferences</span>
          <h2>Settings</h2>
        </div>
        <div className="settings-header-actions">
          <span className={hasUnsavedChanges ? "settings-save-state is-dirty" : "settings-save-state"}>
            {!configReady ? (loading ? "Loading settings…" : "Settings unavailable") : hasUnsavedChanges ? "Unsaved changes" : "All changes saved"}
          </span>
          <button
            type="button"
            className="settings-icon-button"
            onClick={async () => { if (await confirmDiscard()) void loadAll(true); }}
            disabled={loading}
          >
            <ArrowPathIcon aria-hidden="true" />
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          <button type="button" onClick={async () => { if (await confirmDiscard()) void loadAll(); }} disabled={!hasUnsavedChanges || loading}>
            Discard
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => void (mode === "advanced" && jsonDirty ? onReplaceRuntime() : onSaveBasic())}
            disabled={!hasUnsavedChanges || loading || !configReady}
          >
            Save changes
          </button>
        </div>
      </div>

      <div className="settings-search">
        <MagnifyingGlassIcon aria-hidden="true" />
        <input
          ref={settingsSearchRef}
          type="search"
          value={settingsSearch}
          onChange={(event) => setSettingsSearch(event.target.value)}
          placeholder="Find a setting..."
          aria-label="Find a setting"
        />
        <kbd>{/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘ K" : "Ctrl K"}</kbd>
      </div>

      <div className="settings-workspace">
        <aside className="settings-local-nav" aria-label="Settings categories">
          <div className="settings-local-nav-title">Configuration</div>
          {SETTINGS_NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                type="button"
                key={item.key}
                className={mode === item.key && !normalizedSettingsSearch ? "active" : ""}
                aria-current={mode === item.key && !normalizedSettingsSearch ? "page" : undefined}
                onClick={() => selectSettingsSection(item.key)}
              >
                <Icon aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </aside>

        <main className="settings-main">
          {notice && <div className="panel-ok">{notice}</div>}
          {error && <div className="panel-error">{error}</div>}
          {!savedRuntimeSnapshot && <p role="status">{loading ? "Loading saved settings…" : "Settings could not be loaded. Use Refresh to retry."}</p>}
          {savedRuntimeSnapshot && <fieldset className="settings-fields" disabled={loading || !configReady}>
          {uvcWarning && <p className="panel-note" role="status">{uvcWarning}</p>}

          {normalizedSettingsSearch && (
            <section className="settings-results" aria-live="polite">
              <div className="settings-content-heading">
                <div>
                  <span className="settings-eyebrow">Search results</span>
                  <h3>{settingsSearchResults.length} settings categories found</h3>
                  <p>Results for “{settingsSearch.trim()}”</p>
                </div>
              </div>
              <div className="settings-result-list">
                {settingsSearchResults.map((item) => (
                  <button
                    type="button"
                    key={item.label}
                    onClick={() => selectSettingsSection(item.section)}
                  >
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
                    </span>
                    <ChevronRightIcon aria-hidden="true" />
                  </button>
                ))}
                {settingsSearchResults.length === 0 && (
                  <div className="settings-empty-search">
                    <MagnifyingGlassIcon aria-hidden="true" />
                    <strong>No matching settings</strong>
                    <span>Search categories and common keywords such as “session”, “RTSP”, or “retention”.</span>
                  </div>
                )}
              </div>
            </section>
          )}

          {!normalizedSettingsSearch && mode === "quick" && (
            <div className="quick-settings">
              <div className="settings-content-heading">
                <div>
                  <span className="settings-eyebrow">Overview</span>
                  <h3>Quick settings</h3>
                  <p>The controls used most often during day-to-day operation.</p>
                </div>
                <button type="button" onClick={() => selectSettingsSection("general")}>
                  View all settings
                </button>
              </div>

              <div className="quick-status-strip" aria-label="System configuration status">
                <div className="ok">
                  <CheckCircleIcon aria-hidden="true" />
                  <span><strong>API listening now</strong><small>{listener.host && listener.port ? `${listener.host}:${listener.port}` : "Unavailable"}</small></span>
                </div>
                <div className={runtime.mediamtx?.autostart_on_api_start ? "ok" : "muted"}>
                  <CheckCircleIcon aria-hidden="true" />
                  <span><strong>MediaMTX Configured</strong><small>{runtime.mediamtx?.control_mode}</small></span>
                </div>
                <div className={runtime.recording?.enabled ? "ok" : "muted"}>
                  <CheckCircleIcon aria-hidden="true" />
                  <span><strong>Recording {runtime.recording?.enabled ? "Enabled" : "Disabled"}</strong><small>{runtime.recording?.record_format}</small></span>
                </div>
              </div>

              <div className="quick-settings-grid">
                <section className="quick-settings-primary">
                  <StartupSettings api={api} />
                  <h4>Frequently used</h4>
                  <div className="quick-setting-list">
                    <div className="quick-setting-row">
                      <span className="quick-setting-icon"><ShieldCheckIcon aria-hidden="true" /></span>
                      <span className="quick-setting-copy">
                        <strong>Viewer access</strong>
                        <small>Require viewers to sign in before opening camera streams.</small>
                      </span>
                      <label className="quick-toggle">
                        <input
                          type="checkbox"
                          checked={Boolean(runtime.auth?.viewer_auth_required)}
                          onChange={(event) =>
                            setRuntime((prev) => ({
                              ...prev,
                              auth: { ...(prev.auth ?? {}), viewer_auth_required: event.target.checked },
                            }))
                          }
                        />
                        <span>{runtime.auth?.viewer_auth_required ? "Required" : "Public"}</span>
                      </label>
                      <button type="button" className="quick-row-link" onClick={() => selectSettingsSection("runtime")} aria-label="Open viewer access settings">
                        <ChevronRightIcon aria-hidden="true" />
                      </button>
                    </div>

                    <div className="quick-setting-row">
                      <span className="quick-setting-icon"><VideoCameraIcon aria-hidden="true" /></span>
                      <span className="quick-setting-copy">
                        <strong>Recording</strong>
                        <small>{recordAllCameras ? "All configured cameras" : "Selected camera paths"} · {runtime.recording?.record_format}</small>
                      </span>
                      <label className="quick-toggle">
                        <input
                          type="checkbox"
                          checked={Boolean(runtime.recording?.enabled)}
                          onChange={(event) =>
                            setRuntime((prev) => ({
                              ...prev,
                              recording: { ...(prev.recording ?? {}), enabled: event.target.checked },
                            }))
                          }
                        />
                        <span>{runtime.recording?.enabled ? "Enabled" : "Disabled"}</span>
                      </label>
                      <button type="button" className="quick-row-link" onClick={() => selectSettingsSection("recording")} aria-label="Open recording settings">
                        <ChevronRightIcon aria-hidden="true" />
                      </button>
                    </div>

                    <div className="quick-setting-row">
                      <span className="quick-setting-icon"><DocumentTextIcon aria-hidden="true" /></span>
                      <span className="quick-setting-copy">
                        <strong>Log level</strong>
                        <small>Choose how much diagnostic detail is written to logs.</small>
                      </span>
                      <select
                        aria-label="Log level"
                        value={runtime.logging?.level ?? "ERROR"}
                        onChange={(event) =>
                          setRuntime((prev) => ({
                            ...prev,
                            logging: {
                              ...(prev.logging ?? {}),
                              level: event.target.value as "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL",
                            },
                          }))
                        }
                      >
                        <option value="DEBUG">DEBUG</option>
                        <option value="INFO">INFO</option>
                        <option value="WARNING">WARNING</option>
                        <option value="ERROR">ERROR</option>
                        <option value="CRITICAL">CRITICAL</option>
                      </select>
                      <button type="button" className="quick-row-link" onClick={() => selectSettingsSection("logging")} aria-label="Open logging settings">
                        <ChevronRightIcon aria-hidden="true" />
                      </button>
                    </div>

                    <div className="quick-setting-row">
                      <span className="quick-setting-icon"><ArrowPathIcon aria-hidden="true" /></span>
                      <span className="quick-setting-copy">
                        <strong>Thumbnail refresh</strong>
                        <small>How often Live View thumbnails refresh automatically.</small>
                      </span>
                      <div className="quick-stepper" aria-label="Thumbnail refresh interval">
                        <button
                          type="button"
                          onClick={() =>
                            setRuntime((prev) => ({
                              ...prev,
                              snapshot: {
                                ...(prev.snapshot ?? {}),
                                thumbnail_refresh_interval_sec: Math.max(
                                  0.5,
                                  (prev.snapshot?.thumbnail_refresh_interval_sec ?? 10) - 5,
                                ),
                              },
                            }))
                          }
                          aria-label="Decrease thumbnail refresh interval"
                        >
                          <MinusIcon aria-hidden="true" />
                        </button>
                        <span>{runtime.snapshot?.thumbnail_refresh_interval_sec ?? 10} sec</span>
                        <button
                          type="button"
                          onClick={() =>
                            setRuntime((prev) => ({
                              ...prev,
                              snapshot: {
                                ...(prev.snapshot ?? {}),
                                thumbnail_refresh_interval_sec: Math.min(
                                  3600,
                                  (prev.snapshot?.thumbnail_refresh_interval_sec ?? 10) + 5,
                                ),
                              },
                            }))
                          }
                          aria-label="Increase thumbnail refresh interval"
                        >
                          <PlusIcon aria-hidden="true" />
                        </button>
                      </div>
                      <button type="button" className="quick-row-link" onClick={() => selectSettingsSection("runtime")} aria-label="Open thumbnail refresh settings">
                        <ChevronRightIcon aria-hidden="true" />
                      </button>
                    </div>
                  </div>

                  <h4>Configuration shortcuts</h4>
                  <div className="settings-shortcuts">
                    <button type="button" onClick={() => selectSettingsSection("mediamtx")}>
                      <SignalIcon aria-hidden="true" />
                      <span><strong>Network endpoints</strong><small>API, RTSP, and WebRTC URLs</small></span>
                      <ChevronRightIcon aria-hidden="true" />
                    </button>
                    <button type="button" onClick={() => selectSettingsSection("recording")}>
                      <VideoCameraIcon aria-hidden="true" />
                      <span><strong>Storage & retention</strong><small>Formats and deletion policies</small></span>
                      <ChevronRightIcon aria-hidden="true" />
                    </button>
                    <button type="button" onClick={() => selectSettingsSection("general")}>
                      <Cog6ToothIcon aria-hidden="true" />
                      <span><strong>Branding</strong><small>Titles and footer text</small></span>
                      <ChevronRightIcon aria-hidden="true" />
                    </button>
                  </div>
                </section>

                <aside className="quick-settings-aside">
                  <section>
                    <div className="quick-aside-heading">
                      <div>
                        <span className="settings-eyebrow">This session</span>
                        <h4>Pending changes</h4>
                      </div>
                    </div>
                    {quickChangeItems.length > 0 ? (
                      <div className="quick-change-list">
                        {quickChangeItems.map((item) => (
                          <div key={item.label}>
                            <span className="change-dot" />
                            <span><strong>{item.label}</strong><small>{item.value}</small></span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="quick-empty-state">
                        <CheckCircleIcon aria-hidden="true" />
                        <span><strong>No pending changes</strong><small>Last refreshed at {lastRefreshedAt || "—"}</small></span>
                      </div>
                    )}
                    <div className="quick-aside-actions">
                      <button type="button" onClick={async () => { if (await confirmDiscard()) void loadAll(); }} disabled={!hasUnsavedChanges}>Discard</button>
                      <button type="button" className="primary" onClick={() => void onSaveBasic()} disabled={!hasUnsavedChanges}>Save changes</button>
                    </div>
                  </section>

                  <section className="quick-search-help">
                    <MagnifyingGlassIcon aria-hidden="true" />
                    <div>
                      <strong>Need an advanced setting?</strong>
                      <p>Search settings categories and common keywords.</p>
                      <small>Try “Session TTL”, “RTSP Base URL”, or “Snapshot Timeout”.</small>
                    </div>
                    <button type="button" onClick={() => settingsSearchRef.current?.focus()}>Search settings categories</button>
                  </section>
                </aside>
              </div>
            </div>
          )}

          {!normalizedSettingsSearch && mode !== "quick" && mode !== "advanced" && (
          <div className="settings-detail" data-settings-filter={mode}>
            <div className="settings-content-heading">
              <div>
                <span className="settings-eyebrow">Configuration</span>
                <h3>{SETTINGS_NAV_ITEMS.find((item) => item.key === mode)?.label}</h3>
                <p>Edit this category without losing your place in the rest of the system settings.</p>
              </div>
            </div>
          <div className="section settings-section settings-section-general">
            <h3>Web App</h3>
            <div className="form-grid">
              <label>
                App Title
                <input
                  value={runtime.ui?.app_title ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      ui: { ...(prev.ui ?? {}), app_title: e.target.value },
                    }))
                  }
                />
              </label>
              <label>
                Sidebar Title
                <input
                  value={runtime.ui?.sidebar_title ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      ui: { ...(prev.ui ?? {}), sidebar_title: e.target.value },
                    }))
                  }
                />
              </label>
              <label>
                Footer Text
                <input
                  value={runtime.ui?.footer_text ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      ui: { ...(prev.ui ?? {}), footer_text: e.target.value },
                    }))
                  }
                />
              </label>
            </div>
          </div>

          {installation && (
            <div className="section settings-section settings-section-general">
              <h3>Software updates</h3>
              <div className="settings-field-actions">
                <button type="button" disabled={loading} onClick={() => void onInstallationAction(async () => {
                  const release = await api.getUpdates();
                  setUpdateMessage(release.message ?? (release.available
                    ? `Version ${release.version} is available. Stop monitoring before installing the update.`
                    : `You are using version ${release.current_release ?? release.current}${release.channel === 'preview' ? ' (Under Development)' : ''}. No newer release is available.`));
                })}>Check for updates</button>
                <a href="https://github.com/noguhiro2002/FlintEye/releases" target="_blank" rel="noreferrer">Download community releases</a>
              </div>
              {updateMessage && <p className="field-help" role="status">{updateMessage}</p>}
            </div>
          )}

          <div className="section settings-section settings-section-runtime">
            <h3>Core Runtime</h3>
            <div className="form-grid">
              <div className="runtime-subsection-title form-span-3">
                <h4>API & Session</h4>
                <span>Saved connection and browser-session defaults for the FlintEye API.</span>
                <span>Listening now: {listener.host && listener.port ? `${listener.host}:${listener.port} (${listener.source})` : "Unavailable"}. Host and port changes apply after restarting FlintEye. A command-line override takes precedence for that launch.</span>
              </div>
              <label>
                API Host
                <input
                  value={runtime.api?.host ?? "127.0.0.1"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      api: { ...(prev.api ?? {}), host: e.target.value },
                    }))
                  }
                />
                <small className="field-help">Saved listening interface for the next launch.</small>
              </label>
              <label>
                API Port
                <input
                  type="number"
                  min={1}
                  max={65535}
                  value={runtime.api?.port ?? 18080}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      api: { ...(prev.api ?? {}), port: Number(e.target.value) },
                    }))
                  }
                />
                <small className="field-help">Saved TCP port for the next launch; --port can override it.</small>
              </label>
              <label>
                Session TTL (sec)
                <input
                  type="number"
                  min={60}
                  value={runtime.auth?.session_ttl_sec ?? 43200}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      auth: { ...(prev.auth ?? {}), session_ttl_sec: Number(e.target.value) },
                    }))
                  }
                />
                <small className="field-help">Time-to-live for authenticated browser sessions.</small>
              </label>
              <label>
                Session Cookie Name
                <input
                  value={runtime.auth?.session_cookie_name ?? "orch_session"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      auth: { ...(prev.auth ?? {}), session_cookie_name: e.target.value },
                    }))
                  }
                />
                <small className="field-help">Cookie name used to store the authenticated session.</small>
              </label>
              <div className="runtime-subsection-title form-span-3">
                <h4>Authentication</h4>
                <span>Choose the authentication backend and whether viewers must sign in.</span>
              </div>
              <label>
                Auth Provider
                <select
                  value={runtime.auth?.provider ?? "legacy_token"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      auth: { ...(prev.auth ?? {}), provider: e.target.value as "legacy_token" | "local" | "oidc" },
                    }))
                  }
                >
                  <option value="legacy_token">legacy_token</option>
                  <option value="local">local</option>
                  <option value="oidc">oidc (not implemented)</option>
                </select>
                <small className="field-help">Authentication backend used by the system.</small>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={Boolean(runtime.auth?.viewer_auth_required)}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      auth: { ...(prev.auth ?? {}), viewer_auth_required: e.target.checked },
                    }))
                  }
                />
                <span className="runtime-check-copy">
                  Viewer authentication required
                  <small>Require authentication before viewers can access the application.</small>
                </span>
              </label>
              {installation && runtime.auth?.provider === "local" && (
                <div className="form-field form-span-3">
                  <label htmlFor="viewer-password">New viewer password</label>
                  <div className="settings-field-actions">
                    <input id="viewer-password" type="password" autoComplete="new-password" minLength={12} maxLength={1024}
                      value={viewerPassword} disabled={loading} onChange={e => setViewerPassword(e.target.value)} />
                    <button type="button" disabled={loading || hasUnsavedChanges || viewerPassword.length < 12 || viewerPassword.length > 1024}
                      onClick={() => void onInstallationAction(async () => {
                        await api.setViewerPassword(viewerPassword);
                        setViewerPassword("");
                        onUiConfigChanged?.();
                      })}>Set viewer password and sign in again</button>
                  </div>
                  <small className="field-help">Use 12–1024 characters. Changing this password signs everyone out.</small>
                  {hasUnsavedChanges && <small className="field-help">Save or discard your other changes before changing the password.</small>}
                </div>
              )}
              <details className="runtime-advanced form-span-3">
                <summary>
                  <span>
                    <strong>Advanced runtime options</strong>
                    <small>Usernames, snapshot timeout, and thumbnail refresh defaults.</small>
                  </span>
                </summary>
                <div className="runtime-advanced-grid">
                  <label>
                    Admin Username
                    <input
                      value={runtime.auth?.local?.admin?.username ?? "admin"}
                      readOnly
                    />
                  </label>
                  <label>
                    Viewer Username
                    <input
                      value={runtime.auth?.local?.viewer?.username ?? "viewer"}
                      readOnly
                    />
                  </label>
                  <label>
                    Snapshot Timeout (sec)
                    <input
                      type="number"
                      min={0.1}
                      max={120}
                      step={0.5}
                      value={runtime.snapshot?.timeout_sec ?? 3.0}
                      onChange={(e) =>
                        setRuntime((prev) => ({
                          ...prev,
                          snapshot: {
                            ...(prev.snapshot ?? {}),
                            timeout_sec: Number(e.target.value),
                          },
                        }))
                      }
                    />
                  </label>
                  <label>
                    Thumbnail Refresh Interval (sec)
                    <input
                      type="number"
                      min={0.5}
                      max={3600}
                      step={0.5}
                      value={runtime.snapshot?.thumbnail_refresh_interval_sec ?? 10.0}
                      onChange={(e) =>
                        setRuntime((prev) => ({
                          ...prev,
                          snapshot: {
                            ...(prev.snapshot ?? {}),
                            thumbnail_refresh_interval_sec: Number(e.target.value),
                          },
                        }))
                      }
                    />
                  </label>
                </div>
                {!installation && <div className="panel-note">
                  Usernames and passwords are changed with the account tool. Use <code>python3 tools/manage_auth.py init-local --runtime-file runtime.json</code>
                  {" "}or <code>python3 tools/manage_auth.py set-password --runtime-file runtime.json --role admin</code>.
                </div>}
              </details>
            </div>
          </div>

          <div className="section settings-section settings-section-logging">
            <h3>Logging</h3>
            <div className="form-grid">
              <label>
                Log Directory
                <input
                  value={runtime.logging?.directory ?? "./logs"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      logging: { ...(prev.logging ?? {}), directory: e.target.value },
                    }))
                  }
                />
              </label>
              <label>
                Log Level
                <select
                  value={runtime.logging?.level ?? "ERROR"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      logging: {
                        ...(prev.logging ?? {}),
                        level: e.target.value as "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL",
                      },
                    }))
                  }
                >
                  <option value="DEBUG">DEBUG</option>
                  <option value="INFO">INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                  <option value="CRITICAL">CRITICAL</option>
                </select>
              </label>
              <label>
                Log Retention
                <input
                  value={runtime.logging?.retention ?? ""}
                  placeholder="blank = use record delete after"
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      logging: {
                        ...(prev.logging ?? {}),
                        retention: e.target.value || null,
                      },
                    }))
                  }
                />
              </label>
            </div>
          </div>

          <div className="section settings-section settings-section-mediamtx">
            <h3>MediaMTX</h3>
            <div className="form-grid">
              <label>
                Control Mode
                <select
                  value={runtime.mediamtx?.control_mode ?? "systemd"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      mediamtx: { ...(prev.mediamtx ?? {}), control_mode: e.target.value },
                    }))
                  }
                >
                  <option value="windows_service">windows_service</option>
                  <option value="systemd">systemd</option>
                  <option value="launchd">launchd</option>
                  <option value="direct">direct</option>
                  <option value="external">external</option>
                  <option value="docker_compose">docker_compose (not implemented)</option>
                </select>
              </label>
              <label>
                Service Name
                <input
                  value={runtime.mediamtx?.service_name ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      mediamtx: { ...(prev.mediamtx ?? {}), service_name: e.target.value },
                    }))
                  }
                />
              </label>
              <label>
                RTSP Base URL
                <input
                  value={runtime.mediamtx?.rtsp_base_url ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      mediamtx: { ...(prev.mediamtx ?? {}), rtsp_base_url: e.target.value },
                    }))
                  }
                />
              </label>
              <label>
                Internal RTSP Base URL
                <input
                  value={runtime.mediamtx?.internal_rtsp_base_url ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      mediamtx: {
                        ...(prev.mediamtx ?? {}),
                        internal_rtsp_base_url: e.target.value,
                      },
                    }))
                  }
                />
                <small className="field-help">
                  Optional. Local publishers on the same machine should usually use `rtsp://127.0.0.1:8554`.
                </small>
              </label>
              <label>
                WebRTC Base URL
                <input
                  value={runtime.mediamtx?.webrtc_base_url ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      mediamtx: { ...(prev.mediamtx ?? {}), webrtc_base_url: e.target.value },
                    }))
                  }
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={Boolean(runtime.mediamtx?.autostart_on_api_start)}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      mediamtx: {
                        ...(prev.mediamtx ?? {}),
                        autostart_on_api_start: e.target.checked,
                      },
                    }))
                  }
                />
                Auto-start MediaMTX on API startup
              </label>
            </div>
          </div>

          <div className="section settings-section settings-section-recording">
            <h3>Recording</h3>
            <div className="form-grid">
              <label className="check">
                <input
                  type="checkbox"
                  checked={Boolean(runtime.recording?.enabled)}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        enabled: e.target.checked,
                      },
                    }))
                  }
                />
                Recording Enabled
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={recordAllCameras}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        record_all_cameras: e.target.checked,
                      },
                    }))
                  }
                />
                Record all configured cameras
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={Boolean(runtime.recording?.auto_apply)}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        auto_apply: e.target.checked,
                      },
                    }))
                  }
                />
                Auto apply recording config
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={Boolean(runtime.recording?.include_multiview)}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        include_multiview: e.target.checked,
                      },
                    }))
                  }
                />
                Include multiview paths
              </label>
              {!recordAllCameras && (
                <div className="form-field form-span-3">
                  <span>Recorded Camera Paths</span>
                  {sourceOptions.length > 0 ? (
                    <div className="source-option-grid">
                      {sourceOptions.map((option) => {
                        const selected = selectedRecordingPathSet.has(option.path.toLowerCase());
                        return (
                          <label
                            key={option.path}
                            className={`source-option${selected ? " selected" : ""}${option.enabled ? "" : " muted"}`}
                          >
                            <input
                              type="checkbox"
                              checked={selected}
                              onChange={(e) => onToggleRecordingKnownSource(option.path, e.target.checked)}
                            />
                            <span className="source-option-meta">
                              <strong>{option.label}</strong>
                              <small>
                                /{option.path} • {option.type.toUpperCase()}
                                {option.enabled ? "" : " • disabled"}
                              </small>
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="panel-empty">No configured cameras yet. Add/apply cameras first.</div>
                  )}
                  <small className="field-help">
                    Clear &quot;Record all configured cameras&quot; to record only the checked camera paths.
                  </small>
                </div>
              )}
              <label className="form-span-3">
                Additional Record Paths
                <textarea
                  rows={3}
                  value={extraRecordingSourcePaths.join("\n")}
                  onChange={(e) => onChangeExtraRecordingSourcePaths(e.target.value)}
                  placeholder={"custom_path_a\ncustom_path_b"}
                />
                <small className="field-help">
                  Optional extra MediaMTX paths to record even if they are not listed above.
                </small>
              </label>
              <div className="form-field form-span-3">
                <label htmlFor="recording-folder">Recording folder</label>
                <div className="settings-field-actions">
                  <input id="recording-folder" value={runtime.recording?.record_root ?? ""} disabled={loading}
                    onChange={e => setRuntime(prev => ({ ...prev, recording: { ...prev.recording, record_root: e.target.value } }))} />
                  {installation?.folder_picker && <button type="button" disabled={loading} onClick={onBrowseRecordingFolder}>Browse folders…</button>}
                </div>
                <small className="field-help">Choose a folder on the computer running FlintEye. Changing folders does not move existing recordings.</small>
              </div>
              {runtime.recording?.managed_storage && <>
                <div className="form-field">
                  <label htmlFor="recording-capacity">Maximum recording storage (GB)</label>
                  <input id="recording-capacity" type="number" min="0.1" step="0.1" disabled={loading}
                    value={runtime.recording.max_bytes == null || runtime.recording.max_bytes === 0 ? "" : Number((runtime.recording.max_bytes / 1e9).toFixed(1))}
                    placeholder="Not set"
                    onChange={e => setRuntime(prev => ({ ...prev, recording: { ...prev.recording,
                      max_bytes: Math.round(Number(e.target.value) * 1e9) } }))} />
                  {installation && <button type="button" disabled={loading} onClick={onSuggestRecordingCapacity}>Suggest from free space</button>}
                </div>
                <label>
                  Maximum retention (days)
                  <input type="number" min="0.000001" step="any" disabled={loading}
                    value={Number.isFinite(retentionDays(runtime.recording.record_delete_after ?? ""))
                      ? retentionDays(runtime.recording.record_delete_after ?? "") : ""}
                    onChange={e => setRuntime(prev => ({ ...prev, recording: { ...prev.recording,
                      record_delete_after: e.target.value === "" ? "" : `${Number(e.target.value) * 24}h` } }))} />
                </label>
                <label className="check form-span-3">
                  <input type="checkbox" checked={runtime.recording.show_previous ?? true} disabled={loading}
                    onChange={e => setRuntime(prev => ({ ...prev, recording: { ...prev.recording, show_previous: e.target.checked } }))} />
                  Show recordings from previous locations
                </label>
                <p className="panel-note form-span-3">Oldest completed recordings are deleted when either limit is reached.
                  Hiding previous locations does not stop their automatic cleanup. Use Save changes to apply your choices.</p>
              </>}
              <label>
                Record Format
                <select
                  value={runtime.recording?.record_format ?? "fmp4"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        record_format: e.target.value as "fmp4" | "mpegts",
                      },
                    }))
                  }
                >
                  <option value="fmp4">fmp4</option>
                  <option value="mpegts">mpegts</option>
                </select>
              </label>
              <label>
                Segment Duration
                <input
                  value={runtime.recording?.record_segment_duration ?? "10m"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        record_segment_duration: e.target.value,
                      },
                    }))
                  }
                />
              </label>
              {!runtime.recording?.managed_storage && (
              <label>
                Recording Delete After
                <input
                  value={runtime.recording?.record_delete_after ?? "168h"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        record_delete_after: e.target.value,
                      },
                    }))
                  }
                />
              </label>
              )}
              <label>
                Playback Cache Delete After
                <input
                  value={runtime.recording?.playback_cache_delete_after ?? "24h"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        playback_cache_delete_after: e.target.value,
                      },
                    }))
                  }
                />
                <small className="field-help">
                  Playback-friendly MP4 files are internal, omitted from Recordings, and deleted after this period.
                </small>
              </label>
              <label>
                Record Part Duration
                <input
                  value={runtime.recording?.record_part_duration ?? "1s"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        record_part_duration: e.target.value,
                      },
                    }))
                  }
                />
              </label>
              <label>
                Record Max Part Size
                <input
                  value={runtime.recording?.record_max_part_size ?? "50M"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      recording: {
                        ...(prev.recording ?? {}),
                        record_max_part_size: e.target.value,
                      },
                    }))
                  }
                />
              </label>
            </div>
            <div className="panel-note">
              Recording Enabled controls the `record: yes/no` flag for the resolved MediaMTX recording paths.
              Unselected orchestrator-managed paths are now forced to `record: no`.
            </div>
          </div>

          <div className="section settings-section settings-section-multiview">
            <h3>Multiview</h3>
            <div className="form-grid">
              <label className="check form-span-3">
                <input
                  type="checkbox"
                  checked={Boolean(runtime.multiview?.enabled)}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        enabled: e.target.checked,
                      },
                    }))
                  }
                />
                Multiview Enabled
              </label>
              <label>
                Source Mode
                <select
                  value={runtime.multiview?.source_mode ?? "hybrid"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        source_mode: e.target.value as "env" | "api" | "hybrid",
                      },
                    }))
                  }
                >
                  <option value="hybrid">hybrid</option>
                  <option value="env">env</option>
                  <option value="api">api</option>
                </select>
                <small className="field-help">env = selected paths only, api = MediaMTX API only, hybrid = both.</small>
              </label>
              <label>
                MediaMTX API URL
                <input
                  value={runtime.multiview?.mtx_api_url ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        mtx_api_url: e.target.value,
                      },
                    }))
                  }
                  placeholder="http://127.0.0.1:9997/v3/paths/list"
                />
                <small className="field-help">
                  Required for api/hybrid mode. Saving settings also syncs MediaMTX `api` and `apiAddress` to this URL. Use
                  `127.0.0.1` when multiview runs on the same machine.
                </small>
              </label>
              <label>
                Output Prefix
                <input
                  value={runtime.multiview?.output_prefix ?? "multiview"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        output_prefix: e.target.value,
                      },
                    }))
                  }
                />
                <small className="field-help">Output paths become {`<prefix>_1, <prefix>_2, ...`}.</small>
              </label>
              <label className="check form-span-3">
                <input
                  type="checkbox"
                  checked={runtime.multiview?.auto_placeholder_missing_sources ?? true}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        auto_placeholder_missing_sources: e.target.checked,
                      },
                    }))
                  }
                />
                Auto No Stream placeholders for missing MediaMTX paths
              </label>
              <div className="form-field form-span-3">
                <span>Source Cameras / Paths</span>
                {sourceOptions.length > 0 ? (
                  <div className="source-option-grid">
                    {sourceOptions.map((option) => {
                      const selected = selectedSourcePathSet.has(option.path.toLowerCase());
                      return (
                        <label
                          key={option.path}
                          className={`source-option${selected ? " selected" : ""}${option.enabled ? "" : " muted"}`}
                        >
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={(e) => onToggleKnownSource(option.path, e.target.checked)}
                          />
                          <span className="source-option-meta">
                            <strong>{option.label}</strong>
                            <small>
                              /{option.path} • {option.type.toUpperCase()}
                              {option.enabled ? "" : " • disabled"}
                            </small>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                ) : (
                  <div className="panel-empty">No configured cameras yet. Add/apply cameras first.</div>
                )}
                <small className="field-help">Multiview needs at least 2 usable source paths.</small>
              </div>
              <label className="form-span-3">
                Extra Source Paths
                <textarea
                  rows={3}
                  value={extraMultiviewSourcePaths.join("\n")}
                  onChange={(e) => onChangeExtraSourcePaths(e.target.value)}
                  placeholder={"custom_path_a\ncustom_path_b"}
                />
                <small className="field-help">Use this for paths that are not listed above but should still feed multiview.</small>
              </label>
              <label>
                Tile Count
                <input
                  type="number"
                  min={2}
                  max={32}
                  value={runtime.multiview?.tile_count ?? 4}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        tile_count: Number(e.target.value),
                      },
                    }))
                  }
                />
              </label>
              <label>
                Max Sources
                <input
                  type="number"
                  min={2}
                  max={128}
                  value={runtime.multiview?.max_sources ?? 32}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        max_sources: Number(e.target.value),
                      },
                    }))
                  }
                />
              </label>
              <label>
                Default IP Input
                <select
                  value={runtime.multiview?.input_defaults?.mode ?? "primary"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        input_defaults: {
                          ...(prev.multiview?.input_defaults ?? {}),
                          mode: e.target.value as "primary" | "normalized_primary",
                        },
                      },
                    }))
                  }
                >
                  <option value="primary">Primary path — current behavior</option>
                  <option value="normalized_primary">Normalize primary path</option>
                </select>
                <small className="field-help">Primary keeps one camera connection. Other modes may start an internal CFR worker.</small>
              </label>
              <label>
                Normalized Input FPS
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={runtime.multiview?.input_defaults?.target_fps ?? 10}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        input_defaults: {
                          ...(prev.multiview?.input_defaults ?? {}),
                          target_fps: Number(e.target.value) || 10,
                        },
                      },
                    }))
                  }
                />
              </label>
              <label>
                Normalized Resolution
                <input
                  value={runtime.multiview?.input_defaults?.resolution ?? "auto"}
                  placeholder="auto or 640x360"
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        input_defaults: {
                          ...(prev.multiview?.input_defaults ?? {}),
                          resolution: e.target.value || "auto",
                        },
                      },
                    }))
                  }
                />
              </label>
              <label>
                Normalized Input Quality
                <select
                  value={runtime.multiview?.input_defaults?.quality_preset ?? "standard"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        input_defaults: {
                          ...(prev.multiview?.input_defaults ?? {}),
                          quality_preset: e.target.value as "high" | "standard" | "low",
                        },
                      },
                    }))
                  }
                >
                  <option value="high">high</option>
                  <option value="standard">standard</option>
                  <option value="low">low</option>
                </select>
              </label>
              <details className="ip-camera-details form-span-2">
                <summary>Normalized input conversion details</summary>
                <div className="ip-detail-grid">
                  {(["encoder", "bitrate", "maxrate", "bufsize", "x264_preset"] as const).map((field) => (
                    <label key={field}>
                      {field}
                      <input
                        value={String(runtime.multiview?.input_defaults?.[field] ?? "")}
                        onChange={(e) =>
                          setRuntime((prev) => ({
                            ...prev,
                            multiview: {
                              ...(prev.multiview ?? {}),
                              input_defaults: {
                                ...(prev.multiview?.input_defaults ?? {}),
                                [field]: e.target.value,
                              },
                            },
                          }))
                        }
                      />
                    </label>
                  ))}
                </div>
              </details>
              <label className="table-check">
                <input
                  type="checkbox"
                  checked={runtime.multiview?.input_defaults?.fallback_to_primary ?? true}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        input_defaults: {
                          ...(prev.multiview?.input_defaults ?? {}),
                          fallback_to_primary: e.target.checked,
                        },
                      },
                    }))
                  }
                />
                Fall back to the public primary path
              </label>
              <section className="panel-note form-span-3 sync-buffer-settings">
                <div className="sync-buffer-heading">
                  <div>
                    <strong>Raw wall-clock compositor</strong>
                    <small>Decode inputs independently, select all tiles at one delayed server time, then encode only the completed canvas.</small>
                  </div>
                  <label className="table-check">
                    <input
                      type="checkbox"
                      checked={runtime.multiview?.sync_buffer?.enabled ?? false}
                      onChange={(e) => setRuntime((prev) => ({
                        ...prev,
                        multiview: {
                          ...(prev.multiview ?? {}),
                          sync_buffer: { ...(prev.multiview?.sync_buffer ?? {}), enabled: e.target.checked },
                        },
                      }))}
                    />
                    Enable synchronized raw composition
                  </label>
                </div>
                {runtime.multiview?.sync_buffer?.enabled && runtime.multiview?.input_defaults?.mode === "normalized_primary" && (
                  <small className="panel-note">
                    Primary is recommended. Normalize existing primary adds a redundant H.264 encode, internal RTSP hop, and decode before the raw ring buffer.
                  </small>
                )}
                <div className="ip-detail-grid">
                  <label>
                    Sync delay (sec)
                    <input type="number" min={0} max={60} step={0.5}
                      value={runtime.multiview?.sync_buffer?.delay_sec ?? 3}
                      onChange={(e) => setRuntime((prev) => ({ ...prev, multiview: { ...(prev.multiview ?? {}), sync_buffer: { ...(prev.multiview?.sync_buffer ?? {}), delay_sec: Number(e.target.value) } } }))}
                    />
                  </label>
                  <label>
                    Buffer capacity (sec)
                    <input type="number" min={1} max={120} step={0.5}
                      value={runtime.multiview?.sync_buffer?.buffer_sec ?? 5}
                      onChange={(e) => setRuntime((prev) => ({ ...prev, multiview: { ...(prev.multiview ?? {}), sync_buffer: { ...(prev.multiview?.sync_buffer ?? {}), buffer_sec: Number(e.target.value) } } }))}
                    />
                  </label>
                  <label>
                    Sync / output FPS
                    <input type="number" min={1} max={60}
                      value={runtime.multiview?.sync_buffer?.fps ?? 10}
                      onChange={(e) => setRuntime((prev) => ({ ...prev, multiview: { ...(prev.multiview ?? {}), sync_buffer: { ...(prev.multiview?.sync_buffer ?? {}), fps: Number(e.target.value) } } }))}
                    />
                  </label>
                  <label>
                    Late frame policy
                    <select value={runtime.multiview?.sync_buffer?.late_frame_policy ?? "hold"}
                      onChange={(e) => setRuntime((prev) => ({ ...prev, multiview: { ...(prev.multiview ?? {}), sync_buffer: { ...(prev.multiview?.sync_buffer ?? {}), late_frame_policy: e.target.value as "hold" | "no_stream" } } }))}
                    >
                      <option value="hold">Hold last frame, then No Stream</option>
                      <option value="no_stream">Show No Stream immediately</option>
                    </select>
                  </label>
                </div>
                <details className="ip-camera-details">
                  <summary>Sync buffer details</summary>
                  <div className="ip-detail-grid">
                    <label>
                      Maximum hold (sec)
                      <input type="number" min={0} max={3600} step={1}
                        value={runtime.multiview?.sync_buffer?.max_hold_sec ?? 10}
                        onChange={(e) => setRuntime((prev) => ({ ...prev, multiview: { ...(prev.multiview ?? {}), sync_buffer: { ...(prev.multiview?.sync_buffer ?? {}), max_hold_sec: Number(e.target.value) } } }))}
                      />
                    </label>
                    <label>
                      Memory limit / input (MB)
                      <input type="number" min={2} max={2048} step={1}
                        value={runtime.multiview?.sync_buffer?.memory_limit_mb_per_input ?? 64}
                        onChange={(e) => setRuntime((prev) => ({ ...prev, multiview: { ...(prev.multiview ?? {}), sync_buffer: { ...(prev.multiview?.sync_buffer ?? {}), memory_limit_mb_per_input: Number(e.target.value) } } }))}
                      />
                    </label>
                    <label>
                      Source reconnect (sec)
                      <input type="number" min={0.5} max={60} step={0.5}
                        value={runtime.multiview?.sync_buffer?.reconnect_sec ?? 2}
                        onChange={(e) => setRuntime((prev) => ({ ...prev, multiview: { ...(prev.multiview ?? {}), sync_buffer: { ...(prev.multiview?.sync_buffer ?? {}), reconnect_sec: Number(e.target.value) } } }))}
                      />
                    </label>
                  </div>
                </details>
              </section>
              <label>
                FPS
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={runtime.multiview?.quality?.fps ?? 10}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        quality: {
                          ...(prev.multiview?.quality ?? {}),
                          fps: Number(e.target.value),
                        },
                      },
                    }))
                  }
                />
                <small className="field-help">Final Multiview CFR rate. New configurations default to 10 fps.</small>
              </label>
              <label>
                Quality Preset
                <select
                  value={runtime.multiview?.quality?.quality_preset ?? "standard"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        quality: {
                          ...(prev.multiview?.quality ?? {}),
                          quality_preset: e.target.value as "high" | "standard" | "low",
                        },
                      },
                    }))
                  }
                >
                  <option value="high">high</option>
                  <option value="standard">standard</option>
                  <option value="low">low</option>
                </select>
              </label>
              <label>
                Encoder
                <input
                  value={runtime.multiview?.quality?.encoder ?? "auto"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        quality: {
                          ...(prev.multiview?.quality ?? {}),
                          encoder: e.target.value,
                        },
                      },
                    }))
                  }
                />
              </label>
              <label>
                Latency Preset
                <select
                  value={runtime.multiview?.latency_preset ?? "low"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        latency_preset: e.target.value as "normal" | "low",
                      },
                    }))
                  }
                >
                  <option value="low">low</option>
                  <option value="normal">normal</option>
                </select>
                <small className="field-help">low reduces buffering. normal is safer if inputs are unstable.</small>
              </label>
              <label>
                Input Stall Timeout (sec)
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={runtime.multiview?.input_stall_timeout_sec ?? 15}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        input_stall_timeout_sec: Number(e.target.value),
                      },
                    }))
                  }
                />
                <small className="field-help">Restarts multiview when an RTSP input stops responding. Use 0 to disable.</small>
              </label>
              <label>
                Input Stall Option
                <select
                  value={runtime.multiview?.input_stall_timeout_option ?? "auto"}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        input_stall_timeout_option: e.target.value as
                          | "auto"
                          | "rw_timeout"
                          | "stimeout"
                          | "timeout"
                          | "none",
                      },
                    }))
                  }
                >
                  <option value="auto">auto</option>
                  <option value="rw_timeout">rw_timeout</option>
                  <option value="stimeout">stimeout</option>
                  <option value="timeout">timeout</option>
                  <option value="none">none</option>
                </select>
                <small className="field-help">auto chooses an FFmpeg timeout option supported by this build.</small>
              </label>
              <label className="table-check">
                <input
                  type="checkbox"
                  checked={runtime.multiview?.input_healthcheck_enabled ?? true}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: { ...(prev.multiview ?? {}), input_healthcheck_enabled: e.target.checked },
                    }))
                  }
                />
                Monitor every Multiview input
              </label>
              <label>
                Health Check / Isolation / Retry
                <div className="ip-inline-fields">
                  <input
                    type="number"
                    min={1}
                    value={runtime.multiview?.input_healthcheck_interval_sec ?? 5}
                    aria-label="Multiview input health interval"
                    onChange={(e) => setRuntime((prev) => ({
                      ...prev,
                      multiview: { ...(prev.multiview ?? {}), input_healthcheck_interval_sec: Number(e.target.value) || 5 },
                    }))}
                  />
                  <input
                    type="number"
                    min={1}
                    value={runtime.multiview?.input_isolation_threshold ?? 3}
                    aria-label="Multiview input isolation threshold"
                    onChange={(e) => setRuntime((prev) => ({
                      ...prev,
                      multiview: { ...(prev.multiview ?? {}), input_isolation_threshold: Number(e.target.value) || 3 },
                    }))}
                  />
                  <input
                    type="number"
                    min={1}
                    value={runtime.multiview?.input_retry_interval_sec ?? 30}
                    aria-label="Multiview input retry interval"
                    onChange={(e) => setRuntime((prev) => ({
                      ...prev,
                      multiview: { ...(prev.multiview ?? {}), input_retry_interval_sec: Number(e.target.value) || 30 },
                    }))}
                  />
                </div>
                <small className="field-help">Seconds between checks / failures before No Stream / retry seconds.</small>
              </label>
              <label>
                Input Queue
                <input
                  type="number"
                  min={1}
                  value={runtime.multiview?.input_thread_queue_size ?? 128}
                  onChange={(e) => setRuntime((prev) => ({
                    ...prev,
                    multiview: { ...(prev.multiview ?? {}), input_thread_queue_size: Number(e.target.value) || 128 },
                  }))}
                />
                <small className="field-help">Normal uses this value; Low caps it at 32 packets.</small>
              </label>
              <label>
                Bitrate
                <input
                  value={runtime.multiview?.quality?.bitrate ?? ""}
                  placeholder="2M"
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        quality: {
                          ...(prev.multiview?.quality ?? {}),
                          bitrate: e.target.value,
                        },
                      },
                    }))
                  }
                />
                <small className="field-help">FFmpeg rate syntax. Examples: 2M, 800k, 4000000.</small>
              </label>
              <label>
                Maxrate
                <input
                  value={runtime.multiview?.quality?.maxrate ?? ""}
                  placeholder="2M"
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        quality: {
                          ...(prev.multiview?.quality ?? {}),
                          maxrate: e.target.value,
                        },
                      },
                    }))
                  }
                />
                <small className="field-help">Peak encoder bitrate. Usually equal to or slightly above bitrate.</small>
              </label>
              <label>
                Buffer Size
                <input
                  value={runtime.multiview?.quality?.bufsize ?? ""}
                  placeholder="4M"
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        quality: {
                          ...(prev.multiview?.quality ?? {}),
                          bufsize: e.target.value,
                        },
                      },
                    }))
                  }
                />
                <small className="field-help">Encoder rate-control buffer size, using the same units as bitrate/maxrate.</small>
              </label>
              <label>
                Input RTSP Base URL
                <input
                  value={runtime.multiview?.input_rtsp_base_url ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        input_rtsp_base_url: e.target.value,
                      },
                    }))
                  }
                />
              </label>
              <label>
                Output RTSP Base URL
                <input
                  value={runtime.multiview?.output_rtsp_base_url ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        output_rtsp_base_url: e.target.value,
                      },
                    }))
                  }
                />
              </label>
              <label>
                Grid Columns
                <input
                  type="number"
                  min={2}
                  max={8}
                  placeholder="auto"
                  value={runtime.multiview?.layout?.grid_columns ?? ""}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        layout: {
                          ...(prev.multiview?.layout ?? {}),
                          grid_columns: e.target.value ? Number(e.target.value) : null,
                        },
                      },
                    }))
                  }
                />
                <small className="field-help">
                  Leave blank for auto packing. Auto uses 2 columns for 2-4 tiles, 3 for 5-9, and 4 for 10+.
                </small>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={Boolean(runtime.multiview?.maintenance?.enabled)}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        maintenance: {
                          ...(prev.multiview?.maintenance ?? {}),
                          enabled: e.target.checked,
                        },
                      },
                    }))
                  }
                />
                Periodic multiview restart
              </label>
              <label>
                Restart Interval (sec)
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={runtime.multiview?.maintenance?.restart_interval_sec ?? 43200}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        maintenance: {
                          ...(prev.multiview?.maintenance ?? {}),
                          restart_interval_sec: Number(e.target.value),
                        },
                      },
                    }))
                  }
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={Boolean(runtime.multiview?.maintenance?.align_with_record_segments)}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        maintenance: {
                          ...(prev.multiview?.maintenance ?? {}),
                          align_with_record_segments: e.target.checked,
                        },
                      },
                    }))
                  }
                />
                Align with record segments
              </label>
              <label>
                Restart Offset (sec)
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={runtime.multiview?.maintenance?.restart_offset_sec ?? 2}
                  onChange={(e) =>
                    setRuntime((prev) => ({
                      ...prev,
                      multiview: {
                        ...(prev.multiview ?? {}),
                        maintenance: {
                          ...(prev.multiview?.maintenance ?? {}),
                          restart_offset_sec: Number(e.target.value),
                        },
                      },
                    }))
                  }
                />
              </label>
            </div>
            <div
              className={
                !runtime.multiview?.enabled || multiviewSourcePaths.length >= 2 ? "panel-note" : "panel-error"
              }
            >
              Selected multiview sources: {multiviewSourcePaths.length}. Enable multiview only after at least 2 working source paths are selected.
            </div>
          </div>

          <div className="section settings-section settings-section-cameras">
            <h3>UVC Camera Discovery</h3>
            {uvcWarning && <div className="panel-note">{uvcWarning}</div>}
            <div className="panel-list">
              <div className="panel-list-title">Managed UVC Cameras</div>
              {managedUvcCameraStates.length > 0 ? (
                <table className="table responsive-table managed-camera-table">
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Camera</th>
                      <th>Stored Device</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {managedUvcCameraStates.map(({ camera, detectedDevice }) => (
                      <tr key={camera.id}>
                        <td data-label="Status">
                          <span className={`status-tag ${detectedDevice ? "ok" : "muted"}`}>
                            {detectedDevice ? "detected" : "missing"}
                          </span>
                        </td>
                        <td data-label="Camera">
                          <strong>{getCameraLabel(camera)}</strong>
                          <div className="table-note">
                            /{camera.path}
                            {camera.enabled ? "" : " • disabled"}
                          </div>
                        </td>
                        <td data-label="Stored Device">
                          <code>{camera.uvc?.env?.DEVICE ?? "(unknown)"}</code>
                        </td>
                        <td data-label="Actions">
                          <div className="button-row wrap">
                            {detectedDevice && (
                              <button type="button" onClick={() => onSelectDevice(detectedDevice.device_id)}>
                                Select Device
                              </button>
                            )}
                            <button
                              type="button"
                              className="button-danger"
                              onClick={() => void onIgnoreManagedUvcCamera(camera)}
                            >
                              Ignore / Remove
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="panel-empty">No managed UVC cameras are configured yet.</div>
              )}
            </div>
            <div className="uvc-layout">
              <div className="uvc-device-groups">
                <div className="panel-list">
                  <div className="panel-list-title">Detected Devices</div>
                  {activeUvcDevices.length > 0 ? (
                    activeUvcDevices.map((device) => (
                      <button
                        key={device.device_id}
                        type="button"
                        className={device.device_id === selectedDeviceId ? "panel-list-item active" : "panel-list-item"}
                        onClick={() => onSelectDevice(device.device_id)}
                      >
                        <div className="panel-list-item-title">
                          <span>{device.display_name}</span>
                          <span className="status-tag ok">{device.driver}</span>
                        </div>
                        <small>
                          {device.recommended.width}x{device.recommended.height} @ {formatFps(device.recommended.fps)} fps
                        </small>
                      </button>
                    ))
                  ) : (
                    <div className="panel-empty">No active UVC devices detected.</div>
                  )}
                </div>

                <div className="panel-list">
                  <div className="panel-list-title">Ignored Devices</div>
                  {ignoredUvcDevices.length > 0 ? (
                    ignoredUvcDevices.map((device) => (
                      <button
                        key={device.device_id}
                        type="button"
                        className={device.device_id === selectedDeviceId ? "panel-list-item active ignored" : "panel-list-item ignored"}
                        onClick={() => onSelectDevice(device.device_id)}
                      >
                        <div className="panel-list-item-title">
                          <span>{device.display_name}</span>
                          <span className="status-tag muted">ignored</span>
                        </div>
                        <small>{device.driver}</small>
                      </button>
                    ))
                  ) : (
                    <div className="panel-empty">No ignored devices.</div>
                  )}
                </div>
              </div>

              <div className="form-grid">
                {selectedDevice ? (
                  <div className="uvc-device-summary form-span-3">
                    <div className="uvc-device-title-row">
                      <strong>{selectedDevice.display_name}</strong>
                      <span className={`status-tag ${selectedDevice.ignored ? "muted" : "ok"}`}>
                        {selectedDevice.ignored ? "ignored" : selectedDevice.driver}
                      </span>
                      <span className="status-tag">{selectedModeOptions.length} modes</span>
                    </div>
                    <div className="uvc-device-meta">
                      <span>FFmpeg device: {selectedDevice.ffmpeg_device}</span>
                      <span>
                        Recommended: {selectedDevice.recommended.width}x{selectedDevice.recommended.height} @{" "}
                        {formatFps(selectedDevice.recommended.fps)} fps
                      </span>
                      {selectedMatchedCamera && (
                        <span>
                          Current managed camera: {getCameraLabel(selectedMatchedCamera)} (/{selectedMatchedCamera.path})
                        </span>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="panel-empty form-span-3">Select a detected device to configure it.</div>
                )}
                <label>
                  Profile
                  <input value={suggestProfile} onChange={(e) => setSuggestProfile(e.target.value)} />
                </label>
                <label>
                  Path
                  <input value={suggestPath} onChange={(e) => setSuggestPath(e.target.value)} />
                </label>
                <label>
                  Camera Name
                  <input value={suggestName} onChange={(e) => setSuggestName(e.target.value)} />
                </label>
                <label>
                  Supported Mode
                  <select
                    value={selectedModeKey}
                    disabled={!selectedDevice || selectedModeOptions.length === 0}
                    onChange={(e) => {
                      const nextKey = e.target.value;
                      setSelectedModeKey(nextKey);
                      const modeOption = selectedModeOptions.find((item) => item.key === nextKey);
                      if (!modeOption) {
                        return;
                      }
                      setSuggestWidth(modeOption.width);
                      setSuggestHeight(modeOption.height);
                      setSuggestFps(modeOption.fps);
                    }}
                  >
                    {selectedModeOptions.map((modeOption) => (
                      <option key={modeOption.key} value={modeOption.key}>
                        {modeOption.label}
                      </option>
                    ))}
                  </select>
                  <small className="field-help">Use one of the capture modes reported by ffmpeg for this device.</small>
                </label>
                {selectedModeOptions.length > 0 ? (
                  <>
                    <label>
                      Width
                      <input type="number" min={1} value={suggestWidth} readOnly />
                    </label>
                    <label>
                      Height
                      <input type="number" min={1} value={suggestHeight} readOnly />
                    </label>
                    <label>
                      FPS
                      <input type="number" min={1} max={240} value={suggestFps} readOnly />
                      <small className="field-help">Width, height, and FPS follow the selected capture mode.</small>
                    </label>
                  </>
                ) : (
                  <>
                    <label>
                      Width
                      <input
                        type="number"
                        min={1}
                        value={suggestWidth}
                        onChange={(e) => setSuggestWidth(Number(e.target.value))}
                      />
                    </label>
                    <label>
                      Height
                      <input
                        type="number"
                        min={1}
                        value={suggestHeight}
                        onChange={(e) => setSuggestHeight(Number(e.target.value))}
                      />
                    </label>
                    <label>
                      FPS
                      <input
                        type="number"
                        min={1}
                        max={240}
                        value={suggestFps}
                        onChange={(e) => setSuggestFps(Number(e.target.value))}
                      />
                      <small className="field-help">The runtime stores integer FPS values.</small>
                    </label>
                  </>
                )}
                <label>
                  Bitrate
                  <input
                    value={suggestBitrate}
                    placeholder="2M"
                    onChange={(e) => setSuggestBitrate(e.target.value)}
                  />
                  <small className="field-help">Optional per-camera video bitrate. Leave blank to use preset/default behavior.</small>
                </label>
                <div className="form-span-3 panel-note">
                  {selectedDevice
                    ? selectedModeOptions.length > 0
                      ? `Probe returned ${selectedModeOptions.length} capture modes for this device. Select one from the list above.`
                      : "Detailed mode list is unavailable for this device/driver. Enter width, height, and FPS manually."
                    : "Select a device to see suggested settings and supported capture modes."}
                </div>
                <div className="button-row wrap form-span-3">
                  <button type="button" onClick={() => void onPreviewSuggestion()} disabled={!selectedDevice}>
                    Preview Suggestion
                  </button>
                  <button type="button" onClick={() => void onApplyUvc()} disabled={!selectedDevice}>
                    Apply Device
                  </button>
                  <button
                    type="button"
                    className={selectedDevice?.ignored ? "" : "button-danger"}
                    onClick={() => selectedDevice && void onToggleIgnoredDevice(selectedDevice)}
                    disabled={!selectedDevice}
                  >
                    {selectedDevice?.ignored ? "Restore to Discovery" : "Ignore / Remove from System"}
                  </button>
                </div>
                {suggestion && (
                  <div className="code-block">
                    <div>Suggested .env lines</div>
                    <pre>{suggestion.env_lines.join("\n")}</pre>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="section settings-section settings-section-cameras">
            <div className="section-head">
              <div>
                <h3>IP Cameras</h3>
                <p className="form-help">Inspect ONVIF capabilities and measured RTSP timing before publishing each camera.</p>
              </div>
              <button type="button" className="icon-text-button" onClick={onAddIpDraft}>
                <PlusIcon aria-hidden="true" />
                Add IP Camera
              </button>
            </div>
            <div className="ip-camera-list">
              {ipDrafts.map((draft, idx) => {
                const probeState = ipProbeStates[draft.id];
                const probe = probeState?.result;
                const ptzProfiles = (probe?.onvif.profiles ?? []).filter((profile) => profile.ptz?.supported);
                const ptzSupported = Boolean(probe?.onvif.ptz?.supported && ptzProfiles.length > 0);
                const ptzEvidence = ptzSupported || draft.ip.ptz.enabled;
                const effectiveMultiviewMode = draft.ip.multiview_input.mode === "inherit"
                  ? runtime.multiview?.input_defaults?.mode ?? "primary"
                  : draft.ip.multiview_input.mode;
                const effectiveMultiviewPath = effectiveMultiviewMode === "primary"
                  ? draft.path
                  : `__mv_input/${draft.path}`;
                const multiviewInputStatus = multiviewStatus.views
                  .flatMap((view) => view.inputs)
                  .find((input) => input.path === effectiveMultiviewPath);
                const encodeEnabled =
                  draft.ip.relay_mode === "libx264" || ["auto", "cfr"].includes(draft.ip.timestamp_mode);
                return (
                  <article className="ip-camera-card" key={draft.id}>
                    <header className="ip-camera-card-head">
                      <label className="ip-camera-enable">
                        <input
                          type="checkbox"
                          checked={draft.enabled}
                          onChange={(e) => onUpdateIpDraft(idx, { enabled: e.target.checked })}
                        />
                        <span>
                          <strong>{draft.display_name.trim() || draft.path || `IP Camera ${idx + 1}`}</strong>
                          <small>{draft.path || "Path not set"}</small>
                        </span>
                      </label>
                      <button type="button" className="icon-text-button" onClick={() => onRemoveIpDraft(idx)}>
                        <TrashIcon aria-hidden="true" />
                        Remove
                      </button>
                    </header>

                    <div className="ip-camera-identity-grid">
                      <label>
                        Display Name
                        <input
                          value={draft.display_name}
                          onChange={(e) => onUpdateIpDraft(idx, { display_name: e.target.value })}
                          placeholder="Lobby IP Camera"
                        />
                      </label>
                      <label>
                        MediaMTX Path
                        <input value={draft.path} onChange={(e) => onUpdateIpDraft(idx, { path: e.target.value })} />
                      </label>
                    </div>

                    <section className="ip-camera-panel ip-camera-connection-panel">
                      <div className="ip-camera-panel-title">
                        <div>
                          <h4>Camera connection</h4>
                          <p>Use the full RTSP address. Credentials remain in runtime configuration.</p>
                        </div>
                        <button
                          type="button"
                          className="icon-text-button"
                          onMouseDown={(event) => event.preventDefault()}
                          onClick={() => void onInspectIpCamera(idx)}
                          disabled={probeState?.loading || !draft.ip.source_url.trim()}
                        >
                          <MagnifyingGlassIcon aria-hidden="true" />
                          {probeState?.loading ? "Inspecting…" : "Inspect camera"}
                        </button>
                      </div>
                      <label className="ip-source-field">
                        Source URL
                        <input
                          value={draft.ip.source_url}
                          onChange={(e) => onUpdateIpDraft(idx, { ip: { source_url: e.target.value } })}
                          onBlur={() => void onInspectIpCamera(idx, false)}
                          placeholder="rtsp://username:password@10.5.1.145:554/stream1"
                          spellCheck={false}
                        />
                      </label>
                      <div className="ip-onvif-grid">
                        <label>
                          ONVIF discovery
                          <select
                            value={draft.ip.onvif_mode}
                            onChange={(e) =>
                              onUpdateIpDraft(idx, {
                                ip: { onvif_mode: e.target.value as "auto" | "manual" | "disabled" },
                              })
                            }
                          >
                            <option value="auto">Auto detect</option>
                            <option value="manual">Manual address</option>
                            <option value="disabled">Disabled</option>
                          </select>
                        </label>
                        {draft.ip.onvif_mode === "manual" && (
                          <label className="ip-onvif-address-field">
                            ONVIF device service address
                            <input
                              value={draft.ip.onvif_address}
                              onChange={(e) => onUpdateIpDraft(idx, { ip: { onvif_address: e.target.value } })}
                              placeholder="http://camera-host/onvif/device_service"
                              spellCheck={false}
                            />
                          </label>
                        )}
                        {draft.ip.onvif_mode !== "disabled" && (
                          <>
                            <label>
                              ONVIF Username <small>Optional</small>
                              <input
                                value={draft.ip.onvif_username}
                                onChange={(e) => onUpdateIpDraft(idx, { ip: { onvif_username: e.target.value } })}
                                placeholder="Use Source URL credentials"
                                autoComplete="off"
                              />
                            </label>
                            <label>
                              ONVIF Password <small>Optional</small>
                              <input
                                type="password"
                                value={draft.ip.onvif_password}
                                onChange={(e) => onUpdateIpDraft(idx, { ip: { onvif_password: e.target.value } })}
                                placeholder="Use Source URL credentials"
                                autoComplete="new-password"
                              />
                            </label>
                          </>
                        )}
                      </div>

                      {probeState?.error && (
                        <div className="ip-probe-banner is-error">
                          <ExclamationTriangleIcon aria-hidden="true" />
                          <span>{probeState.error}</span>
                        </div>
                      )}
                      {probe && (
                        <div className="ip-probe-result">
                          {probe.recommendation.cfr_fps && <div className="panel-note">
                            Suggested CFR: {probe.recommendation.cfr_fps} fps. Inspection does not change your settings.
                            <button type="button" onClick={() => onUpdateIpDraft(idx, { ip: { cfr_fps: probe.recommendation.cfr_fps ?? DEFAULT_IP_CAMERA_SETTINGS.cfr_fps } })}>Apply recommended FPS</button>
                          </div>}
                          <div className={`ip-probe-banner ${probe.rtsp.timestamp_healthy ? "is-ok" : "is-warning"}`}>
                            {probe.rtsp.timestamp_healthy ? (
                              <CheckCircleIcon aria-hidden="true" />
                            ) : (
                              <ExclamationTriangleIcon aria-hidden="true" />
                            )}
                            <span>
                              {probe.rtsp.available
                                ? probe.rtsp.timestamp_healthy
                                  ? "RTSP timing is healthy."
                                  : `Timing instability detected. Auto recommends ${probe.recommendation.timestamp_mode}.`
                                : probe.rtsp.error || "RTSP stream is unavailable."}
                            </span>
                          </div>
                          {probe.rtsp.available && (
                            <div className="ip-probe-metrics">
                              <span><small>Video</small><strong>{probe.rtsp.width}×{probe.rtsp.height}</strong></span>
                              <span><small>Codec</small><strong>{probe.rtsp.codec || "—"}</strong></span>
                              <span><small>Measured FPS</small><strong>{probe.rtsp.observed_fps ?? "—"}</strong></span>
                              <span><small>Max gap</small><strong>{probe.rtsp.max_delta_ms ?? "—"} ms</strong></span>
                              <span><small>Time reversals</small><strong>{probe.rtsp.nonpositive_delta_count ?? 0}</strong></span>
                              <span><small>Decode errors</small><strong>{probe.rtsp.decode_error_count ?? 0}</strong></span>
                            </div>
                          )}
                          <div className="ip-onvif-result">
                            <div>
                              <small>ONVIF</small>
                              <strong>
                                {probe.onvif.device
                                  ? [probe.onvif.device.manufacturer, probe.onvif.device.model].filter(Boolean).join(" ")
                                  : probe.onvif.status}
                              </strong>
                              <span>{probe.onvif.message}</span>
                            </div>
                            {probe.onvif.device && (
                              <div>
                                <small>Firmware</small>
                                <strong>{probe.onvif.device.firmware_version || "Unknown"}</strong>
                                <span>{probe.onvif.resolved_address}</span>
                              </div>
                            )}
                          </div>
                          {Boolean(probe.onvif.profiles?.length) && (
                            <div className="ip-profile-list">
                              {probe.onvif.profiles?.map((profile) => (
                                <div key={profile.token || profile.name}>
                                  <strong>{profile.name}</strong>
                                  <span>
                                    {[profile.media_service, profile.encoding, profile.width && profile.height ? `${profile.width}×${profile.height}` : null,
                                      profile.fps ? `${formatFps(profile.fps)} fps` : null]
                                      .filter(Boolean)
                                      .join(" · ")}
                                  </span>
                                  {profile.stream_uri && <code title={profile.stream_uri}>{profile.stream_uri}</code>}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      <section className={`ip-ptz-panel ${ptzSupported ? "is-supported" : ""}`}>
                        <div className="ip-ptz-heading">
                          <div className="ip-ptz-title">
                            <ArrowsPointingOutIcon aria-hidden="true" />
                            <div>
                              <h4>ONVIF PTZ</h4>
                              <p>
                                {probe
                                  ? probe.onvif.ptz?.message || "This camera did not advertise standard PTZ control."
                                  : draft.ip.ptz.enabled
                                    ? "Saved PTZ configuration. Inspect the camera to refresh capabilities."
                                    : "Inspect the camera to detect Pan, Tilt and Zoom support."}
                              </p>
                            </div>
                          </div>
                          <label className="ip-ptz-enable">
                            <input
                              type="checkbox"
                              checked={draft.ip.ptz.enabled}
                              disabled={!ptzEvidence && !draft.ip.ptz.enabled}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: { ptz: { ...draft.ip.ptz, enabled: e.target.checked } },
                                })
                              }
                            />
                            Enable PTZ
                          </label>
                        </div>

                        {ptzSupported && (
                          <div className="ip-ptz-capabilities" aria-label="Detected PTZ capabilities">
                            <span className={probe?.onvif.ptz?.pan_tilt ? "status-tag ok" : "status-tag muted"}>
                              Pan / Tilt {probe?.onvif.ptz?.pan_tilt ? "available" : "not available"}
                            </span>
                            <span className={probe?.onvif.ptz?.zoom ? "status-tag ok" : "status-tag muted"}>
                              Zoom {probe?.onvif.ptz?.zoom ? "available" : "not available"}
                            </span>
                          </div>
                        )}

                        <div className="ip-ptz-settings-grid">
                          <label>
                            Control access
                            <select
                              value={draft.ip.ptz.access}
                              disabled={!draft.ip.ptz.enabled}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: {
                                    ptz: {
                                      ...draft.ip.ptz,
                                      access: e.target.value as "admin" | "viewer",
                                    },
                                  },
                                })
                              }
                            >
                              <option value="admin">Admin only</option>
                              <option value="viewer">Admin + authenticated Viewer</option>
                            </select>
                          </label>
                          <label>
                            ONVIF media profile
                            <select
                              value={draft.ip.ptz.profile_token}
                              disabled={!draft.ip.ptz.enabled}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: { ptz: { ...draft.ip.ptz, profile_token: e.target.value } },
                                })
                              }
                            >
                              <option value="">Auto match Source URL</option>
                              {draft.ip.ptz.profile_token &&
                                !ptzProfiles.some((profile) => profile.token === draft.ip.ptz.profile_token) && (
                                  <option value={draft.ip.ptz.profile_token}>Saved: {draft.ip.ptz.profile_token}</option>
                                )}
                              {ptzProfiles.map((profile) => (
                                <option
                                  key={`${profile.media_service || "Media"}:${profile.token || profile.name}`}
                                  value={profile.token || ""}
                                >
                                  {profile.name} · {profile.media_service} ·
                                  {profile.ptz?.pan_tilt ? " PT" : ""}
                                  {profile.ptz?.zoom ? " Z" : ""}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            Pan / Tilt speed <span>{Math.round(draft.ip.ptz.pan_tilt_speed * 100)}%</span>
                            <input
                              type="range"
                              min="0.1"
                              max="1"
                              step="0.05"
                              value={draft.ip.ptz.pan_tilt_speed}
                              disabled={!draft.ip.ptz.enabled}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: { ptz: { ...draft.ip.ptz, pan_tilt_speed: Number(e.target.value) } },
                                })
                              }
                            />
                          </label>
                          <label>
                            Zoom speed <span>{Math.round(draft.ip.ptz.zoom_speed * 100)}%</span>
                            <input
                              type="range"
                              min="0.1"
                              max="1"
                              step="0.05"
                              value={draft.ip.ptz.zoom_speed}
                              disabled={!draft.ip.ptz.enabled}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: { ptz: { ...draft.ip.ptz, zoom_speed: Number(e.target.value) } },
                                })
                              }
                            />
                          </label>
                          <label>
                            Relative step <span>{Math.round(draft.ip.ptz.relative_step * 100)}%</span>
                            <input
                              type="range"
                              min="0.05"
                              max="0.5"
                              step="0.05"
                              value={draft.ip.ptz.relative_step}
                              disabled={!draft.ip.ptz.enabled}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: { ptz: { ...draft.ip.ptz, relative_step: Number(e.target.value) } },
                                })
                              }
                            />
                          </label>
                        </div>
                        <small className="field-help">
                          Public viewers can never operate PTZ. Settings are independent from the FFmpeg relay command.
                        </small>
                      </section>
                    </section>

                    <section className="ip-camera-panel ip-multiview-input-panel">
                      <div className="ip-camera-panel-title">
                        <div>
                          <h4>Multiview input</h4>
                          <p>The public MediaMTX camera path remains unchanged. These settings affect only Multiview.</p>
                        </div>
                      </div>
                      <div className="ip-multiview-route-status">
                        <span className={`status-tag ${multiviewHealthClass(multiviewInputStatus?.state)}`}>
                          {multiviewInputStatus?.state ?? (runtime.multiview?.enabled ? "starting" : "disabled")}
                        </span>
                        <div>
                          <strong>Effective route: {effectiveMultiviewMode}</strong>
                          <small>{effectiveMultiviewMode === "primary" ? `Public path /${draft.path}` : `Internal path /${effectiveMultiviewPath}`}</small>
                          {multiviewInputStatus?.reason && <small>{multiviewInputStatus.reason}</small>}
                        </div>
                      </div>
                      <div className="ip-detail-grid">
                        <label>
                          Input mode
                          <select
                            value={draft.ip.multiview_input.mode}
                            onChange={(e) =>
                              onUpdateIpDraft(idx, {
                                ip: {
                                  multiview_input: {
                                    ...draft.ip.multiview_input,
                                    mode: e.target.value as IpCameraDraft["ip"]["multiview_input"]["mode"],
                                  },
                                },
                              })
                            }
                          >
                            <option value="inherit">Use Multiview default</option>
                            <option value="primary">Primary path — current behavior</option>
                            <option value="normalized_primary">Normalize existing primary path</option>
                            <option value="onvif">ONVIF substream</option>
                            <option value="manual">Manual substream URL</option>
                          </select>
                        </label>
                        {draft.ip.multiview_input.mode === "onvif" && (
                          <label>
                            ONVIF media profile
                            <select
                              value={draft.ip.multiview_input.profile_token}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: {
                                    multiview_input: {
                                      ...draft.ip.multiview_input,
                                      profile_token: e.target.value,
                                    },
                                  },
                                })
                              }
                            >
                              <option value="">Auto — smallest suitable profile</option>
                              {probe?.onvif.profiles
                                ?.filter((profile) => profile.stream_uri && !["jpeg", "mjpeg"].includes(String(profile.encoding).toLowerCase()))
                                .map((profile) => (
                                  <option key={String(profile.media_service) + ":" + String(profile.token)} value={profile.token || ""}>
                                    {profile.name} · {profile.encoding} · {profile.width}×{profile.height} · {formatFps(profile.fps || 0)} fps
                                  </option>
                                ))}
                            </select>
                          </label>
                        )}
                        {draft.ip.multiview_input.mode === "manual" && (
                          <label className="form-span-2">
                            Manual RTSP URL
                            <input
                              value={draft.ip.multiview_input.manual_url}
                              spellCheck={false}
                              placeholder="rtsp://camera-host/substream"
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: {
                                    multiview_input: {
                                      ...draft.ip.multiview_input,
                                      manual_url: e.target.value,
                                    },
                                  },
                                })
                              }
                            />
                          </label>
                        )}
                        <label>
                          FPS override
                          <input
                            type="number"
                            min={1}
                            max={120}
                            placeholder={String(runtime.multiview?.input_defaults?.target_fps ?? 10)}
                            value={draft.ip.multiview_input.target_fps ?? ""}
                            onChange={(e) =>
                              onUpdateIpDraft(idx, {
                                ip: {
                                  multiview_input: {
                                    ...draft.ip.multiview_input,
                                    target_fps: e.target.value ? Number(e.target.value) : null,
                                  },
                                },
                              })
                            }
                          />
                        </label>
                        <label>
                          Resolution override
                          <input
                            value={draft.ip.multiview_input.resolution}
                            placeholder="auto or 640x360"
                            onChange={(e) =>
                              onUpdateIpDraft(idx, {
                                ip: {
                                  multiview_input: {
                                    ...draft.ip.multiview_input,
                                    resolution: e.target.value,
                                  },
                                },
                              })
                            }
                          />
                        </label>
                        <label>
                          Quality override
                          <select
                            value={draft.ip.multiview_input.quality_preset}
                            onChange={(e) =>
                              onUpdateIpDraft(idx, {
                                ip: {
                                  multiview_input: {
                                    ...draft.ip.multiview_input,
                                    quality_preset: e.target.value as IpCameraDraft["ip"]["multiview_input"]["quality_preset"],
                                  },
                                },
                              })
                            }
                          >
                            <option value="">Inherit</option>
                            <option value="high">high</option>
                            <option value="standard">standard</option>
                            <option value="low">low</option>
                          </select>
                        </label>
                      </div>
                      {(draft.ip.multiview_input.mode === "onvif" || draft.ip.multiview_input.mode === "manual") && (
                        <div className="ip-probe-banner is-warning">
                          <ExclamationTriangleIcon aria-hidden="true" />
                          <span>This opens a second RTSP stream from the camera and falls back to the primary path on failure.</span>
                        </div>
                      )}
                      <details className="ip-camera-details">
                        <summary>Conversion details</summary>
                        <div className="ip-detail-grid">
                          {(["encoder", "bitrate", "maxrate", "bufsize", "x264_preset"] as const).map((field) => (
                            <label key={field}>
                              {field}
                              <input
                                value={draft.ip.multiview_input[field]}
                                placeholder={String(runtime.multiview?.input_defaults?.[field] ?? "inherit")}
                                onChange={(e) =>
                                  onUpdateIpDraft(idx, {
                                    ip: {
                                      multiview_input: {
                                        ...draft.ip.multiview_input,
                                        [field]: e.target.value,
                                      },
                                    },
                                  })
                                }
                              />
                            </label>
                          ))}
                          <label>
                            thread queue
                            <input
                              type="number"
                              min={1}
                              placeholder={String(runtime.multiview?.input_thread_queue_size ?? 128)}
                              value={draft.ip.multiview_input.thread_queue_size ?? ""}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: {
                                    multiview_input: {
                                      ...draft.ip.multiview_input,
                                      thread_queue_size: e.target.value ? Number(e.target.value) : null,
                                    },
                                  },
                                })
                              }
                            />
                          </label>
                          <label>
                            stall timeout
                            <input
                              type="number"
                              min={0}
                              placeholder={String(runtime.multiview?.input_stall_timeout_sec ?? 15)}
                              value={draft.ip.multiview_input.stall_timeout_sec ?? ""}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: {
                                    multiview_input: {
                                      ...draft.ip.multiview_input,
                                      stall_timeout_sec: e.target.value ? Number(e.target.value) : null,
                                    },
                                  },
                                })
                              }
                            />
                          </label>
                        </div>
                      </details>
                    </section>

                    <div className="ip-camera-control-grid">
                      <section className="ip-camera-panel">
                        <h4>Stream handling</h4>
                        <label>
                          Timestamp mode
                          <select
                            value={draft.ip.timestamp_mode}
                            onChange={(e) =>
                              onUpdateIpDraft(idx, {
                                ip: { timestamp_mode: e.target.value as "auto" | "source" | "wallclock" | "cfr" },
                              })
                            }
                          >
                            <option value="auto">Auto — measured policy</option>
                            <option value="source">Source — preserve camera time</option>
                            <option value="wallclock">Wall-clock — replace camera time</option>
                            <option value="cfr">CFR — fixed FPS re-encode</option>
                          </select>
                        </label>
                        <label>
                          Relay mode
                          <select
                            value={draft.ip.relay_mode}
                            onChange={(e) =>
                              onUpdateIpDraft(idx, { ip: { relay_mode: e.target.value as "copy" | "libx264" } })
                            }
                          >
                            <option value="copy">Copy — lowest overhead</option>
                            <option value="libx264">libx264 — re-encode</option>
                          </select>
                        </label>
                        <label>
                          CFR FPS
                          <input
                            type="number"
                            min={1}
                            max={240}
                            step={1}
                            value={draft.ip.cfr_fps}
                            disabled={!(["auto", "cfr"].includes(draft.ip.timestamp_mode))}
                            onChange={(e) =>
                              onUpdateIpDraft(idx, {
                                ip: { cfr_fps: Number(e.target.value) || DEFAULT_IP_CAMERA_SETTINGS.cfr_fps },
                              })
                            }
                          />
                        </label>
                        <p className="table-note">
                          Auto measures the stream at relay start. CFR always decodes and re-encodes at the selected FPS.
                        </p>
                      </section>

                      <details className="ip-camera-panel ip-camera-details">
                        <summary>Stability & watchdog</summary>
                        <div className="ip-detail-grid">
                          <label className="table-check">
                            <input
                              type="checkbox"
                              checked={draft.ip.periodic_restart_enabled}
                              onChange={(e) => onUpdateIpDraft(idx, { ip: { periodic_restart_enabled: e.target.checked } })}
                            />
                            Auto Restart
                          </label>
                          <label>
                            Restart Interval (sec)
                            <input
                              type="number"
                              min={60}
                              value={draft.ip.periodic_restart_interval_sec}
                              onChange={(e) =>
                                onUpdateIpDraft(idx, {
                                  ip: { periodic_restart_interval_sec: Number(e.target.value) || 43200 },
                                })
                              }
                            />
                          </label>
                          <label className="table-check">
                            <input
                              type="checkbox"
                              checked={draft.ip.watchdog_enabled}
                              onChange={(e) => onUpdateIpDraft(idx, { ip: { watchdog_enabled: e.target.checked } })}
                            />
                            Snapshot Watchdog
                          </label>
                          <label>
                            Interval / Timeout / Failures
                            <div className="ip-inline-fields">
                              <input type="number" min={10} value={draft.ip.watchdog_interval_sec} aria-label="Watchdog interval"
                                onChange={(e) => onUpdateIpDraft(idx, { ip: { watchdog_interval_sec: Number(e.target.value) || 300 } })} />
                              <input type="number" min={1} step={0.5} value={draft.ip.watchdog_timeout_sec} aria-label="Watchdog timeout"
                                onChange={(e) => onUpdateIpDraft(idx, { ip: { watchdog_timeout_sec: Number(e.target.value) || 8 } })} />
                              <input type="number" min={1} value={draft.ip.watchdog_failure_threshold} aria-label="Failure threshold"
                                onChange={(e) => onUpdateIpDraft(idx, { ip: { watchdog_failure_threshold: Number(e.target.value) || 3 } })} />
                            </div>
                          </label>
                        </div>
                      </details>

                      <details className="ip-camera-panel ip-camera-details">
                        <summary>Encode settings</summary>
                        <div className="ip-detail-grid ip-encode-grid">
                          {(["bitrate", "maxrate", "bufsize"] as const).map((field) => (
                            <label key={field}>
                              {field.charAt(0).toUpperCase() + field.slice(1)}
                              <input
                                value={draft.ip[field]}
                                disabled={!encodeEnabled}
                                placeholder={field === "bufsize" ? "4M" : "2M"}
                                onChange={(e) => onUpdateIpDraft(idx, { ip: { [field]: e.target.value } })}
                              />
                            </label>
                          ))}
                          <label>
                            GOP
                            <input type="number" min={1} value={draft.ip.gop} disabled={!encodeEnabled}
                              onChange={(e) => onUpdateIpDraft(idx, { ip: { gop: Number(e.target.value) || 40 } })} />
                          </label>
                          <label>
                            Preset
                            <input value={draft.ip.x264_preset} disabled={!encodeEnabled}
                              onChange={(e) => onUpdateIpDraft(idx, { ip: { x264_preset: e.target.value } })} />
                          </label>
                        </div>
                      </details>
                    </div>
                  </article>
                );
              })}
              {ipDrafts.length === 0 && <div className="panel-note">No IP cameras configured.</div>}
            </div>
          </div>

          <details className="settings-restart-options">
            <summary>Restart options</summary>
            <p>Most changes apply without interrupting streams. Use a full restart only when a runtime change requires it.</p>
            <button type="button" className="button-danger" onClick={() => void onSaveBasic(true)}>
              Save changes and restart entire stack
            </button>
          </details>
        </div>
      )}

      {!normalizedSettingsSearch && mode === "advanced" && (
        <div className="settings-detail">
          <div className="settings-content-heading">
            <div>
              <span className="settings-eyebrow">Expert settings</span>
              <h3>Advanced</h3>
              <p>Review and replace the complete runtime configuration.</p>
            </div>
          </div>
        <div className="section">
          <h3>Advanced: Full Runtime JSON</h3>
          <p className="form-help">
            This editor allows editing all runtime fields. Replace is atomic and immediately persisted to runtime.json.
          </p>
          <textarea
            aria-label="Full runtime JSON"
            className="json-editor"
            value={runtimeJsonText}
            onChange={(e) => setRuntimeJsonText(e.target.value)}
          />
          <div className="button-row">
            <button type="button" onClick={async () => { if (!jsonDirty || await ask("Discard the JSON edits and replace them with the current form values?")) setRuntimeJsonText(JSON.stringify(runtime, null, 2)); }}>
              Sync JSON From Form
            </button>
            <button type="button" onClick={() => void onReplaceRuntime()}>
              Replace Runtime & Apply
            </button>
            <button type="button" className="primary" onClick={() => void onReplaceRuntime(true)}>
              Replace Runtime & Restart
            </button>
          </div>
        </div>
        </div>
      )}
          </fieldset>}
        </main>
      </div>
    </div>
    </SettingsHelp>
  );
}
