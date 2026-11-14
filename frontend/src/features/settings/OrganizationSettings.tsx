import useDialog from "../../hooks/useDialog";
import ModalHeader from "../../components/ModalHeader";
import { useEffect, useState, type FormEvent } from "react";
import { Trash2, X } from "lucide-react";
import { api, errorMessage, mutationOptions } from "../../lib/api";
import LoadingIndicator from "../../components/LoadingIndicator";
import { isBackdropClick } from "../../lib/dialogBackdrop";
import ConfirmationDialog from "../../components/ConfirmationDialog";
import EditOrganization from "./EditOrganization";

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
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [createError, setCreateError] = useState("");
  const createDialog = useDialog(creating);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<User[]>([]);
  const [newUser, setNewUser] = useState<User>();
  const [addingUser, setAddingUser] = useState(false);
  const [addUserError, setAddUserError] = useState("");
  const [removingMember, setRemovingMember] = useState<Member>();
  const [removeError, setRemoveError] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const addUserDialog = useDialog(addingUser);
  const [role, setRole] = useState<Organization["role"]>("user");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const selected = organizations.find((org) => org.id === selectedId);


  function closeCreate() {
    if (busy) return;
    setCreating(false); setName(""); setCreateError("");
  }


  function closeAddUser() {
    if (busy) return;
    setAddingUser(false); setQuery(""); setResults([]); setNewUser(undefined); setAddUserError("");
  }

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
    event.preventDefault(); setBusy(true); setCreateError("");
    try {
      const created = await api<Organization>("/organizations", mutationOptions(csrf, { name: name.trim() }));
      setName(""); setCreating(false); await changeSelection(created.id); setRevision((value) => value + 1);
    } catch (failure) { if (!onAccessError(failure)) setCreateError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function addUser(event: FormEvent) {
    event.preventDefault(); if (!newUser || !selected) return;
    setBusy(true); setAddUserError("");
    try {
      await api(`/organizations/${selected.id}/members/${newUser.id}`, { ...mutationOptions(csrf, { user_id: newUser.id, role }), method: "PUT" });
      setAddingUser(false); setNewUser(undefined); setQuery(""); setResults([]); setRole("user"); setRevision((value) => value + 1);
    } catch (failure) { if (!onAccessError(failure)) setAddUserError(errorMessage(failure)); }
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
  async function removeMember() {
    if (!selected || !removingMember) return;
    setBusy(true); setRemoveError("");
    try {
      await api(`/organizations/${selected.id}/members/${removingMember.user_id}`, {
        ...mutationOptions(csrf), method: "DELETE",
      });
      setMembers((current) => current.filter((member) => member.user_id !== removingMember.user_id));
      setRemovingMember(undefined);
    } catch (failure) { if (!onAccessError(failure)) setRemoveError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!selected || busy) return;
    const creator = selected.created_by === userId;
    if (creator && !confirmingDelete) return;
    const path = creator ? `/organizations/${selected.id}` : `/organizations/${selected.id}/members/me`;
    setBusy(true); setError(""); setDeleteError("");
    try {
      await api(path, { ...mutationOptions(csrf), method: "DELETE" });
      setConfirmingDelete(false);
      setSelectedId(""); setRevision((value) => value + 1); await onSaved();
    } catch (failure) {
      if (!onAccessError(failure)) {
        if (creator) setDeleteError(errorMessage(failure));
        else setError(errorMessage(failure));
      }
    }
    finally { setBusy(false); }
  }
  return <div id="organization-settings" className="organization-settings">
    {loading && <LoadingIndicator label="Loading organizations…" />}
    {error && <p role="alert" className="error">{error}</p>}
    <select id="organization-select" aria-label="Organization" value={selectedId} disabled={busy} onChange={(event) => void changeSelection(event.target.value)}>
      <option value="">Personal events</option>
      {organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
    </select>
    <div className="form-actions">
      <button id="organization-create-button" type="button" disabled={busy} onClick={() => { setCreateError(""); setCreating(true); }}>Create</button>
      {selected?.role === "admin" && <button id="organization-edit-button" type="button" disabled={busy} onClick={() => setEditing(true)}>Edit</button>}
      {selected && <button id={selected.created_by === userId ? "organization-delete-button" : "organization-leave-button"} type="button" disabled={busy} onClick={() => {
        if (selected.created_by === userId) { setDeleteError(""); setConfirmingDelete(true); }
        else void remove();
      }}>{selected.created_by === userId ? "Delete" : "Leave organization"}</button>}
    </div>
    {creating && <dialog id="organization-create-dialog" ref={createDialog} aria-labelledby="organization-create-heading"
      onCancel={(event) => { event.preventDefault(); closeCreate(); }}
      onClick={(event) => { if (isBackdropClick(event)) closeCreate(); }}>
      <ModalHeader>
        <h2 id="organization-create-heading">Create an organization</h2>
        <button type="button" aria-label="Close create organization" title="Close" disabled={busy} onClick={closeCreate}><X size={18} aria-hidden="true" /></button>
      </ModalHeader>
      <form id="organization-create-form" className="create-organization-form" onSubmit={(event) => void create(event)}>
        <label htmlFor="organization-name">Organization name</label>
        <input id="organization-name" autoFocus required maxLength={100} placeholder="Enter a unique name for your org"
          value={name} disabled={busy} onChange={(event) => setName(event.target.value)} />
        {createError && <p role="alert" className="error">{createError}</p>}
        <div className="form-actions"><button type="submit" className="primary" disabled={busy || !name.trim()}>{busy ? "Creating…" : "Create"}</button></div>
      </form>
    </dialog>}
    {selected && <>
      {editing && selected.role === "admin" && <EditOrganization organization={selected} csrf={csrf} onAccessError={onAccessError}
        onClose={() => setEditing(false)} onSaved={async (name) => {
          setOrganizations((current) => current.map((org) => org.id === selected.id ? { ...org, name } : org));
          await onSaved();
        }} />}
      <h3>{selected.name}</h3>
      <div className="organization-member-table-wrap"><table className="organization-member-table">
        <thead><tr><th scope="col">Username</th><th scope="col">Permission</th><th scope="col">Delete</th></tr></thead>
        <tbody>{members.map((member) => <tr id={`organization-member-${member.user_id}`} key={member.user_id}>
          <td>{member.username}</td>
          <td><select id={`organization-member-role-${member.user_id}`} aria-label={`Permission for ${member.username}`} value={member.role}
            disabled={busy || selected.role !== "admin" || member.user_id === selected.created_by}
            onChange={(event) => void changeRole(member, event.target.value as Organization["role"])}>
            <option value="user">User</option><option value="editor">Editor</option><option value="admin">Admin</option>
          </select></td>
          <td><button id={`organization-member-delete-${member.user_id}`} type="button" aria-label={`Delete ${member.username}`} title={`Delete ${member.username}`} disabled={busy || selected.role !== "admin" || member.user_id === selected.created_by || member.user_id === userId}
            onClick={() => { setRemoveError(""); setRemovingMember(member); }}><Trash2 size={18} aria-hidden="true" /></button></td>
        </tr>)}</tbody>
      </table></div>
      {removingMember && <ConfirmationDialog id={`organization-member-remove-dialog-${removingMember.user_id}`} title={`Remove ${removingMember.username}?`} busy={busy} error={removeError}
        onCancel={() => { setRemovingMember(undefined); setRemoveError(""); }} onConfirm={() => void removeMember()}>
        <p>Are you sure you want to remove {removingMember.username} from {selected.name}?</p>
      </ConfirmationDialog>}
      {selected.role === "admin" && <button id="organization-add-user-button" type="button" disabled={busy} onClick={() => { setAddUserError(""); setAddingUser(true); }}>Add User</button>}
      {selected.role === "admin" && addingUser && <dialog id="organization-add-user-dialog" ref={addUserDialog} aria-labelledby="organization-add-user-heading"
        onCancel={(event) => { event.preventDefault(); closeAddUser(); }}
        onClick={(event) => { if (isBackdropClick(event)) closeAddUser(); }}>
        <ModalHeader>
          <h2 id="organization-add-user-heading">Add User</h2>
          <button type="button" aria-label="Close add user" title="Close" disabled={busy} onClick={closeAddUser}><X size={18} aria-hidden="true" /></button>
        </ModalHeader>
        <form id="organization-add-user-form" className="create-organization-form" onSubmit={(event) => void addUser(event)}>
        <label htmlFor="organization-user-search">Search users</label>
        <input id="organization-user-search" type="search" value={query} placeholder="Search known users" onChange={(event) => { setQuery(event.target.value); setNewUser(undefined); }} />
        {query.trim().length >= 2 && !newUser && <ul className="add-player-results" role="listbox" aria-label="Suggested users">
          {results.map((user) => <li key={user.id} role="option" aria-selected="false"><button id={`organization-user-select-${user.id}`} type="button" onClick={() => { setNewUser(user); setQuery(user.username); }}>{user.username} ({user.id})</button></li>)}
        </ul>}
        {newUser && <p>Selected: {newUser.username}</p>}
        <label htmlFor="organization-role">Permission</label>
        <select id="organization-role" value={role} onChange={(event) => setRole(event.target.value as Organization["role"])}>
          <option value="user">User (read only)</option><option value="editor">Editor (full edit)</option><option value="admin">Admin (edit and add users)</option>
        </select>
        {addUserError && <p role="alert" className="error">{addUserError}</p>}
        <div className="form-actions"><button type="submit" className="primary" disabled={busy || !newUser}>{busy ? "Adding…" : "Add User"}</button></div>
        </form>
      </dialog>}
      {confirmingDelete && <ConfirmationDialog id="organization-delete-dialog" title="Delete organization?" busy={busy} error={deleteError}
        onCancel={() => { setConfirmingDelete(false); setDeleteError(""); }} onConfirm={() => void remove()}>
        <p>Are you sure you want to delete {selected.name}? This cannot be undone.</p>
      </ConfirmationDialog>}
    </>}
  </div>;
}
