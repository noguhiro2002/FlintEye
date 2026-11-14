import { useState } from "react";
import type { ApiClient } from "../api/client";
import type { DashboardStatus } from "../types";
import { usePolling } from "../hooks/usePolling";
import { StatusBadge } from "../components/StatusBadge";

interface DashboardPageProps {
  api: ApiClient;
}

export function DashboardPage({ api }: DashboardPageProps): JSX.Element {
  const [status, setStatus] = useState<DashboardStatus | null>(null);
  const [error, setError] = useState("");

  usePolling(async () => {
    try {
      const next = await api.getStatus();
      setStatus(next);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch status");
    }
  }, 3000);

  if (!status && error) {
    return <div className="panel-error">{error}</div>;
  }

  return (
    <div className="page">
      <h2>Dashboard</h2>
      {error && <div className="panel-error">{error}</div>}
      {status ? (
        <>
          <div className="cards">
            <div className="card">
              <div className="card-title">MediaMTX</div>
              <StatusBadge ok={Boolean(status.mediamtx.running)} label={status.mediamtx.status} />
              <div className="card-sub">{status.mediamtx.mode}</div>
            </div>
            <div className="card">
              <div className="card-title">Cameras</div>
              <div className="card-value">
                {status.cameras_enabled} / {status.cameras_total}
              </div>
            </div>
            <div className="card">
              <div className="card-title">Multiview</div>
              <StatusBadge ok={status.multiview_enabled} label={status.multiview_enabled ? "Enabled" : "Disabled"} />
            </div>
            <div className="card">
              <div className="card-title">Running Processes</div>
              <div className="card-value">{status.running_processes}</div>
            </div>
          </div>

          <div className="section">
            <h3>Process List</h3>
            <div className="table-scroll">
            <table className="table responsive-table dashboard-process-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>PID</th>
                  <th>Restarts</th>
                </tr>
              </thead>
              <tbody>
                {status.processes.items.map((item) => (
                  <tr key={item.id}>
                    <td data-label="ID">{item.id}</td>
                    <td data-label="Kind">{item.kind}</td>
                    <td data-label="Status">{item.status}</td>
                    <td data-label="PID">{item.pid ?? "-"}</td>
                    <td data-label="Restarts">{item.restart_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        </>
      ) : (
        <div>Loading...</div>
      )}
    </div>
  );
}
