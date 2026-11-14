import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import PlayerPairEditor from "./PlayerPairEditor";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("confirms breaking the target's current link before saving the new pair", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const onChanged = vi.fn();
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/players") return new Response(JSON.stringify([
      { discord_id: "3", discord_name: "Carol", real_name: "" },
    ]));
    const body = JSON.parse(String(options?.body));
    return new Response(JSON.stringify(body.replace_partner_id === "4"
      ? { profile: { partner: { id: "3", name: "Carol" } } }
      : { confirmation_required: true, replace_partner_id: "4", message: "This will break the link between Carol and Dave. Continue?" }));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<PlayerPairEditor playerId="1" partner={{ id: "2", name: "Bob" }} csrf="csrf"
    onChanged={onChanged} onBusy={vi.fn()} onAccessError={() => false} />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Carol" } });
  fireEvent.click(await screen.findByRole("button", { name: "Link Carol (3)" }));
  let confirmation = await screen.findByRole("dialog", { name: "Replace player link?" });
  expect(confirmation).toHaveTextContent("Carol and Dave");
  expect(onChanged).not.toHaveBeenCalled();
  fireEvent.click(within(confirmation).getByRole("button", { name: "Cancel" }));
  expect(screen.getByText(/Linked to Bob/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Link Carol (3)" }));
  confirmation = await screen.findByRole("dialog", { name: "Replace player link?" });
  fireEvent.click(within(confirmation).getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledWith({ id: "3", name: "Carol" }));
  expect(fetchMock).toHaveBeenLastCalledWith("/api/players/1/partner", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ partner_id: "3", replace_partner_id: "4" }),
    headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
  }));
});

it("shows the linked player without editing controls for read-only members", () => {
  render(<PlayerPairEditor playerId="1" partner={{ id: "2", name: "Bob" }} csrf="csrf" readOnly
    onChanged={vi.fn()} onBusy={vi.fn()} onAccessError={() => false} />);
  expect(screen.getByText(/Linked to Bob/)).toBeVisible();
  expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
