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
  expect(screen.getByRole("button", { name: "Cancel", exact: true })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Confirm", exact: true }));
  expect(onConfirm).toHaveBeenCalledOnce();
  view.rerender(<ConfirmationDialog {...props} busy={true}>Details</ConfirmationDialog>);
  expect(screen.getByRole("button", { name: "Confirm", exact: true })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
  expect(onCancel).not.toHaveBeenCalled();
  view.rerender(<ConfirmationDialog {...props} busy={false}>Details</ConfirmationDialog>);
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
  expect(onCancel).toHaveBeenCalledOnce();
  view.unmount();
  expect(trigger).toHaveFocus();
  trigger.remove();
});
