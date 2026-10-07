import { useCallback, useEffect, useRef } from "react";

export type PollTick = {
  /** False once polling stopped mid-await — drop stale replies. */
  isActive: () => boolean;
};

export type PollOptions = {
  intervalMs: number;
  /** Optional deadline — stops polling first, then runs `onTimeout`. */
  timeoutMs?: number;
  onTimeout?: () => void;
};

/**
 * setInterval loop for async ticks. `start` replaces any running poll and
 * can take a timeout deadline; `stop` clears both timers, and unmount
 * cleans up automatically. A tick that is still awaiting when `stop` runs
 * can bail out via `isActive()`.
 */
export function usePolling(): {
  start: (tick: (ctx: PollTick) => void | Promise<void>, opts: PollOptions) => void;
  stop: () => void;
} {
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stop = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const start = useCallback(
    (tick: (ctx: PollTick) => void | Promise<void>, opts: PollOptions) => {
      stop();
      if (opts.timeoutMs != null) {
        timeoutRef.current = setTimeout(() => {
          stop();
          opts.onTimeout?.();
        }, opts.timeoutMs);
      }
      pollRef.current = setInterval(() => {
        void tick({ isActive: () => pollRef.current !== null });
      }, opts.intervalMs);
    },
    [stop],
  );

  useEffect(() => stop, [stop]);

  return { start, stop };
}
