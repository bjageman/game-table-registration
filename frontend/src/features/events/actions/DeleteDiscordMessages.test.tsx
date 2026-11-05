import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import DeleteDiscordMessages from "./DeleteDiscordMessages";
import type { EventRecord } from "../../../lib/api";

const event: EventRecord = { id: "event", title: "Games", status: "assigned", starts_at: 3800000000,
  duration_hours: 24, tables: [{ name: "A", capacity: 1 }], closes_at: 3700000000,
  archived_at: 1, discord_url: null };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("resumes Discord message deletion for an archived event", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, discord_cleanup_remaining: 2, discord_cleanup_retry_after: 0, discord_cleanup_error: null })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, discord_cleanup_remaining: 0, discord_cleanup_retry_after: 0, discord_cleanup_error: null })));
  vi.stubGlobal("fetch", fetchMock);
  const onUpdated = vi.fn();
  render(<DeleteDiscordMessages event={event} csrf="csrf" onUpdated={onUpdated} onAccessError={() => false} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete Discord messages" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ discord_cleanup_remaining: 0 }), expect.any(String)));
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock).toHaveBeenCalledWith("/api/events/event/discord-messages/delete", expect.objectContaining({ method: "POST" }));
});
