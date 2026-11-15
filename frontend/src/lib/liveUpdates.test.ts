import { afterEach, expect, it, vi } from "vitest";
import { subscribeLiveUpdates } from "./liveUpdates";

class Source extends EventTarget {
  static instances: Source[] = [];
  onopen?: () => void;
  onerror?: () => void;
  close = vi.fn();
  constructor(public url: string) { super(); Source.instances.push(this); }
}
let dispose: (() => void)[] = [];
afterEach(() => {
  dispose.forEach((close) => close()); dispose = [];
  Source.instances = [];
  vi.useRealTimers(); vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("shares a stream, coalesces changes, and falls back while disconnected", async () => {
  vi.useFakeTimers(); vi.stubGlobal("EventSource", Source);
  const first = vi.fn(), second = vi.fn();
  dispose.push(subscribeLiveUpdates(first), subscribeLiveUpdates(second));
  expect(Source.instances).toHaveLength(1);
  const source = Source.instances[0];
  expect(source.url).toBe("/api/live");
  source.onopen?.();
  await vi.advanceTimersByTimeAsync(150);
  expect(first).toHaveBeenCalledTimes(1);
  source.dispatchEvent(new Event("change"));
  source.dispatchEvent(new Event("change"));
  await vi.advanceTimersByTimeAsync(150);
  expect(first).toHaveBeenCalledTimes(2);
  expect(second).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(2000);
  expect(first).toHaveBeenCalledTimes(2);
  source.onerror?.();
  await vi.advanceTimersByTimeAsync(2000);
  expect(first).toHaveBeenCalledTimes(3);
  dispose[0]();
  expect(source.close).not.toHaveBeenCalled();
  dispose[1]();
  expect(source.close).toHaveBeenCalledOnce();
  dispose = [];
});

it("pauses hidden pages and refreshes immediately on return with a new connection", async () => {
  vi.useFakeTimers(); vi.stubGlobal("EventSource", Source);
  let hidden = false;
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  const refresh = vi.fn();
  dispose.push(subscribeLiveUpdates(refresh, "/api/public/live/share"));
  hidden = true; document.dispatchEvent(new Event("visibilitychange"));
  expect(Source.instances[0].close).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(30000);
  expect(refresh).not.toHaveBeenCalled();
  hidden = false; document.dispatchEvent(new Event("visibilitychange"));
  expect(refresh).toHaveBeenCalledOnce();
  expect(Source.instances).toHaveLength(2);
});

it("polls without EventSource and cleans up timers", async () => {
  vi.useFakeTimers(); vi.stubGlobal("EventSource", undefined);
  const refresh = vi.fn();
  const stop = subscribeLiveUpdates(refresh);
  await vi.advanceTimersByTimeAsync(2000);
  expect(refresh).toHaveBeenCalledOnce();
  stop();
  await vi.advanceTimersByTimeAsync(30000);
  expect(refresh).toHaveBeenCalledOnce();
});

it("refreshes through normal APIs when stream access is revoked", async () => {
  vi.useFakeTimers(); vi.stubGlobal("EventSource", Source);
  const refresh = vi.fn();
  dispose.push(subscribeLiveUpdates(refresh));
  Source.instances[0].dispatchEvent(new Event("access-revoked"));
  expect(refresh).toHaveBeenCalledOnce();
  expect(Source.instances[0].close).toHaveBeenCalledOnce();
});
