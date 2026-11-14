import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import PublicEvent from "./PublicEvent";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows public seats and waitlists without player editing controls", async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify({
    title: "Monday games", description: "Bring a friend", location: "Game Store",
    starts_at: 2000000000, archived: false,
    tables: [{ name: "One", capacity: 1, players: [{ name: "Mary" }], waitlist: [{ name: "Dan" }] }],
  })));
  vi.stubGlobal("fetch", fetch);
  render(<PublicEvent token="shared-token" />);
  expect(await screen.findByRole("heading", { name: "Monday games" })).toBeVisible();
  expect(screen.getByText("Mary")).toBeVisible();
  expect(screen.getByText("Dan")).toBeVisible();
  expect(screen.getByText("1/1")).toBeVisible();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith("/api/public/events/shared-token", expect.objectContaining({ cache: "no-store" }));
});
