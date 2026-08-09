import { useEffect, useState } from "react";

/** Track a CSS media query. jsdom lacks matchMedia — falls back to false. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    if (!window.matchMedia) return;
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** Below the sm breakpoint — paged layouts, dialog-style menus. */
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 639px)");
}
