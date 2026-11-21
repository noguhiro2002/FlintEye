export type ProcessStatus = "running" | "stopped" | "error";

export interface ProcessItem {
  id: string;
  kind: string;
  status: ProcessStatus;
  desired: boolean;
  pid: number | null;
  started_at: number | null;
  restart_count: number;
  last_exit_code: number | null;
  last_error: string | null;
  health_state?: CameraHealthState;
  healthcheck_failures?: number;
  last_healthcheck_at?: number | null;
  last_healthcheck_error?: string | null;
  manual_excluded?: boolean;
  manual_excluded_since?: number | null;
  quarantined?: boolean;
  quarantine_since?: number | null;
  quarantine_reason?: string | null;
  command: string;
}

export type CameraHealthState =
  | "healthy"
  | "degraded"
  | "starting"
  | "unhealthy"
  | "quarantined"
  | "excluded"
  | "disabled"
  | "unknown";

export interface CameraHealth {
  state: CameraHealthState;
  healthy: boolean;
  reason: string;
  manual_excluded: boolean;
  manual_excluded_since?: number | null;
  quarantined: boolean;
  quarantine_since?: number | null;
  healthcheck_failures?: number;
  last_healthcheck_at?: number | null;
  last_healthcheck_error?: string | null;
  placeholder: boolean;
}

export interface AuthMeResponse {
  authenticated: boolean;
  provider: "legacy_token" | "local" | "oidc";
  role: "viewer" | "admin" | null;
  username: string | null;
  viewer_auth_required: boolean;
  setup_required: boolean;
  setup_mode?: "desktop" | "server";
  setup_handoff_ready?: boolean;
  local: {
    admin_username: string;
    viewer_username: string;
  };
  oidc: {
    configured: boolean;
  };
}

export interface CameraUvcConfig {
  profile: string;
  env: Record<string, string>;
  extra_args: string[];
}

export type PtzMoveMode = "continuous" | "relative" | "absolute";

export interface CameraPtzConfig {
  enabled: boolean;
  access: "admin" | "viewer";
  profile_token: string | null;
  pan_tilt_speed: number;
  zoom_speed: number;
  relative_step: number;
}

export interface PtzAxisModes {
  continuous: boolean;
  relative: boolean;
  absolute: boolean;
}

export interface PtzRange {
  min: number;
  max: number;
}

export interface PtzSpace {
  uri?: string | null;
  x?: PtzRange;
  y?: PtzRange;
}

export interface PtzProfileCapability {
  profile_token?: string | null;
  profile_name?: string | null;
  media_service?: "Media" | "Media2" | null;
  configuration_token?: string | null;
  node_token?: string | null;
  supported: boolean;
  pan_tilt: boolean;
  zoom: boolean;
  modes: {
    pan_tilt: PtzAxisModes;
    zoom: PtzAxisModes;
  };
  spaces: Record<string, PtzSpace[]>;
}

export interface PtzCapabilities {
  camera_id: string;
  enabled: boolean;
  access: "admin" | "viewer";
  supported: boolean;
  service_available: boolean;
  message?: string | null;
  pan_tilt: boolean;
  zoom: boolean;
  modes: {
    pan_tilt: PtzAxisModes;
    zoom: PtzAxisModes;
  };
  spaces: Record<string, PtzSpace[]>;
  selected_profile_token?: string | null;
  selected_profile_name?: string | null;
  profiles: Array<{
    token?: string | null;
    name?: string | null;
    media_service?: "Media" | "Media2" | null;
    stream_uri?: string | null;
    ptz?: PtzProfileCapability | null;
  }>;
  current: { pan: number | null; tilt: number | null; zoom: number | null };
  cache_ttl_sec: number;
}

export interface CameraIpConfig {
  source_url: string | null;
  relay_mode?: "copy" | "libx264";
  timestamp_mode?: "auto" | "source" | "wallclock" | "cfr";
  cfr_fps?: number;
  onvif_mode?: "auto" | "manual" | "disabled";
  onvif_address?: string | null;
  onvif_username?: string | null;
  onvif_password?: string | null;
  ptz?: CameraPtzConfig;
  multiview_input?: {
    mode?: "inherit" | "primary" | "normalized_primary" | "onvif" | "manual";
    profile_token?: string | null;
    manual_url?: string | null;
    target_fps?: number | null;
    resolution?: string | null;
    encoder?: string | null;
    quality_preset?: "high" | "standard" | "low" | null;
    bitrate?: string | null;
    maxrate?: string | null;
    bufsize?: string | null;
    x264_preset?: string | null;
    thread_queue_size?: number | null;
    stall_timeout_sec?: number | null;
  };
  bitrate?: string | null;
  maxrate?: string | null;
  bufsize?: string | null;
  gop?: number;
  x264_preset?: string;
  periodic_restart_enabled?: boolean;
  periodic_restart_interval_sec?: number;
  watchdog_enabled?: boolean;
  watchdog_interval_sec?: number;
  watchdog_timeout_sec?: number;
  watchdog_failure_threshold?: number;
}

