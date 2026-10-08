import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAsyncData } from "@/hooks/use-async-data";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useAsyncData", () => {
  it("applies a resolved load", async () => {
    const apply = vi.fn();
    const { result } = renderHook(() => useAsyncData(async () => "data", apply, []));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(apply).toHaveBeenCalledWith("data");
    expect(result.current.error).toBeNull();
  });

  it("drops a stale result when deps change mid-flight", async () => {
    const first = deferred<string>();
    const apply = vi.fn();
    const { result, rerender } = renderHook(
      ({ dep }) =>
        useAsyncData(() => (dep === 1 ? first.promise : Promise.resolve("next")), apply, [dep]),
      { initialProps: { dep: 1 } },
    );
    rerender({ dep: 2 });
    await waitFor(() => expect(result.current.loading).toBe(false));
    first.resolve("stale");
    await Promise.resolve();
    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply).toHaveBeenCalledWith("next");
  });

  it("does not apply an in-flight result after unmount", async () => {
    const d = deferred<string>();
    const apply = vi.fn();
    const { unmount } = renderHook(() => useAsyncData(() => d.promise, apply, []));
    unmount();
    d.resolve("late");
    await Promise.resolve();
    expect(apply).not.toHaveBeenCalled();
  });

  it("does not apply an in-flight rejection after unmount", async () => {
    const d = deferred<string>();
    const onError = vi.fn();
    const { unmount } = renderHook(() => useAsyncData(() => d.promise, vi.fn(), [], { onError }));
    unmount();
    d.reject(new Error("late"));
    await Promise.resolve();
    expect(onError).not.toHaveBeenCalled();
  });
});
