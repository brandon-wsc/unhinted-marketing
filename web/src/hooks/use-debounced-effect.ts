import { type DependencyList, useEffect } from "react";

/** setTimeout debounce as an effect — runs `effect` `delay` ms after the latest deps change. */
export function useDebouncedEffect(effect: () => void, delay: number, deps: DependencyList): void {
  // biome-ignore lint/correctness/useExhaustiveDependencies: deps is the caller's trigger list; effect may be a fresh closure.
  useEffect(() => {
    const handle = setTimeout(effect, delay);
    return () => clearTimeout(handle);
  }, deps);
}
