import { useEffect, useState } from 'react';
import type { ApiClient } from '../api/client';

type NetworkStatus = Awaited<ReturnType<ApiClient['getNetwork']>>;

function RestartInstructions() {
  return <details className="restart-instructions">
    <summary>How to restart FlintEye</summary>
    <ul>
      <li>Desktop: choose Quit FlintEye from the app menu, then open it again.</li>
      <li>Terminal or SSH: stop FlintEye with Ctrl+C, then rerun the same command.</li>
      <li>systemd: restart the FlintEye service using <code>systemctl restart flinteye</code> with your administrator account.</li>
      <li>Docker Compose: run <code>docker compose restart</code> in your FlintEye project directory.</li>
    </ul>
  </details>;
}

export function ConnectionReminder({api, onConfigure}: {api: ApiClient; onConfigure: () => void}) {
  const [status, setStatus] = useState<NetworkStatus | null>(null);
  useEffect(() => {
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(window.location.hostname)) return;
    let active = true;
    void api.getNetwork().then(value => {
      if (active && value.saved) setStatus(value);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [api]);
  if (!status || (!status.restart_required && status.lan_state !== 'unavailable')) return null;
  return <section className="connection-reminder panel-note" aria-label="LAN or VPN connection">
    <p role="status">{status.restart_required ? 'Connection changes are saved. Restart FlintEye to apply them.' :
      status.error || 'LAN HTTPS could not start. Change the connection settings on this computer.'}</p>
    {status.restart_required && <RestartInstructions />}
    <button type="button" onClick={onConfigure}>Open connection settings</button>
  </section>;
}

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
  const activeAddress = status?.restart_required ? null : status?.lan_url;
  const connectionLabel = status?.restart_required ? 'Restart required' : status?.lan_url ? 'Active' :
    status?.lan_state === 'unavailable' ? 'Listener unavailable' : 'Off';
  const dirty = Boolean(status && (enabled !== status.saved.enabled || rtspEnabled !== Boolean(status.saved.rtsp_enabled) || address !== status.saved.address || sources !== status.saved.allowed_subnets.join(', ')));
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  const refresh = async (resetForm = true) => {
    const next = await api.getNetwork();
    if (!next.saved) throw new Error('LAN settings unavailable');
    setStatus(next);
    if (resetForm) {
      setEnabled(next.saved.enabled);
      setRtspEnabled(Boolean(next.saved.rtsp_enabled));
      setAddress(next.saved.address);
      setSources(next.saved.allowed_subnets.join(', '));
    }
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
  return <details id="lan-connection" className="runtime-advanced network-access form-span-3" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary><span><strong>LAN connection and certificate trust</strong><small>Optional access from other devices on a LAN or VPN.</small></span></summary>
    <div className="network-access-body">
    <p className="field-help">Allow access below, save, and restart FlintEye. On each viewing device, trust the public certificate before opening the active HTTPS address.</p>
    {error && <p className="panel-error" role="alert">{error}</p>}
    {status && <>
      <dl className="network-addresses">
        <div><dt>This computer (HTTP)</dt><dd>{status.local_url || 'Unavailable'}</dd></div>
        <div><dt>LAN or VPN connection</dt><dd>{connectionLabel}</dd></div>
        {activeAddress && <div><dt>Active address for other devices (HTTPS)</dt><dd><a href={activeAddress}>{activeAddress}</a></dd></div>}
      </dl>
      {status.error && <p className="panel-error" role="alert">{status.error}</p>}
      {status.restart_required && <>
        <p className="panel-note" role="status">Connection changes are saved. Restart FlintEye to apply them.</p>
        <RestartInstructions />
      </>}
      {status.fingerprint && <div className="network-certificate"><strong>CA SHA-256 fingerprint</strong><code>{status.fingerprint}</code><span>Expires: {status.ca_expires}</span></div>}
      <form aria-busy={busy} onSubmit={e => {e.preventDefault(); void act(() => api.networkAction('', {enabled, address, rtsp_enabled: enabled && rtspEnabled, allowed_subnets: sources.split(',').map(s => s.trim()).filter(Boolean)}, 'PUT'), true);}}>
        <fieldset className="settings-fields" disabled={busy || blocked}>
          <div className="form-grid">
          <label className="check form-span-3"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /><span>Allow access from other devices on LAN or VPN (HTTPS)</span></label>
          <label>Server IPv4 address<input value={address} onChange={e => setAddress(e.target.value)} placeholder="192.168.1.10" required={enabled} aria-describedby="network-address-help"/></label>
          <label className="form-span-2">Permitted source networks (comma separated)<input value={sources} onChange={e => setSources(e.target.value)} placeholder="192.168.1.0/24" required={enabled} aria-describedby="network-source-help"/></label>
          <p id="network-source-help" className="field-help form-span-3">Enter client networks as seen by FlintEye. A VPN can give the client a different IP range from the server. For Tailscale, enter this server’s Tailscale IPv4 address and allow the viewing devices’ addresses, using /32 for an individual device.</p>
          <label className="check form-span-3 advanced-setting"><input type="checkbox" disabled={!enabled} checked={enabled && rtspEnabled} onChange={e => setRtspEnabled(e.target.checked)} /><span>Allow external players (RTSPS, TCP 8322)</span></label>
          <p id="network-address-help" className="field-help form-span-3">Choose an IP assigned to this server. Reserve it in your router to keep the same address after reboot. Saving does not change the current connection.</p>
          </div>
          <div className="button-row">
          <button type="submit" disabled={!dirty}>Save connection settings</button>
          <button type="button" disabled={!dirty} onClick={() => {if (window.confirm('Discard the unsaved LAN connection changes?')) void refresh();}}>Discard connection changes</button>
          </div>
        </fieldset>
      </form>
      <div className="button-row">
        <button type="button" disabled={busy} onClick={() => void refresh(false).catch(() => setError('Could not read the active connection status.'))}>Refresh connection status</button>
        <button disabled={busy || blocked || !activeAddress}
          onClick={() => void act(() => api.networkAction('/guide', {}))}>Save public certificate and connection guide</button>
        {status.can_manage_firewall && <button className="advanced-setting" disabled={busy || blocked || !status.saved.enabled} onClick={() => { if (window.confirm('Allow HTTPS TCP 18080 (or your configured API port) and WebRTC UDP 8189 (plus RTSPS TCP 8322 if enabled) for the selected IP and source ranges, on Private networks only? Windows will request administrator approval.')) void act(() => api.networkAction('/firewall', {action:'apply'})); }}>Windows: allow selected LAN access…</button>}
        {status.can_manage_firewall && <button className="advanced-setting" disabled={busy || blocked} onClick={() => void act(() => api.networkAction('/firewall', {action:'remove'}))}>Windows: remove this installation’s rules…</button>}
        <button className="advanced-setting" disabled={busy || blocked || !status.saved.enabled} onClick={() => {if (window.confirm('Replace the trust certificate? Every viewing device will need to trust the new certificate.')) void act(() => api.networkAction('/renew-trust', {confirm:true}));}}>Renew trust certificate…</button>
      </div>
      {status.last_denied_source && <p className="panel-note" role="status">Last source outside the permitted ranges <code>{status.last_denied_source}</code>. Compare this address with the permitted source networks above.</p>}
      {status.saved.rtsp_enabled && <div className="advanced-setting">
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
      <p className="field-help">If your browser reports ERR_CERT_AUTHORITY_INVALID, match the public CA fingerprint against this screen and follow the trust instructions on the viewing device.</p>
    </>}
    </div>
  </details>;
}
