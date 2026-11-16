import { useEffect, useMemo, useRef, useState } from "react";
import type { ApiClient } from "../api/client";
import type { ViewerCameraItem } from "../types";
import { usePolling } from "../hooks/usePolling";
import { WebRtcEmbed } from "../components/WebRtcEmbed";
import { PtzControls } from "../components/PtzControls";
import { useMediaPaused } from '../hooks/MonitoringContext';

interface LiveViewPageProps {
  api: ApiClient;
  canManage?: boolean;
  authRole?: "viewer" | "admin" | null;
  onConfigure?: () => void;
}

function healthLabel(state: string | undefined): string {
  switch (state) {
    case "healthy":
      return "OK";
    case "degraded":
      return "Degraded";
    case "starting":
      return "Starting";
    case "quarantined":
      return "Quarantined";
    case "excluded":
      return "Excluded";
    case "disabled":
      return "Disabled";
    case "unhealthy":
      return "Unhealthy";
    default:
      return "Unknown";
  }
}

function healthClass(state: string | undefined): string {
  if (state === "healthy") {
    return "ok";
  }
  if (state === "degraded" || state === "starting") {
    return "warn";
  }
  if (state === "disabled" || state === "excluded") {
    return "muted";
  }
  return "ng";
}

export function LiveViewPage({ api, canManage = false, authRole = null, onConfigure }: LiveViewPageProps): JSX.Element {
  const paused = useMediaPaused();
  const pausedRef = useRef(paused); pausedRef.current = paused;
  const fetchingSnapshots = useRef(false);
  const [cameras, setCameras] = useState<ViewerCameraItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snapshotMap, setSnapshotMap] = useState<Record<string, string>>({});
  const snapshotMapRef = useRef<Record<string, string>>({});
  const [snapshotUpdatedAtMap, setSnapshotUpdatedAtMap] = useState<Record<string, number>>({});
  const [snapshotErrorMap, setSnapshotErrorMap] = useState<Record<string, string>>({});
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [thumbnailRefreshIntervalMs, setThumbnailRefreshIntervalMs] = useState(10000);
  const [error, setError] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);
  const cameraRequest = useRef(0);
  const snapshotRequest = useRef(0);

  usePolling(async (isCurrent) => {
    const request = ++cameraRequest.current;
    try {
      const data = await api.getViewerCameras();
      if (!isCurrent() || request !== cameraRequest.current) return;
      setCameras(data.items);
      setError("");
    } catch (e) {
      if (isCurrent() && request === cameraRequest.current) setError(e instanceof Error ? e.message : "Failed to load cameras");
    } finally {
      if (isCurrent() && request === cameraRequest.current) setInitialLoading(false);
    }
  }, 4000);

  usePolling(async (isCurrent) => {
    try {
      const info = await api.getViewerInfo();
      if (!isCurrent()) return;
      setThumbnailRefreshIntervalMs(
        Math.max(500, Math.round((info.snapshot.thumbnail_refresh_interval_sec || 10) * 1000)),
      );
    } catch {
      // Keep the previous interval when viewer info cannot be loaded.
    }
  }, 30000);

  useEffect(() => {
    setSelectedId(previous => cameras.some(camera => camera.id === previous) ? previous : cameras[0]?.id ?? null);
  }, [cameras]);

  const selectedCamera = useMemo(
    () => cameras.find((camera) => camera.id === selectedId) ?? null,
    [cameras, selectedId],
  );
  const canControlSelectedPtz = Boolean(
    selectedCamera?.ptz?.enabled &&
      (authRole === "admin" || (authRole === "viewer" && selectedCamera.ptz.access === "viewer")),
  );

  const refreshSnapshots = async (): Promise<void> => {
    if (pausedRef.current || fetchingSnapshots.current) return;
    fetchingSnapshots.current = true;
    const request = ++snapshotRequest.current;
    if (cameras.length === 0) {
      Object.values(snapshotMapRef.current).forEach(url => URL.revokeObjectURL(url));
      snapshotMapRef.current = {};
      setSnapshotMap({});
      setSnapshotUpdatedAtMap({});
      setSnapshotErrorMap({});
      setLoadingSnapshots(false);
      fetchingSnapshots.current = false;
      return;
    }
    setLoadingSnapshots(true);
    try {
      const nextSuccessful: Record<string, string> = {};
      const nextErrors: Record<string, string> = {};
      await Promise.all(
        cameras.map(async (camera) => {
          try {
            const blob = await api.getCameraSnapshot(camera.id);
            nextSuccessful[camera.id] = URL.createObjectURL(blob);
            nextErrors[camera.id] = "";
          } catch (e) {
            nextErrors[camera.id] = e instanceof Error ? e.message : "Failed to capture snapshot";
          }
        }),
      );
      if (request !== snapshotRequest.current || pausedRef.current) {
        Object.values(nextSuccessful).forEach(url => URL.revokeObjectURL(url));
        return;
      }

      setSnapshotMap((prev) => {
        const next: Record<string, string> = {};
        const activeCameraIds = new Set(cameras.map((camera) => camera.id));
        for (const camera of cameras) {
          const fresh = nextSuccessful[camera.id];
          if (fresh) {
            if (prev[camera.id]) {
              URL.revokeObjectURL(prev[camera.id]);
            }
            next[camera.id] = fresh;
          } else if (prev[camera.id]) {
            next[camera.id] = prev[camera.id];
          }
        }
        Object.entries(prev).forEach(([cameraId, url]) => {
          if (!activeCameraIds.has(cameraId) && url) {
            URL.revokeObjectURL(url);
          }
        });
        return next;
      });
      setSnapshotUpdatedAtMap((prev) => {
        const next: Record<string, number> = {};
        const now = Date.now();
        for (const camera of cameras) {
          next[camera.id] = nextSuccessful[camera.id] ? now : prev[camera.id];
        }
        return next;
      });
      setSnapshotErrorMap(nextErrors);
    } finally {
      fetchingSnapshots.current = false;
      if (request === snapshotRequest.current) setLoadingSnapshots(false);
    }
  };

  useEffect(() => {
    snapshotRequest.current++;
    if (paused) setLoadingSnapshots(false);
    else void refreshSnapshots();
  }, [paused]);

  useEffect(() => {
    void refreshSnapshots();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameras.map((x) => x.id).join(",")]);

  usePolling(async () => {
    await refreshSnapshots();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, thumbnailRefreshIntervalMs);

  useEffect(() => {
    snapshotMapRef.current = snapshotMap;
  }, [snapshotMap]);

  useEffect(() => {
    return () => {
      snapshotRequest.current++;
      cameraRequest.current++;
      Object.values(snapshotMapRef.current).forEach((url) => {
        if (url) {
          URL.revokeObjectURL(url);
        }
      });
    };
  }, []);

  const handleExclude = async (camera: ViewerCameraItem): Promise<void> => {
    const request = ++cameraRequest.current;
    try {
      await api.excludeCamera(camera.id, "Manually excluded from Live View");
      const data = await api.getViewerCameras();
      if (request !== cameraRequest.current) return;
      setCameras(data.items);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to exclude camera");
    }
  };

  const handleRestore = async (camera: ViewerCameraItem): Promise<void> => {
    const request = ++cameraRequest.current;
    try {
      await api.restoreCamera(camera.id);
      const data = await api.getViewerCameras();
      if (request !== cameraRequest.current) return;
      setCameras(data.items);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to restore camera");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Live View</h2>
        <div className="button-row">
          <div className="panel-note">Auto refresh: {(thumbnailRefreshIntervalMs / 1000).toFixed(1)}s</div>
          <button type="button" onClick={() => void refreshSnapshots()} disabled={paused || loadingSnapshots || cameras.length === 0}>
            {loadingSnapshots ? "Refreshing..." : "Refresh Thumbnails"}
          </button>
        </div>
      </div>
      {error && <div className="panel-error">{error}</div>}
      {initialLoading && <p role="status">Loading cameras…</p>}
      {!initialLoading && !error && cameras.length === 0 && <div className="panel-empty">
        No cameras are configured.{canManage && onConfigure
          ? <button type="button" onClick={onConfigure}>Add a camera in Settings</button>
          : " Ask your administrator to add a camera."}
      </div>}

      <div className="live-layout">
        <div className="thumb-grid">
          {cameras.map((camera) => {
            const selected = camera.id === selectedId;
            const health = camera.health;
            const hasStaleSnapshot = Boolean(snapshotMap[camera.id] && snapshotErrorMap[camera.id]);
            const updatedAt = snapshotUpdatedAtMap[camera.id];
            return (
              <div
                key={camera.id}
                className={selected ? "thumb selected" : "thumb"}
              >
                <button type="button" className="thumb-select" aria-label={`View ${camera.label || camera.id}`} aria-pressed={selected} onClick={() => setSelectedId(camera.id)}>
                <div className="thumb-title-row">
                  <span className="thumb-title">{camera.label || camera.id}</span>
                  <span className={`status-tag ${paused ? 'muted' : healthClass(health?.state)}`}>{paused ? 'Stopped' : healthLabel(health?.state)}</span>
                </div>
                {snapshotMap[camera.id] ? (
                  <div className="thumb-image-wrap">
                    <img src={snapshotMap[camera.id]} alt={camera.label || camera.id} />
                    {hasStaleSnapshot ? <span className="thumb-stale">stale</span> : null}
                  </div>
                ) : (
                  <div className="thumb-empty">
                    <div>{paused ? 'Monitoring stopped' : 'No snapshot'}</div>
                    {!paused && snapshotErrorMap[camera.id] ? <small>{snapshotErrorMap[camera.id]}</small> : null}
                  </div>
                )}
                <div className="thumb-meta">
                  {!paused && health?.reason && health.reason !== "OK" ? <small>{health.reason}</small> : null}
                  {hasStaleSnapshot && updatedAt ? (
                    <small>Last snapshot: {new Date(updatedAt).toLocaleTimeString()}</small>
                  ) : null}
                </div>
                </button>
                {canManage ? (
                  <div className="thumb-actions" onClick={(e) => e.stopPropagation()}>
                    {health?.manual_excluded || health?.quarantined ? (
                      <button type="button" onClick={() => void handleRestore(camera)}>
                        Restore
                      </button>
                    ) : (
                      <button type="button" onClick={() => void handleExclude(camera)}>
                        Exclude
                      </button>
                    )}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>

        <div className="live-view-stage">
          {selectedCamera && <WebRtcEmbed
            url={selectedCamera?.addresses.webrtc_url ?? null}
            title={selectedCamera ? `Camera: ${selectedCamera.label || selectedCamera.id}` : "Camera"}
          />}
          {selectedCamera && canControlSelectedPtz && !paused ? (
            <PtzControls key={selectedCamera.id} api={api} camera={selectedCamera} isAdmin={canManage} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
