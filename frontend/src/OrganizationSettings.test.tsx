import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import OrganizationSettings from "./OrganizationSettings";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

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
  render(<OrganizationSettings csrf="csrf" userId="owner" onSaved={async () => {}} onAccessError={() => false} />);
  expect(await screen.findByText("Organizer — admin")).toBeVisible();
  fireEvent.change(screen.getByRole("searchbox", { name: "Add User" }), { target: { value: "Ma" } });
  fireEvent.click(await screen.findByRole("button", { name: "Mary (123)" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Permission" }), { target: { value: "editor" } });
  fireEvent.click(screen.getByRole("button", { name: "Add User" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/organizations/org/members/123", expect.objectContaining({ method: "PUT", body: JSON.stringify({ user_id: "123", role: "editor" }) }),
  ));
});
