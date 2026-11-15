import { afterEach, expect, it, vi } from "vitest";
import { pollWhileVisible } from "./visiblePolling";

let stop: (() => void) | undefined;
afterEach(() => { stop?.(); stop = undefined; vi.useRealTimers(); vi.restoreAllMocks(); });

it("polls every two seconds and stops on cleanup", async () => {
  vi.useFakeTimers();
  const load = vi.fn(async () => {});
  stop = pollWhileVisible(load);
  await vi.advanceTimersByTimeAsync(0);
  expect(load).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(1999);
  expect(load).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(1);
  expect(load).toHaveBeenCalledTimes(2);
  stop();
  await vi.advanceTimersByTimeAsync(10000);
  expect(load).toHaveBeenCalledTimes(2);
});

it("pauses hidden tabs and refreshes immediately on return", async () => {
  vi.useFakeTimers();
  let hidden = true;
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  const load = vi.fn(async () => {});
  stop = pollWhileVisible(load);
  await vi.advanceTimersByTimeAsync(10000);
  expect(load).not.toHaveBeenCalled();
  hidden = false;
  document.dispatchEvent(new Event("visibilitychange"));
  expect(load).toHaveBeenCalledOnce();
  hidden = true;
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(10000);
  expect(load).toHaveBeenCalledOnce();
  hidden = false;
  document.dispatchEvent(new Event("visibilitychange"));
  expect(load).toHaveBeenCalledTimes(2);
});

it("waits for slow requests and never overlaps them", async () => {
  vi.useFakeTimers();
  let complete!: () => void;
  const load = vi.fn(() => new Promise<void>((resolve) => { complete = resolve; }));
  stop = pollWhileVisible(load);
  await vi.advanceTimersByTimeAsync(10000);
  expect(load).toHaveBeenCalledOnce();
  complete();
  await vi.advanceTimersByTimeAsync(1999);
  expect(load).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(1);
  expect(load).toHaveBeenCalledTimes(2);
});

it("supports one-second pending checks, slower completed checks, and stopping", async () => {
  vi.useFakeTimers();
  const load = vi.fn<() => Promise<number | false>>()
    .mockResolvedValueOnce(1000).mockResolvedValueOnce(15000).mockResolvedValue(false);
  stop = pollWhileVisible(load);
  await vi.advanceTimersByTimeAsync(1000);
  expect(load).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(14999);
  expect(load).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(load).toHaveBeenCalledTimes(3);
  await vi.advanceTimersByTimeAsync(30000);
  expect(load).toHaveBeenCalledTimes(3);
});
