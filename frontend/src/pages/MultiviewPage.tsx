import { useMemo, useState } from "react";
import type { ApiClient } from "../api/client";
import type { MultiviewStatus, MultiviewViewItem } from "../types";
import { usePolling } from "../hooks/usePolling";
import { ResponsiveDetails } from "../components/ResponsiveDetails";
import { WebRtcEmbed } from "../components/WebRtcEmbed";
import { useMediaPaused } from '../hooks/MonitoringContext';

interface MultiviewPageProps {
  api: ApiClient;
  onConfigure?: () => void;
}

function healthClass(state: string | undefined): string {
  if (state === "healthy") {
    return "ok";
  }
  if (state === "degraded" || state === "starting" || state === "buffering" || state === "holding" || state === "reconnecting") {
    return "warn";
  }
  if (state === "disabled" || state === "excluded" || state === 'Stopped') {
    return "muted";
  }
  return "ng";
}

export function MultiviewPage({ api, onConfigure }: MultiviewPageProps): JSX.Element {
  const paused = useMediaPaused();
  const [views, setViews] = useState<MultiviewViewItem[]>([]);
  const [selectedViewId, setSelectedViewId] = useState<string | null>(null);
  const [status, setStatus] = useState<MultiviewStatus>({ updated_at: null, views: [] });
  const [error, setError] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);
  const [healthError, setHealthError] = useState("");

  usePolling(async (isCurrent) => {
    try {
      const [viewsResult, health] = await Promise.allSettled([api.getMultiviewViews(), api.getMultiviewStatus()]);
      if (!isCurrent()) return;
      if (health.status === "fulfilled") {
        setStatus(health.value); setHealthError("");
      } else {
        setStatus({ updated_at: null, views: [] }); setHealthError("Multiview health status is unavailable. Retrying automatically.");
      }
      if (viewsResult.status === "rejected") throw viewsResult.reason;
      const data = viewsResult.value;
      setViews(data.items);
      setSelectedViewId(previous => data.items.some(view => view.id === previous) ? previous : data.items[0]?.id ?? null);
      setError("");
    } catch (e) {
      if (isCurrent()) setError(e instanceof Error ? e.message : "Failed to load multiview data");
    } finally {
      if (isCurrent()) setInitialLoading(false);
    }
  }, 4000);

  const selectedView = useMemo(
    () => views.find((view) => view.id === selectedViewId) ?? null,
    [views, selectedViewId],
  );
  const selectedStatus = selectedView?.status ?? status.views.find((view) => view.id === selectedViewId);

  return (
    <div className="page">
      <h2>Multiview</h2>
      {error && <div className="panel-error">{error}</div>}
      {!paused && healthError && <div className="panel-note">{healthError}</div>}
      {initialLoading && <p role="status">Loading multiview outputs…</p>}
      <div className="live-layout multiview-live-layout">
        {selectedView && <div className="multiview-live-stage"><WebRtcEmbed
          url={selectedView?.webrtc_url ?? null}
          title={selectedView ? `Multiview: ${selectedView.id}` : "Multiview"}
          unavailableMessage="The selected Multiview output has no playback address. Check its configuration and stream status."
        /></div>}
        <div className="panel-list">
          <div className="panel-list-title">Views</div>
          {views.length === 0 ? (!initialLoading && !error && (
            <div className="panel-empty">No multiview outputs are configured.
              {onConfigure ? <button type="button" onClick={onConfigure}>Configure Multiview in Settings</button> : " Ask your administrator to configure Multiview."}
            </div>)
          ) : (
            views.map((view) => {
              const current = view.status ?? status.views.find((item) => item.id === view.id);
              return (
              <button
                key={view.id}
                type="button"
                className={view.id === selectedViewId ? "panel-list-item active" : "panel-list-item"}
                aria-pressed={view.id === selectedViewId}
                onClick={() => setSelectedViewId(view.id)}
              >
                <div>{view.id}</div>
                <small>
                  {view.sources.length} sources
                  {view.source_items?.some((source) => source.health.placeholder)
                    ? ` / ${view.source_items.filter((source) => source.health.placeholder).length} no stream`
                    : ""}
                  {(current?.decode_error_count ?? 0) > 0
                    ? ` / ${current?.decode_error_count} decode errors`
                    : ""}
                </small>
                {current && (
                  <span className={`status-tag ${paused ? 'muted' : healthClass(current.state)}`}>
                    {paused ? 'Stopped' : current.state}
                  </span>
                )}
              </button>
              );
            })
          )}
          {selectedView?.source_items?.length ? (
            <ResponsiveDetails summary="Source status">
            <div className="source-health-list">
              {selectedView.source_items.map((source) => {
                const input = selectedStatus?.inputs.find(
                  (item) => item.path === source.path || item.path === "__mv_input/" + source.path
                    || item.path === "__mv_buffer/" + source.path,
                );
                const state = paused ? 'Stopped' : input?.state ?? source.health.state;
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
                    {!paused && input?.reason && <small>{input.reason}</small>}
                  </div>
                </div>
                );
              })}
            </div>
            </ResponsiveDetails>
          ) : null}
        </div>

      </div>
    </div>
  );
}
