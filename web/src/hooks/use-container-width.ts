import { useLayoutEffect, useRef, useState } from "react";

/**
 * Observe an element's content width (ResizeObserver).
 * Initial width uses window.innerWidth as a full-bleed shell guess, then
 * corrects to the real container on the first layout pass.
 */
export function useContainerWidth<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(() => (typeof window !== "undefined" ? window.innerWidth : 0));

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    const update = () => {
      setWidth(el.getBoundingClientRect().width);
    };
    update();

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setWidth(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}
