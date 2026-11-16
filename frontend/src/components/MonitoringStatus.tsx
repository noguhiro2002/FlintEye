import { useState } from 'react';
import type { ApiClient } from '../api/client';
import { useMonitoring } from '../hooks/MonitoringContext';

export function MonitoringStatus({ api, canManage }: { api: ApiClient; canManage: boolean }) {
  const {status, unavailable, refresh} = useMonitoring();
  const [error, setError] = useState('');
  const [acting, setActing] = useState(false);
  const [activeAction, setActiveAction] = useState('');
  const act = async (action: 'start' | 'stop' | 'restart') => {
    if (acting) return;
    setActing(true); setActiveAction(action); setError('');
    try { await api.monitoringControl(action); await refresh(); }
    catch (error) { setError(error instanceof Error ? error.message : 'The operation could not be completed.'); }
    finally { setActing(false); }
  };
  const disabled = acting || status?.busy || unavailable;
  const counts = status?.counts;
  const symbols: Record<string, string> = { running: '▶', stopped: '■', error: '×', idle: '–' };
  return <section className="monitoring-status" aria-label="Monitoring status">
    <div className="monitoring-summary" role="status">
      <strong className={`monitoring-indicator is-${unavailable ? 'amber' : status?.color ?? 'gray'}`}>
        <span aria-hidden="true">{unavailable ? '!' : symbols[status?.state ?? ''] ?? '!'}</span>{' '}
        {unavailable ? 'Status unavailable' : status?.label ?? 'Checking monitoring status…'}
      </strong>
      {counts && <span>{counts.receiving} receiving / {counts.targets} targets · {counts.recording} recording · {counts.configured} configured</span>}
    </div>
    <p className="panel-note">{unavailable ? 'Cannot reach FlintEye. The last known state may be outdated.' : status?.message}</p>
    {canManage && status && <div className="button-row">
      <button type="button" disabled={disabled || status.desired_running || status.phase === 'finalizing'} onClick={() => void act('start')}>Start monitoring</button>
      <button type="button" disabled={disabled || (!status.desired_running && status.phase !== 'finalizing')} onClick={() => void act('stop')}>{status.phase === 'finalizing' && !status.busy ? 'Retry Stop' : 'Stop monitoring'}</button>
      <button type="button" disabled={disabled || !status.desired_running || status.phase === 'finalizing'} onClick={() => void act('restart')}>Restart monitoring</button>
      {acting && <span role="status">{activeAction === 'start' ? 'Starting monitoring…' : activeAction === 'restart' ? 'Restarting monitoring; finishing recordings first…' : 'Stopping monitoring; finishing recordings…'}</span>}
    </div>}
    {status?.phase === 'finalizing' && Boolean(status.pending_segments) && <p>{status.pending_segments} recording segment(s) awaiting completion.</p>}
    {Boolean(status?.previous_incomplete_segments) && <p className="panel-note">{status?.previous_incomplete_segments} segment(s) from a previous session have no completion record. Check storage and logs.</p>}
    {status && status.cameras.some(camera => !camera.receiving) && status.desired_running && <details>
      <summary>Camera reception details</summary>
      <ul>{status.cameras.map(camera => <li key={camera.id}>{camera.id}: {camera.reason}{camera.last_received_at ? ` · Last reception: ${new Date(camera.last_received_at * 1000).toLocaleString()}` : ''}</li>)}</ul>
    </details>}
    {error && <p role="alert" className="panel-error">{error}</p>}
  </section>;
}
