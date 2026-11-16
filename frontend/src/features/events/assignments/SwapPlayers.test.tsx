import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import EventTables from "./EventTables";
import type { EventRecord } from "../../../lib/api";

const event: EventRecord = {
  id: "event", title: "Games", starts_at: 2000000000, duration_hours: 24,
  status: "assigned", closes_at: null, discord_url: null,
  tables: [{ name: "A", capacity: 1 }, { name: "B", capacity: 1 }],
};
const rows = [
  { name: "A", players: [{ id: "1", name: "Alice" }], waitlist: [{ id: "2", name: "Bob" }] },
  { name: "B", players: [{ id: "3", name: "Carol" }], waitlist: [{ id: "4", name: "dan", display_name: "Daniel" }] },
];
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("searches all waitlists and other tables and refreshes after swapping", async () => {
  let swapped = false;
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/swap-players")) { swapped = true; return new Response("{}"); }
    return new Response(JSON.stringify(swapped ? [
      { ...rows[0], players: [rows[1].waitlist[0]] },
      { ...rows[1], waitlist: [rows[0].players[0]] },
    ] : rows));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<EventTables event={event} csrf="csrf" onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Swap Alice at A" }));
  const dialog = within(screen.getByRole("dialog", { name: "Swap Alice" }));
  expect(dialog.getByRole("button", { name: /Bob/ })).toBeVisible();
  expect(dialog.getByRole("button", { name: /Carol/ })).toBeVisible();
  fireEvent.change(dialog.getByRole("searchbox"), { target: { value: "dan" } });
  expect(dialog.queryByRole("button", { name: /Carol/ })).not.toBeInTheDocument();
  fireEvent.click(dialog.getByRole("button", { name: /Daniel.*Waitlist/ }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/events/event/swap-players", expect.objectContaining({
    method: "POST", body: JSON.stringify({ player_id: "1", table: "A", waitlist: false, other_player_id: "4", other_table: "B", other_waitlist: true }),
  })));
  expect(await screen.findByRole("button", { name: "Swap Daniel at A" })).toBeVisible();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps failed swaps open with an error and allows cancelling", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/swap-players")
    ? new Response(JSON.stringify({ detail: "Placements changed" }), { status: 409 })
    : new Response(JSON.stringify(rows))));
  render(<EventTables event={event} csrf="csrf" onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Swap Bob on A waitlist" }));
  const dialog = screen.getByRole("dialog", { name: "Swap Bob" });
  fireEvent.click(within(dialog).getByRole("button", { name: /Carol/ }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("Placements changed");
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it.each(["draft", "scheduled", "open", "review", "assigned"])("only offers the new controls after closing: %s", async (status) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(rows))));
  render(<EventTables event={{ ...event, status }} csrf="csrf" onAccessError={() => false} />);
  await screen.findByRole("button", { name: "Alice" });
  expect(Boolean(screen.queryByRole("checkbox", { name: "Auto-promote waitlisted players" }))).toBe(["review", "assigned"].includes(status));
  expect(Boolean(screen.queryByRole("button", { name: "Swap Alice at A" }))).toBe(["review", "assigned"].includes(status));
});

it("disables auto-promotion and updates the removal confirmation", async () => {
  const fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith("/waitlist-settings") ? { auto_promote_waitlist: false } : rows)));
  vi.stubGlobal("fetch", fetchMock);
  render(<EventTables event={event} csrf="csrf" onAccessError={() => false} />);
  await screen.findByRole("button", { name: "Alice" });
  fireEvent.click(screen.getByRole("checkbox", { name: "Auto-promote waitlisted players" }));
  await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeChecked());
  expect(fetchMock).toHaveBeenCalledWith("/api/events/event/waitlist-settings", expect.objectContaining({ method: "PUT", body: JSON.stringify({ auto_promote_waitlist: false }) }));
  fireEvent.click(screen.getByRole("button", { name: "Remove Alice from table" }));
  expect(screen.getByRole("dialog", { name: "Remove player from table?" })).toHaveTextContent("No waitlisted player will be added automatically.");
});

it.each([true, false])("hides mutation controls when read-only or archived: %s", async (readOnly) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(rows))));
  render(<EventTables event={{ ...event, archived_at: readOnly ? null : 1 }} csrf="csrf" readOnly={readOnly} onAccessError={() => false} />);
  await screen.findByText("Alice");
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Swap/ })).not.toBeInTheDocument();
});

it.each([false, true])("offers same-table seat and waitlist swaps in both directions: %s", async (fromWaitlist) => {
  const fetchMock = vi.fn(async (url: string) => new Response(url.endsWith("/swap-players") ? "{}" : JSON.stringify(rows)));
  vi.stubGlobal("fetch", fetchMock);
  render(<EventTables event={event} csrf="csrf" onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: fromWaitlist ? "Swap Bob on A waitlist" : "Swap Alice at A" }));
  const dialog = within(screen.getByRole("dialog", { name: fromWaitlist ? "Swap Bob" : "Swap Alice" }));
  fireEvent.click(dialog.getByRole("button", { name: fromWaitlist ? /Alice.*Seated/ : /Bob.*Waitlist/ }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/events/event/swap-players", expect.objectContaining({
    body: JSON.stringify({ player_id: fromWaitlist ? "2" : "1", table: "A", waitlist: fromWaitlist, other_player_id: fromWaitlist ? "1" : "2", other_table: "A", other_waitlist: !fromWaitlist }),
  })));
});
