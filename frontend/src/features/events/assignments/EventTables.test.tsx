import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import EventTables, { TableColumns } from "./EventTables";
import type { EventRecord } from "../../../lib/api";

const event: EventRecord = {
  id: "event", title: "Games", starts_at: 2000000000, duration_hours: 24,
  status: "open", closes_at: null, discord_url: "https://discord.com/poll",
  tables: [{ name: "Table A", capacity: 8 }, { name: "Table B", capacity: 12 }],
};
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("suggests known players as the manager types and adds the selected player", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  let added = false;
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/players") return new Response(JSON.stringify([
      { discord_id: "123", discord_name: "mary", real_name: "Mary Jones" },
      { discord_id: "456", discord_name: "dan", real_name: "Daniel" },
    ]));
    if (url.includes("/manager-players/123") && options?.method === "PUT") { added = true; return new Response("{}", { status: 200 }); }
    return new Response(JSON.stringify([{ name: "Table A", players: added ? [{ id: "123", name: "mary" }] : [] }, { name: "Table B", players: [] }]));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<EventTables csrf="csrf" event={event} onAccessError={() => false} />);
  fireEvent.click(screen.getAllByRole("button", { name: "Add Player" })[0]);
  const search = screen.getByRole("combobox", { name: "Search players" });
  fireEvent.change(search, { target: { value: "mar" } });
  expect(await screen.findByRole("listbox", { name: "Suggested players" })).toBeVisible();
  expect(screen.getByRole("button", { name: /Mary Jones/ })).toBeVisible();
  expect(screen.queryByRole("button", { name: /Daniel/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Mary Jones/ }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/events/event/manager-players/123", expect.objectContaining({ method: "PUT" }),
  ));
  expect(await screen.findByRole("button", { name: "mary" })).toBeVisible();
});

it("closes the add player dialog with its X and a backdrop click", () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
  render(<EventTables csrf="csrf" event={{ ...event, status: "draft", discord_url: null }} onAccessError={() => false} />);
  const add = screen.getAllByRole("button", { name: "Add Player" })[0];
  fireEvent.click(add);
  fireEvent.click(screen.getByRole("button", { name: "Close add player" }));
  expect(screen.queryByRole("dialog", { name: /Add a player/ })).not.toBeInTheDocument();
  fireEvent.click(add);
  const dialog = screen.getByRole("dialog", { name: /Add a player/ });
  fireEvent.click(dialog, { clientX: -1, clientY: -1 });
  expect(dialog).not.toBeInTheDocument();
});

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

