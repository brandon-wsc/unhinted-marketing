import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Transient "saved / copied" notice state: `set(v)` shows the value and
 * auto-clears after `ms`; `set(null)` clears now and cancels the timer.
 * Pass `autoClear: false` for a value that should persist (e.g. errors).
 */
export function useFlash<T>(
  ms = 2500,
): [value: T | null, set: (v: T | null, autoClear?: boolean) => void] {
  const [value, setValue] = useState<T | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const set = useCallback(
    (v: T | null, autoClear = v !== null) => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      setValue(v);
      if (autoClear && v !== null) {
        timerRef.current = setTimeout(() => setValue(null), ms);
      }
    },
    [ms],
  );

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  return [value, set];
}
