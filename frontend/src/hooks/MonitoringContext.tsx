import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type { ApiClient } from '../api/client';
import type { MonitoringStatusResponse } from '../types';
import { usePolling } from './usePolling';

const Context = createContext<{ status: MonitoringStatusResponse | null; unavailable: boolean; refresh: () => Promise<void> }>({status: null, unavailable: false, refresh: async () => {}});

export function MonitoringProvider({ api, children }: { api: ApiClient; children: ReactNode }) {
  const [status, setStatus] = useState<MonitoringStatusResponse | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  const refresh = useCallback(async () => {
    const request = ++generation.current;
    try {
      const next = await api.getMonitoringStatus();
      if (!next.state || !next.counts || !Array.isArray(next.cameras)) throw new Error('Invalid monitoring status');
      if (request === generation.current) { setStatus(next); setUnavailable(false); }
    } catch { if (request === generation.current) setUnavailable(true); }
  }, [api]);
  usePolling(async () => { await refresh(); }, 2000);
  return <Context.Provider value={{status, unavailable, refresh}}>{children}</Context.Provider>;
}

export const useMonitoring = () => useContext(Context);
export function useMediaPaused(): boolean {
  const {status, unavailable} = useMonitoring();
  return Boolean(status && (unavailable || status.desired_running === false || ['stopping', 'finalizing', 'stopped'].includes(status.phase)));
}
