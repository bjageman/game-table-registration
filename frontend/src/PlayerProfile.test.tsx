import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import PlayerProfile from "./PlayerProfile";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("loads and saves a real name while keeping Discord name and weighting read-only", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const profile = { discord_id: "123", discord_name: "Mary", real_name: "Mary Smith", weighting: 1.0 };
  const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
    if (options.method === "PUT") profile.real_name = JSON.parse(options.body as string).real_name;
    return new Response(JSON.stringify(profile));
  });
  vi.stubGlobal("fetch", fetchMock);
  const props = { player: { id: "123", name: "Mary" }, csrf: "csrf", onClose: vi.fn(), onAccessError: vi.fn(() => false) };
  const view = render(<PlayerProfile {...props} />);
  expect(await screen.findByLabelText("Real Name")).toHaveValue("Mary Smith");
  expect(screen.getByText("1.0")).toBeVisible();
  expect(screen.getAllByRole("textbox")).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("Real Name"), { target: { value: "Mary Jones" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Player information saved.");
  expect(fetchMock).toHaveBeenCalledWith("/api/players/123", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ real_name: "Mary Jones" }),
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
  view.unmount();
  render(<PlayerProfile {...props} />);
  expect(await screen.findByLabelText("Real Name")).toHaveValue("Mary Jones");
});

it("marks saved test users and retains edited names and weights on reopening", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const profile = { discord_id: "test-123", discord_name: "Test Player 001", real_name: "", weighting: 1.0, is_test: true };
  const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
    if (options.method === "PUT") Object.assign(profile, JSON.parse(options.body as string));
    return new Response(JSON.stringify(profile));
  });
  vi.stubGlobal("fetch", fetchMock);
  const props = { player: { id: profile.discord_id, name: profile.discord_name }, csrf: "csrf", onClose: vi.fn(), onAccessError: vi.fn(() => false) };
  const view = render(<PlayerProfile {...props} />);
  expect(await screen.findByText("Test User")).toBeVisible();
  fireEvent.change(screen.getByLabelText("Real Name"), { target: { value: "Saved Test Name" } });
  fireEvent.change(screen.getByLabelText("Current Weighting"), { target: { value: "2.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Player information saved.");
  expect(fetchMock).toHaveBeenCalledWith("/api/players/test-123", expect.objectContaining({ method: "PUT", body: JSON.stringify({ real_name: "Saved Test Name", weighting: 2.5 }) }));
  view.unmount();
  render(<PlayerProfile {...props} />);
  expect(await screen.findByLabelText("Real Name")).toHaveValue("Saved Test Name");
  expect(screen.getByLabelText("Current Weighting")).toHaveValue(2.5);
});
