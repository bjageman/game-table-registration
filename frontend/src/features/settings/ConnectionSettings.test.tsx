import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ConnectionSettings from "./ConnectionSettings";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const props = { csrf: "csrf", organizationId: "org", onSaved: vi.fn(async () => {}), onAccessError: vi.fn(() => false) };

it("shows Connect and allows saving assignment settings without Discord", async () => {
  const fetchMock = vi.fn(async (path: string) => new Response(JSON.stringify(path === "/api/settings"
    ? { selection: null, disconnected: true, organization_role: "admin", connect_url: "/api/auth/connect" }
    : { automatic_weight_adjustment: true, announce_table_changes: false })));
  vi.stubGlobal("fetch", fetchMock);
  render(<ConnectionSettings {...props} />);
  expect(await screen.findByRole("link", { name: "Connect" })).toHaveAttribute("href", "/api/auth/connect");
  fireEvent.click(screen.getByRole("tab", { name: "General" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save" }));
  await waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => path === "/api/settings/assignment")).toHaveLength(2));
});

it("shows Disconnect beside Save and refreshes the server dropdown", async () => {
  let guilds = [{ id: "100", name: "First" }];
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(
    path === "/api/settings" ? { selection: { guild_id: "100", guild_name: "First", channel_id: "101", channel_name: "games" }, organization_role: "admin", disconnected: false }
      : path === "/api/settings/guilds" ? { guilds }
      : path.startsWith("/api/settings/channels") ? { channels: [{ id: "101", name: "games" }] }
      : { automatic_weight_adjustment: true, announce_table_changes: false }
  ))));
  render(<ConnectionSettings {...props} />);
  const server = await screen.findByRole("combobox", { name: "Discord Server" });
  expect(server).toHaveAttribute("aria-disabled", "true");
  const disconnect = screen.getByRole("button", { name: "Disconnect" });
  expect(disconnect.previousElementSibling).toContainElement(screen.getByRole("button", { name: "Save" }));
  guilds = [...guilds, { id: "200", name: "Second" }];
  fireEvent.click(screen.getByRole("button", { name: "Refresh Servers" }));
  await waitFor(() => expect(server).not.toHaveAttribute("aria-disabled", "true"));
  fireEvent.mouseDown(server);
  fireEvent.click(await screen.findByRole("option", { name: "Second" }));
  expect(server).toHaveTextContent("Second");
});
