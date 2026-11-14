import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import AssignmentSettings from "./AssignmentSettings";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows assignment options on separate rows and restricts organization editors", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({
    automatic_weight_adjustment: true, announce_table_changes: false,
  })));
  vi.stubGlobal("fetch", fetchMock);
  render(<AssignmentSettings csrf="csrf" restricted onAccessError={() => false} />);
  const weights = await screen.findByRole("checkbox", { name: "Automatically Adjust Player Weights" });
  const announcements = screen.getByRole("checkbox", { name: "Announce Table Changes on Discord" });
  expect(screen.getByRole("checkbox", { name: "Review assignments before sending to Discord" })).toBeDisabled();
  expect(weights).toBeDisabled();
  expect(announcements).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Show players in open Discord signups" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Send private messages for waitlist promotions" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "Timezone" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Post Discord updates to a new thread" })).toBeDisabled();
  expect(screen.queryByRole("heading", { name: "Assignments" })).not.toBeInTheDocument();
  expect(weights.closest("label")?.parentElement).not.toBe(announcements.closest("label")?.parentElement);
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("saves assignment options for an admin", async () => {
  const fetchMock = vi.fn(async (_url: string, options?: RequestInit) => new Response(JSON.stringify(
    options?.method === "PUT"
      ? { review_assignments_before_discord: false, automatic_weight_adjustment: true, announce_table_changes: true, post_discord_updates_to_thread: true, timezone: "America/New_York", show_open_signup_players: true, dm_waitlist_promotions: true }
      : { automatic_weight_adjustment: true, announce_table_changes: false, post_discord_updates_to_thread: false, show_open_signup_players: false, dm_waitlist_promotions: false },
  )));
  vi.stubGlobal("fetch", fetchMock);
  render(<AssignmentSettings csrf="csrf" onAccessError={() => false} />);
  const announcements = await screen.findByRole("checkbox", { name: "Announce Table Changes on Discord" });
  const privateMessages = screen.getByRole("checkbox", { name: "Send private messages for waitlist promotions" });
  expect(privateMessages).not.toBeChecked();
  fireEvent.click(screen.getByRole("checkbox", { name: "Review assignments before sending to Discord" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
    method: "PUT",
    body: JSON.stringify({
      review_assignments_before_discord: false, automatic_weight_adjustment: true, announce_table_changes: false,
      post_discord_updates_to_thread: false, timezone: null, show_open_signup_players: false, dm_waitlist_promotions: false,
    }),
  }));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Review assignments before sending to Discord" })).not.toBeChecked());
  fireEvent.click(privateMessages);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({ method: "PUT" }));
  fireEvent.click(announcements);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  fireEvent.click(screen.getByRole("checkbox", { name: "Post Discord updates to a new thread" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
  fireEvent.click(screen.getByRole("checkbox", { name: "Show players in open Discord signups" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
  fireEvent.change(screen.getByRole("combobox", { name: "Timezone" }), { target: { value: "America/New_York" } });
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(7));
  expect(fetchMock.mock.calls[6][1]).toEqual(expect.objectContaining({
    method: "PUT",
    body: expect.stringContaining('"timezone":"America/New_York"'),
  }));
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Post Discord updates to a new thread" })).toBeChecked();
});

it("enables every General toggle by default before the first settings save", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    automatic_weight_adjustment: true, announce_table_changes: true,
  }))));
  render(<AssignmentSettings csrf="csrf" onAccessError={() => false} />);
  await screen.findByRole("checkbox", { name: "Automatically Adjust Player Weights" });
  const toggles = screen.getAllByRole("checkbox");
  expect(toggles).toHaveLength(6);
  toggles.forEach((toggle) => expect(toggle).toBeChecked());
});
