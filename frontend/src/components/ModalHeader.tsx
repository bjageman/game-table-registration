import { useLayoutEffect, useRef, type ReactNode } from "react";

export default function ModalHeader({ children, className = "" }: {
  children: ReactNode;
  className?: string;
}) {
  const header = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const container = header.current;
    const heading = container?.querySelector("h2");
    if (!container || !heading) return;
    function fit() {
      if (!heading) return;
      heading.style.removeProperty("font-size");
      if (heading.clientWidth <= 0 || heading.scrollWidth <= heading.clientWidth) return;
      const size = parseFloat(getComputedStyle(heading).fontSize);
      heading.style.fontSize = `${Math.max(1, size * heading.clientWidth / heading.scrollWidth - 0.2)}px`;
    }
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(fit);
    observer?.observe(container);
    observer?.observe(heading);
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
  }, [children]);
  return <div ref={header} className={`event-modal-header ${className}`.trim()}>{children}</div>;
}
