/** Poll after each request completes, pausing background tabs. */
export function pollWhileVisible(
  refresh: () => Promise<number | false | void>,
  interval = 2000,
) {
  let active = true;
  let inFlight = false;
  let refreshOnFinish = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function run() {
    if (!active || document.hidden) return;
    if (inFlight) { refreshOnFinish = true; return; }
    inFlight = true;
    let next: number | false | void = interval;
    try {
      next = await refresh();
    } finally {
      inFlight = false;
      if (active && !document.hidden && next !== false) {
        timer = setTimeout(() => void run(), refreshOnFinish ? 0 : next ?? interval);
      }
      refreshOnFinish = false;
    }
  }
  function visibility() {
    clearTimeout(timer);
    if (!document.hidden) void run();
  }
  document.addEventListener("visibilitychange", visibility);
  void run();
  return () => {
    active = false;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", visibility);
  };
}
