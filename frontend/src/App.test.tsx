import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("offers Discord sign-in for an unauthenticated moderator", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (input) =>
      new Response(
        JSON.stringify(input === "/api/setup" ? { configured: true } : {}),
        { status: input === "/api/me" ? 401 : 200 },
      ),
  );
  render(<App />);
  expect(
    await screen.findByRole("link", { name: /Continue with Discord/ }),
  ).toHaveAttribute("href", "/api/auth/login");
});
it("shows setup guidance instead of a broken login link", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (input) =>
      new Response(JSON.stringify({ configured: false }), {
        status: input === "/api/me" ? 401 : 200,
      }),
  );
  render(<App />);
  expect(
    await screen.findByText(/Complete the Discord configuration/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: /Continue with Discord/ }),
  ).not.toBeInTheDocument();
});
