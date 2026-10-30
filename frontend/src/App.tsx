import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  CalendarDays,
  Check,
  Dice5,
  LogOut,
  Plus,
  Trash2,
  Users,
} from "lucide-react";

type Table = { name: string; capacity: number };
type Event = {
  id: string;
  title: string;
  starts_at: number;
  duration_hours: number;
  tables: Table[];
  status: string;
  closes_at: number | null;
  discord_url: string | null;
};
type User = { username: string; csrf: string };
const date = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short",
  });

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((e: { msg: string }) => e.msg).join(". ")
          : "Something went wrong. Please try again.",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [configured, setConfigured] = useState(true);
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [starts, setStarts] = useState("");
  const [duration, setDuration] = useState(72);
  const [tables, setTables] = useState<Table[]>([{ name: "", capacity: 15 }]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const setup = await api<{ configured: boolean }>("/setup");
        if (active) setConfigured(setup.configured);
        const response = await fetch("/api/me");
        if (response.status === 401) return;
        if (!response.ok)
          throw new Error(
            "Could not verify moderator access. Try signing in again.",
          );
        const profile: User = await response.json();
        const list = await api<Event[]>("/events");
        if (active) {
          setUser(profile);
          setEvents(list);
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  async function mutate(path: string, body?: unknown) {
    return api(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": user?.csrf ?? "",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await mutate("/events", {
        title,
        starts_at: new Date(starts).toISOString(),
        duration_hours: duration,
        tables,
      });
      setEvents(await api<Event[]>("/events"));
      setEditing(false);
      setTitle("");
      setStarts("");
      setTables([{ name: "", capacity: 15 }]);
      setNotice("Draft saved. Review it below before publishing to Discord.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function publish(event: Event) {
    if (
      !window.confirm(
        `Publish “${event.title}” to your Discord signup channel now? Signups will stay open for ${event.duration_hours} hours.`,
      )
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await mutate(`/events/${event.id}/publish`);
      setNotice("Your signup poll is live on Discord.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      try {
        setEvents(await api<Event[]>("/events"));
      } catch {
        setError("Could not refresh events. Reload before publishing again.");
      }
      setBusy(false);
    }
  }
  async function logout() {
    setBusy(true);
    try {
      await mutate("/auth/logout");
      setUser(null);
      setEvents([]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen">
      <header className="topbar">
        <a className="brand" href="/">
          <Dice5 size={27} />
          <span>
            gather<span className="brand-dot">.</span>
          </span>
        </a>
        <span className="header-label">GAME NIGHT, SORTED</span>
        {user && (
          <button
            className="quiet"
            onClick={() => void logout()}
            disabled={busy}
          >
            <span>{user.username}</span>
            <LogOut size={17} />
            <span className="sr-only">Sign out</span>
          </button>
        )}
      </header>
      <main>
        <div className="eyebrow">
          <span className="status-dot" /> YOUR NEXT GOOD NIGHT
        </div>
        <div className="page-heading">
          <div>
            <h1>A seat at the table.</h1>
            <p>Bring your people together. Let the games take it from there.</p>
          </div>
          {user && !editing && (
            <button className="primary" onClick={() => setEditing(true)}>
              <Plus size={18} /> New game night
            </button>
          )}
        </div>
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
        {notice && (
          <div role="status" className="notice">
            <Check size={18} />
            {notice}
          </div>
        )}
        {loading ? (
          <section className="panel" aria-live="polite">
            Getting your game nights…
          </section>
        ) : !user ? (
          <section className="welcome panel">
            <div className="icon-box">
              <Dice5 size={38} />
            </div>
            <h2>Good games start here.</h2>
            <p>
              Sign in with Discord to organize your tables and open signups for
              your community.
            </p>
            {configured ? (
              <a className="primary" href="/api/auth/login">
                Continue with Discord <ArrowUpRight size={18} />
              </a>
            ) : (
              <div className="setup-note">
                Your organizer is almost ready. Complete the Discord
                configuration in your server’s .env file, then restart the API.
              </div>
            )}
            <span className="caption">
              For your server’s owner and moderators
            </span>
          </section>
        ) : (
          <>
            <div className="summary">
              <div>
                <CalendarDays size={20} />
                <span>
                  <strong>{events.length}</strong> game nights
                </span>
              </div>
              <div>
                <Users size={20} />
                <span>
                  <strong>
                    {events.filter((e) => e.status === "open").length}
                  </strong>{" "}
                  open for signup
                </span>
              </div>
              <span className="timezone">
                Times shown in{" "}
                {Intl.DateTimeFormat().resolvedOptions().timeZone}
              </span>
            </div>
            {editing && (
              <form className="panel editor" onSubmit={(e) => void save(e)}>
                <div className="section-heading">
                  <h2>Plan a game night</h2>
                  <span className="badge">NEW DRAFT</span>
                </div>
                <p className="muted">
                  Save a draft first. Publishing opens your Discord poll
                  immediately.
                </p>
                <div className="fields">
                  <label>
                    Event name
                    <input
                      required
                      maxLength={100}
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="Friday at the tavern"
                    />
                  </label>
                  <label>
                    Event date & time
                    <input
                      required
                      type="datetime-local"
                      value={starts}
                      onChange={(e) => setStarts(e.target.value)}
                    />
                  </label>
                  <label>
                    Signup window (hours)
                    <input
                      required
                      type="number"
                      min={1}
                      max={768}
                      value={duration}
                      onChange={(e) => setDuration(Number(e.target.value))}
                    />
                  </label>
                </div>
                <div className="section-heading">
                  <h3>The tables</h3>
                  <span className="muted">{tables.length} / 10 tables</span>
                </div>
                <div className="table-fields">
                  {tables.map((table, index) => (
                    <div className="table-row" key={index}>
                      <span className="table-number">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <label>
                        Table name
                        <input
                          required
                          maxLength={35}
                          value={table.name}
                          placeholder="e.g. Blood on the Clocktower"
                          onChange={(e) =>
                            setTables(
                              tables.map((t, i) =>
                                i === index
                                  ? { ...t, name: e.target.value }
                                  : t,
                              ),
                            )
                          }
                        />
                      </label>
                      <label className="capacity">
                        Seats
                        <input
                          required
                          type="number"
                          min={1}
                          max={999}
                          value={table.capacity}
                          onChange={(e) =>
                            setTables(
                              tables.map((t, i) =>
                                i === index
                                  ? { ...t, capacity: Number(e.target.value) }
                                  : t,
                              ),
                            )
                          }
                        />
                      </label>
                      <button
                        type="button"
                        className="quiet remove"
                        aria-label={`Remove table ${index + 1}`}
                        disabled={tables.length === 1}
                        onClick={() =>
                          setTables(tables.filter((_, i) => i !== index))
                        }
                      >
                        <Trash2 size={18} />
                      </button>
                    </div>
                  ))}
                </div>
                <button
                  type="button"
                  className="quiet add"
                  disabled={tables.length >= 10}
                  onClick={() =>
                    setTables([...tables, { name: "", capacity: 15 }])
                  }
                >
                  <Plus size={16} /> Add a table
                </button>
                <div className="form-actions">
                  <button
                    type="button"
                    className="quiet"
                    disabled={busy}
                    onClick={() => setEditing(false)}
                  >
                    Cancel
                  </button>
                  <button className="primary" disabled={busy}>
                    {busy ? "Saving…" : "Save draft"}
                  </button>
                </div>
              </form>
            )}
            <div className="section-heading list-heading">
              <h2>Your game nights</h2>
              <span className="muted">
                {events.length === 0
                  ? "A fresh start"
                  : "Let’s make room for everyone"}
              </span>
            </div>
            {events.length === 0 ? (
              <section className="panel empty">
                <CalendarDays size={32} />
                <h3>Your next game night belongs here.</h3>
                <p>
                  Create an event, add your tables, and invite your community to
                  join.
                </p>
                {!editing && (
                  <button
                    className="quiet add"
                    onClick={() => setEditing(true)}
                  >
                    <Plus size={16} /> Plan your first night
                  </button>
                )}
              </section>
            ) : (
              <div className="event-list">
                {events.map((event) => (
                  <article className="panel event" key={event.id}>
                    <div className="event-header">
                      <div className="event-date">
                        <span>
                          {new Date(event.starts_at * 1000).toLocaleString([], {
                            month: "short",
                          })}
                        </span>
                        <strong>
                          {new Date(event.starts_at * 1000).getDate()}
                        </strong>
                      </div>
                      <div className="event-title">
                        <span
                          className={`badge ${event.status === "open" ? "live" : ""}`}
                        >
                          {event.status.replaceAll("_", " ")}
                        </span>
                        <h3>{event.title}</h3>
                        <p>{date(event.starts_at)}</p>
                      </div>
                    </div>
                    <div className="table-chips">
                      {event.tables.map((t) => (
                        <span key={t.name}>
                          {t.name}
                          <span>
                            <Users size={13} />
                            {t.capacity}
                          </span>
                        </span>
                      ))}
                    </div>
                    <div className="event-footer">
                      <span>
                        {event.closes_at
                          ? `Signups close ${date(event.closes_at)}`
                          : `Signup window · ${event.duration_hours} hours`}
                      </span>
                      {event.status === "draft" && (
                        <button
                          className="primary small"
                          disabled={busy}
                          onClick={() => void publish(event)}
                        >
                          Publish to Discord <ArrowUpRight size={16} />
                        </button>
                      )}
                      {event.discord_url && (
                        <a
                          className="quiet"
                          href={event.discord_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          View poll <ArrowUpRight size={16} />
                        </a>
                      )}
                      {["needs_review", "publishing"].includes(
                        event.status,
                      ) && (
                        <span className="review-note">
                          Check Discord before attempting another post.
                        </span>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
            <p className="milestone-note">
              Early preview · Poll publishing is ready. Automatic allocation and
              recurring schedules are coming next.
            </p>
          </>
        )}
        <footer>
          <span>GATHER · MADE FOR PLAYING TOGETHER</span>
          <span>More games. Less organizing.</span>
        </footer>
      </main>
    </div>
  );
}
