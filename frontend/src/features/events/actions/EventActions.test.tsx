import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import EventActions from "./EventActions";
import type { EventRecord } from "../../../lib/api";

const event: EventRecord = {
  id: "event", title: "Games", starts_at: 2000000000, duration_hours: 24,
  status: "open", closes_at: null, discord_url: "https://discord.com/poll",
  tables: [{ name: "Table A", capacity: 8 }],
};
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

it.each([false, true])("asks whether to delete the Discord poll (selected: %s)", async (deletePoll) => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
  const onDeleted = vi.fn();
  render(<EventActions event={event} csrf="csrf" onEdit={vi.fn()} onDeleted={onDeleted} onAccessError={() => false} />);
  expect(screen.queryByRole("button", { name: "Edit draft" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Delete signup" }));
  const checkbox = screen.getByRole("checkbox", { name: "Also delete the signup message on Discord" });
  expect(checkbox).not.toBeChecked();
  expect(fetchMock).not.toHaveBeenCalled();
  if (deletePoll) fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(event));
  expect(fetchMock).toHaveBeenCalledWith(`/api/events/event${deletePoll ? "?delete_poll=true" : ""}`,
    expect.objectContaining({ method: "DELETE", headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }) }));
});

it("remembers the delete choice when the dialog is reopened and remounted", () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const props = { event, csrf: "csrf", onEdit: vi.fn(), onDeleted: vi.fn(), onAccessError: () => false };
  const view = render(<EventActions {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete signup" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Also delete the signup message on Discord" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  view.unmount();
  render(<EventActions {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete signup" }));
  expect(screen.getByRole("checkbox", { name: "Also delete the signup message on Discord" })).toBeChecked();
});
