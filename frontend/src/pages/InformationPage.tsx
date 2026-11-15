import { useEffect, useRef, useState } from "react";
import type { ApiClient } from "../api/client";
import type { ViewerInfoResponse } from "../types";

interface InformationPageProps {
  api: ApiClient;
}

export function InformationPage({ api }: InformationPageProps): JSX.Element {
  const [build, setBuild] = useState<Awaited<ReturnType<ApiClient['getBuildInfo']>> | null>(null);
  const [info, setInfo] = useState<ViewerInfoResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const requestId = useRef(0);
  const [error, setError] = useState("");

  const load = async (): Promise<void> => {
    const request = ++requestId.current;
    setLoading(true);
    try {
      const [response, multiviewViews] = await Promise.all([
        api.getViewerInfo(),
        api.getMultiviewViews(),
      ]);
      if (request !== requestId.current) return;
      setInfo({
        ...response,
        multiview: {
          ...response.multiview,
          views: multiviewViews.items,
        },
      });
      setBuild(await api.getBuildInfo().catch(() => null));
      setError("");
    } catch (e) {
      if (request === requestId.current) setError(e instanceof Error ? e.message : "Failed to load information");
    } finally {
      if (request === requestId.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    return () => { requestId.current++; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="page">
      <div className="page-header">
        <h2>Information</h2>
        <button type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>
      {error && <div className="panel-error">{error}</div>}
      {!info ? (
        <div className="panel-empty" role="status">{loading ? "Loading information…" : "Information is unavailable. Use Refresh to retry."}</div>
      ) : (
        <>
          <div className="section">
            <h3>System</h3>
            <p>FlintEye {build?.version ?? 'version unavailable'} · {build?.channel ?? 'channel unavailable'}</p>
            <p className="panel-note">Build: <code>{build?.commit ?? 'source commit not recorded'}</code>{build?.dirty ? ' (local changes)' : ''}</p>
            <div className="form-grid">
              <label>
                Swagger UI
                <a href={info.api.swagger_url} target="_blank" rel="noreferrer">
                  {info.api.swagger_url}
                </a>
              </label>
              <label>
                ReDoc
                <a href={info.api.redoc_url} target="_blank" rel="noreferrer">
                  {info.api.redoc_url}
                </a>
              </label>
              <label>
                OpenAPI JSON
                <a href={info.api.openapi_url} target="_blank" rel="noreferrer">
                  {info.api.openapi_url}
                </a>
              </label>
              <label>
                RTSP Base URL
                <input value={info.rtsp_base_url} readOnly />
              </label>
              <label>
                WebRTC Base URL
                <input value={info.webrtc_base_url} readOnly />
              </label>
              <label>
                Updated At
                <input value={new Date(info.generated_at * 1000).toLocaleString()} readOnly />
              </label>
              <label>
                Snapshot Timeout
                <input value={`${info.snapshot.timeout_sec}s`} readOnly />
              </label>
              <label>
                Thumbnail Refresh
                <input value={`${info.snapshot.thumbnail_refresh_interval_sec}s`} readOnly />
              </label>
            </div>
          </div>

          <div className="section">
            <h3>Cameras</h3>
            {info.cameras.length === 0 && <p className="panel-note">No cameras are configured. An administrator can add cameras in Settings.</p>}
            <div className="table-scroll">
            <table className="table responsive-table information-camera-table">
              <thead>
                <tr>
                  <th>Camera</th>
                  <th>Type</th>
                  <th>RTSP</th>
                  <th>WebRTC</th>
                  <th>Resolution</th>
                  <th>FPS</th>
                  <th>Bitrate</th>
                  <th>Encoder</th>
                </tr>
              </thead>
              <tbody>
                {info.cameras.map((camera) => {
                  const width = camera.settings.width || "-";
                  const height = camera.settings.height || "-";
                  const fps = camera.settings.fps || "-";
                  const bitrate = camera.settings.bitrate || "-";
                  const encoder = camera.settings.encoder || "-";
                  return (
                    <tr key={camera.id}>
                      <td data-label="Camera">{camera.label || camera.id}</td>
                      <td data-label="Type">{camera.type}</td>
                      <td data-label="RTSP"><code>{camera.addresses.rtsp_url}</code></td>
                      <td data-label="WebRTC"><a href={camera.addresses.webrtc_url} target="_blank" rel="noreferrer">{camera.addresses.webrtc_url}</a></td>
                      <td data-label="Resolution">{width !== "-" && height !== "-" ? `${width}x${height}` : "-"}</td>
                      <td data-label="FPS">{fps}</td>
                      <td data-label="Bitrate">{bitrate}</td>
                      <td data-label="Encoder">{encoder}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </div>

          <div className="section">
            <h3>Multiview</h3>
            <div className="form-grid">
              <label>
                Enabled
                <input value={String(info.multiview.enabled)} readOnly />
              </label>
              <label>
                Output Prefix
                <input value={info.multiview.output_prefix} readOnly />
              </label>
              <label>
                Tile Count
                <input value={String(info.multiview.tile_count)} readOnly />
              </label>
              <label>
                Canvas
                <input value={`${info.multiview.canvas_width}x${info.multiview.canvas_height}`} readOnly />
              </label>
              <label>
                FPS
                <input value={String(info.multiview.fps)} readOnly />
              </label>
              <label>
                Bitrate
                <input value={info.multiview.bitrate ?? "-"} readOnly />
              </label>
              <label>
                Encoder
                <input value={info.multiview.encoder} readOnly />
              </label>
              <label>
                Quality Preset
                <input value={info.multiview.quality_preset} readOnly />
              </label>
            </div>
            <h4 className="information-subheading">Output addresses</h4>
            {info.multiview.views.length === 0 ? (
              <div className="panel-note">No Multiview output is currently configured.</div>
            ) : (
              <div className="table-scroll">
                <table className="table responsive-table information-address-table">
                  <thead>
                    <tr>
                      <th>View</th>
                      <th>RTSP</th>
                      <th>WebRTC</th>
                      <th>Sources</th>
                    </tr>
                  </thead>
                  <tbody>
                    {info.multiview.views.map((view) => (
                      <tr key={view.id}>
                        <td data-label="View">{view.id}</td>
                        <td data-label="RTSP"><code>{view.rtsp_url}</code></td>
                        <td data-label="WebRTC">
                          <a href={view.webrtc_url} target="_blank" rel="noreferrer">
                            {view.webrtc_url}
                          </a>
                        </td>
                        <td data-label="Sources">{view.sources.length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
