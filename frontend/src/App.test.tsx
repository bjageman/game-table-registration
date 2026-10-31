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
});

function mockApi(meStatus = 200, configured = true) {
  const fetchMock = vi.fn(async (path: string) => {
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
  fireEvent.click(await screen.findByRole("button", { name: "Log out" }));
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
    await screen.findByRole("heading", { name: "Moderator access required" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Log out" }),
  ).not.toBeInTheDocument();
});
