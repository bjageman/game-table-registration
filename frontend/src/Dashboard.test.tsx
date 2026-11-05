import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

it("opens event details from a compact event listing", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify([draft]))),
  );
  render(<Dashboard {...props} />);
  const item = await screen.findByRole("button", { name: /^Friday games/ });
  expect(item).toBeVisible();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(item);
  expect(screen.getByRole("dialog", { name: "Friday games" })).toBeVisible();
  expect(screen.getAllByText("draft")).toHaveLength(2);
  expect(screen.getByText("0/15")).toBeVisible();
  expect(screen.getByText(/24 hours from publication/)).toBeVisible();
  expect(screen.getAllByRole("listitem").filter((li) => li.parentElement?.className === "table-players")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Close event" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("offers PDF and CSV downloads for assigned events", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([{ ...draft, status: "assigned" }]))));
  render(<Dashboard {...props} />);
  expect(await screen.findByRole("button", { name: "Download all event signups" })).toBeVisible();
  fireEvent.click(await screen.findByRole("button", { name: /^Friday games/ }));
  fireEvent.click(screen.getByRole("button", { name: "Download event signups" }));
  expect(screen.getByRole("dialog", { name: "Download signups for Friday games" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Download PDF" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Download CSV" })).toBeVisible();
});

it("offers retry after a failed request instead of showing an empty list", async () => {
  const fetchMock = vi
    .fn()
    .mockImplementation((path: string) => path.includes("recurring-series")
      ? Promise.resolve(new Response("[]"))
      : fetchMock.mock.calls.filter(([url]) => String(url).includes("/events")).length === 1
        ? Promise.reject(new Error("offline"))
        : Promise.resolve(new Response("[]")));
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

it("searches titles and sorts by title/date while respecting archived events", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([
    { ...draft, id: "a", title: "Alpha Night", starts_at: 2000000300 },
    { ...draft, id: "z", title: "Zebra Night", starts_at: 2000000100 },
    { ...draft, id: "b", title: "Beta Night", starts_at: 2000000200 },
    { ...draft, id: "archived", title: "Alpha Archived", starts_at: 2000000400, archived_at: 2000000000 },
  ]))));
  render(<Dashboard {...props} />);
  await screen.findByRole("button", { name: /^Alpha Night/ });
  const titles = () => within(screen.getByRole("list")).getAllByRole("button").map((button) => button.querySelector(".event-list-title")?.textContent);
  expect(titles()).toEqual(["Zebra Night", "Beta Night", "Alpha Night"]);
  for (const [label, expected] of [
    ["Title: A–Z", ["Alpha Night", "Beta Night", "Zebra Night"]],
    ["Title: Z–A", ["Zebra Night", "Beta Night", "Alpha Night"]],
    ["Event Date: Latest First", ["Alpha Night", "Beta Night", "Zebra Night"]],
  ] as const) {
    fireEvent.click(screen.getByRole("button", { name: "Sort events" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: label }));
    expect(titles()).toEqual(expected);
  }
  fireEvent.change(screen.getByRole("searchbox", { name: "Search events" }), { target: { value: " ALPHA " } });
  expect(titles()).toEqual(["Alpha Night"]);
  fireEvent.click(screen.getByLabelText("Show Archived"));
  expect(titles()).toEqual(["Alpha Archived", "Alpha Night"]);
  fireEvent.change(screen.getByRole("searchbox", { name: "Search events" }), { target: { value: "Clocktower" } });
  expect(screen.getByText("No Matching Events")).toBeVisible();
});
