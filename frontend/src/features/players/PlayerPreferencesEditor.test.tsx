import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import PlayerPreferencesEditor, { type PreferredPlayer } from "./PlayerPreferencesEditor";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const initial = [{ id: "2", name: "Bob" }];
function Editor({ onChanged = vi.fn(), readOnly = false }: { onChanged?: (players: PreferredPlayer[]) => void; readOnly?: boolean }) {
  const [preferences, setPreferences] = useState(initial);
  return <PlayerPreferencesEditor playerId="1" preferences={preferences} csrf="csrf" readOnly={readOnly}
    onChanged={(players) => { setPreferences(players); onChanged(players); }} onBusy={vi.fn()} onAccessError={() => false} />;
}

it("adds multiple preferences without replacing the existing selection, then removes one", async () => {
  const onChanged = vi.fn();
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/players") return new Response(JSON.stringify([
      { discord_id: "1", discord_name: "Alice", real_name: "" },
      { discord_id: "2", discord_name: "Bob", real_name: "" },
      { discord_id: "3", discord_name: "Carol", real_name: "" },
    ]));
    const body = JSON.parse(String(options?.body));
    return new Response(JSON.stringify({ profile: { paired_preferences: [...initial, { id: "3", name: "Carol" }].filter((player) => body.player_ids.includes(player.id)) } }));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<Editor onChanged={onChanged} />);
  fireEvent.focus(screen.getByRole("combobox", { name: "Paired Player Preferences" }));
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "Carol" } });
  fireEvent.click(await screen.findByRole("option", { name: "Carol (3)" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledWith([...initial, { id: "3", name: "Carol" }]));
  expect(screen.getByText("Bob")).toBeVisible();
  expect(screen.getByText("Carol")).toBeVisible();
  expect(fetchMock).toHaveBeenLastCalledWith("/api/players/1/pairings", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ player_ids: ["2", "3"] }),
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
  fireEvent.keyDown(screen.getByRole("combobox"), { key: "Backspace" });
  await waitFor(() => expect(onChanged).toHaveBeenLastCalledWith(initial));
  expect(screen.queryByText("Carol")).not.toBeInTheDocument();
});

it("keeps the saved selection when a change fails", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/players"
    ? new Response(JSON.stringify([{ discord_id: "3", discord_name: "Carol", real_name: "" }]))
    : new Response(JSON.stringify({ detail: "Could not save preferences" }), { status: 409 })));
  render(<Editor />);
  fireEvent.focus(screen.getByRole("combobox"));
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "Carol" } });
  fireEvent.click(await screen.findByRole("option", { name: "Carol (3)" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not save preferences");
  expect(screen.getByText("Bob")).toBeVisible();
  expect(screen.queryByText("Carol")).not.toBeInTheDocument();
});

it("shows preferences without editing controls for read-only members", () => {
  render(<Editor readOnly />);
  expect(screen.getByText("Bob")).toBeVisible();
  expect(screen.getByRole("combobox", { name: "Paired Player Preferences" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
});
