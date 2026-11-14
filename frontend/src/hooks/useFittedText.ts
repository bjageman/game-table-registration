import { useLayoutEffect, type RefObject } from "react";

function fitTextToWidth(target: HTMLElement) {
  target.style.removeProperty("font-size");
  if (target.clientWidth <= 0) return;
  for (let attempt = 0; attempt < 4 && target.scrollWidth > target.clientWidth; attempt++) {
    const size = parseFloat(getComputedStyle(target).fontSize);
    target.style.fontSize = `${Math.max(1, size * target.clientWidth / target.scrollWidth - 0.2)}px`;
  }
}

function fitModalTitle(container: HTMLElement, target: HTMLElement) {
  container.style.removeProperty("--modal-badge-scale");
  target.style.removeProperty("font-size");
  if (container.clientWidth <= 0 || target.scrollWidth <= target.clientWidth) return;
  const size = parseFloat(getComputedStyle(target).fontSize);
  let lower = 0;
  let upper = 1;
  function apply(scale: number) {
    container.style.setProperty("--modal-badge-scale", String(scale ** 1.5));
    target.style.fontSize = `${size * scale}px`;
  }
  for (let attempt = 0; attempt < 12; attempt++) {
    const scale = (lower + upper) / 2;
    apply(scale);
    if (target.scrollWidth > target.clientWidth) upper = scale;
    else lower = scale;
  }
  apply(lower * 0.995);
}

function fitDateRows(container: HTMLElement) {
  const rows = [...container.querySelectorAll<HTMLElement>(".event-date-line")];
  rows.forEach((row) => row.style.removeProperty("font-size"));
  if (!window.matchMedia?.("(max-width: 600px)").matches || !rows.length) return;
  let size = Math.min(...rows.map((row) => parseFloat(getComputedStyle(row).fontSize)));
  for (let attempt = 0; attempt < 4; attempt++) {
    const scale = Math.min(1, ...rows.map((row) => row.clientWidth > 0 ? row.clientWidth / row.scrollWidth : 1));
    if (scale >= 1) break;
    size = Math.max(1, size * scale - 0.2);
    rows.forEach((row) => { row.style.fontSize = `${size}px`; });
  }
}

export default function useFittedText(ref: RefObject<HTMLElement | null>, content: unknown, selector?: string) {
  useLayoutEffect(() => {
    const container = ref.current;
    const target = selector ? container?.querySelector<HTMLElement>(selector) : container;
    if (!container || !target) return;
    function fit() {
      if (!container || !target) return;
      if (selector === ".event-date-line") fitDateRows(container);
      else if (selector === "h2" && container.querySelector(":scope > .badge, :scope > .event-badges .badge")) {
        fitModalTitle(container, target);
      } else fitTextToWidth(target);
    }
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(fit);
    observer?.observe(container);
    if (target !== container) observer?.observe(target);
    const frame = requestAnimationFrame(fit);
    window.addEventListener("resize", fit);
    let active = true;
    void document.fonts?.ready.then(() => { if (active) fit(); });
    fit();
    return () => {
      active = false;
      observer?.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", fit);
    };
  }, [ref, content, selector]);
}
