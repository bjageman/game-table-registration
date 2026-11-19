import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import PublicEvent from "./PublicEvent";

afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("shows public seats and waitlists without player editing controls", async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify({
    title: "Monday games", description: "Bring a friend", location: "Game Store",
    starts_at: 2000000000, archived: false,
    tables: [{ name: "One", capacity: 1, players: [{ id: "mary", name: "Mary" }], waitlist: [{ id: "dan", name: "Dan" }] }],
  })));
  vi.stubGlobal("fetch", fetch);
  render(<PublicEvent token="shared-token" />);
  expect(await screen.findByRole("heading", { name: "Monday games" })).toBeVisible();
  expect(screen.getByText("Mary")).toBeVisible();
  expect(screen.getByText("Dan")).toBeVisible();
  expect(screen.getByText("1/1")).toBeVisible();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith("/api/public/events/shared-token", expect.objectContaining({ cache: "no-store" }));
});

function mockRoster() {
  const roster = {
    title: "Games", description: "", location: "", starts_at: 2000000000, archived: false,
    tables: [{ name: "One", capacity: 2, players: [{ id: "a", name: "Alex" }, { id: "b", name: "Alex" }], waitlist: [{ id: "c", name: "Chris" }] }],
  };
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(roster))));
  return roster;
}

it("persists independent checkmarks by player and public link", async () => {
  mockRoster();
  const view = render(<PublicEvent token="one" />);
  const checks = await screen.findAllByRole("checkbox", { name: "Mark Alex as arrived" });
  fireEvent.click(checks[0]);
  expect(checks[0]).toBeChecked();
  expect(checks[1]).not.toBeChecked();
  fireEvent.click(checks[0]);
  expect(checks[0]).not.toBeChecked();
  fireEvent.click(checks[0]);
  fireEvent.click(screen.getByRole("checkbox", { name: "Mark Chris as arrived" }));
  view.unmount();
  const restored = render(<PublicEvent token="one" />);
  expect((await screen.findAllByRole("checkbox", { name: "Mark Alex as arrived" }))[0]).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Mark Chris as arrived" })).toBeChecked();
  restored.unmount();
  render(<PublicEvent token="two" />);
  expect((await screen.findAllByRole("checkbox", { name: "Mark Alex as arrived" }))[0]).not.toBeChecked();
});

it("retains entries when polling renames, reorders, or promotes players", async () => {
  const roster = mockRoster();
  render(<PublicEvent token="one" />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Mark Chris as arrived" }));
  roster.tables[0].players = [{ id: "c", name: "New name" }, { id: "b", name: "Alex" }];
  roster.tables[0].waitlist = [];
  fireEvent(document, new Event("visibilitychange"));
  expect(await screen.findByRole("checkbox", { name: "Mark New name as arrived" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Mark Alex as arrived" })).not.toBeChecked();
});

it("handles corrupt storage and reports failed saves while keeping edits usable", async () => {
  mockRoster();
  localStorage.setItem("public-event-checklist:one", '{"a":{"arrived":"wrong","notes":3}}');
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage disabled"); });
  render(<PublicEvent token="one" />);
  const checks = await screen.findAllByRole("checkbox", { name: "Mark Alex as arrived" });
  expect(checks[0]).not.toBeChecked();
  fireEvent.click(checks[0]);
  expect(checks[0]).toBeChecked();
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be saved");
  vi.restoreAllMocks();
  fireEvent.click(checks[0]);
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
});
