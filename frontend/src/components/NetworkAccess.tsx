import { useEffect, useState } from 'react';
import type { ApiClient } from '../api/client';

export function NetworkAccess({api, blocked, onDirtyChange, onSaved}: {api: ApiClient; blocked: boolean; onDirtyChange: (dirty: boolean) => void; onSaved: () => Promise<void>}) {
  const [status, setStatus] = useState<Awaited<ReturnType<ApiClient['getNetwork']>> | null>(null);
  const [error, setError] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [address, setAddress] = useState('');
  const [rtspEnabled, setRtspEnabled] = useState(false);
  const [credential, setCredential] = useState<{ username: string; password: string } | null>(null);
  const [sources, setSources] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [open, setOpen] = useState(false);
  const dirty = Boolean(status && (enabled !== status.saved.enabled || rtspEnabled !== Boolean(status.saved.rtsp_enabled) || address !== status.saved.address || sources !== status.saved.allowed_subnets.join(', ')));
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  const refresh = async () => {
    const next = await api.getNetwork();
    if (!next.saved) throw new Error('LAN settings unavailable');
    setStatus(next); setEnabled(next.saved.enabled); setRtspEnabled(Boolean(next.saved.rtsp_enabled)); setAddress(next.saved.address); setSources(next.saved.allowed_subnets.join(', '));
  };
  useEffect(() => { if (open) void refresh().catch(() => setError('Connection settings can be changed on the server computer. Open FlintEye there to configure LAN access.')); }, [open]);
  const act = async (action: () => Promise<unknown>, reload = false) => {
    if (busy || blocked) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await action() as {message?: string; path?: string; restart_required?: boolean};
      let feedback = result.message || 'Saved.';
      if (result.path) feedback += ` Folder: ${result.path}`;
      if (result.restart_required) feedback += ' Restart FlintEye to apply connection changes.';
      setMessage(feedback);
      if (reload) await onSaved();
      await refresh();
    }
    catch (e) { setError(e instanceof Error ? e.message : 'Operation failed'); }
    finally { setBusy(false); }
  };
  return <details className="runtime-advanced network-access form-span-3" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary><span><strong>LAN connection and certificate trust</strong><small>Optional access from other computers and mobile devices.</small></span></summary>
    <div className="network-access-body">
    <p className="field-help">Use this PC only by default. Optional LAN access uses HTTPS on port 18080 (or your configured API port). Each viewing PC, iPhone, iPad or Android device must first trust this installation’s certificate.</p>
    {error && <p className="panel-error" role="alert">{error}</p>}
    {status && <>
      <dl className="network-addresses">
        <div><dt>This computer</dt><dd>{status.local_url || 'Unavailable'}</dd></div>
        {status.lan_url && <div><dt>Other devices</dt><dd>{status.lan_url}</dd></div>}
      </dl>
      {status.error && <p className="panel-error" role="alert">{status.error}</p>}
      {status.restart_required && <p className="panel-note" role="status">Connection changes take effect after restarting FlintEye.</p>}
      {status.fingerprint && <div className="network-certificate"><strong>CA SHA-256 fingerprint</strong><code>{status.fingerprint}</code><span>Expires: {status.ca_expires}</span></div>}
      <form aria-busy={busy} onSubmit={e => {e.preventDefault(); void act(() => api.networkAction('', {enabled, address, rtsp_enabled: enabled && rtspEnabled, allowed_subnets: sources.split(',').map(s => s.trim()).filter(Boolean)}, 'PUT'), true);}}>
        <fieldset className="settings-fields" disabled={busy || blocked}>
          <div className="form-grid">
          <label className="check form-span-3"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /><span>Enable LAN HTTPS</span></label>
          <label>Server IPv4 address<input value={address} onChange={e => setAddress(e.target.value)} placeholder="192.168.1.10" required={enabled} aria-describedby="network-address-help"/></label>
          <label className="form-span-2">Permitted source networks (comma separated)<input value={sources} onChange={e => setSources(e.target.value)} placeholder="192.168.1.0/24" required={enabled}/></label>
          <label className="check form-span-3"><input type="checkbox" disabled={!enabled} checked={enabled && rtspEnabled} onChange={e => setRtspEnabled(e.target.checked)} /><span>Allow external players (RTSPS, TCP 8322)</span></label>
          <p id="network-address-help" className="field-help form-span-3">Choose an IP assigned to this server. Reserve it in your router to keep the same address after reboot. Saving does not change the current connection.</p>
          </div>
          <div className="button-row">
          <button type="submit" disabled={!dirty}>Save connection settings</button>
          <button type="button" disabled={!dirty} onClick={() => {if (window.confirm('Discard the unsaved LAN connection changes?')) void refresh();}}>Discard connection changes</button>
          </div>
        </fieldset>
      </form>
      <div className="button-row">
        <button disabled={busy || blocked || !status.saved.enabled} onClick={() => void act(() => api.networkAction('/guide', {}))}>Save public certificate and connection guide</button>
        <button disabled={busy || blocked || !status.saved.enabled} onClick={() => { if (window.confirm('Allow HTTPS TCP 18080 (or your configured API port) and WebRTC UDP 8189 (plus RTSPS TCP 8322 if enabled) for the selected IP and source ranges, on Private networks only? Windows will request administrator approval.')) void act(() => api.networkAction('/firewall', {action:'apply'})); }}>Windows: allow selected LAN access…</button>
        <button disabled={busy || blocked} onClick={() => void act(() => api.networkAction('/firewall', {action:'remove'}))}>Windows: remove this installation’s rules…</button>
        <button disabled={busy || blocked || !status.saved.enabled} onClick={() => {if (window.confirm('Replace the trust certificate? Every viewing device will need to trust the new certificate.')) void act(() => api.networkAction('/renew-trust', {confirm:true}));}}>Renew trust certificate…</button>
      </div>
      {status.saved.rtsp_enabled && <div>
        <button type="button" disabled={busy || blocked || dirty} onClick={() => {
          if (!window.confirm('Create a new RTSPS reader password? Existing players will need the new password.')) return;
          void act(async () => {
            const value = await api.networkAction('/rtsps-credential', {}) as { username: string; password: string };
            setCredential(value);
            return { message: 'Copy the RTSPS reader credentials now.' };
          });
        }}>Create or replace RTSPS reader password…</button>
        {credential && <p><strong>{credential.username}</strong> <code>{credential.password}</code>{" "}
          <button type="button" onClick={() => setCredential(null)}>Hide</button></p>}
      </div>}
      <p className="field-help"><a href={status.guide_url} target="_blank" rel="noreferrer">Trust, Firewall and recovery instructions / 日本語の手順</a></p>
      {message && <p className="panel-ok" role="status">{message}</p>}
      {blocked && <p className="field-help">Save or discard your other settings before changing LAN access.</p>}
      <p className="field-help">Use the public connection guide to transfer the CA certificate; compare its fingerprint on the server. Do not ignore browser certificate warnings or share private keys.</p>
    </>}
    </div>
  </details>;
}
