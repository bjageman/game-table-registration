import { useCallback, useEffect, useState } from "react";
import { ChevronDown, GitBranch, Menu as MenuIcon } from "lucide-react";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import {
  api,
  ApiError,
  errorMessage,
  mutationOptions,
  type ModeratorSession,
} from "../lib/api";
import Dashboard from "../features/events/Dashboard";
import ConnectionSettings from "../features/settings/ConnectionSettings";
import LoadingIndicator from "../components/LoadingIndicator";
import PlayerLookup from "../features/players/PlayerLookup";
import { TimezoneContext } from "../lib/timezone";

type AuthState =
  | { kind: "loading" }
  | { kind: "signed-out"; configured: boolean }
  | { kind: "ready"; session: ModeratorSession }
  | { kind: "error" | "forbidden"; message: string };

interface Branding { name: string; tagline: string; logo_url: string | null }
const defaultBranding: Branding = { name: "TableSignup", tagline: "Made for your next game night.", logo_url: null };

export default function App() {
  const [branding, setBranding] = useState<Branding | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api<Branding>("/branding", { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setBranding(result); })
      .catch(() => { if (!controller.signal.aborted) setBranding(defaultBranding); });
    return () => controller.abort();
  }, []);
  useEffect(() => { document.title = branding?.name ?? "Loading…"; }, [branding?.name]);
  const [page, setPage] = useState(() => window.location.hash.slice(2) || "events");
  useEffect(() => {
    const changed = () => setPage(window.location.hash.slice(2) || "events");
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  const [auth, setAuth] = useState<AuthState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [accountAnchor, setAccountAnchor] = useState<HTMLElement | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");

  const onAccessError = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) {
      setAuth({ kind: "signed-out", configured: true });
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    async function load() {
      try {
        const session = await api<ModeratorSession>("/me", options);
        if (!controller.signal.aborted) setAuth({ kind: "ready", session });
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) {
          try {
            const setup = await api<{ configured: boolean }>("/setup", options);
            if (!controller.signal.aborted)
              setAuth({ kind: "signed-out", configured: setup.configured });
          } catch (setupError) {
            if (!controller.signal.aborted)
              setAuth({ kind: "error", message: errorMessage(setupError) });
          }
        } else {
          setAuth({
            kind:
              error instanceof ApiError && error.status === 403
                ? "forbidden"
                : "error",
            message: errorMessage(error),
          });
        }
      }
    }
    void load();
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    if (auth.kind !== "ready") return;
    let checking = false;
    async function refreshSession() {
      if (checking || document.visibilityState === "hidden") return;
      checking = true;
      try {
        const session = await api<ModeratorSession>("/me");
        setAuth({ kind: "ready", session });
      } catch (error) {
        onAccessError(error);
      } finally {
        checking = false;
      }
    }
    window.addEventListener("focus", refreshSession);
    document.addEventListener("visibilitychange", refreshSession);
    return () => {
      window.removeEventListener("focus", refreshSession);
      document.removeEventListener("visibilitychange", refreshSession);
    };
  }, [auth.kind, onAccessError]);

  function retry() {
    setAuth({ kind: "loading" });
    setLogoutError("");
    setAttempt((value) => value + 1);
  }

  async function logout() {
    if (auth.kind !== "ready" || loggingOut) return;
    setLoggingOut(true);
    setLogoutError("");
    try {
      await api<void>("/auth/logout", mutationOptions(auth.session.csrf));
      setAuth({ kind: "signed-out", configured: true });
    } catch (error) {
      if (!onAccessError(error)) setLogoutError(errorMessage(error));
    } finally {
      setLoggingOut(false);
    }
  }

  return (
    <TimezoneContext.Provider value={auth.kind === "ready" ? auth.session.timezone ?? null : null}>
    <div id="app-shell" className="app-shell">
      <header id="site-header" className="site-header">
        <div id="site-branding" className="site-branding">
          {branding && <h1 id="site-title"><a id="home-link" className="home-link" href="/">{branding.logo_url && <img className="brand-logo" src={branding.logo_url} alt="" />}{branding.name}</a></h1>}
        </div>
        {auth.kind === "ready" && (
          <div className="account">
            {auth.session.organization && <span id="active-organization" className="active-organization">{auth.session.organization.name}</span>}
            <button
              id="profile-menu-button"
              className="profile-button"
              aria-label={auth.session.username}
              aria-haspopup="menu"
              aria-expanded={Boolean(accountAnchor)}
              aria-controls={accountAnchor ? "account-menu" : undefined}
              onClick={(event) => setAccountAnchor(event.currentTarget)}
            >
              <MenuIcon className="profile-icon" size={22} aria-hidden="true" />
              <span><strong>{auth.session.username}</strong></span>
              <ChevronDown className="profile-chevron" size={16} aria-hidden="true" />
            </button>
            <Menu
              id="account-menu"
              anchorEl={accountAnchor}
              open={Boolean(accountAnchor)}
              onClose={() => setAccountAnchor(null)}
              anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
              transformOrigin={{ vertical: "top", horizontal: "right" }}
            >
              <MenuItem id="profile-players-link" component="a" href="#/players" onClick={() => setAccountAnchor(null)}>
                Player Lookup
              </MenuItem>
              <MenuItem id="profile-settings-link" component="a" href="#/settings" onClick={() => setAccountAnchor(null)}>
                Settings
              </MenuItem>
              <MenuItem
                id="profile-logout-button"
                disabled={loggingOut}
                onClick={() => {
                  setAccountAnchor(null);
                  void logout();
                }}
              >
                {loggingOut ? "Signing Out…" : "Log Out"}
              </MenuItem>
            </Menu>
          </div>
        )}
      </header>
      <main id="main-content">
        {logoutError && (
          <p role="alert" className="error">
            {logoutError}
          </p>
        )}
        {auth.kind === "loading" && (
          <p><LoadingIndicator label="Checking your Discord session…" /></p>
        )}
        {auth.kind === "signed-out" && (
          <section id="sign-in-panel" className="panel sign-in" aria-labelledby="sign-in-heading">
            <h2 id="sign-in-heading">Discord Login Required</h2>
            {auth.configured ? (
              <a id="discord-login-button" className="button primary" href="/api/auth/login">
                Log in with Discord
              </a>
            ) : (
              <p role="status">
                Discord sign-in is not configured. Contact the organizer.
              </p>
            )}
          </section>
        )}
        {(auth.kind === "error" || auth.kind === "forbidden") && (
          <section className="panel">
            <h2>
              {auth.kind === "forbidden"
                ? "Moderator Access Required"
                : "Unable to Load Your Session"}
            </h2>
            <p role="alert" className="error">
              {auth.message}
            </p>
            {auth.kind === "forbidden" && (
              <p>
                Ask the organizer to check your server membership and moderator
                role.
              </p>
            )}
            <button id="session-retry-button" onClick={retry}>Check again</button>
          </section>
        )}
        {auth.kind === "ready" && (
          page === "settings" || auth.session.needs_setup ? (
            <ConnectionSettings csrf={auth.session.csrf} userId={auth.session.user_id} organizationId={auth.session.organization?.id} onAccessError={onAccessError}
              onSaved={async () => {
                const session = await api<ModeratorSession>("/me");
                setAuth({ kind: "ready", session });
              }} />
          ) : page === "players" ? (
            <PlayerLookup key={`${auth.session.destination ?? "legacy"}:${auth.session.organization?.id ?? "personal"}`} session={auth.session} onAccessError={onAccessError} />
          ) : <Dashboard key={`${auth.session.destination ?? "legacy"}:${auth.session.organization?.id ?? "personal"}`} session={auth.session} onAccessError={onAccessError} />
        )}
      </main>
      <footer id="site-footer">
        <a id="footer-github-link" className="footer-icon-link" href="https://github.com/bjageman/game-table-registration"
          target="_blank" rel="noopener noreferrer" aria-label="GitHub" title="GitHub">
          <GitBranch size={18} aria-hidden="true" />
        </a>
      </footer>
    </div>
    </TimezoneContext.Provider>
  );
}
