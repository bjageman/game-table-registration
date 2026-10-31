import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";

const props = {
  session: { username: "organizer", csrf: "csrf" },
  onAccessError: vi.fn(() => false),
};
const draft = {
  id: "event",
  title: "Friday games",
  starts_at: 2000000000,
  duration_hours: 24,
  tables: [{ name: "Clocktower", capacity: 15 }],
  status: "draft",
  closes_at: null,
  discord_url: null,
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("loads event dates, tables, and publication status", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify([draft]))),
  );
  render(<Dashboard {...props} />);
  expect(
    await screen.findByRole("heading", { name: "Friday games" }),
  ).toBeVisible();
  expect(screen.getByText("draft")).toBeVisible();
  expect(screen.getByText(/15 seats/)).toBeVisible();
  expect(screen.getByText(/24 hours from publication/)).toBeVisible();
});

it("offers retry after a failed request instead of showing an empty list", async () => {
  const fetchMock = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(new Response("[]"));
  vi.stubGlobal("fetch", fetchMock);
  render(<Dashboard {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/Could not reach/);
  expect(screen.queryByText("No Events Yet")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("No Events Yet")).toBeVisible();
});

it("passes expired-session errors to the auth boundary", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Expired" }), { status: 401 }),
    ),
  );
  render(<Dashboard {...props} />);
  await screen.findByRole("alert");
  expect(props.onAccessError).toHaveBeenCalledWith(
    expect.objectContaining({ status: 401 }),
  );
});
