import { useEffect, useState } from 'react';
import type { ApiClient } from '../api/client';

export function NetworkAccess({api, blocked, onDirtyChange, onSaved}: {api: ApiClient; blocked: boolean; onDirtyChange: (dirty: boolean) => void; onSaved: () => Promise<void>}) {
  const [status, setStatus] = useState<Awaited<ReturnType<ApiClient['getNetwork']>> | null>(null);
  const [error, setError] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [address, setAddress] = useState('');
  const [sources, setSources] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [open, setOpen] = useState(false);
  const dirty = Boolean(status && (enabled !== status.saved.enabled || address !== status.saved.address || sources !== status.saved.allowed_subnets.join(', ')));
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  const refresh = async () => {
    const next = await api.getNetwork();
    if (!next.saved) throw new Error('LAN settings unavailable');
    setStatus(next); setEnabled(next.saved.enabled); setAddress(next.saved.address); setSources(next.saved.allowed_subnets.join(', '));
  };
  useEffect(() => { if (open) void refresh().catch(() => setError('Connection settings can be changed on the server computer. Open FlintEye there to configure LAN access.')); }, [open]);
  const act = async (action: () => Promise<unknown>, reload = false) => {
    if (busy || blocked) return;
    setBusy(true); setError(''); setMessage('');
    try { const result = await action() as {message?: string; path?: string}; setMessage(result.message || 'Saved. Restart FlintEye to apply connection changes.'); if (result.path) setMessage(`${result.message} Folder: ${result.path}`); if (reload) await onSaved(); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Operation failed'); }
    finally { setBusy(false); }
  };
  return <details className="runtime-advanced form-span-3" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary>LAN connection and certificate trust</summary>
    <p>Use this PC only by default. Optional LAN access uses HTTPS on port 18080 (or your configured API port). Each viewing PC, iPhone, iPad or Android device must first trust this installation’s certificate.</p>
    {error && <p role="alert">{error}</p>}
    {status && <>
      <p>Active local address: {status.local_url || 'Unavailable'}{status.lan_url && <> · LAN: {status.lan_url}</>}</p>
      {status.error && <p role="alert">{status.error}</p>}
      {status.restart_required && <p role="status">Connection changes take effect after restarting FlintEye.</p>}
      {status.fingerprint && <p className="panel-note">CA SHA-256: <code style={{overflowWrap: 'anywhere'}}>{status.fingerprint}</code><br/>Expires: {status.ca_expires}</p>}
      <form onSubmit={e => {e.preventDefault(); void act(() => api.networkAction('', {enabled, address, allowed_subnets: sources.split(',').map(s => s.trim()).filter(Boolean)}, 'PUT'), true);}}>
        <fieldset disabled={busy || blocked}>
          <label className="check"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />Enable LAN HTTPS</label>
          <label>Server IPv4 address<input value={address} onChange={e => setAddress(e.target.value)} placeholder="192.168.1.10" required={enabled}/></label>
          <label>Permitted source networks (comma separated)<input value={sources} onChange={e => setSources(e.target.value)} placeholder="192.168.1.0/24" required={enabled}/></label>
          <p>Choose an IP assigned to this server. Reserve it in your router to keep the same address after reboot. Saving does not change the current connection.</p>
          <button type="submit">Save connection settings</button>
          <button type="button" disabled={!dirty} onClick={() => {if (window.confirm('Discard the unsaved LAN connection changes?')) void refresh();}}>Discard connection changes</button>
        </fieldset>
      </form>
      <div className="button-row">
        <button disabled={busy || blocked || !status.saved.enabled} onClick={() => void act(() => api.networkAction('/guide', {}))}>Save public certificate and connection guide</button>
        <button disabled={busy || blocked || !status.saved.enabled} onClick={() => { if (window.confirm('Allow HTTPS TCP 18080 (or your configured API port) and WebRTC UDP 8189 for the selected IP and source ranges, on Private networks only? Windows will request administrator approval.')) void act(() => api.networkAction('/firewall', {action:'apply'})); }}>Windows: allow selected LAN access…</button>
        <button disabled={busy || blocked} onClick={() => void act(() => api.networkAction('/firewall', {action:'remove'}))}>Windows: remove this installation’s rules…</button>
        <button disabled={busy || blocked || !status.saved.enabled} onClick={() => {if (window.confirm('Replace the trust certificate? Every viewing device will need to trust the new certificate.')) void act(() => api.networkAction('/renew-trust', {confirm:true}));}}>Renew trust certificate…</button>
      </div>
      <p><a href={status.guide_url} target="_blank" rel="noreferrer">Trust, Firewall and recovery instructions / 日本語の手順</a></p>
      {message && <p role="status">{message}</p>}
      {blocked && <p>Save or discard your other settings before changing LAN access.</p>}
      <p>Use the public connection guide to transfer the CA certificate; compare its fingerprint on the server. Do not ignore browser certificate warnings or share private keys.</p>
    </>}
  </details>;
}
