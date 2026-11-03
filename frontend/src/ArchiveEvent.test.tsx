import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ArchiveEvent from "./ArchiveEvent";
import type { EventRecord } from "./api";

const event: EventRecord = { id: "event", title: "Games", status: "assigned", starts_at: 3800000000,
  duration_hours: 24, tables: [{ name: "A", capacity: 1 }], closes_at: 3700000000, discord_url: "https://discord.com/poll" };
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

it("remembers the archive cleanup choice and sends it to the server", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const fetchMock = vi.fn(async (path: string) => new Response(JSON.stringify({
    ...event, archived_at: 1,
    discord_cleanup_remaining: path.includes("/archive") ? 2 : 0,
    discord_cleanup_retry_after: 0,
    discord_cleanup_error: null,
  })));
  vi.stubGlobal("fetch", fetchMock);
  const onUpdated = vi.fn();
  render(<ArchiveEvent event={event} csrf="csrf" onUpdated={onUpdated} onAccessError={() => false} />);
  fireEvent.click(screen.getByRole("button", { name: "Archive event" }));
  const checkbox = screen.getByRole("checkbox", { name: "Also delete the signup and assignment messages on Discord" });
  expect(checkbox).not.toBeChecked();
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Archive event" }));
  expect(checkbox).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/events/event/archive?delete_discord_messages=true", expect.anything()));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/events/event/discord-messages/delete", expect.anything()));
  await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ discord_cleanup_remaining: 0 }), expect.any(String)));
});

it("reports an archived event when Discord cleanup pauses", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    ...event, archived_at: 1, discord_cleanup_remaining: 2,
    discord_cleanup_retry_after: 0, discord_cleanup_error: "Discord deletion failed (403).",
  }))));
  const onUpdated = vi.fn();
  render(<ArchiveEvent event={event} csrf="csrf" onUpdated={onUpdated} onAccessError={() => false} />);
  fireEvent.click(screen.getByRole("button", { name: "Archive event" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Also delete the signup and assignment messages on Discord" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(
    expect.objectContaining({ archived_at: 1 }), expect.stringContaining("Show Archived"),
  ));
});
