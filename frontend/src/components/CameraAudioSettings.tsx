import { useEffect, useRef, useState } from "react";
import type { ApiClient } from "../api/client";
import type { CameraAudioConfig } from "../types";

const INITIAL: CameraAudioConfig = {
  enabled: false, preset: "standard", codec: "pcm", sample_rate: 16000,
  bit_depth: 16, channels: 1, bitrate_kbps: 64,
};
const PRESETS = {
  standard: [16000, 16], high: [48000, 24], middle: [12000, 16], low: [8000, 16],
} as const;
const MESSAGES: Record<string, string> = {
  available: "Audio input detected.",
  no_input: "This camera has no detected audio input.",
  permission: "FlintEye cannot access this microphone. Check microphone permissions.",
  capture_unavailable: "The Linux camera microphone requires ALSA capture utilities.",
  unknown: "Check whether this camera has an available audio input.",
};

export function CameraAudioSettings({ api, cameraId, blocked, saved, current }: {
  api: ApiClient;
  cameraId: string;
  current?: CameraAudioConfig;
  blocked: boolean;
  saved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(current ?? INITIAL);
  const [original, setOriginal] = useState<CameraAudioConfig | null>(current ?? INITIAL);
  const [availability, setAvailability] = useState("unknown");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(0);
  useEffect(() => () => { request.current += 1; }, []);
  const check = async () => {
    const id = ++request.current;
    setBusy(true);
    setError("");
    try {
      const result = await api.getCameraAudio(cameraId);
      if (request.current !== id) return;
      setDraft(result.settings);
      setOriginal(result.settings);
      setAvailability(result.availability);
    } catch (e) {
      if (request.current === id) setError(e instanceof Error ? e.message : "Audio check failed.");
    } finally {
      if (request.current === id) setBusy(false);
    }
  };
  const save = async () => {
    const id = ++request.current;
    setBusy(true);
    setError("");
    try {
      const result = await api.saveCameraAudio(cameraId, draft);
      if (request.current !== id) return;
      setDraft(result.settings);
      setOriginal(result.settings);
      if (result.settings.enabled) setAvailability(result.availability);
      await saved();
    } catch (e) {
      if (request.current === id) setError(e instanceof Error ? e.message : "Audio settings could not be saved.");
    } finally {
      if (request.current === id) setBusy(false);
    }
  };
  const custom = draft.preset === "custom";
  const dirty = Boolean(original && JSON.stringify(draft) !== JSON.stringify(original));
  const changePreset = (preset: CameraAudioConfig["preset"]) => {
    if (preset === "custom") {
      setDraft({ ...draft, preset });
      return;
    }
    const [sample_rate, bit_depth] = PRESETS[preset];
    setDraft({ ...draft, preset, sample_rate, bit_depth, codec: "pcm", channels: 1 });
  };
  return <section className="camera-audio" aria-label="Camera audio">
    <fieldset className="settings-fields" disabled={busy || blocked}>
      <div className="camera-audio-toolbar">
        <label className="check">
          <input type="checkbox" checked={draft.enabled} disabled={!original || (!draft.enabled && availability !== "available")}
            onChange={e => setDraft({ ...draft, enabled: e.target.checked })} />
          <span>Enable camera audio</span>
        </label>
        <span className="field-help" role="status">{busy ? "Checking or saving audio…" : MESSAGES[availability]}</span>
        <button type="button" onClick={() => void check()} disabled={dirty}>Check audio input</button>
        {dirty && <button type="button" onClick={() => void save()}>Save camera audio</button>}
      </div>
      {draft.enabled && <div className="form-grid">
        <label>Audio preset<select value={draft.preset} onChange={e => changePreset(e.target.value as CameraAudioConfig["preset"])}>
          <option value="standard">Standard · 16 kHz · 16 bit</option>
          <option value="high">High · 48 kHz · 24 bit</option>
          <option value="middle">Middle · 12 kHz · 16 bit</option>
          <option value="low">Low · 8 kHz · 16 bit</option>
          <option value="custom">Custom</option>
        </select></label>
        {custom && <>
          <label>Recording codec<select value={draft.codec} onChange={e => setDraft({ ...draft, codec: e.target.value as CameraAudioConfig["codec"] })}>
            <option value="pcm">PCM (uncompressed)</option><option value="aac">AAC</option>
          </select></label>
          <label>Sample rate<select value={draft.sample_rate} onChange={e => setDraft({ ...draft, sample_rate: Number(e.target.value) })}>
            {[8000, 12000, 16000, 22050, 24000, 32000, 44100, 48000].map(rate => <option key={rate} value={rate}>{rate} Hz</option>)}
          </select></label>
          <label>Channels<select value={draft.channels} onChange={e => setDraft({ ...draft, channels: Number(e.target.value) })}>
            <option value={1}>Mono</option><option value={2}>Stereo</option>
          </select></label>
          {draft.codec === "pcm" ? <label>Bit depth<select value={draft.bit_depth} onChange={e => setDraft({ ...draft, bit_depth: Number(e.target.value) })}>
            <option value={16}>16 bit</option><option value={24}>24 bit</option>
          </select></label> : <label>Target bitrate (kbps)<input type="number" min={16} max={320} value={draft.bitrate_kbps}
            onChange={e => setDraft({ ...draft, bitrate_kbps: Number(e.target.value) })} /></label>}
        </>}
        {draft.codec === "pcm" && <p className="field-help">Audio uses {draft.sample_rate * draft.bit_depth * draft.channels / 1000} kbps before container overhead.</p>}
      </div>}
    </fieldset>
    {error && <p role="alert" className="panel-error">{error}</p>}
  </section>;
}
