import { UpdateNotice } from "./components/UpdateNotice";
import { StorageStatus } from "./components/StorageStatus";
import { MonitoringProvider } from './hooks/MonitoringContext';
import { useConfirmChanges } from "./components/ConfirmChanges";
import { FirstRun } from "./components/FirstRun";
import { ConnectionReminder } from "./components/NetworkAccess";
import { ThemeMenu, useTheme } from "./components/ThemeMenu";
import type { SettingsTarget } from "./settingsNavigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const { ask, confirmation } = useConfirmChanges();
  const theme = useTheme();
  const [showGuide, setShowGuide] = useState(false);
  const [settingsTarget, setSettingsTarget] = useState<SettingsTarget>();
  const [page, setPage] = useState<PageKey>("dashboard");
  const [appTitle, setAppTitle] = useState(DEFAULT_APP_TITLE);
  const [sidebarTitle, setSidebarTitle] = useState(DEFAULT_SIDEBAR_TITLE);
  const [footerText, setFooterText] = useState(DEFAULT_FOOTER_TEXT);
  const [hasAdminAccess, setHasAdminAccess] = useState(false);
  const [auth, setAuth] = useState<AuthMeResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [showLogin, setShowLogin] = useState(false);
  const [authError, setAuthError] = useState("");
  const settingsDirty = useRef(false);
  const settingsSaves = useRef(new Map<Promise<boolean>, (saved: boolean) => void>());
  const setSettingsDirty = useCallback((dirty: boolean) => { settingsDirty.current = dirty; }, []);
  const navigationRequest = useRef(0);
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
      settingsSaves.current.forEach(finish => finish(false));
      settingsSaves.current.clear();
      setPage("dashboard");
    }
  }, [hasAdminAccess, page]);

  const isViewerAllowed = Boolean(auth && (auth.authenticated || !auth.viewer_auth_required));
  const onSettingsSaveStarted = (): ((saved: boolean) => void) => {
    let resolveSave: (saved: boolean) => void = () => undefined;
    const save = new Promise<boolean>(resolve => { resolveSave = resolve; });
    settingsSaves.current.set(save, resolveSave);
    return saved => {
      settingsSaves.current.delete(save);
      resolveSave(saved);
    };
  };
  const canLeaveSettings = async (): Promise<boolean> => {
    while (settingsSaves.current.size) {
      const results = await Promise.all(settingsSaves.current.keys());
      if (results.includes(false)) return false;
    }
    return !settingsDirty.current || ask("Your changes have not been saved. Discard them to leave Settings.");
  };
  const navigate = async (next: PageKey, target?: SettingsTarget): Promise<void> => {
    const request = ++navigationRequest.current;
    if (next === page) {
      if (next === "settings" && target) setSettingsTarget({ ...target });
      return;
    }
    if (!await canLeaveSettings() || request !== navigationRequest.current) return;
    setSettingsDirty(false);
    setSettingsTarget(target);
    setPage(next);
  };

  const onLogout = async (): Promise<void> => {
    const request = ++navigationRequest.current;
    if (!await canLeaveSettings() || request !== navigationRequest.current) return;
    setSettingsDirty(false);
    await api.logout().catch(() => undefined);
    await refreshSession();
  };

  if (authLoading) {
    return <div className="page loading-page">Loading...</div>;
  }

  if (authError || !auth) {
    return <div className="login-page"><section className="login-card">
      <div className="login-title"><h1>FlintEye</h1><ThemeMenu {...theme} /></div>
      <p role="alert">Unable to check your session. {authError}</p>
      <button type="button" onClick={() => void refreshSession()}>Retry connection</button>
    </section></div>;
  }

  if (auth?.setup_required || showLogin || !isViewerAllowed) {
    return <LoginPage appearance={<ThemeMenu {...theme} />} api={api} auth={auth} onLoggedIn={refreshSession} onCancel={isViewerAllowed ? () => setShowLogin(false) : undefined} />;
  }

  return (
    <MonitoringProvider api={api}><div className="app">
      {confirmation}
      <Sidebar active={page} onSelect={navigate} brandTitle={sidebarTitle} canAccessSettings={hasAdminAccess} />
      <main className="content">
        <header className="topbar">
          <div className="topbar-title">{appTitle}</div>
          <div className="session-box">
            {hasAdminAccess && showGuide && <button type="button" className="topbar-guide" onClick={() => document.querySelector(".first-run")?.scrollIntoView({ block: "start" })}>Getting started</button>}
            <ThemeMenu {...theme} />
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

        {hasAdminAccess && page !== "settings" && <ConnectionReminder api={api} onConfigure={() => void navigate("settings", { section: "runtime", anchor: "lan-connection" })} />}
        <StorageStatus />
        {hasAdminAccess && <UpdateNotice />}
        {hasAdminAccess && showGuide && <FirstRun api={api} navigate={navigate} onClose={() => setShowGuide(false)} />}
        {page === "dashboard" && <DashboardPage api={api} canManage={hasAdminAccess} />}
        {page === "information" && <InformationPage api={api} onOpenGuide={hasAdminAccess ? () => setShowGuide(true) : undefined} />}
        {page === "settings" && hasAdminAccess && (
          <SettingsPage api={api} target={settingsTarget} onDirtyChange={setSettingsDirty} onSaveStarted={onSettingsSaveStarted} onUiConfigChanged={() => void refreshSession()} />
        )}
        {page === "live" && (
          <LiveViewPage api={api} canManage={hasAdminAccess} authRole={auth?.role ?? null} onConfigure={() => void navigate("settings", { section: "cameras" })} />
        )}
        {page === "multiview" && <MultiviewPage api={api} onConfigure={hasAdminAccess ? () => void navigate("settings", { section: "multiview" }) : undefined} />}
        {page === "recordings" && <RecordingsPage api={api} canDownload={hasAdminAccess} />}
        <footer className="app-footer">{footerText}</footer>
      </main>
    </div></MonitoringProvider>
  );
}
