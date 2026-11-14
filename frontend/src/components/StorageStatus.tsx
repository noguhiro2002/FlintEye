import { useEffect, useState } from 'react';
export function StorageStatus() {
  const [message, setMessage] = useState('');
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch('/api/v1/storage/status', { credentials: 'include' });
        if (response.ok) { const status = await response.json(); if (active) setMessage(status.message ?? ''); }
      } catch { /* Dashboard reports connection failures. */ }
    };
    void refresh(); const timer = window.setInterval(() => void refresh(), 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return message ? <div className="panel-error" role="alert">{message}</div> : null;
}
