import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { EventRecord } from "../../../lib/api";
import ReviewAssignments from "./ReviewAssignments";

const event: EventRecord = { id: "event", title: "Games", status: "review", starts_at: 3800000000,
  discord_url: "https://discord.com/poll", duration_hours: 24, tables: [{ name: "A", capacity: 1 }], closes_at: 3700000000 };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("keeps the preview available after an approval failure and retries with CSRF", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const updated = vi.fn();
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Please retry" }), { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, status: "assigned" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<ReviewAssignments event={event} csrf="csrf" readOnly={false} onUpdated={updated} onAccessError={() => false} />);
  const button = screen.getByRole("button", { name: "Send to Discord" });
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(button);
  const confirmation = screen.getByRole("dialog", { name: "Send assignments to Discord?" });
  expect(confirmation).toHaveTextContent("Are you sure you want to send these assignments?");
  fireEvent.click(within(confirmation).getByRole("checkbox", { name: "Also delete the signup message on Discord" }));
  fireEvent.click(within(confirmation).getByRole("button", { name: "Confirm" }));
  expect(await within(confirmation).findByRole("alert")).toHaveTextContent("Please retry");
  expect(updated).not.toHaveBeenCalled();
  fireEvent.click(button);
  fireEvent.click(within(screen.getByRole("dialog", { name: "Send assignments to Discord?" })).getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(updated).toHaveBeenCalledWith(expect.objectContaining({ status: "assigned" })));
  expect(fetchMock).toHaveBeenLastCalledWith("/api/events/event/assignments/approve?delete_signup_message=true", expect.objectContaining({
    method: "POST", headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
});

it("shows review status without approval controls for read-only users", () => {
  render(<ReviewAssignments event={event} csrf="csrf" readOnly onUpdated={vi.fn()} onAccessError={() => false} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("shows an alert and retains review when Discord delivery fails", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const updated = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    ...event, assignment_publication_pending: true,
    assignment_publication_error: "Discord rejected the announcement.",
  }))));
  render(<ReviewAssignments event={event} csrf="csrf" readOnly={false} onUpdated={updated} onAccessError={() => false} />);
  fireEvent.click(screen.getByRole("button", { name: "Send to Discord" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Assignments have not been posted to Discord");
  expect(screen.getByRole("dialog", { name: "Send assignments to Discord?" })).toBeVisible();
  expect(updated).toHaveBeenCalledWith(expect.objectContaining({ status: "review" }));
});
