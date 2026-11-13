import { useLayoutEffect, type RefObject } from "react";

function fitTextToWidth(target: HTMLElement) {
  target.style.removeProperty("font-size");
  if (target.clientWidth <= 0) return;
  for (let attempt = 0; attempt < 4 && target.scrollWidth > target.clientWidth; attempt++) {
    const size = parseFloat(getComputedStyle(target).fontSize);
    target.style.fontSize = `${Math.max(1, size * target.clientWidth / target.scrollWidth - 0.2)}px`;
  }
}

export default function useFittedText(ref: RefObject<HTMLElement | null>, content: unknown, selector?: string) {
  useLayoutEffect(() => {
    const container = ref.current;
    const target = selector ? container?.querySelector<HTMLElement>(selector) : container;
    if (!container || !target) return;
    function fit() {
      if (target) fitTextToWidth(target);
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
