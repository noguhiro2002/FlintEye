import { SetupAccount } from "../components/FirstRun";
import { useState } from "react";
import type { ApiClient } from "../api/client";
import type { AuthMeResponse } from "../types";

interface LoginPageProps {
  api: ApiClient;
  auth: AuthMeResponse | null;
  onLoggedIn: () => Promise<void> | void;
  onCancel?: () => void;
}

export function LoginPage({ api, auth, onLoggedIn, onCancel }: LoginPageProps): JSX.Element {
  const [username, setUsername] = useState(auth?.local.admin_username ?? "admin");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.login(username, password);
      setPassword("");
      setError("");
      await onLoggedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const provider = auth?.provider ?? "local";
  const setupRequired = Boolean(auth?.setup_required);

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>FlintEye</h1>
        <p className="login-subtitle">Sign in to manage cameras, multiview, and recordings.</p>
        {provider === "legacy_token" ? (
          <div className="panel-note">
            Legacy token mode: sign in with username <code>admin</code> or <code>viewer</code>, and use the
            corresponding token as the password.
          </div>
        ) : provider !== "local" ? (
          <div className="panel-error">Login UI is not implemented for this auth provider yet.</div>
        ) : setupRequired ? (
          <SetupAccount api={api} onDone={() => void onLoggedIn()} />
        ) : null}
        {(provider === "legacy_token" || (provider === "local" && !setupRequired)) && (
          <form className="login-form" onSubmit={(e) => void onSubmit(e)}>
            {error && <div className="panel-error">{error}</div>}
            <label>
              Username
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
            </label>
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <button type="submit" className="primary" disabled={loading}>
              {loading ? "Signing in..." : "Sign In"}
            </button>
            {onCancel && !setupRequired && (
              <button type="button" onClick={onCancel}>
                Back
              </button>
            )}
            <div className="login-hint">
              Viewer username: <code>{provider === "legacy_token" ? "viewer" : auth?.local.viewer_username ?? "viewer"}</code>
              {" | "}Admin username: <code>{provider === "legacy_token" ? "admin" : auth?.local.admin_username ?? "admin"}</code>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
