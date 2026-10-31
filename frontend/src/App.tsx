import { useCallback, useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import {
  api,
  ApiError,
  errorMessage,
  mutationOptions,
  type ModeratorSession,
} from "./api";
import Dashboard from "./Dashboard";
import ConnectionSettings from "./ConnectionSettings";

type AuthState =
  | { kind: "loading" }
  | { kind: "signed-out"; configured: boolean }
  | { kind: "ready"; session: ModeratorSession }
  | { kind: "error" | "forbidden"; message: string };

export default function App() {
  const [page, setPage] = useState(() => window.location.hash === "#/settings" ? "settings" : "events");
  useEffect(() => {
    const changed = () => setPage(window.location.hash === "#/settings" ? "settings" : "events");
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
    <div className="app-shell">
      <header className="site-header">
        <div>
          <h1><a className="home-link" href="/">TableSignup</a></h1>
        </div>
        {auth.kind === "ready" && (
          <div className="account">
            <button
              className="profile-button"
              aria-haspopup="menu"
              aria-expanded={Boolean(accountAnchor)}
              aria-controls={accountAnchor ? "account-menu" : undefined}
              onClick={(event) => setAccountAnchor(event.currentTarget)}
            >
              <span><strong>{auth.session.username}</strong></span>
              <ChevronDown size={16} aria-hidden="true" />
            </button>
            <Menu
              id="account-menu"
              anchorEl={accountAnchor}
              open={Boolean(accountAnchor)}
              onClose={() => setAccountAnchor(null)}
              anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
              transformOrigin={{ vertical: "top", horizontal: "right" }}
            >
              <MenuItem component="a" href="#/settings" onClick={() => setAccountAnchor(null)}>
                Settings
              </MenuItem>
              <MenuItem
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
      <main>
        {logoutError && (
          <p role="alert" className="error">
            {logoutError}
          </p>
        )}
        {auth.kind === "loading" && (
          <p role="status">Checking your Discord session…</p>
        )}
        {auth.kind === "signed-out" && (
          <section className="panel sign-in" aria-labelledby="sign-in-heading">
            <h2 id="sign-in-heading">Bring Everyone to the Table.</h2>
            <p>Sign in with Discord to manage your community’s game events.</p>
            {auth.configured ? (
              <a className="button primary" href="/api/auth/login">
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
            <button onClick={retry}>Check again</button>
          </section>
        )}
        {auth.kind === "ready" && (
          page === "settings" || auth.session.needs_setup ? (
            <ConnectionSettings csrf={auth.session.csrf} onAccessError={onAccessError}
              onSaved={async () => {
                const session = await api<ModeratorSession>("/me");
                setAuth({ kind: "ready", session });
              }} />
          ) : <Dashboard key={auth.session.destination ?? "legacy"} session={auth.session} onAccessError={onAccessError} />
        )}
      </main>
      <footer>Made for your next game night.</footer>
    </div>
  );
}
