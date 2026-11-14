import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import CloseSignups from "./CloseSignups";
import type { EventRecord } from "../../../lib/api";

const event: EventRecord = { id: "event", title: "Games", status: "open", starts_at: 3800000000,
  duration_hours: 24, tables: [{ name: "A", capacity: 1 }], closes_at: 3700000000, discord_url: "https://discord.com/poll" };
function props() {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  return { event, csrf: "csrf", onUpdated: vi.fn(), onAccessError: vi.fn(() => false) };
}
afterEach(() => { cleanup(); localStorage.clear(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it.each(["assigned", "review"])("requires confirmation and handles a completed %s draw with CSRF", async (status) => {
  const parameters = props();
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ review_assignments_before_discord: false })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ review_assignments_before_discord: false })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, status })));
  vi.stubGlobal("fetch", fetchMock);
  render(<CloseSignups {...parameters} />);
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  const confirmation = await screen.findByRole("dialog", { name: "Close signups for Games?" });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).not.toHaveBeenCalledWith("/api/events/event/close", expect.anything());
  fireEvent.click(within(confirmation).getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  const reopenedConfirmation = await screen.findByRole("dialog", { name: "Close signups for Games?" });
  fireEvent.click(within(reopenedConfirmation).getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(parameters.onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status })));
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(fetchMock).toHaveBeenLastCalledWith("/api/events/event/close", expect.objectContaining({ method: "POST", headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }) }));
});

it("closes directly into verification without a confirmation dialog", async () => {
  const parameters = props();
  localStorage.setItem("delete-discord-signup-on-close", "true");
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ review_assignments_before_discord: true })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, status: "review" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<CloseSignups {...parameters} />);
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  await waitFor(() => expect(parameters.onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: "review" })));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenLastCalledWith("/api/events/event/close", expect.objectContaining({ method: "POST" }));
});

it("remembers message deletion and sends the selected close option", async () => {
  const parameters = props();
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ review_assignments_before_discord: false })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ review_assignments_before_discord: false })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, status: "assigned", discord_url: null })));
  vi.stubGlobal("fetch", fetchMock);
  render(<CloseSignups {...parameters} />);
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  let confirmation = await screen.findByRole("dialog", { name: "Close signups for Games?" });
  fireEvent.click(within(confirmation).getByRole("checkbox", { name: "Also delete the signup message on Discord" }));
  fireEvent.click(within(confirmation).getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  confirmation = await screen.findByRole("dialog", { name: "Close signups for Games?" });
  expect(within(confirmation).getByRole("checkbox", { name: "Also delete the signup message on Discord" })).toBeChecked();
  fireEvent.click(within(confirmation).getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith("/api/events/event/close?delete_signup_message=true", expect.anything()));
});

it("continues only after explicit closing responses and blocks duplicate confirmation", async () => {
  const parameters = props();
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ review_assignments_before_discord: false })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, status: "closing" }), { status: 202 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, status: "assigned" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<CloseSignups {...parameters} />);
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  await screen.findByRole("dialog", { name: "Close signups for Games?" });
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
  await waitFor(() => expect(parameters.onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: "closing" })));
  await waitFor(() => expect(parameters.onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: "assigned" })), { timeout: 3000 });
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("does not automatically repeat a failed settings lookup", async () => {
  const parameters = props();
  const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
  vi.stubGlobal("fetch", fetchMock);
  render(<CloseSignups {...parameters} />);
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
