import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.title = "TableSignup";
});

function mockApi(meStatus = 200, configured = true, branding = { name: "TableSignup", tagline: "Made for your next game night.", logo_url: null as string | null }) {
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/branding") return new Response(JSON.stringify(branding));
    if (path === "/api/events") return new Response("[]");
    if (path === "/api/me")
      return new Response(
        JSON.stringify(
          meStatus === 200
            ? { username: "organizer", csrf: "test-csrf" }
            : { detail: "Access denied" },
        ),
        { status: meStatus },
      );
    if (path === "/api/setup")
      return new Response(JSON.stringify({ configured }));
    if (path === "/api/auth/logout") return new Response(null, { status: 204 });
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("uses server branding for the header, browser title, footer, and logo", async () => {
  mockApi(401, true, { name: "Game Night", tagline: "Find your next table.", logo_url: "https://example.org/logo.svg" });
  render(<App />);
  const link = await screen.findByRole("link", { name: "Game Night" });
  expect(link).toContainElement(link.querySelector("img"));
  expect(link.querySelector("img")).toHaveAttribute("src", "https://example.org/logo.svg");
  expect(document.title).toBe("Game Night");
  expect(screen.getByText("Find your next table.")).toBeVisible();
});

it("connects signed-out users to Discord OAuth", async () => {
  mockApi(401);
  render(<App />);
  expect(
    await screen.findByRole("link", { name: "Log in with Discord" }),
  ).toHaveAttribute("href", "/api/auth/login");
});

it("does not offer login before Discord is configured", async () => {
  mockApi(401, false);
  render(<App />);
  expect(
    await screen.findByText(/Discord sign-in is not configured/),
  ).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "Log in with Discord" }),
  ).not.toBeInTheDocument();
});

it("restores the moderator session and logs out with its CSRF token", async () => {
  const fetchMock = mockApi();
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "organizer" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Log Out" }));
  expect(
    await screen.findByRole("link", { name: "Log in with Discord" }),
  ).toBeVisible();
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/logout",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        headers: expect.objectContaining({ "X-CSRF-Token": "test-csrf" }),
      }),
    ),
  );
});

it("explains when server membership or moderator access is missing", async () => {
  mockApi(403);
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Moderator Access Required" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Log out" }),
  ).not.toBeInTheDocument();
});
