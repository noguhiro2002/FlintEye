import { UpdateNotice } from "./components/UpdateNotice";
import { StorageStatus } from "./components/StorageStatus";
import { FirstRun } from "./components/FirstRun";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiClient } from "./api/client";
import { Sidebar, type PageKey } from "./components/Sidebar";
import { DashboardPage } from "./pages/DashboardPage";
import { InformationPage } from "./pages/InformationPage";
import { LiveViewPage } from "./pages/LiveViewPage";
import { LoginPage } from "./pages/LoginPage";
import { MultiviewPage } from "./pages/MultiviewPage";
import { RecordingsPage } from "./pages/RecordingsPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { AuthMeResponse } from "./types";

const DEFAULT_APP_TITLE = "FlintEye";
const DEFAULT_SIDEBAR_TITLE = "FlintEye";
const DEFAULT_FOOTER_TEXT = "© 2026 Noguhiro. Sustainable Use License + additional permission.";

export default function App(): JSX.Element {
  const [showGuide, setShowGuide] = useState(false);
  const [page, setPage] = useState<PageKey>("dashboard");
  const [appTitle, setAppTitle] = useState(DEFAULT_APP_TITLE);
  const [sidebarTitle, setSidebarTitle] = useState(DEFAULT_SIDEBAR_TITLE);
  const [footerText, setFooterText] = useState(DEFAULT_FOOTER_TEXT);
  const [hasAdminAccess, setHasAdminAccess] = useState(false);
  const [auth, setAuth] = useState<AuthMeResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [showLogin, setShowLogin] = useState(false);
  const [authError, setAuthError] = useState("");
  const [settingsDirty, setSettingsDirty] = useState(false);
  const sessionRequest = useRef(0);

  const api = useMemo(() => new ApiClient(), []);
  useEffect(() => { document.title = appTitle; }, [appTitle]);

  const refreshSession = async (): Promise<void> => {
    const request = ++sessionRequest.current;
    if (!auth) setAuthLoading(true);
    setAuthError("");
    try {
      const authMe = await api.getAuthMe();
      if (request !== sessionRequest.current) return;
      setAuth(authMe);
      setHasAdminAccess(authMe.role === "admin");
      setShowLogin(false);
      // Branding is optional for viewers and must not determine authentication.
      const runtime = await api.getRuntimeConfig().catch(() => null);
      if (request !== sessionRequest.current) return;
      if (!runtime) return;
      setAppTitle(runtime.ui?.app_title || DEFAULT_APP_TITLE);
      setSidebarTitle(runtime.ui?.sidebar_title || DEFAULT_SIDEBAR_TITLE);
      setFooterText(runtime.ui?.footer_text || DEFAULT_FOOTER_TEXT);
      setHasAdminAccess(authMe.role === "admin");
      setShowGuide(authMe.role === "admin" && !runtime.ui?.onboarding_done);
      setShowLogin(false);
    } catch (error) {
      if (request !== sessionRequest.current) return;
      setAuth(null);
      setAuthError(error instanceof Error ? error.message : "Unable to check your session.");
      setHasAdminAccess(false);
    } finally {
      if (request === sessionRequest.current) setAuthLoading(false);
    }
  };

  useEffect(() => {
    void refreshSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!hasAdminAccess && page === "settings") {
      setPage("dashboard");
    }
  }, [hasAdminAccess, page]);

  const isViewerAllowed = Boolean(auth && (auth.authenticated || !auth.viewer_auth_required));
  const canLeaveSettings = (): boolean => !settingsDirty || window.confirm("Discard your unsaved settings and leave this page?");
  const navigate = (next: PageKey): void => {
    if (next === page || !canLeaveSettings()) return;
    setSettingsDirty(false);
    setPage(next);
  };

  const onLogout = async (): Promise<void> => {
    if (!canLeaveSettings()) return;
    setSettingsDirty(false);
    await api.logout().catch(() => undefined);
    await refreshSession();
  };

  if (authLoading) {
    return <div className="page loading-page">Loading...</div>;
  }

  if (authError || !auth) {
    return <div className="page loading-page"><h1>FlintEye</h1>
      <p role="alert">Unable to check your session. {authError}</p>
      <button type="button" onClick={() => void refreshSession()}>Retry connection</button>
    </div>;
  }

  if (auth?.setup_required || showLogin || !isViewerAllowed) {
    return <LoginPage api={api} auth={auth} onLoggedIn={refreshSession} onCancel={isViewerAllowed ? () => setShowLogin(false) : undefined} />;
  }

  return (
    <div className="app">
      <Sidebar active={page} onSelect={navigate} brandTitle={sidebarTitle} canAccessSettings={hasAdminAccess} />
      <main className="content">
        <header className="topbar">
          <div className="topbar-title">{appTitle}</div>
          <div className="session-box">
            {hasAdminAccess && <button type="button" onClick={() => setShowGuide(true)}>Getting started</button>}
            <div className="session-meta">
              <strong>{auth?.authenticated ? auth.username : "Public viewer"}</strong>
              <span>{auth?.role ?? (auth?.viewer_auth_required ? "guest" : "public")}</span>
            </div>
            {auth?.authenticated && (
              <button type="button" onClick={() => void onLogout()}>
                Logout
              </button>
            )}
            {!auth?.authenticated && !auth?.setup_required && (
              <button type="button" onClick={() => setShowLogin(true)}>
                Login
              </button>
            )}
          </div>
        </header>

        <StorageStatus />
        {hasAdminAccess && <UpdateNotice />}
        {hasAdminAccess && showGuide && <FirstRun api={api} navigate={navigate} onClose={() => setShowGuide(false)} />}
        {page === "dashboard" && <DashboardPage api={api} />}
        {page === "information" && <InformationPage api={api} />}
        {page === "settings" && hasAdminAccess && (
          <SettingsPage api={api} onDirtyChange={setSettingsDirty} onUiConfigChanged={() => void refreshSession()} />
        )}
        {page === "live" && (
          <LiveViewPage api={api} canManage={hasAdminAccess} authRole={auth?.role ?? null} onConfigure={() => navigate("settings")} />
        )}
        {page === "multiview" && <MultiviewPage api={api} onConfigure={hasAdminAccess ? () => navigate("settings") : undefined} />}
        {page === "recordings" && <RecordingsPage api={api} canDownload={hasAdminAccess} />}
        <footer className="app-footer">{footerText}</footer>
      </main>
    </div>
  );
}
