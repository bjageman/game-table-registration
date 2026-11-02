import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import EventTables, { TableColumns } from "./EventTables";
import type { EventRecord } from "./api";

const event: EventRecord = {
  id: "event", title: "Games", starts_at: 2000000000, duration_hours: 24,
  status: "open", closes_at: null, discord_url: "https://discord.com/poll",
  tables: [{ name: "Table A", capacity: 8 }, { name: "Table B", capacity: 12 }],
};
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("refreshes names and counts when votes are added and removed, and stops on close", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify([
      { name: "Table A", players: [] }, { name: "Table B", players: [] },
    ])))
    .mockResolvedValueOnce(new Response(JSON.stringify([
      { name: "Table A", players: [{ id: "1", name: "Mary" }] },
      { name: "Table B", players: [{ id: "2", name: "Dan" }] },
    ])))
    .mockResolvedValueOnce(new Response(JSON.stringify([
      { name: "Table A", players: [] },
      { name: "Table B", players: [{ id: "2", name: "Dan" }] },
    ])))
    .mockRejectedValueOnce(new Error("Discord unavailable"));
  vi.stubGlobal("fetch", fetchMock);
  const view = render(<EventTables csrf="csrf" event={event} onAccessError={() => false} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(screen.getByText("0/8")).toBeVisible();
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(screen.getByText("Mary")).toBeVisible();
  expect(screen.getByRole("button", { name: "Mary" })).toHaveAttribute("aria-haspopup", "dialog");
  expect(screen.getByText("1/8")).toBeVisible();
  expect(screen.getByText("Dan")).toBeVisible();
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(screen.queryByText("Mary")).not.toBeInTheDocument();
  expect(screen.getByText("0/8")).toBeVisible();
  expect(screen.getByText("Dan")).toBeVisible();
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(screen.getByRole("alert")).toHaveTextContent("Showing the last loaded list");
  expect(screen.getByText("Dan")).toBeVisible();
  expect(screen.getByText("0/8")).toBeVisible();
  view.unmount();
  await vi.advanceTimersByTimeAsync(30000);
  expect(fetchMock).toHaveBeenCalledTimes(4);
});

it("prefers display names for assigned and waiting players, with Discord name fallback", () => {
  render(<TableColumns event={{ ...event, status: "assigned" }} onSelect={() => {}} rows={[
    { name: "Table A", players: [{ id: "1", name: "DiscordMary", display_name: "Mary Display" }, { id: "2", name: "Dan" }], waitlist: [{ id: "3", name: "DiscordCarl", display_name: "Carl Display" }] },
    { name: "Table B", players: [] },
  ]} />);
  expect(screen.getByRole("button", { name: "Mary Display" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Dan" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Carl Display" })).toBeVisible();
  expect(screen.queryByText("DiscordMary")).not.toBeInTheDocument();
  expect(screen.queryByText("Wt")).not.toBeInTheDocument();
});

it("labels the guarantee, player, and weight columns for every open table", () => {
  render(<TableColumns event={event} rows={[
    { name: "Table A", players: [{ id: "1", name: "Mary" }] },
    { name: "Table B", players: [] },
  ]} />);
  expect(screen.getAllByText("⭐")).toHaveLength(2);
  expect(screen.getAllByText("Player")).toHaveLength(2);
  expect(screen.getAllByText("Wt")).toHaveLength(2);
});

it("shows saved placements after the Discord signup message is deleted", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify([
    { name: "Table A", players: [{ id: "1", name: "Mary" }], waitlist: [] },
    { name: "Table B", players: [] },
  ])));
  vi.stubGlobal("fetch", fetchMock);
  render(<EventTables csrf="csrf" event={{ ...event, status: "assigned", discord_url: null, signup_deleted_at: 1 }} onAccessError={() => false} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Mary" })).toBeVisible());
  expect(screen.getByText("1/8")).toBeVisible();
  expect(fetchMock).toHaveBeenCalledWith("/api/events/event/signups", expect.anything());
});

it("edits a weight for the event and selects one guaranteed table", async () => {
  const rows = [
    { name: "Table A", players: [{ id: "1", name: "Mary", weighting: 1, guaranteed_table: null }] },
    { name: "Table B", players: [{ id: "1", name: "Mary", weighting: 1, guaranteed_table: null }] },
  ];
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(rows)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ weighting: 1, guaranteed_table: "Table A", guaranteed_seat: false })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ weighting: 2.5, guaranteed_table: "Table A", guaranteed_seat: false })));
  vi.stubGlobal("fetch", fetchMock);
  render(<EventTables csrf="csrf" event={event} onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Guarantee Mary at Table A" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Remove Mary at Table A" })).toBeVisible());
  expect(screen.getByRole("button", { name: "Guarantee Mary at Table B" })).toBeVisible();
  fireEvent.click(screen.getAllByRole("button", { name: "Edit weight for Mary: 1.0" })[0]);
  fireEvent.change(screen.getByRole("spinbutton", { name: "Weight for Mary" }), { target: { value: "2.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getAllByRole("button", { name: "Edit weight for Mary: 2.5" })).toHaveLength(2));
  expect(fetchMock.mock.calls[1][0]).toContain("/events/event/players/1/settings");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ guaranteed_table: "Table A" });
  expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ weighting: 2.5 });
});
