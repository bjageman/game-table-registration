import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import CloseSignups from "./CloseSignups";
import type { EventRecord } from "./api";

const event: EventRecord = { id: "event", title: "Games", status: "open", starts_at: 3800000000,
  duration_hours: 24, tables: [{ name: "A", capacity: 1 }], closes_at: 3700000000, discord_url: "https://discord.com/poll" };
function props() {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  return { event, csrf: "csrf", onUpdated: vi.fn(), onAccessError: vi.fn(() => false) };
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("requires confirmation and sends the close operation with CSRF", async () => {
  const parameters = props();
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ...event, status: "assigned" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<CloseSignups {...parameters} />);
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(parameters.onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: "assigned" })));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith("/api/events/event/close", expect.objectContaining({ method: "POST", headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }) }));
});

it("continues only after explicit closing responses and blocks duplicate confirmation", async () => {
  vi.useFakeTimers();
  const parameters = props();
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, status: "closing" }), { status: 202 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...event, status: "assigned" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<CloseSignups {...parameters} />);
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(parameters.onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: "closing" }));
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(parameters.onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: "assigned" }));
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("does not automatically repeat a failed network operation", async () => {
  const parameters = props();
  const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
  vi.stubGlobal("fetch", fetchMock);
  render(<CloseSignups {...parameters} />);
  fireEvent.click(screen.getByRole("button", { name: "Close Signups" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
});