export interface IpCameraProbeResult {
  ok: boolean;
  source: string;
  inspected_at: number;
  elapsed_sec: number;
  rtsp: {
    available: boolean;
    error?: string;
    codec?: string | null;
    profile?: string | null;
    width?: number | null;
    height?: number | null;
    declared_avg_fps?: number | null;
    declared_rate_fps?: number | null;
    observed_fps?: number | null;
    recommended_cfr_fps?: number | null;
    frame_count?: number;
    median_delta_ms?: number | null;
    p95_delta_ms?: number | null;
    max_delta_ms?: number | null;
    nonpositive_delta_count?: number;
    large_gap_count?: number;
    decode_error_count?: number;
    timestamp_healthy?: boolean;
    recommended_timestamp_mode?: "source" | "wallclock" | "cfr";
  };
  onvif: {
    status: string;
    supported: boolean | null;
    message: string;
    discovery_method?: string;
    resolved_address?: string;
    errors?: string[];
    device?: {
      manufacturer?: string | null;
      model?: string | null;
      firmware_version?: string | null;
      serial_number?: string | null;
      hardware_id?: string | null;
    };
    services?: string[];
    service_details?: Array<{
      name: string;
      namespace?: string | null;
      xaddr?: string | null;
      version?: { major?: number | null; minor?: number | null };
    }>;
    media_service?: "Media" | "Media2" | null;
    media_errors?: string[];
    profiles?: Array<{
      token?: string | null;
      name: string;
      media_service?: "Media" | "Media2";
      encoding?: string | null;
      width?: number | null;
      height?: number | null;
      fps?: number | null;
      bitrate_kbps?: number | null;
      gov_length?: number | null;
      stream_uri?: string | null;
      ptz_configuration_token?: string | null;
      ptz_node_token?: string | null;
      ptz?: PtzProfileCapability | null;
    }>;
    ptz?: {
      supported: boolean;
      service_available: boolean;
      message: string;
      pan_tilt?: boolean;
      zoom?: boolean;
      profiles?: PtzProfileCapability[];
      errors?: string[];
    };
  };
  recommendation: {
    timestamp_mode: "source" | "wallclock" | "cfr" | null;
    cfr_fps: number | null;
  };
}

export interface CameraItem {
  id: string;
  type: "uvc" | "ip";
  enabled: boolean;
  path: string;
  display_name?: string | null;
  uvc: CameraUvcConfig | null;
  ip: CameraIpConfig | null;
  addresses: {
    rtsp_url: string;
    client_rtsp_url?: string | null;
    rtsp_status?: string;
    webrtc_url: string;
  };
  process: ProcessItem | null;
  health?: CameraHealth;
}

export interface CameraAudioConfig {
  enabled: boolean;
  preset: "standard" | "high" | "middle" | "low" | "custom";
  codec: "pcm" | "aac";
  sample_rate: number;
  bit_depth: number;
  channels: number;
  bitrate_kbps: number;
}

export interface ViewerCameraItem {
  id: string;
  label: string;
  type: "uvc" | "ip";
  enabled: boolean;
  audio_enabled?: boolean;
  audio_receiving?: boolean;
  path: string;
  addresses: {
    rtsp_url: string;
    client_rtsp_url?: string | null;
    rtsp_status?: string;
    webrtc_url: string;
  };
  process: ProcessItem | null;
  health: CameraHealth;
  ptz?: {
    enabled: boolean;
    access: "admin" | "viewer";
  };
}

export interface UvcSuggestion {
  profile: string;
  path: string;
  rtsp_url: string;
  camera_name: string;
  env_lines: string[];
  runtime_camera: Record<string, unknown>;
  matched_camera_id: string | null;
}

export interface UvcDeviceItem {
  device_id: string;
  driver: "avfoundation" | "dshow" | "v4l2";
  display_name: string;
  index: string | null;
  ffmpeg_device: string;
  ffmpeg_device_index: string;
  mode_warning?: string;
  modes: Array<{ width: number; height: number; fps?: number; input_format?: string }>;
  recommended: { width: number; height: number; fps: number; input_format?: string };
  ignored?: boolean;
  suggestion?: UvcSuggestion;
}

