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
  expect(weights).toBeDisabled();
  expect(announcements).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Show players in open Discord signups" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Send private messages for waitlist promotions" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "Timezone" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Post Discord updates to a new thread" })).toBeDisabled();
  expect(screen.queryByRole("heading", { name: "Assignments" })).not.toBeInTheDocument();
  expect(weights.closest("label")?.parentElement).not.toBe(announcements.closest("label")?.parentElement);
  const save = screen.getByRole("button", { name: "Save" });
  expect(save).toBeDisabled();
  expect(save.parentElement).toHaveAttribute("title", "Only users with admin privileges can save");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("saves assignment options for an admin", async () => {
  const fetchMock = vi.fn(async (_url: string, options?: RequestInit) => new Response(JSON.stringify(
    options?.method === "PUT"
      ? { automatic_weight_adjustment: true, announce_table_changes: true, post_discord_updates_to_thread: true, timezone: "America/New_York", show_open_signup_players: true, dm_waitlist_promotions: true }
      : { automatic_weight_adjustment: true, announce_table_changes: false },
  )));
  vi.stubGlobal("fetch", fetchMock);
  render(<AssignmentSettings csrf="csrf" onAccessError={() => false} />);
  const announcements = await screen.findByRole("checkbox", { name: "Announce Table Changes on Discord" });
  const privateMessages = screen.getByRole("checkbox", { name: "Send private messages for waitlist promotions" });
  expect(privateMessages).not.toBeChecked();
  fireEvent.click(privateMessages);
  fireEvent.click(announcements);
  fireEvent.click(screen.getByRole("checkbox", { name: "Post Discord updates to a new thread" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Show players in open Discord signups" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Timezone" }), { target: { value: "America/New_York" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/settings/assignment",
    expect.objectContaining({ method: "PUT", body: JSON.stringify({
      automatic_weight_adjustment: true, announce_table_changes: true, post_discord_updates_to_thread: true, timezone: "America/New_York", show_open_signup_players: true, dm_waitlist_promotions: true,
    }) }),
  ));
  expect(screen.getByRole("checkbox", { name: "Post Discord updates to a new thread" })).toBeChecked();
});
