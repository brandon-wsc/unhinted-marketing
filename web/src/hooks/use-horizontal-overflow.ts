import { type CSSProperties, useCallback, useEffect, useState } from "react";

const FADE_PX = 24;

/**
 * Horizontal overflow state for a scrolling row: which edges have hidden content,
 * an edge-fade mask, chevron scrolling, and keeping the active item in view
 * (on mount, resize, and when the active attribute moves).
 */
export function useHorizontalOverflow<T extends HTMLElement = HTMLDivElement>(
  activeSelector: string,
) {
  const [node, setNode] = useState<T | null>(null);
  const [edges, setEdges] = useState({ start: false, end: false });

  useEffect(() => {
    if (!node) return;
    const sync = () => {
      const { scrollLeft, clientWidth, scrollWidth } = node;
      const start = scrollLeft > 1;
      const end = scrollLeft + clientWidth < scrollWidth - 1;
      setEdges((prev) => (prev.start === start && prev.end === end ? prev : { start, end }));
    };
    const reveal = () => {
      const item = node.querySelector<HTMLElement>(activeSelector);
      if (!item || node.scrollWidth <= node.clientWidth) return;
      const box = node.getBoundingClientRect();
      const rect = item.getBoundingClientRect();
      if (rect.left < box.left + FADE_PX) {
        node.scrollBy?.({ left: rect.left - box.left - FADE_PX });
      } else if (rect.right > box.right - FADE_PX) {
        node.scrollBy?.({ left: rect.right - box.right + FADE_PX });
      }
    };
    const refresh = () => {
      reveal();
      sync();
    };
    refresh();
    node.addEventListener("scroll", sync, { passive: true });
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(refresh);
    resize?.observe(node);
    for (const child of Array.from(node.children)) resize?.observe(child);
    const mutation = new MutationObserver(refresh);
    mutation.observe(node, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["data-state", "aria-current"],
    });
    return () => {
      node.removeEventListener("scroll", sync);
      resize?.disconnect();
      mutation.disconnect();
    };
  }, [node, activeSelector]);

  const scroll = useCallback(
    (dir: -1 | 1) => node?.scrollBy({ left: dir * node.clientWidth * 0.6, behavior: "smooth" }),
    [node],
  );

  const overflowing = edges.start || edges.end;
  const fadeStyle: CSSProperties | undefined = overflowing
    ? {
        maskImage: `linear-gradient(to right, transparent 0, #000 ${edges.start ? FADE_PX : 0}px, #000 calc(100% - ${edges.end ? FADE_PX : 0}px), transparent 100%)`,
      }
    : undefined;

  return { ref: setNode, ...edges, overflowing, scroll, fadeStyle };
}

export type HorizontalOverflow = ReturnType<typeof useHorizontalOverflow>;
