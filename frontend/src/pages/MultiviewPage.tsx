import { useMemo, useState } from "react";
import type { ApiClient } from "../api/client";
import type { MultiviewStatus, MultiviewViewItem } from "../types";
import { usePolling } from "../hooks/usePolling";
import { WebRtcEmbed } from "../components/WebRtcEmbed";

interface MultiviewPageProps {
  api: ApiClient;
}

function healthClass(state: string | undefined): string {
  if (state === "healthy") {
    return "ok";
  }
  if (state === "degraded" || state === "starting" || state === "buffering" || state === "holding" || state === "reconnecting") {
    return "warn";
  }
  if (state === "disabled" || state === "excluded") {
    return "muted";
  }
  return "ng";
}

export function MultiviewPage({ api }: MultiviewPageProps): JSX.Element {
  const [views, setViews] = useState<MultiviewViewItem[]>([]);
  const [selectedViewId, setSelectedViewId] = useState<string | null>(null);
  const [status, setStatus] = useState<MultiviewStatus>({ updated_at: null, views: [] });
  const [error, setError] = useState("");

  usePolling(async () => {
    try {
      const [data, health] = await Promise.all([api.getMultiviewViews(), api.getMultiviewStatus()]);
      setViews(data.items);
      setStatus(health);
      if (!selectedViewId && data.items.length > 0) {
        setSelectedViewId(data.items[0].id);
      }
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load multiview data");
    }
  }, 4000);

  const selectedView = useMemo(
    () => views.find((view) => view.id === selectedViewId) ?? null,
    [views, selectedViewId],
  );
  const selectedStatus = status.views.find((view) => view.id === selectedViewId);

  return (
    <div className="page">
      <h2>Multiview</h2>
      {error && <div className="panel-error">{error}</div>}
      <div className="live-layout">
        <div className="panel-list">
          <div className="panel-list-title">Views</div>
          {views.length === 0 ? (
            <div className="panel-empty">No multiview outputs available.</div>
          ) : (
            views.map((view) => (
              <button
                key={view.id}
                type="button"
                className={view.id === selectedViewId ? "panel-list-item active" : "panel-list-item"}
                onClick={() => setSelectedViewId(view.id)}
              >
                <div>{view.id}</div>
                <small>
                  {view.sources.length} sources
                  {view.source_items?.some((source) => source.health.placeholder)
                    ? ` / ${view.source_items.filter((source) => source.health.placeholder).length} no stream`
                    : ""}
                  {(status.views.find((item) => item.id === view.id)?.decode_error_count ?? 0) > 0
                    ? ` / ${status.views.find((item) => item.id === view.id)?.decode_error_count} decode errors`
                    : ""}
                </small>
                {status.views.find((item) => item.id === view.id) && (
                  <span className={`status-tag ${healthClass(status.views.find((item) => item.id === view.id)?.state)}`}>
                    {status.views.find((item) => item.id === view.id)?.state}
                  </span>
                )}
              </button>
            ))
          )}
          {selectedView?.source_items?.length ? (
            <div className="source-health-list">
              {selectedView.source_items.map((source) => {
                const input = selectedStatus?.inputs.find(
                  (item) => item.path === source.path || item.path.endsWith(`/${source.path}`),
                );
                const state = input?.state ?? source.health.state;
                return (
                <div key={source.path} className="source-health-item">
                  <div>
                    <strong>{source.label || source.path}</strong>
                    <small>/{source.path}</small>
                  </div>
                  <div>
                    <span className={`status-tag ${healthClass(state)}`}>{state}</span>
                    {input?.buffer_delay_sec != null && (
                      <small>{input.buffered_frames ?? 0} frames / {input.buffer_delay_sec}s delayed</small>
                    )}
                    {input?.reason && <small>{input.reason}</small>}
                  </div>
                </div>
                );
              })}
            </div>
          ) : null}
        </div>
        <WebRtcEmbed
          url={selectedView?.webrtc_url ?? null}
          title={selectedView ? `Multiview: ${selectedView.id}` : "Multiview"}
        />
      </div>
    </div>
  );
}
