import { useEffect, useState } from "react";
import type { ApiClient } from "../api/client";
import type { EventRecordingSettings, RecordingEvent, RecordingItem } from "../types";
import { usePolling } from "../hooks/usePolling";

export function EventRecordingOptions({ api, onSaveStarted }: {
  api: ApiClient;
  onSaveStarted?: () => (saved: boolean) => void;
}): JSX.Element {
  const [settings, setSettings] = useState<EventRecordingSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    void api.getEventRecordingSettings().then(value => {
      if (current) setSettings(value);
    }).catch(() => {
      if (current) setError("Event recording settings could not be loaded.");
    });
    return () => { current = false; };
  }, [api]);

  const save = async (rotate: boolean): Promise<void> => {
    if (!settings || busy) return;
    const finish = onSaveStarted?.();
    let saved = false;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.saveEventRecordingSettings({
        enabled: settings.enabled, folder: settings.folder, max_lookback_sec: settings.max_lookback_sec,
      }, rotate);
      setSettings(result);
      setMessage("Event recording settings saved.");
      saved = true;
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not save event recording settings.");
    } finally {
      setBusy(false);
      finish?.(saved);
    }
  };

  return <section className="configuration-card">
    <h4>Event recordings</h4>
    <p className="form-help">Save the video before an equipment event in a separate folder. The current recording segment finishes normally.</p>
    {error && <p className="panel-error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {settings && <>
      <div className="form-grid">
        <label className="check form-span-3">
          <input type="checkbox" checked={settings.enabled} disabled={busy}
            onChange={event => setSettings({ ...settings, enabled: event.target.checked })} />
          Enable event recordings
        </label>
        <label className="form-span-2">Event recording folder
          <input value={settings.folder} disabled={busy}
            onChange={event => setSettings({ ...settings, folder: event.target.value })} />
        </label>
        <label>Maximum lookback (seconds)
          <input type="number" min={1} max={3600} value={settings.max_lookback_sec} disabled={busy}
            onChange={event => setSettings({ ...settings, max_lookback_sec: Number(event.target.value) })} />
        </label>
      </div>
      <div className="button-row">
        <button type="button" aria-label="Save event settings" disabled={busy} onClick={() => void save(false)}>
          {busy ? "Saving event settings…" : "Save event settings"}
        </button>
        {settings.token_configured && <button type="button" disabled={busy} onClick={() => void save(true)}>
          Replace event token
        </button>}
      </div>
      {settings.token && <label className="form-span-3">
        Event token (copy it now)
        <input value={settings.token} readOnly onFocus={event => event.currentTarget.select()} autoComplete="off" />
      </label>}
    </>}
  </section>;
}

const PAGE_SIZE = 50;
const statusLabels: Record<string, string> = {
  waiting_recording: "Waiting for recording",
  waiting_storage: "Waiting for storage",
  processing: "Preparing clip",
  ready: "Saved",
  partial: "Partially saved",
  unavailable: "No recording",
  failed: "Failed",
  cancelled: "Cancelled",
};

function date(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString();
}

export function EventRecordingList({ api, canDownload, onPlay, busy }: {
  api: ApiClient;
  canDownload: boolean;
  onPlay: (item: RecordingItem) => void;
  busy: boolean;
}): JSX.Element {
  const [items, setItems] = useState<RecordingEvent[] | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState("");
  const refresh = async (isCurrent = () => true): Promise<void> => {
    try {
      const result = await api.getRecordingEvents(PAGE_SIZE + 1, offset);
      if (isCurrent()) { setItems(result.items); setError(""); }
    } catch (error) {
      if (isCurrent()) setError(error instanceof Error ? error.message : "Event recordings could not be loaded.");
    }
  };
  usePolling(refresh, 3000, offset);

  const cancel = async (id: string): Promise<void> => {
    setCancelling(id);
    try {
      await api.cancelRecordingEvent(id);
      await refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Event recording could not be cancelled.");
    } finally {
      setCancelling("");
    }
  };

  return <section className="section" aria-label="Event recordings">
    <h3>Event recordings</h3>
    {error && <p role="alert" className="panel-error">{error}</p>}
    {!items && !error && <p role="status">Loading event recordings…</p>}
    {items?.length === 0 && <p>No event recordings yet.</p>}
    {items?.slice(0, PAGE_SIZE).map(event => <article key={event.id} className="configuration-card">
      <h4>{event.label || "Equipment event"} · {date(event.occurred_at)}</h4>
      <p>{statusLabels[event.status] ?? event.status} · {event.detail}</p>
      <p>Requested {date(event.requested_from)} – {date(event.occurred_at)}</p>
      {event.cameras.map(camera => {
        const clips = event.clips.filter(clip => clip.camera_id === camera.id);
        return <div key={camera.id}>
          <strong>{camera.label}</strong>
          {clips.length === 0 && <div className="form-help">
            {["waiting_recording", "waiting_storage", "processing"].includes(event.status) ? "Clip pending" : "No saved clip"}
          </div>}
          {clips.map(clip => {
            const item: RecordingItem = {
              ...clip, relative_path: camera.label, is_stable: true, age_sec: 0,
              duration_sec: clip.ended_at - clip.started_at,
            };
            return <div key={clip.file_id} className="button-row">
              <span>{date(clip.started_at)} – {date(clip.ended_at)}</span>
              <button type="button" disabled={busy} onClick={() => onPlay(item)}>Play {camera.label}</button>
              {canDownload && <a href={api.getRecordingFileUrl(clip.file_id)} download>Download {camera.label}</a>}
            </div>;
          })}
        </div>;
      })}
      {canDownload && ["waiting_recording", "waiting_storage"].includes(event.status) &&
        <button type="button" disabled={Boolean(cancelling)} onClick={() => void cancel(event.id)}>Cancel event</button>}
    </article>)}
    {items && (offset > 0 || items.length > PAGE_SIZE) && <nav className="button-row" aria-label="Event recording pages">
      <button type="button" disabled={offset === 0} onClick={() => { setItems(null); setOffset(offset - PAGE_SIZE); }}>Previous</button>
      <button type="button" disabled={items.length <= PAGE_SIZE} onClick={() => { setItems(null); setOffset(offset + PAGE_SIZE); }}>Next</button>
    </nav>}
  </section>;
}