it("refreshes assigned placements while the modal is open", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify([
      { name: "Table A", players: [{ id: "1", name: "Mary" }], waitlist: [] },
      { name: "Table B", players: [], waitlist: [] },
    ])))
    .mockResolvedValueOnce(new Response(JSON.stringify([
      { name: "Table A", players: [{ id: "1", name: "Mary" }, { id: "2", name: "Dan" }], waitlist: [] },
      { name: "Table B", players: [], waitlist: [] },
    ])));
  vi.stubGlobal("fetch", fetchMock);
  const view = render(<EventTables csrf="csrf" event={{ ...event, status: "assigned" }} onAccessError={() => false} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(screen.getByText("1/8")).toBeVisible();
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(screen.getByText("2/8")).toBeVisible();
  expect(screen.getByRole("button", { name: "Dan" })).toBeVisible();
  view.unmount();
  await vi.advanceTimersByTimeAsync(15000);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("prefers display names for assigned and waiting players, with Discord name fallback", () => {
  render(<TableColumns event={{ ...event, status: "assigned" }} onSelect={() => {}} rows={[
    { name: "Table A", players: [{ id: "1", name: "DiscordMary", display_name: "Mary Display" }, { id: "2", name: "A very long assigned player name" }], waitlist: [{ id: "3", name: "DiscordCarl", display_name: "Carl Display" }] },
    { name: "Table B", players: [] },
  ]} />);
  expect(screen.getByRole("button", { name: "Mary Display" })).toBeVisible();
  expect(screen.getByRole("button", { name: "A very long assigned player name" })).toHaveTextContent("A very long assigned player name");
  expect(screen.getByRole("button", { name: "Mary Display" }).closest("li")).toHaveClass("table-assigned-player");
  expect(screen.getByRole("button", { name: "Carl Display" })).toBeVisible();
  expect(screen.queryByText("DiscordMary")).not.toBeInTheDocument();
  expect(screen.queryByText("Wt")).not.toBeInTheDocument();
});

it.each([
  [1, "The next waitlisted player will be added automatically."],
  [2, "No waitlisted player will be added automatically."],
])("explains removal from a table with %i players and one seat", async (count, message) => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([
    { name: "Table A", players: [{ id: "1", name: "Mary" }, ...(count === 2 ? [{ id: "2", name: "Dan" }] : [])], waitlist: [{ id: "3", name: "Carl" }] },
    { name: "Table B", players: [], waitlist: [] },
  ]))));
  render(<EventTables csrf="csrf" event={{ ...event, status: "assigned", tables: [{ name: "Table A", capacity: 1 }, event.tables[1]] }} onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Remove Mary from table" }));
  expect(screen.getByRole("dialog", { name: "Remove player from table?" })).toHaveTextContent(message);
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

it("sorts each table by guarantee, player, or weight and reverses on a second click", () => {
  render(<TableColumns event={event} onSelect={() => {}} rows={[
    { name: "Table A", players: [
      { id: "1", name: "Zoe", weighting: 2 },
      { id: "2", name: "Amy", weighting: 1, guaranteed_table: "Table A" },
      { id: "3", name: "Bill", weighting: 0.5 },
    ] },
    { name: "Table B", players: [
      { id: "4", name: "Yara", weighting: 3 },
      { id: "5", name: "Carl", weighting: 1 },
    ] },
  ]} />);
  const tables = document.querySelectorAll(".event-table");
  const names = (index: number) => Array.from(tables[index].querySelectorAll(".table-player-row .player-name"), (node) => node.textContent);
  expect(names(0)).toEqual(["Zoe", "Amy", "Bill"]);
  fireEvent.click(screen.getByRole("button", { name: "Sort Table A by player" }));
  expect(names(0)).toEqual(["Amy", "Bill", "Zoe"]);
  expect(names(1)).toEqual(["Yara", "Carl"]);
  fireEvent.click(screen.getByRole("button", { name: "Sort Table A by player, ascending" }));
  expect(names(0)).toEqual(["Zoe", "Bill", "Amy"]);
  fireEvent.click(screen.getByRole("button", { name: "Sort Table A by weight" }));
  expect(names(0)).toEqual(["Bill", "Amy", "Zoe"]);
  fireEvent.click(screen.getByRole("button", { name: "Sort Table A by weight, ascending" }));
  expect(names(0)).toEqual(["Zoe", "Amy", "Bill"]);
  fireEvent.click(screen.getByRole("button", { name: "Sort Table A by guarantee" }));
  expect(names(0)).toEqual(["Amy", "Zoe", "Bill"]);
  fireEvent.click(screen.getByRole("button", { name: "Sort Table A by guarantee, ascending" }));
  expect(names(0)).toEqual(["Zoe", "Bill", "Amy"]);
  fireEvent.click(screen.getByRole("button", { name: "Sort Table B by player" }));
  expect(names(1)).toEqual(["Carl", "Yara"]);
  expect(names(0)).toEqual(["Zoe", "Bill", "Amy"]);
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

it("confirms a waitlist addition and shows the count above capacity", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  let added = false;
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/assigned-players/2") && options?.method === "POST") {
      added = true;
      return new Response("{}");
    }
    return new Response(JSON.stringify([
      { name: "Table A", players: [{ id: "1", name: "Mary" }, ...(added ? [{ id: "2", name: "Dan" }] : [])], waitlist: added ? [] : [{ id: "2", name: "Dan" }] },
      { name: "Table B", players: [], waitlist: [] },
    ]));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<EventTables csrf="csrf" event={{ ...event, status: "assigned", tables: [{ name: "Table A", capacity: 1 }, event.tables[1]] }} onAccessError={() => false} />);
  const add = await screen.findByRole("button", { name: "Add Dan to Table A" });
  expect(screen.getByRole("list", { name: "Waitlist for Table A" }).tagName).toBe("UL");
  expect(add.closest("li")?.firstElementChild).toBe(add);
  fireEvent.click(add);
  expect(screen.getByRole("dialog", { name: "Add waitlisted player?" })).toHaveTextContent("Are you sure you want to add this player? It will go beyond the table limit.");
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/events/event/assigned-players/2", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText("2/1")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Add Dan to Table A" })).not.toBeInTheDocument();
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
  const weight = screen.getByRole("textbox", { name: "Weight for Mary" });
  expect(weight).toHaveValue("1");
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  fireEvent.change(weight, { target: { value: "2.5" } });
  fireEvent.blur(weight);
  await waitFor(() => expect(screen.getAllByRole("button", { name: "Edit weight for Mary: 2.5" })).toHaveLength(2));
  expect(fetchMock.mock.calls[1][0]).toContain("/events/event/players/1/settings");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ guaranteed_table: "Table A" });
  expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ weighting: 2.5 });
});

it("closes an inline weight edit without saving on Escape", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify([
    { name: "Table A", players: [{ id: "1", name: "Mary", weighting: 1 }] },
    { name: "Table B", players: [] },
  ])));
  vi.stubGlobal("fetch", fetchMock);
  render(<EventTables csrf="csrf" event={event} onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit weight for Mary: 1.0" }));
  const weight = screen.getByRole("textbox", { name: "Weight for Mary" });
  fireEvent.change(weight, { target: { value: "3" } });
  fireEvent.keyDown(weight, { key: "Escape" });
  expect(screen.queryByRole("textbox", { name: "Weight for Mary" })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it.each([[11, 10], [-1, 0.1]])("clamps event weight %s to %s", async (entered, expected) => {
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "PUT") return new Response(JSON.stringify({ weighting: expected, guaranteed_table: null, guaranteed_seat: false }));
    return new Response(JSON.stringify([{ name: "Table A", players: [{ id: "1", name: "Mary", weighting: 5 }] }]));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<EventTables csrf="csrf" event={event} onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit weight for Mary: 5.0" }));
  const input = screen.getByRole("textbox", { name: "Weight for Mary" });
  fireEvent.change(input, { target: { value: String(entered) } });
  fireEvent.submit(input.closest("form")!);
  await waitFor(() => expect(fetchMock.mock.calls.some(([, options]) => options?.method === "PUT" && JSON.parse(options.body as string).weighting === expected)).toBe(true));
  expect(screen.getByText(entered > 10 ? /maximum weight is 10/ : /minimum weight is 0.1/)).toBeVisible();
});
