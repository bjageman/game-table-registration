import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import AssignmentAnnouncement from "./AssignmentAnnouncement";
import type { EventRecord } from "./api";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const event: EventRecord = {
  id: "event", title: "Games", starts_at: 2000000000, duration_hours: 24,
  status: "assigned", closes_at: null, discord_url: null,
  tables: [{ name: "Table A", capacity: 1 }],
};

it("updates the existing Discord assignment from the event modal", async () => {
  const fetchMock = vi.fn(async (_url: string, options?: RequestInit) =>
    new Response(JSON.stringify(options?.method === "POST" ? { updated: 1 } : {
      status: "sent", error: null, url: "https://discord.com/channels/guild/channel/message",
    })));
  vi.stubGlobal("fetch", fetchMock);
  render(<AssignmentAnnouncement event={event} csrf="csrf" refreshToken={0} onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Update Discord" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/events/event/announcement/update", expect.objectContaining({ method: "POST" }),
  ));
  expect(await screen.findByRole("status")).toHaveTextContent("Discord assignments updated.");
});
