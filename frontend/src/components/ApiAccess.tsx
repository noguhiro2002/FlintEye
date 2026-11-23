import { useEffect, useState } from "react";
import type { ApiClient } from "../api/client";
import type { ApiKeyItem } from "../types";

export function ApiAccess({api}: {api: ApiClient}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ApiKeyItem[] | null>(null);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<ApiKeyItem["scope"]>("read");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let current = true;
    setError("");
    void api.getApiKeys().then(value => {
      if (current) setItems(value.items);
    }).catch(error => {
      if (current) setError(error.message);
    });
    return () => { current = false; };
  }, [api, open]);

  const create = async () => {
    setBusy(true); setError(""); setToken("");
    try {
      const {token: secret, ...item} = await api.createApiKey(name.trim(), scope);
      setItems(previous => [item, ...(previous ?? [])]);
      setName(""); setToken(secret);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not create the API key.");
    } finally { setBusy(false); }
  };
  const revoke = async (item: ApiKeyItem) => {
    if (!window.confirm("Revoke the API key for " + item.name + "?")) return;
    setBusy(true); setError(""); setToken("");
    try {
      await api.revokeApiKey(item.id);
      setItems(value => value?.map(row => row.id === item.id
        ? {...row, revoked_at: Date.now() / 1000} : row) ?? []);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not revoke the API key.");
    } finally { setBusy(false); }
  };
  const statusUrl = new URL(api.buildUrl("/api/v1/status/monitoring"), window.location.href).href;

  return <details className="runtime-advanced api-access form-span-3" onToggle={event => {
    setOpen(event.currentTarget.open);
    if (!event.currentTarget.open) setToken("");
  }}>
    <summary><span><strong>API access</strong><small>Keys for external tools</small></span></summary>
    <div className="api-access-body">
      <p className="field-help">Issue a separate key for each integration. Use the server’s HTTPS address from other devices.</p>
      {error && <p className="panel-error" role="alert">{error}</p>}
      {items && <>
        <form className="settings-field-actions" onSubmit={event => {
          event.preventDefault();
          if (name.trim() && !busy) void create();
        }}>
          <label>API key name<input value={name} onChange={event => setName(event.target.value)} maxLength={80} required disabled={busy} /></label>
          <label>API key permissions<select value={scope} onChange={event => setScope(event.target.value as ApiKeyItem["scope"])} disabled={busy}>
            <option value="read">Read only</option>
            <option value="monitor">Read and control monitoring</option>
          </select></label>
          <button type="submit" disabled={busy || !name.trim()}>Create API key</button>
        </form>
        {token && <div className="settings-field-actions">
          <label>New API key (copy it now)<input value={token} readOnly autoComplete="off"
            onFocus={event => event.currentTarget.select()} /></label>
          <button type="button" onClick={() => setToken("")}>Hide key</button>
        </div>}
        {items.length > 0 && <ul className="api-key-list" aria-label="Issued API keys">
          {items.map(item => <li key={item.id}>
            <strong>{item.name}</strong>
            <span>{item.scope === "read" ? "Read only" : "Read and control monitoring"}</span>
            <span>{item.revoked_at === null ? "Active" : "Revoked"}</span>
            {item.revoked_at === null && <button type="button" disabled={busy} onClick={() => void revoke(item)}>Revoke key</button>}
          </li>)}
        </ul>}
      </>}
      <pre>{'curl --fail-with-body -H "Authorization: Bearer $FLINTEYE_API_KEY" "' + statusUrl + '"'}</pre>
      <p className="field-help">
        For equipment events, use the token in Settings → Recording → Event recordings.
        {" "}<a href="https://github.com/noguhiro2002/FlintEye/blob/main/docs/advanced/API.md#rest-api-keys" target="_blank" rel="noreferrer">API reference</a>
      </p>
    </div>
  </details>;
}
