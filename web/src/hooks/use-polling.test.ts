import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePolling } from "@/hooks/use-polling";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("usePolling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("ticks on the interval until stop", () => {
    const { result } = renderHook(() => usePolling());
    const tick = vi.fn();
    act(() => result.current.start(tick, { intervalMs: 100 }));
    act(() => vi.advanceTimersByTime(250));
    expect(tick).toHaveBeenCalledTimes(2);
    act(() => result.current.stop());
    act(() => vi.advanceTimersByTime(300));
    expect(tick).toHaveBeenCalledTimes(2);
  });

  it("start replaces a running poll", () => {
    const { result } = renderHook(() => usePolling());
    const first = vi.fn();
    const second = vi.fn();
    act(() => result.current.start(first, { intervalMs: 100 }));
    act(() => result.current.start(second, { intervalMs: 100 }));
    act(() => vi.advanceTimersByTime(100));
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("marks a tick inactive once stop ran mid-await", async () => {
    const { result } = renderHook(() => usePolling());
    const d = deferred<void>();
    const seen: boolean[] = [];
    act(() =>
      result.current.start(
        async ({ isActive }) => {
          await d.promise;
          seen.push(isActive());
        },
        { intervalMs: 100 },
      ),
    );
    act(() => vi.advanceTimersByTime(100));
    act(() => result.current.stop());
    await act(async () => d.resolve());
    expect(seen).toEqual([false]);
  });

  it("stops the poll then fires onTimeout at the deadline", () => {
    const { result } = renderHook(() => usePolling());
    const tick = vi.fn();
    const onTimeout = vi.fn();
    act(() => result.current.start(tick, { intervalMs: 100, timeoutMs: 300, onTimeout }));
    act(() => vi.advanceTimersByTime(200));
    expect(tick).toHaveBeenCalledTimes(2);
    act(() => vi.advanceTimersByTime(100));
    expect(onTimeout).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(500));
    expect(tick).toHaveBeenCalledTimes(2); // interval stopped too
  });

  it("clears timers on unmount", () => {
    const { result, unmount } = renderHook(() => usePolling());
    const tick = vi.fn();
    const onTimeout = vi.fn();
    act(() => result.current.start(tick, { intervalMs: 100, timeoutMs: 300, onTimeout }));
    unmount();
    act(() => vi.advanceTimersByTime(1000));
    expect(tick).not.toHaveBeenCalled();
    expect(onTimeout).not.toHaveBeenCalled();
  });
});