export interface UvcDevicesResponse {
  driver: string;
  ffmpeg_bin: string;
  warning: string;
  count: number;
  items: UvcDeviceItem[];
}

export interface MultiviewViewItem {
  id: string;
  index: number;
  sources: string[];
  source_items?: Array<{
    path: string;
    label: string;
    type: "uvc" | "ip" | "external";
    camera_id?: string;
    health: CameraHealth;
  }>;
  rtsp_url: string;
  webrtc_url: string;
}

export interface MultiviewStatus {
  updated_at: number | null;
  views: Array<{
    id: string;
    state: "starting" | "healthy" | "degraded";
    restart_count: number;
    decode_error_count: number;
    inputs: Array<{
      path: string;
      state: "starting" | "buffering" | "healthy" | "holding" | "no_stream" | "reconnecting" | "degraded" | "isolated" | "fallback";
      last_progress_at?: number | null;
      failures: number;
      isolated: boolean;
      reason?: string | null;
      buffer_delay_sec?: number | null;
      buffered_frames?: number;
      target_at?: number | null;
      selected_frame_at?: number | null;
    }>;
  }>;
}

type MediamtxScalar = string | number | boolean;
type MediamtxOptions = Record<string, MediamtxScalar | MediamtxScalar[]>;

export interface RuntimeConfigResponse {
  api?: {
    host?: string;
    port?: number;
    admin_token?: string;
    viewer_token?: string;
    viewer_auth_required?: boolean;
    bearer_token?: string;
  };
  auth?: {
    provider?: "legacy_token" | "local" | "oidc";
    viewer_auth_required?: boolean;
    session_cookie_name?: string;
    session_ttl_sec?: number;
    session_secret?: string;
    oidc_issuer_url?: string | null;
    oidc_client_id?: string | null;
    oidc_client_secret?: string | null;
    oidc_redirect_uri?: string | null;
    oidc_scopes?: string;
    local?: {
      admin?: {
        username?: string;
        password_hash?: string;
      };
      viewer?: {
        username?: string;
        password_hash?: string;
      };
    };
  };
  ui?: {
    app_title?: string;
    sidebar_title?: string;
    footer_text?: string;
    onboarding_done?: boolean;
  };
  logging?: {
    directory?: string;
    level?: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
    retention?: string | null;
  };
  snapshot?: {
    timeout_sec?: number;
    thumbnail_refresh_interval_sec?: number;
  };
  mediamtx?: {
    control_mode?: string;
    service_name?: string;
    autostart_on_api_start?: boolean;
    rtsp_base_url?: string;
    internal_rtsp_base_url?: string | null;
    webrtc_base_url?: string;
    direct?: {
      command?: string[];
      working_dir?: string | null;
    };
    managed?: {
      enabled?: boolean;
      global?: MediamtxOptions;
      global_?: MediamtxOptions;
      paths?: Record<string, MediamtxOptions>;
    };
  };
  multiview?: {
    enabled?: boolean;
    source_mode?: "env" | "api" | "hybrid";
    source_paths?: string[];
    auto_placeholder_missing_sources?: boolean;
    mtx_api_url?: string;
    input_rtsp_base_url?: string;
    output_rtsp_base_url?: string;
    output_prefix?: string;
    max_sources?: number;
    tile_count?: number;
    latency_preset?: "normal" | "low";
    restart_backoff_sec?: number;
    input_stall_timeout_sec?: number;
    input_stall_timeout_option?: "auto" | "rw_timeout" | "stimeout" | "timeout" | "none";
    input_healthcheck_enabled?: boolean;
    input_healthcheck_interval_sec?: number;
    input_isolation_threshold?: number;
    input_retry_interval_sec?: number;
    input_thread_queue_size?: number;
    status_file?: string;
    input_defaults?: {
      mode?: "primary" | "normalized_primary";
      target_fps?: number;
      resolution?: string;
      encoder?: string;
      quality_preset?: "high" | "standard" | "low";
      bitrate?: string;
      maxrate?: string;
      bufsize?: string;
      x264_preset?: string;
      fallback_to_primary?: boolean;
    };
    sync_buffer?: {
      enabled?: boolean;
      delay_sec?: number;
      buffer_sec?: number;
      fps?: number;
      width?: number;
      height?: number;
      late_frame_policy?: "hold" | "no_stream";
      max_hold_sec?: number;
      memory_limit_mb_per_input?: number;
      reconnect_sec?: number;
    };
    ffmpeg_bin?: string;
    loglevel?: string;
    verbose?: boolean;
    quality?: {
      fps?: number;
      encoder?: string;
      quality_preset?: "high" | "standard" | "low";
      bitrate?: string;
      maxrate?: string;
      bufsize?: string;
      gop?: number;
      bframes?: number;
      x264_preset?: string;
    };
    layout?: {
      canvas_width?: number;
      canvas_height?: number;
      grid_columns?: number | null;
      global_slots?: string | null;
      per_view_slots?: Record<string, string>;
    };
    maintenance?: {
      enabled?: boolean;
      restart_interval_sec?: number;
      align_with_record_segments?: boolean;
      restart_offset_sec?: number;
    };
  };
  recording?: {
    enabled?: boolean;
    auto_apply?: boolean;
    config_path?: string | null;
    record_segment_duration?: string;
    record_delete_after?: string;
    playback_cache_delete_after?: string;
    playback_cache_max_bytes?: number;
    record_root?: string;
    max_bytes?: number | null;
    managed_storage?: boolean;
    show_previous?: boolean;
    record_format?: "fmp4" | "mpegts";
    record_part_duration?: string;
    record_max_part_size?: string;
    record_all_cameras?: boolean | null;
    record_paths?: string[];
    include_multiview?: boolean;
    multiview_max_count?: number;
  };
  device_discovery?: {
    ignored_uvc_devices?: string[];
  };
  cameras?: Array<{
    id: string;
    type: "uvc" | "ip";
    enabled: boolean;
    audio?: CameraAudioConfig;
    path: string;
    display_name?: string | null;
    uvc?: CameraUvcConfig | null;
    ip?: CameraIpConfig | null;
  }>;
}

