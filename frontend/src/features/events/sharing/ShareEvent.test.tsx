import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ShareEvent from "./ShareEvent";

const originalCopy = Object.getOwnPropertyDescriptor(document, "execCommand");
afterEach(() => {
  cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  if (originalCopy) Object.defineProperty(document, "execCommand", originalCopy);
  else Reflect.deleteProperty(document, "execCommand");
});

async function openShare(clipboard: unknown, execCommand = vi.fn(() => true)) {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  vi.stubGlobal("navigator", { clipboard });
  Object.defineProperty(document, "execCommand", { configurable: true, value: execCommand });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ path: "/#/shared/token" }))));
  render(<ShareEvent eventId="event" csrf="csrf" onAccessError={() => false} />);
  fireEvent.click(screen.getByRole("button", { name: "Share event" }));
  const input = await screen.findByRole<HTMLInputElement>("textbox", { name: "Public link" });
  return { input, copy: screen.getByRole("button", { name: "Copy link" }), execCommand };
}

it("prefers the Clipboard API when available", async () => {
  const writeText = vi.fn(async () => {});
  const { input, copy, execCommand } = await openShare({ writeText });
  fireEvent.click(copy);
  expect(await screen.findByRole("button", { name: "Copied" })).toBeVisible();
  expect(writeText).toHaveBeenCalledWith(input.value);
  expect(execCommand).not.toHaveBeenCalled();
});

it.each([undefined, { writeText: async () => { throw new Error("Clipboard denied"); } }])(
  "copies from the visible selected field when clipboard access is unavailable or denied (%#)", async clipboard => {
    let selected = "";
    const execCommand = vi.fn(() => {
      const input = document.activeElement as HTMLInputElement;
      selected = input.value.slice(input.selectionStart ?? 0, input.selectionEnd ?? 0);
      return true;
    });
    const { input, copy } = await openShare(clipboard, execCommand);
    fireEvent.click(copy);
    expect(await screen.findByRole("button", { name: "Copied" })).toBeVisible();
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(selected).toBe(input.value);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  },
);

it("leaves a failed copy selected for manual copying and clears the error on a successful retry", async () => {
  const execCommand = vi.fn(() => false);
  const { input, copy } = await openShare(undefined, execCommand);
  fireEvent.click(copy);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not copy");
  expect(input).toHaveFocus();
  expect(input.selectionStart).toBe(0);
  expect(input.selectionEnd).toBe(input.value.length);
  execCommand.mockReturnValue(true);
  fireEvent.click(copy);
  expect(await screen.findByRole("button", { name: "Copied" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
