import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import OrganizationSettings from "./OrganizationSettings";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("requires confirmation to delete the organization and allows cancellation and retry", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  let deleted = false;
  let attempts = 0;
  const onSaved = vi.fn(async () => {});
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/organizations") return new Response(JSON.stringify({
      selected_id: deleted ? null : "org",
      organizations: deleted ? [] : [{ id: "org", name: "Friday Crew", created_by: "owner", role: "admin" }],
    }));
    if (url === "/api/organizations/org/members") return new Response("[]");
    if (url === "/api/organizations/org" && options?.method === "DELETE") {
      attempts++;
      if (attempts === 1) return new Response(JSON.stringify({ detail: "Please try again" }), { status: 503 });
      deleted = true;
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<OrganizationSettings csrf="csrf" userId="owner" onSaved={onSaved} onAccessError={() => false} />);
  const deleteButton = await screen.findByRole("button", { name: "Delete" });
  fireEvent.click(deleteButton);
  let dialog = screen.getByRole("dialog", { name: "Delete organization?" });
  expect(dialog).toHaveTextContent("Are you sure you want to delete Friday Crew?");
  expect(attempts).toBe(0);
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(dialog).not.toBeInTheDocument();
  expect(attempts).toBe(0);
  fireEvent.click(deleteButton);
  dialog = screen.getByRole("dialog", { name: "Delete organization?" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("Please try again");
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(dialog).not.toBeInTheDocument());
  expect(onSaved).toHaveBeenCalledOnce();
  expect(fetchMock).toHaveBeenCalledWith("/api/organizations/org", expect.objectContaining({
    method: "DELETE", headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
});

it("opens the create form in a dialog and selects the new organization", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/organizations") return new Response(JSON.stringify({ organizations: [], selected_id: null }));
    if (url === "/api/organizations/selection") return new Response("{}");
    if (url === "/api/organizations/new/members") return new Response("[]");
    return new Response(JSON.stringify({ id: "new", name: "New Org", created_by: "owner", role: "admin" }));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<OrganizationSettings csrf="csrf" userId="owner" onSaved={async () => {}} onAccessError={() => false} />);
  fireEvent.click(screen.getByRole("button", { name: "Create" }));
  const dialog = screen.getByRole("dialog", { name: "Create an organization" });
  const name = screen.getByPlaceholderText("Enter a unique name for your org");
  fireEvent.change(name, { target: { value: "New Org" } });
  fireEvent.click(dialog.querySelector('button[type="submit"]')!);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/organizations", expect.objectContaining({ body: JSON.stringify({ name: "New Org" }) }),
  ));
  await waitFor(() => expect(dialog).not.toBeInTheDocument());
});

it("shows organization members and allows an admin to add a known user", async () => {
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/organizations") return new Response(JSON.stringify({
      selected_id: "org", organizations: [{ id: "org", name: "Friday Crew", created_by: "owner", role: "admin" }],
    }));
    if (url === "/api/organizations/org/members") return new Response(JSON.stringify([
      { user_id: "owner", username: "Organizer", role: "admin" },
    ]));
    if (url.includes("/organizations/users")) return new Response(JSON.stringify([{ id: "123", username: "Mary" }]));
    if (url === "/api/organizations/org/members/123" && options?.method === "PUT") return new Response("{}");
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  render(<OrganizationSettings csrf="csrf" userId="owner" onSaved={async () => {}} onAccessError={() => false} />);
  expect(await screen.findByRole("cell", { name: "Organizer" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Delete Organizer" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Add User" }));
  const dialog = screen.getByRole("dialog", { name: "Add User" });
  fireEvent.change(screen.getByRole("searchbox", { name: "Search users" }), { target: { value: "Ma" } });
  fireEvent.click(await screen.findByRole("button", { name: "Mary (123)" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Permission" }), { target: { value: "editor" } });
  fireEvent.click(dialog.querySelector('button[type="submit"]')!);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/organizations/org/members/123", expect.objectContaining({ method: "PUT", body: JSON.stringify({ user_id: "123", role: "editor" }) }),
  ));
});

it("confirms before deleting an organization member", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/organizations") return new Response(JSON.stringify({
      selected_id: "org", organizations: [{ id: "org", name: "Friday Crew", created_by: "owner", role: "admin" }],
    }));
    if (url === "/api/organizations/org/members" && !options?.method) return new Response(JSON.stringify([
      { user_id: "owner", username: "Organizer", role: "admin" },
      { user_id: "123", username: "Mary", role: "editor" },
    ]));
    return new Response(null, { status: 204 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<OrganizationSettings csrf="csrf" userId="owner" onSaved={async () => {}} onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Delete Mary" }));
  const dialog = screen.getByRole("dialog", { name: "Remove Mary?" });
  expect(dialog).toHaveTextContent("Are you sure");
  expect(fetchMock).not.toHaveBeenCalledWith("/api/organizations/org/members/123", expect.anything());
  fireEvent.click(dialog.querySelector('button.primary')!);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/organizations/org/members/123", expect.objectContaining({ method: "DELETE" }),
  ));
  await waitFor(() => expect(screen.queryByRole("cell", { name: "Mary" })).not.toBeInTheDocument());
});

it("opens the organization name in an edit modal and saves it", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const onSaved = vi.fn(async () => {});
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/organizations/org" && options?.method === "PUT")
      return new Response(JSON.stringify({ name: "New Crew" }));
    if (url.endsWith("/members")) return new Response("[]");
    return new Response(JSON.stringify({ selected_id: "org", organizations: [
      { id: "org", name: "Friday Crew", created_by: "owner", role: "admin" },
    ] }));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<OrganizationSettings csrf="csrf" userId="owner" onSaved={onSaved} onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit", exact: true }));
  const dialog = screen.getByRole("dialog", { name: "Edit organization" });
  const name = within(dialog).getByRole("textbox", { name: "Organization name" });
  expect(name).toHaveValue("Friday Crew");
  fireEvent.change(name, { target: { value: "New Crew" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save", exact: true }));
  await waitFor(() => expect(dialog).not.toBeInTheDocument());
  expect(screen.getByRole("heading", { name: "New Crew" })).toBeVisible();
  expect(onSaved).toHaveBeenCalledOnce();
  expect(fetchMock).toHaveBeenCalledWith("/api/organizations/org", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ name: "New Crew" }),
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
});
