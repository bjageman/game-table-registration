import { useLayoutEffect, useRef } from "react";

/** Fit a table title beside its seat count without wrapping or growing past the base size. */
export default function TableTitle({ children }: { children: string }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    const heading = ref.current;
    if (!heading) return;
    let active = true;
    function fit() {
      if (!active || !heading) return;
      heading.style.fontSize = "";
      const base = parseFloat(getComputedStyle(heading).fontSize);
      if (heading.clientWidth > 0 && heading.scrollWidth > heading.clientWidth) {
        heading.style.fontSize = `${base * heading.clientWidth / heading.scrollWidth}px`;
      }
    }
    fit();
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(fit);
    observer?.observe(heading);
    window.addEventListener("resize", fit);
    void document.fonts?.ready.then(fit);
    return () => { active = false; observer?.disconnect(); window.removeEventListener("resize", fit); };
  }, [children]);
  return <h3 ref={ref}>{children}</h3>;
}
