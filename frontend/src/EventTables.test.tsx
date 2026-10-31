import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import EventTables from "./EventTables";
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
