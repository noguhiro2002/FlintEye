import { useState } from 'react';
import { ApiClient, ApiError } from '../api/client';
import type { PageKey } from './Sidebar';
import type { SettingsTarget } from '../settingsNavigation';

export function SetupAccount({api, onDone, desktop, handoffReady}: {
  api: ApiClient; onDone: () => void; desktop: boolean; handoffReady: boolean;
}) {
  const [handoffExpired, setHandoffExpired] = useState(false);
  const useHandoff = handoffReady && !handoffExpired;
  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [lan, setLan] = useState(false);
  const [address, setAddress] = useState('');
  const [sources, setSources] = useState('');
  return <form className="login-form" onSubmit={async e => {
    e.preventDefault(); setError('');
    if (password !== confirm) { setError('Passwords do not match.'); return; }
    setBusy(true);
    try {
      await api.setup(useHandoff ? undefined : token, password, lan ? {
        enabled: true, address, allowed_subnets: sources.split(',').map(s => s.trim()).filter(Boolean),
      } : undefined);
      await api.login('admin', password);
      onDone();
    } catch (err) {
      if (useHandoff && err instanceof ApiError && err.status === 403) {
        setHandoffExpired(true);
        setError('Setup access expired. Reopen FlintEye from the app or enter the current token below.');
      } else {
        setError(err instanceof Error ? err.message : 'Could not complete setup.');
      }
    } finally { setBusy(false); }
  }}>
    <h2>Welcome to FlintEye</h2>
    <p>Create your administrator account. The username is <strong>admin</strong>.</p>
    <p id="setup-password-help">Use a password of at least 12 characters.</p>
    {!useHandoff && <>
      <p id="setup-token-help">{desktop
        ? 'On the computer running FlintEye, choose Open FlintEye from the app to continue automatically. To continue here, use the current token from Address and setup assistance.'
        : 'For Docker or systemd, read the setup-token file in the server data directory.'}</p>
      <label>{desktop ? 'Setup token' : 'Server setup token'}<input type="password" required value={token} onChange={e => setToken(e.target.value)} autoComplete="off" aria-describedby="setup-token-help" /></label>
    </>}
    <label>Password<input type="password" required minLength={12} maxLength={1024} value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" aria-describedby="setup-password-help" /></label>
    <label>Confirm password<input type="password" required minLength={12} value={confirm} onChange={e => setConfirm(e.target.value)} autoComplete="new-password" /></label>
    {['127.0.0.1', 'localhost', '[::1]'].includes(window.location.hostname) && <details>
      <summary>Optional LAN or VPN access for other devices</summary>
      <label className="check setup-lan-toggle"><input type="checkbox" checked={lan} onChange={e => setLan(e.target.checked)}/>Allow access from other devices on LAN or VPN (HTTPS)</label>
      {lan && <>
        <label>Server IPv4 address<input required value={address} onChange={e=>setAddress(e.target.value)} placeholder="192.168.1.10"/></label>
        <label>Permitted source networks<input required value={sources} onChange={e=>setSources(e.target.value)} placeholder="192.168.1.0/24"/></label>
        <p>This saves the connection settings. Restart FlintEye to activate HTTPS, then save the public certificate from Settings → Runtime & access. Each viewing device needs to trust that certificate before opening the shared address.</p>
      </>}
    </details>}
    {error && <p role="alert">{error}</p>}
    <button disabled={busy}>{busy ? 'Creating account…' : 'Create administrator account'}</button>
  </form>;
}

const steps: { title: string; body: string; page: PageKey; target?: SettingsTarget }[] = [
  { title: 'Welcome to FlintEye', body: 'Closing this browser does not stop recording. Use Stop monitoring to pause cameras and recording while keeping settings available. In the desktop menu or control window, Quit FlintEye stops the application completely. A stopped session stays stopped after restarting unless Resume monitoring on startup is enabled. For Docker or systemd, stop the service on the server. Monitoring requires the computer to remain awake and the service to keep running.', page: 'dashboard' },
  { title: 'Add your first camera', body: 'In Settings, find USB cameras to detect a connected device, or add an IP camera using its address and credentials. You can add cameras later.', page: 'settings', target: { section: 'cameras' } },
  { title: 'Choose where to save recordings', body: 'Open Settings → Recording to choose a recording folder on the computer running FlintEye. The suggested limit is half its free space, up to 50 GB. Choose Save changes to apply your choices.', page: 'settings', target: { section: 'recording', anchor: 'recording-folder' } },
  { title: 'Understand loop recording', body: 'FlintEye deletes the oldest completed recordings when either the retention period (7 days by default) or storage limit is reached. Storage limits can shorten the actual history. Previous recording locations are also cleaned even when hidden.', page: 'settings', target: { section: 'recording' } },
  { title: 'View your cameras', body: 'Open Live View to watch cameras and Recordings to play saved footage. Other devices on your LAN must sign in. Set the viewer password in Settings → Runtime & access before sharing access.', page: 'live' },
];

export function FirstRun({ api, navigate, onClose }: { api: ApiClient; navigate: (page: PageKey, target?: SettingsTarget) => void; onClose: () => void }) {
  const [step, setStep] = useState(0);
  const [error, setError] = useState('');
  const close = async () => {
    try { await api.patchRuntimeConfig({ ui: { onboarding_done: true } }); onClose(); }
    catch (err) { setError(String(err)); }
  };
  const go = (index: number) => { setStep(index); navigate(steps[index].page, steps[index].target); };
  return <aside className="first-run" aria-label="Getting started">
    <strong>{step + 1} / {steps.length} — {steps[step].title}</strong>
    <p>{steps[step].body}</p>
    {error && <p role="alert">{error}</p>}
    <div className="first-run-actions">
      <button onClick={() => void close()}>Skip for now</button>
      {step > 0 && <button onClick={() => go(step - 1)}>Back</button>}
      {step < steps.length - 1 ? <button onClick={() => go(step + 1)}>Next</button> : <button onClick={() => void close()}>Finish</button>}
    </div>
  </aside>;
}
