import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("preserves FastAPI validation locations for inline field errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: [
              null,
              { loc: ["body", "tables", 0, "capacity"], msg: "Too many seats" },
            ],
          }),
          { status: 422 },
        ),
    ),
  );
  await expect(api("/events")).rejects.toMatchObject({
    status: 422,
    message: "Too many seats",
    issues: [{ loc: ["body", "tables", 0, "capacity"], msg: "Too many seats" }],
  });
});

it("shows a useful message when a proxy returns a non-JSON error page", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () => new Response("<html>Bad gateway</html>", { status: 502 }),
    ),
  );
  await expect(api("/events")).rejects.toMatchObject({
    status: 502,
    message: "The request could not be completed. Please try again.",
  });
});

it("times out a stalled request without retrying a possible mutation", async () => {
  const controller = new AbortController();
  vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
  const fetchMock = vi.fn(
    (_path: string, options: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        options.signal?.addEventListener("abort", () =>
          reject(new DOMException("Timeout", "TimeoutError")),
        );
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const request = api("/events/id/publish", { method: "POST" });
  controller.abort();
  await expect(request).rejects.toThrow(/Refresh to check the result/);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
