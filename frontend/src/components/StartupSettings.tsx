import { useEffect, useState } from 'react';
import type { ApiClient } from '../api/client';

export function StartupSettings({ api }: { api: ApiClient }) {
  const [resume, setResume] = useState<boolean | null>(null);
  const [startup, setStartup] = useState<{ enabled: boolean; available: boolean; message: string } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    api.getMonitoringPreferences().then(value => { if (alive) setResume(value.resume_on_startup); })
      .catch(error => { if (alive) setError(error.message); });
    api.desktopCapabilities().then(async cap => {
      if (cap.startup_settings) {
        const next = await api.getDesktopStartup();
        if (alive) setStartup(next);
      }
    }).catch(() => undefined);
    return () => { alive = false; };
  }, [api]);
  const change = async (kind: 'resume' | 'startup', value: boolean) => {
    setBusy(true); setError('');
    try {
      if (kind === 'resume') setResume((await api.setMonitoringPreferences(value)).resume_on_startup);
      else setStartup(await api.setDesktopStartup(value));
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not save startup settings'); }
    finally { setBusy(false); }
  };
  return <section className="section startup-settings">
    <h3>Monitoring and startup</h3>
    <p>Stop monitoring leaves settings available. Quit FlintEye from its desktop menu to stop the application completely.</p>
    <label className="checkbox-row"><input type="checkbox" checked={resume ?? false} disabled={busy || resume === null}
      onChange={event => void change('resume', event.target.checked)} />Always resume monitoring when FlintEye starts</label>
    <p className="field-help">Off by default: a stopped session stays stopped after restarting FlintEye or the computer. Quitting while monitoring preserves the running preference. This setting saves immediately.</p>
    {startup && <>
      <label className="checkbox-row"><input type="checkbox" checked={startup.enabled} disabled={busy || !startup.available}
        onChange={event => void change('startup', event.target.checked)} />Start FlintEye when I log in</label>
      <p className="field-help">Starts the desktop application at login; the monitoring preference above still applies. {startup.message}</p>
    </>}
    {error && <p className="panel-error" role="alert">{error}</p>}
  </section>;
}
