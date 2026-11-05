import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import AssignmentAnnouncement from "./AssignmentAnnouncement";
import type { EventRecord } from "./api";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const event: EventRecord = {
  id: "event", title: "Games", starts_at: 2000000000, duration_hours: 24,
  status: "assigned", closes_at: null, discord_url: null,
  tables: [{ name: "Table A", capacity: 1 }],
};

it("shows automatic Discord assignment update status without a button", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({
    status: "sent", error: null, url: "https://discord.com/channels/guild/channel/message",
    update_pending: true, update_error: null,
  })));
  vi.stubGlobal("fetch", fetchMock);
  render(<AssignmentAnnouncement event={event} csrf="csrf" refreshToken={0} onAccessError={() => false} />);
  expect(await screen.findByText("Updating Discord assignments…")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Update Discord" })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/events/event/announcement", expect.anything());
});
