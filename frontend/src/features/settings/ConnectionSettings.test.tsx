import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ConnectionSettings from "./ConnectionSettings";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("clears an organization's server after disconnect and offers Connect after reload", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  let disconnected = false;
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/settings" && options?.method === "DELETE") {
      disconnected = true;
      return new Response(null, { status: 204 });
    }
    if (path === "/api/settings") return Response.json({
      organization_role: "admin", disconnected, connect_url: "/api/auth/connect",
      selection: disconnected ? null : { guild_id: "100", guild_name: "Old Server", channel_id: "101", channel_name: "games" },
    });
    if (path === "/api/settings/channels?guild_id=100") return Response.json({ channels: [{ id: "101", name: "games" }] });
    if (path === "/api/settings/assignment") return Response.json({ automatic_weight_adjustment: true, announce_table_changes: false });
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  const onSaved = vi.fn(async () => {});
  const props = { csrf: "csrf", organizationId: "crew", onSaved, onAccessError: () => false };
  const view = render(<ConnectionSettings {...props} />);
  expect(await screen.findByLabelText("Discord Server")).toHaveValue("Old Server");
  fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
  expect(await screen.findByRole("link", { name: "Connect" })).toHaveAttribute("href", "/api/auth/connect");
  expect(screen.queryByLabelText("Discord Server")).not.toBeInTheDocument();
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledWith("/api/settings", expect.objectContaining({
    method: "DELETE", headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
  view.unmount();
  fetchMock.mockClear();
  render(<ConnectionSettings {...props} />);
  expect(await screen.findByRole("link", { name: "Connect" })).toHaveAttribute("href", "/api/auth/connect");
  expect(screen.queryByLabelText("Discord Server")).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.every(([path]) => path === "/api/settings")).toBe(true);
});

it.each(["editor", "user"])("requires an admin to reconnect a disconnected organization for %s", async (role) => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({
    organization_role: role, disconnected: true, selection: null, connect_url: "/api/auth/connect",
  })));
  render(<ConnectionSettings csrf="csrf" organizationId="crew" onSaved={async () => {}} onAccessError={() => false} />);
  expect(await screen.findByText("An organization admin must connect Discord.")).toBeVisible();
  expect(screen.queryByRole("link", { name: "Connect" })).not.toBeInTheDocument();
});
