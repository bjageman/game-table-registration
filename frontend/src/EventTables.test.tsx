import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import EventTables from "./EventTables";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("lists players under their own tables", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([
    { name: "Table 1", players: [{ id: "mary", name: "Mary" }, { id: "dan", name: "Dan" }] },
    { name: "Table 2", players: [{ id: "carl", name: "Carl" }] },
  ]))));
  render(<EventTables event={{ id: "event", title: "Games", starts_at: 2000000000,
    duration_hours: 24, status: "open", closes_at: null, discord_url: "https://discord.com/poll",
    tables: [{ name: "Table 1", capacity: 12 }, { name: "Table 2", capacity: 8 }],
  }} onAccessError={() => false} />);
  await screen.findByText("Mary");
  const first = screen.getByRole("heading", { name: "Table 1 – 12 seats" }).parentElement!;
  const second = screen.getByRole("heading", { name: "Table 2 – 8 seats" }).parentElement!;
  expect(within(first).getByText("Dan")).toBeVisible();
  expect(within(first).queryByText("Carl")).toBeNull();
  expect(within(second).getByText("Carl")).toBeVisible();
});
