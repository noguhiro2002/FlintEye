import { useEffect, useMemo, useRef, useState } from "react";
import type { ApiClient } from "../api/client";
import type { ViewerCameraItem } from "../types";
import { usePolling } from "../hooks/usePolling";
import { WebRtcEmbed } from "../components/WebRtcEmbed";
import { PtzControls } from "../components/PtzControls";

interface LiveViewPageProps {
  api: ApiClient;
  canManage?: boolean;
  authRole?: "viewer" | "admin" | null;
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

export function LiveViewPage({ api, canManage = false, authRole = null }: LiveViewPageProps): JSX.Element {
  const [cameras, setCameras] = useState<ViewerCameraItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snapshotMap, setSnapshotMap] = useState<Record<string, string>>({});
  const snapshotMapRef = useRef<Record<string, string>>({});
  const [snapshotUpdatedAtMap, setSnapshotUpdatedAtMap] = useState<Record<string, number>>({});
  const [snapshotErrorMap, setSnapshotErrorMap] = useState<Record<string, string>>({});
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [thumbnailRefreshIntervalMs, setThumbnailRefreshIntervalMs] = useState(10000);
  const [error, setError] = useState("");

  usePolling(async () => {
    try {
      const data = await api.getViewerCameras();
      setCameras(data.items);
      if (!selectedId && data.items.length > 0) {
        setSelectedId(data.items[0].id);
      }
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load cameras");
    }
  }, 4000);

  usePolling(async () => {
    try {
      const info = await api.getViewerInfo();
      setThumbnailRefreshIntervalMs(
        Math.max(500, Math.round((info.snapshot.thumbnail_refresh_interval_sec || 10) * 1000)),
      );
    } catch {
      // Keep the previous interval when viewer info cannot be loaded.
    }
  }, 30000);

  const selectedCamera = useMemo(
    () => cameras.find((camera) => camera.id === selectedId) ?? null,
    [cameras, selectedId],
  );
  const canControlSelectedPtz = Boolean(
    selectedCamera?.ptz?.enabled &&
      (authRole === "admin" || (authRole === "viewer" && selectedCamera.ptz.access === "viewer")),
  );

  const refreshSnapshots = async (): Promise<void> => {
    if (cameras.length === 0) {
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
      setLoadingSnapshots(false);
    }
  };

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
      Object.values(snapshotMapRef.current).forEach((url) => {
        if (url) {
          URL.revokeObjectURL(url);
        }
      });
    };
  }, []);

  const handleExclude = async (camera: ViewerCameraItem): Promise<void> => {
    try {
      await api.excludeCamera(camera.id, "Manually excluded from Live View");
      const data = await api.getViewerCameras();
      setCameras(data.items);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to exclude camera");
    }
  };

  const handleRestore = async (camera: ViewerCameraItem): Promise<void> => {
    try {
      await api.restoreCamera(camera.id);
      const data = await api.getViewerCameras();
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
          <button type="button" onClick={() => void refreshSnapshots()} disabled={loadingSnapshots}>
            {loadingSnapshots ? "Refreshing..." : "Refresh Thumbnails"}
          </button>
        </div>
      </div>
      {error && <div className="panel-error">{error}</div>}

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
                role="button"
                tabIndex={0}
                onClick={() => setSelectedId(camera.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelectedId(camera.id);
                  }
                }}
              >
                <div className="thumb-title-row">
                  <span className="thumb-title">{camera.label || camera.id}</span>
                  <span className={`status-tag ${healthClass(health?.state)}`}>{healthLabel(health?.state)}</span>
                </div>
                {snapshotMap[camera.id] ? (
                  <div className="thumb-image-wrap">
                    <img src={snapshotMap[camera.id]} alt={camera.label || camera.id} />
                    {hasStaleSnapshot ? <span className="thumb-stale">stale</span> : null}
                  </div>
                ) : (
                  <div className="thumb-empty">
                    <div>No snapshot</div>
                    {snapshotErrorMap[camera.id] ? <small>{snapshotErrorMap[camera.id]}</small> : null}
                  </div>
                )}
                <div className="thumb-meta">
                  {health?.reason && health.reason !== "OK" ? <small>{health.reason}</small> : null}
                  {hasStaleSnapshot && updatedAt ? (
                    <small>Last snapshot: {new Date(updatedAt).toLocaleTimeString()}</small>
                  ) : null}
                </div>
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
          <WebRtcEmbed
            url={selectedCamera?.addresses.webrtc_url ?? null}
            title={selectedCamera ? `Camera: ${selectedCamera.label || selectedCamera.id}` : "Camera"}
          />
          {selectedCamera && canControlSelectedPtz ? (
            <PtzControls api={api} camera={selectedCamera} isAdmin={canManage} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
