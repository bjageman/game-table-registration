import { useEffect, useState, type FormEvent } from "react";
import { api, errorMessage, mutationOptions } from "./api";
import LoadingIndicator from "./LoadingIndicator";

interface Organization { id: string; name: string; created_by: string; role: "user" | "editor" | "admin" }
interface Member { user_id: string; username: string; role: Organization["role"] }
interface User { id: string; username: string }

export default function OrganizationSettings({ csrf, userId, onSaved, onAccessError }: {
  csrf: string; userId: string; onSaved: () => Promise<void>; onAccessError: (error: unknown) => boolean;
}) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [members, setMembers] = useState<Member[]>([]);
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<User[]>([]);
  const [newUser, setNewUser] = useState<User>();
  const [role, setRole] = useState<Organization["role"]>("user");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const selected = organizations.find((org) => org.id === selectedId);

  useEffect(() => {
    const controller = new AbortController();
    api<{ organizations: Organization[]; selected_id: string | null }>("/organizations", { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) { setOrganizations(data.organizations); setSelectedId(data.selected_id ?? ""); setError(""); } })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision, onAccessError]);
  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    api<Member[]>(`/organizations/${encodeURIComponent(selectedId)}/members`, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setMembers(data); })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [selectedId, revision, onAccessError]);
  useEffect(() => {
    if (query.trim().length < 2 || selected?.role !== "admin") return;
    const controller = new AbortController();
    api<User[]>(`/organizations/users?q=${encodeURIComponent(query)}`, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setResults(data.filter((user) => !members.some((member) => member.user_id === user.id))); })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [query, selected?.role, members, onAccessError]);

  async function changeSelection(id: string) {
    setBusy(true); setError("");
    try {
      await api("/organizations/selection", { ...mutationOptions(csrf, { organization_id: id || null }), method: "PUT" });
      setSelectedId(id); setMembers([]); setQuery(""); setResults([]); setNewUser(undefined);
      await onSaved();
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const created = await api<Organization>("/organizations", mutationOptions(csrf, { name: name.trim() }));
      setName(""); await changeSelection(created.id); setRevision((value) => value + 1);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function addUser(event: FormEvent) {
    event.preventDefault(); if (!newUser || !selected) return;
    setBusy(true); setError("");
    try {
      await api(`/organizations/${selected.id}/members/${newUser.id}`, { ...mutationOptions(csrf, { user_id: newUser.id, role }), method: "PUT" });
      setNewUser(undefined); setQuery(""); setResults([]); setRevision((value) => value + 1);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function changeRole(member: Member, nextRole: Organization["role"]) {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      await api(`/organizations/${selected.id}/members/${member.user_id}`, {
        ...mutationOptions(csrf, { user_id: member.user_id, role: nextRole }), method: "PUT",
      });
      setMembers((current) => current.map((entry) => entry.user_id === member.user_id ? { ...entry, role: nextRole } : entry));
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!selected) return;
    const creator = selected.created_by === userId;
    const path = creator ? `/organizations/${selected.id}` : `/organizations/${selected.id}/members/me`;
    setBusy(true); setError("");
    try {
      await api(path, { ...mutationOptions(csrf), method: "DELETE" });
      setSelectedId(""); setRevision((value) => value + 1); await onSaved();
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  return <div className="organization-settings">
    {loading && <LoadingIndicator label="Loading organizations…" />}
    {error && <p role="alert" className="error">{error}</p>}
    <label htmlFor="organization-select">Organization</label>
    <select id="organization-select" value={selectedId} disabled={busy} onChange={(event) => void changeSelection(event.target.value)}>
      <option value="">Personal events</option>
      {organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
    </select>
    <form onSubmit={(event) => void create(event)}>
      <label htmlFor="organization-name">Create an organization</label>
      <input id="organization-name" required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} />
      <button type="submit" disabled={busy || !name.trim()}>Create</button>
    </form>
    {selected && <>
      <h3>{selected.name}</h3>
      <ul>{members.map((member) => <li key={member.user_id}>{member.username} — {selected.role === "admin" && member.user_id !== selected.created_by ?
        <select aria-label={`Permission for ${member.username}`} value={member.role} disabled={busy}
          onChange={(event) => void changeRole(member, event.target.value as Organization["role"])}>
          <option value="user">User</option><option value="editor">Editor</option><option value="admin">Admin</option>
        </select> : member.role}</li>)}</ul>
      {selected.role === "admin" && <form onSubmit={(event) => void addUser(event)}>
        <label htmlFor="organization-user-search">Add User</label>
        <input id="organization-user-search" type="search" value={query} placeholder="Search known users" onChange={(event) => { setQuery(event.target.value); setNewUser(undefined); }} />
        {query.trim().length >= 2 && !newUser && <ul className="add-player-results" role="listbox" aria-label="Suggested users">
          {results.map((user) => <li key={user.id} role="option" aria-selected="false"><button type="button" onClick={() => { setNewUser(user); setQuery(user.username); }}>{user.username} ({user.id})</button></li>)}
        </ul>}
        {newUser && <p>Selected: {newUser.username}</p>}
        <label htmlFor="organization-role">Permission</label>
        <select id="organization-role" value={role} onChange={(event) => setRole(event.target.value as Organization["role"])}>
          <option value="user">User (read only)</option><option value="editor">Editor (full edit)</option><option value="admin">Admin (edit and add users)</option>
        </select>
        <button type="submit" disabled={busy || !newUser}>Add User</button>
      </form>}
      <button type="button" disabled={busy} onClick={() => void remove()}>{selected.created_by === userId ? "Delete organization" : "Leave organization"}</button>
    </>}
  </div>;
}
