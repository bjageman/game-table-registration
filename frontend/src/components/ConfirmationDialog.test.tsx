import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ConfirmationDialog from "./ConfirmationDialog";

afterEach(cleanup);

it("focuses Cancel, blocks dismissal while busy, and restores trigger focus", () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const trigger = document.createElement("button");
  document.body.append(trigger);
  trigger.focus();
  const onCancel = vi.fn();
  const onConfirm = vi.fn();
  const props = { title: "Delete event?", error: "", onCancel, onConfirm };
  const view = render(<ConfirmationDialog {...props} busy={false}>Details</ConfirmationDialog>);
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(onConfirm).toHaveBeenCalledOnce();
  view.rerender(<ConfirmationDialog {...props} busy={true}>Details</ConfirmationDialog>);
  expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Close dialog" })).toBeDisabled();
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
  expect(onCancel).not.toHaveBeenCalled();
  view.rerender(<ConfirmationDialog {...props} busy={false}>Details</ConfirmationDialog>);
  fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
  expect(onCancel).toHaveBeenCalledOnce();
  view.unmount();
  expect(trigger).toHaveFocus();
  trigger.remove();
});

it("can keep Cancel as the only dismiss control and focus it", () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const onCancel = vi.fn();
  render(<ConfirmationDialog title="Publish event?" busy={false} error="" showClose={false} onCancel={onCancel} onConfirm={() => {}}>{null}</ConfirmationDialog>);
  expect(screen.queryByRole("button", { name: "Close dialog" })).not.toBeInTheDocument();
  const cancel = screen.getByRole("button", { name: "Cancel" });
  expect(cancel).toHaveFocus();
  fireEvent.click(cancel);
  expect(onCancel).toHaveBeenCalledOnce();
});

it.each([false, true])("keeps Escape inside a nested confirmation (busy: %s)", (busy) => {
  const parentCancel = vi.fn();
  const onCancel = vi.fn();
  render(<dialog open aria-label="Event details" onCancel={parentCancel}>
    <ConfirmationDialog title="Publish event?" busy={busy} error="" onCancel={onCancel} onConfirm={() => {}}>{null}</ConfirmationDialog>
  </dialog>);
  fireEvent(screen.getByRole("dialog", { name: "Publish event?" }), new Event("cancel", { bubbles: true, cancelable: true }));
  expect(parentCancel).not.toHaveBeenCalled();
  expect(onCancel).toHaveBeenCalledTimes(busy ? 0 : 1);
});