export interface DashboardStatus {
  timestamp: number;
  mediamtx: {
    mode: string;
    service_name: string;
    status: string;
    running: boolean;
    pid?: number | null;
  };
  processes: {
    items: ProcessItem[];
  };
  cameras_total: number;
  cameras_enabled: number;
  multiview_enabled: boolean;
  running_processes: number;
}

export interface RecordingStreamListResponse {
  record_root: string;
  count: number;
  items: string[];
}

export interface RecordingItem {
  started_at?: number | null;
  ended_at?: number | null;
  duration_sec?: number | null;
  completion_state?: string;
  file_id: string;
  relative_path: string;
  stream_id: string;
  size_bytes: number;
  modified_at: number;
  age_sec: number;
  is_stable: boolean;
}

export interface RecordingListResponse {
  record_root: string;
  stream_id: string;
  total: number;
  limit: number;
  offset: number;
  items: RecordingItem[];
}

export interface RecordingPlaybackPrepareResponse {
  ok: boolean;
  file_id: string;
  has_audio?: boolean | null;
  playable_path: string;
  cache_file: string;
}

export interface ViewerInfoResponse {
  generated_at: number;
  api: {
    base_url: string;
    swagger_url: string;
    redoc_url: string;
    openapi_url: string;
  };
  rtsp_base_url: string;
  webrtc_base_url: string;
  snapshot: {
    timeout_sec: number;
    thumbnail_refresh_interval_sec: number;
  };
  cameras: Array<{
    id: string;
    label: string;
    type: "uvc" | "ip";
    enabled: boolean;
    path: string;
    addresses: {
      rtsp_url: string;
      client_rtsp_url?: string | null;
      rtsp_status?: string;
      webrtc_url: string;
    };
    process: ProcessItem | null;
    settings: {
      profile?: string;
      input_driver?: string;
      width?: string;
      height?: string;
      fps?: string;
      encoder?: string;
      quality_preset?: string;
      latency_preset?: string;
      bitrate?: string;
      maxrate?: string;
      bufsize?: string;
      gop?: string;
      source_configured?: boolean;
      source_host?: string | null;
    };
  }>;
  multiview: {
    enabled: boolean;
    output_prefix: string;
    tile_count: number;
    source_mode: string;
    auto_placeholder_missing_sources: boolean;
    canvas_width: number;
    canvas_height: number;
    fps: number;
    encoder: string;
    quality_preset: string;
    bitrate: string | null;
    maxrate: string | null;
    bufsize: string | null;
    gop: number;
    input_stall_timeout_sec: number;
    input_stall_timeout_option: string;
    views: MultiviewViewItem[];
  };
}
export interface MonitoringStatusResponse {
  state: string; color: 'green' | 'red' | 'amber' | 'gray'; label: string; message: string;
  desired_running: boolean; busy: boolean; phase: string; resume_on_startup: boolean;
  counts: { configured: number; targets: number; receiving: number; recording: number };
  cameras: Array<{ id: string; receiving: boolean; last_received_at: number | null; reason: string }>;
  pending_segments?: number; previous_incomplete_segments?: number;
}
