import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import OrganizationSettings from "./OrganizationSettings";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

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
