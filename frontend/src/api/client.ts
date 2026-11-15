import type {
  MonitoringStatusResponse,
  AuthMeResponse,
  CameraItem,
  DashboardStatus,
  IpCameraProbeResult,
  MultiviewViewItem,
  MultiviewStatus,
  PtzCapabilities,
  RecordingListResponse,
  RecordingPlaybackPrepareResponse,
  RecordingStreamListResponse,
  RuntimeConfigResponse,
  UvcDeviceItem,
  UvcDevicesResponse,
  ViewerInfoResponse,
  ViewerCameraItem,
} from "../types";

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly directApiBase: string;
  private runtimeRevision: string | null = null;

  constructor(baseUrl?: string) {
    this.baseUrl = baseUrl ?? import.meta.env.VITE_API_BASE ?? "";
    this.directApiBase = import.meta.env.VITE_API_DIRECT_BASE ?? "";
  }

  buildUrl(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  buildDirectUrl(path: string): string {
    return `${this.directApiBase || this.baseUrl}${path}`;
  }

  configSession(): ApiClient {
    return new ApiClient(this.baseUrl);
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    expectJson = true,
  ): Promise<T> {
    const headers: Record<string, string> = {
      ...(init.headers as Record<string, string> | undefined),
    };
    if (path === "/api/v1/config/runtime" && this.runtimeRevision && (init.method === "PUT" || init.method === "PATCH")) {
      headers["If-Match"] = this.runtimeRevision;
    }

    const controller = new AbortController();
    const abort = () => controller.abort();
    init.signal?.addEventListener("abort", abort, { once: true });
    if (init.signal?.aborted) controller.abort();
    // A native folder picker waits for a person; media preparation can take longer.
    const timeoutMs = path === "/api/v1/storage/pick-folder" ? 0
      : path.includes("/probe") || path.includes("/prepare") ? 120000
      : path.startsWith('/api/v1/control/') ? 45000 : 30000;
    const timeout = timeoutMs ? window.setTimeout(abort, timeoutMs) : undefined;
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers,
        credentials: "include",
        signal: controller.signal,
      });

      if (!response.ok) {
        let body: unknown = null;
        const rawText = await response.text();
        try {
          body = rawText ? (JSON.parse(rawText) as unknown) : null;
        } catch {
          body = rawText;
        }
        const detail =
          typeof body === "object" && body !== null && "detail" in body
            ? String((body as { detail: unknown }).detail)
            : response.statusText;
        throw new ApiError(response.status, detail, body);
      }

      if (path === "/api/v1/config/effective" || path === "/api/v1/config/runtime") {
        this.runtimeRevision = response.headers.get("ETag");
      }

      if (!expectJson) {
        return (await response.blob()) as T;
      }

      return (await response.json()) as T;
    } catch (error) {
      if (controller.signal.aborted && !init.signal?.aborted) {
        throw new Error("The request timed out. Check the connection and retry. If you were saving changes, refresh to check whether they were saved.");
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
      init.signal?.removeEventListener("abort", abort);
    }
  }

  setup(token: string, password: string): Promise<{ ok: boolean }> {
    return this.request('/api/v1/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, password }) });
  }
  desktopCapabilities(): Promise<{ folder_picker: boolean; startup_settings?: boolean }> { return this.request('/api/v1/desktop'); }
  getMonitoringStatus(): Promise<MonitoringStatusResponse> { return this.request('/api/v1/status/monitoring'); }
  monitoringControl(action: 'start' | 'stop' | 'restart'): Promise<{ ok: boolean }> {
    return this.request('/api/v1/control/' + action, { method: 'POST' });
  }
  getMonitoringPreferences(): Promise<{ resume_on_startup: boolean }> { return this.request('/api/v1/monitoring/preferences'); }
  setMonitoringPreferences(value: boolean): Promise<{ resume_on_startup: boolean }> {
    return this.request('/api/v1/monitoring/preferences', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resume_on_startup: value }) });
  }
  getDesktopStartup(): Promise<{ enabled: boolean; available: boolean; message: string }> { return this.request('/api/v1/desktop/startup'); }
  setDesktopStartup(enabled: boolean): Promise<{ enabled: boolean; available: boolean; message: string }> {
    return this.request('/api/v1/desktop/startup', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
  }
  getBuildInfo(): Promise<{ version: string; release: string; channel: string; commit: string | null; dirty: boolean | null }> { return this.request('/api/v1/build'); }
  getUpdates(): Promise<{ available: boolean; current: string; current_release?: string; channel?: string; version?: string; url?: string; message?: string }> {
    return this.request('/api/v1/updates');
  }
  pickFolder(): Promise<{ path: string }> { return this.request('/api/v1/storage/pick-folder', { method: 'POST' }); }
  suggestStorage(path: string): Promise<{ path: string; max_bytes: number }> {
    return this.request('/api/v1/storage/suggest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
  }
  setViewerPassword(password: string): Promise<{ ok: boolean }> {
    return this.request('/api/v1/accounts/viewer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) });
  }

  getHealth(): Promise<{ ok: boolean; uptime_sec: number }> {
    return this.request("/api/v1/health");
  }

  getAuthMe(): Promise<AuthMeResponse> {
    return this.request("/api/v1/auth/me");
  }

  login(username: string, password: string): Promise<{
    ok: boolean;
    authenticated: boolean;
    role: "viewer" | "admin";
    username: string;
    provider: string;
  }> {
    return this.request("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  }

  logout(): Promise<{ ok: boolean }> {
    return this.request("/api/v1/auth/logout", { method: "POST" });
  }

  getStatus(): Promise<DashboardStatus> {
    return this.request("/api/v1/status");
  }

  getListener(): Promise<{ host?: string; port?: number; source?: string }> {
    return this.request("/api/v1/status/listener");
  }

  getCameras(): Promise<{ items: CameraItem[] }> {
    return this.request("/api/v1/cameras");
  }

  getViewerCameras(): Promise<{ items: ViewerCameraItem[] }> {
    return this.request("/api/v1/viewer/cameras");
  }

  getViewerInfo(): Promise<ViewerInfoResponse> {
    return this.request("/api/v1/viewer/info");
  }

  getCamera(cameraId: string): Promise<CameraItem> {
    return this.request(`/api/v1/cameras/${encodeURIComponent(cameraId)}`);
  }

  probeIpCamera(payload: Record<string, unknown>): Promise<IpCameraProbeResult> {
    return this.request("/api/v1/ip-cameras/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  getPtzCapabilities(cameraId: string, force = false): Promise<PtzCapabilities> {
    const suffix = force ? "?force=true" : "";
    return this.request(`/api/v1/cameras/${encodeURIComponent(cameraId)}/ptz/capabilities${suffix}`);
  }

  movePtz(
    cameraId: string,
    payload: { operation_id: string; pan?: number; tilt?: number; zoom?: number },
  ): Promise<{ ok: boolean; camera_id: string; operation_id: string }> {
    return this.request(`/api/v1/cameras/${encodeURIComponent(cameraId)}/ptz/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  setPtzPosition(
    cameraId: string,
    payload: { operation_id: string; zoom: number },
  ): Promise<{ ok: boolean; camera_id: string; operation_id: string; zoom: number }> {
    return this.request(`/api/v1/cameras/${encodeURIComponent(cameraId)}/ptz/position`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  stopPtz(
    cameraId: string,
    payload: { operation_id?: string; pan_tilt?: boolean; zoom?: boolean } = {},
  ): Promise<{ ok: boolean; camera_id: string }> {
    return this.request(`/api/v1/cameras/${encodeURIComponent(cameraId)}/ptz/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  excludeCamera(cameraId: string, reason?: string): Promise<{ ok: boolean; camera_id: string; excluded: boolean }> {
    return this.request(`/api/v1/cameras/${encodeURIComponent(cameraId)}/exclude`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? "Manually excluded from multiview" }),
    });
  }

  restoreCamera(cameraId: string): Promise<{ ok: boolean; camera_id: string; excluded: boolean }> {
    return this.request(`/api/v1/cameras/${encodeURIComponent(cameraId)}/restore`, { method: "POST" });
  }

  getMultiviewViews(): Promise<{ items: MultiviewViewItem[] }> {
    return this.request("/api/v1/multiview/views");
  }

  getMultiviewStatus(): Promise<MultiviewStatus> {
    return this.request("/api/v1/multiview/status");
  }

  getMultiviewInputCapabilities(cameraId: string): Promise<{
    camera_id: string;
    supported_modes: string[];
    onvif_status: string;
    onvif_message?: string;
    recommended_profile_token?: string | null;
    effective_mode: string;
    target: { width: number; height: number; fps: number };
    profiles: Array<{
      token?: string | null;
      name?: string | null;
      media_service?: string | null;
      encoding?: string | null;
      width?: number | null;
      height?: number | null;
      fps?: number | null;
      bitrate_kbps?: number | null;
    }>;
  }> {
    return this.request(`/api/v1/cameras/${encodeURIComponent(cameraId)}/multiview-input/capabilities`);
  }

  getRuntimeConfig(): Promise<RuntimeConfigResponse> {
    return this.request("/api/v1/config/effective");
  }

  patchRuntimeConfig(payload: Record<string, unknown>): Promise<unknown> {
    return this.request("/api/v1/config/runtime", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  putRuntimeConfig(payload: Record<string, unknown>): Promise<unknown> {
    return this.request("/api/v1/config/runtime", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  applyConfig(): Promise<unknown> {
    return this.request("/api/v1/config/apply", { method: "POST" });
  }

  restartControl(): Promise<unknown> {
    return this.request("/api/v1/control/restart", { method: "POST" });
  }

  getUvcDevices(refresh = false): Promise<UvcDevicesResponse> {
    const suffix = refresh ? "?refresh=true" : "";
    return this.request(`/api/v1/uvc/devices${suffix}`);
  }

  getUvcDevice(deviceId: string): Promise<UvcDeviceItem> {
    return this.request(`/api/v1/uvc/devices/${encodeURIComponent(deviceId)}`);
  }

  suggestUvcDevice(
    deviceId: string,
    payload: Record<string, unknown>,
  ): Promise<{
    device_id: string;
    display_name: string;
    driver: string;
    suggestion: unknown;
  }> {
    return this.request(`/api/v1/uvc/devices/${encodeURIComponent(deviceId)}/suggest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  applyUvcDevice(deviceId: string, payload: Record<string, unknown>): Promise<unknown> {
    return this.request(`/api/v1/uvc/devices/${encodeURIComponent(deviceId)}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  getCameraSnapshot(cameraId: string): Promise<Blob> {
    return this.request(`/api/v1/cameras/${encodeURIComponent(cameraId)}/snapshot`, {}, false);
  }

  getMultiviewSnapshot(viewId: string): Promise<Blob> {
    return this.request(
      `/api/v1/multiview/views/${encodeURIComponent(viewId)}/snapshot`,
      {},
      false,
    );
  }

  getRecordingStreams(): Promise<RecordingStreamListResponse> {
    return this.request("/api/v1/recordings/streams");
  }

  getRecordings(
    params: {
      streamId?: string;
      status?: "all" | "stable" | "recording";
      recordedFrom?: number;
      recordedTo?: number;
      sortBy?: "stream" | "recorded" | "size";
      sortDir?: "asc" | "desc";
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<RecordingListResponse> {
    const search = new URLSearchParams();
    if (params.streamId) {
      search.set("stream_id", params.streamId);
    }
    if (typeof params.limit === "number") {
      search.set("limit", String(params.limit));
    }
    if (typeof params.offset === "number") {
      search.set("offset", String(params.offset));
    }
    if (params.status) {
      search.set("status", params.status);
    }
    if (typeof params.recordedFrom === "number") {
      search.set("recorded_from", String(params.recordedFrom));
    }
    if (typeof params.recordedTo === "number") {
      search.set("recorded_to", String(params.recordedTo));
    }
    if (params.sortBy) {
      search.set("sort_by", params.sortBy);
    }
    if (params.sortDir) {
      search.set("sort_dir", params.sortDir);
    }
    const query = search.toString();
    return this.request(`/api/v1/recordings${query ? `?${query}` : ""}`);
  }

  getRecordingFile(fileId: string): Promise<Blob> {
    return this.request(`/api/v1/recordings/files/${encodeURIComponent(fileId)}`, {}, false);
  }

  getRecordingFileUrl(fileId: string): string {
    return this.buildDirectUrl(`/api/v1/recordings/files/${encodeURIComponent(fileId)}`);
  }

  getRecordingThumbnailUrl(fileId: string, recordedAt?: number): string {
    const path = `/api/v1/recordings/files/${encodeURIComponent(fileId)}/thumbnail`;
    const version = typeof recordedAt === "number" ? `?v=${encodeURIComponent(recordedAt.toFixed(3))}` : "";
    return `${this.buildDirectUrl(path)}${version}`;
  }

  prepareRecordingPlayback(fileId: string): Promise<RecordingPlaybackPrepareResponse> {
    return this.request(`/api/v1/recordings/files/${encodeURIComponent(fileId)}/prepare`, {
      method: "POST",
    });
  }

  getRecordingPlayableUrl(fileId: string): string {
    return this.buildDirectUrl(`/api/v1/recordings/files/${encodeURIComponent(fileId)}/playable`);
  }
}
