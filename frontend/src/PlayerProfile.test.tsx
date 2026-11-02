import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import PlayerProfile from "./PlayerProfile";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("loads and saves a real name while keeping Discord name read-only", async () => {
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
  expect(await screen.findByLabelText("Display Name")).toHaveValue("Mary Smith");
  expect(screen.getByText("1.0")).toBeVisible();
  expect(screen.getByText("Global Weighting")).toBeVisible();
  expect(screen.getByRole("button", { name: "Edit global weighting" })).toBeVisible();
  expect(fetchMock).toHaveBeenCalledWith("/api/players/123?signup_name=Mary", expect.anything());
  expect(screen.getAllByRole("textbox")).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("Display Name"), { target: { value: "Mary Jones" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Player information saved.");
  expect(fetchMock).toHaveBeenCalledWith("/api/players/123", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ real_name: "Mary Jones", guaranteed_seat: false }),
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
  view.unmount();
  render(<PlayerProfile {...props} />);
  expect(await screen.findByLabelText("Display Name")).toHaveValue("Mary Jones");
});

it("edits global weighting for a regular player", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const profile = { discord_id: "123", discord_name: "Mary", real_name: "Mary Smith", weighting: 1.0 };
  const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
    if (options.method === "PUT") Object.assign(profile, JSON.parse(options.body as string));
    return new Response(JSON.stringify(profile));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<PlayerProfile player={{ id: "123", name: "Mary" }} csrf="csrf" onClose={vi.fn()} onAccessError={() => false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit global weighting" }));
  fireEvent.change(screen.getByLabelText("Global Weighting"), { target: { value: "2.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Player information saved.");
  expect(fetchMock).toHaveBeenCalledWith("/api/players/123", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ real_name: "Mary Smith", guaranteed_seat: false, weighting: 2.5 }),
  }));
  expect(screen.getByText("2.5")).toBeVisible();
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
  fireEvent.change(screen.getByLabelText("Display Name"), { target: { value: "Saved Test Name" } });
  fireEvent.click(screen.getByRole("button", { name: "Edit global weighting" }));
  fireEvent.change(screen.getByLabelText("Global Weighting"), { target: { value: "2.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Player information saved.");
  expect(fetchMock).toHaveBeenCalledWith("/api/players/test-123", expect.objectContaining({ method: "PUT", body: JSON.stringify({ real_name: "Saved Test Name", guaranteed_seat: false, weighting: 2.5 }) }));
  view.unmount();
  render(<PlayerProfile {...props} />);
  expect(await screen.findByLabelText("Display Name")).toHaveValue("Saved Test Name");
  expect(screen.getByText("Global Weighting")).toBeVisible();
  expect(screen.getByText("2.5")).toBeVisible();
});

it("saves and clears a guaranteed seat", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const profile = { discord_id: "123", discord_name: "Volunteer", real_name: "", weighting: 1, guaranteed_seat: false };
  const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
    if (options.method === "PUT") Object.assign(profile, JSON.parse(options.body as string));
    return new Response(JSON.stringify(profile));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<PlayerProfile player={{ id: "123", name: "Volunteer" }} csrf="csrf" onClose={vi.fn()} onAccessError={() => false} />);
  const checkbox = await screen.findByLabelText("Guaranteed Seat");
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Player information saved.");
  expect(fetchMock).toHaveBeenCalledWith("/api/players/123", expect.objectContaining({ method: "PUT", body: JSON.stringify({ real_name: "", guaranteed_seat: true }) }));
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Player information saved.");
  expect(profile.guaranteed_seat).toBe(false);
});
