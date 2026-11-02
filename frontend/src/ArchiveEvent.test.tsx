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
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ...event, archived_at: 1 })));
  vi.stubGlobal("fetch", fetchMock);
  render(<ArchiveEvent event={event} csrf="csrf" onUpdated={vi.fn()} onAccessError={() => false} />);
  fireEvent.click(screen.getByRole("button", { name: "Archive event" }));
  const checkbox = screen.getByRole("checkbox", { name: "Also delete the signup and assignment messages on Discord" });
  expect(checkbox).not.toBeChecked();
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Archive event" }));
  expect(checkbox).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/events/event/archive?delete_discord_messages=true", expect.anything()));
});
