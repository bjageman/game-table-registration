import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PlayerProfile from "./PlayerProfile";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const player = { id: "123", name: "Mary" };
const baseProfile = { discord_id: "123", discord_name: "Mary", real_name: "Mary Smith", weighting: 1, guaranteed_seat: false };

function mockProfile(initial = baseProfile) {
  const profile = { ...initial };
  const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
    if (options.method === "PUT") Object.assign(profile, JSON.parse(options.body as string));
    return new Response(JSON.stringify(profile));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { profile, fetchMock };
}

it("saves display name on blur and when closing without a Save button", async () => {
  const { profile, fetchMock } = mockProfile();
  const onClose = vi.fn();
  render(<PlayerProfile player={player} csrf="csrf" onClose={onClose} onAccessError={() => false} />);
  const name = await screen.findByLabelText("Display Name");
  expect(name).toHaveValue("Mary Smith");
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/players/123?signup_name=Mary", expect.anything());
  fireEvent.change(name, { target: { value: "Mary Jones" } });
  fireEvent.blur(name);
  await waitFor(() => expect(profile.real_name).toBe("Mary Jones"));
  expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toEqual({ real_name: "Mary Jones" });
  fireEvent.change(name, { target: { value: "Mary Smith-Jones" } });
  fireEvent.click(screen.getByRole("button", { name: "Close player information" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(profile.real_name).toBe("Mary Smith-Jones");
});

it("saves name and weighting before Enter closes the player dialog", async () => {
  const { profile, fetchMock } = mockProfile();
  const onClose = vi.fn();
  render(<PlayerProfile player={player} csrf="csrf" onClose={onClose} onAccessError={() => false} />);
  const name = await screen.findByLabelText("Display Name");
  fireEvent.change(name, { target: { value: "Mary Jones" } });
  fireEvent.change(screen.getByLabelText("Global Weighting"), { target: { value: "2.5" } });
  fireEvent.keyDown(name, { key: "Enter" });
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(profile.real_name).toBe("Mary Jones");
  expect(profile.weighting).toBe(2.5);
  expect(fetchMock.mock.calls.filter(([, options]) => options.method === "PUT")).toHaveLength(2);
});

it("keeps the player dialog open when Enter finds an invalid weighting", async () => {
  mockProfile();
  const onClose = vi.fn();
  render(<PlayerProfile player={player} csrf="csrf" onClose={onClose} onAccessError={() => false} />);
  const weight = await screen.findByLabelText("Global Weighting");
  fireEvent.change(weight, { target: { value: "" } });
  fireEvent.keyDown(weight, { key: "Enter" });
  expect(screen.getByRole("alert")).toHaveTextContent("Choose a weighting from 0.1 to 10.");
  expectFeedbackAboveDiscordName(screen.getByRole("alert"));
  expect(onClose).not.toHaveBeenCalled();
});

it("saves global weighting on blur in 0.1 steps", async () => {
  const { profile, fetchMock } = mockProfile();
  const onSaved = vi.fn();
  render(<PlayerProfile player={player} csrf="csrf" onClose={vi.fn()} onAccessError={() => false} onSaved={onSaved} />);
  const weight = await screen.findByLabelText("Global Weighting");
  expect(weight).toHaveAttribute("step", "0.1");
  fireEvent.change(weight, { target: { value: "2.5" } });
  fireEvent.blur(weight);
  await waitFor(() => expect(profile.weighting).toBe(2.5));
  expect(weight).toHaveValue(2.5);
  expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toEqual({ weighting: 2.5 });
  expect(onSaved).toHaveBeenCalledOnce();
});

it.each([[11, 10, "maximum weight is 10"], [-1, 0.1, "minimum weight is 0.1"]])("clamps %s to %s and explains the limit", async (entered, expected, message) => {
  const { profile } = mockProfile();
  render(<PlayerProfile player={player} csrf="csrf" onClose={vi.fn()} onAccessError={() => false} />);
  const weight = await screen.findByLabelText("Global Weighting");
  fireEvent.change(weight, { target: { value: String(entered) } });
  fireEvent.blur(weight);
  await waitFor(() => expect(profile.weighting).toBe(expected));
  expect(weight).toHaveValue(expected);
  const feedback = await screen.findByRole("status");
  expect(feedback).toHaveTextContent(String(message));
  expectFeedbackAboveDiscordName(feedback);
});

it("saves a checkbox toggle immediately and serializes rapid changes", async () => {
  const { profile, fetchMock } = mockProfile();
  render(<PlayerProfile player={player} csrf="csrf" onClose={vi.fn()} onAccessError={() => false} />);
  const checkbox = await screen.findByLabelText("Guaranteed Seat");
  fireEvent.click(checkbox);
  fireEvent.click(checkbox);
  await waitFor(() => expect(fetchMock.mock.calls.filter(([, options]) => options.method === "PUT")).toHaveLength(2));
  expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toEqual({ guaranteed_seat: true });
  expect(JSON.parse(fetchMock.mock.calls[2][1].body as string)).toEqual({ guaranteed_seat: false });
  expect(profile.guaranteed_seat).toBe(false);
});

it("serializes name and weight edits without overwriting either", async () => {
  const { profile, fetchMock } = mockProfile();
  render(<PlayerProfile player={player} csrf="csrf" onClose={vi.fn()} onAccessError={() => false} />);
  const name = await screen.findByLabelText("Display Name");
  fireEvent.change(name, { target: { value: "Unsaved Name" } });
  fireEvent.blur(name);
  const weight = screen.getByLabelText("Global Weighting");
  fireEvent.change(weight, { target: { value: "2.5" } });
  fireEvent.blur(weight);
  await waitFor(() => expect(profile.weighting).toBe(2.5));
  expect(screen.getByLabelText("Display Name")).toHaveValue("Unsaved Name");
  expect(fetchMock.mock.calls[1][1].body).toBe(JSON.stringify({ real_name: "Unsaved Name" }));
  expect(fetchMock.mock.calls[2][1].body).toBe(JSON.stringify({ weighting: 2.5 }));
});

it("supports test players and waits for a pending save before closing", async () => {
  const testPlayer = { id: "test-123", name: "Test Player 001" };
  const profile = { ...baseProfile, discord_id: testPlayer.id, discord_name: testPlayer.name, is_test: true };
  let finishSave: ((response: Response) => void) | undefined;
  const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
    if (options.method !== "PUT") return new Response(JSON.stringify(profile));
    Object.assign(profile, JSON.parse(options.body as string));
    return await new Promise<Response>((resolve) => { finishSave = resolve; });
  });
  vi.stubGlobal("fetch", fetchMock);
  const onClose = vi.fn();
  render(<PlayerProfile player={testPlayer} csrf="csrf" onClose={onClose} onAccessError={() => false} />);
  expect(await screen.findByText("Test User")).toBeVisible();
  const weight = screen.getByLabelText("Global Weighting");
  fireEvent.change(weight, { target: { value: "3" } });
  fireEvent.blur(weight);
  fireEvent.click(screen.getByRole("button", { name: "Close player information" }));
  await waitFor(() => expect(finishSave).toBeDefined());
  expect(onClose).not.toHaveBeenCalled();
  finishSave!(new Response(JSON.stringify(profile)));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(profile.weighting).toBe(3);
});


function expectFeedbackAboveDiscordName(feedback: HTMLElement) {
  expect(feedback).toHaveClass("player-profile-feedback");
  expect(feedback.compareDocumentPosition(screen.getByText("Discord Name")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
}

it("shows linked-player lookup errors above Discord Name", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/players"
    ? new Response(JSON.stringify({ detail: "Could not load linked players." }), { status: 502 })
    : new Response(JSON.stringify(baseProfile))));
  render(<PlayerProfile player={player} csrf="csrf" onClose={vi.fn()} onAccessError={() => false} />);
  fireEvent.focus(await screen.findByRole("combobox", { name: "Linked Player" }));
  const feedback = await screen.findByRole("alert");
  expect(feedback).toHaveTextContent("Could not load linked players.");
  expectFeedbackAboveDiscordName(feedback);
});
