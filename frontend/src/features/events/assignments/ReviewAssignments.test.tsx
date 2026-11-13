import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { EventRecord } from "../../../lib/api";
import ReviewAssignments from "./ReviewAssignments";

const event: EventRecord = { id: "event", title: "Games", status: "review", starts_at: 3800000000,
  discord_url: null, duration_hours: 24, tables: [{ name: "A", capacity: 1 }], closes_at: 3700000000 };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("keeps the preview available after an approval failure and retries with CSRF", async () => {
  const updated = vi.fn();
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Please retry" }), { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, status: "assigned" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<ReviewAssignments event={event} csrf="csrf" readOnly={false} onUpdated={updated} onAccessError={() => false} />);
  const button = screen.getByRole("button", { name: "Confirm Assignments and Send to Discord" });
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent("Please retry");
  expect(updated).not.toHaveBeenCalled();
  fireEvent.click(button);
  await waitFor(() => expect(updated).toHaveBeenCalledWith(expect.objectContaining({ status: "assigned" })));
  expect(fetchMock).toHaveBeenLastCalledWith("/api/events/event/assignments/approve", expect.objectContaining({
    method: "POST", headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
});

it("shows review status without approval controls for read-only users", () => {
  render(<ReviewAssignments event={event} csrf="csrf" readOnly onUpdated={vi.fn()} onAccessError={() => false} />);
  expect(screen.getByRole("status")).toHaveTextContent("Results will be sent to Discord after confirmation.");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
