import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useFlash } from "@/hooks/use-flash";

describe("useFlash", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("shows a value and auto-clears after ms", () => {
    const { result } = renderHook(() => useFlash<"saved">(100));
    act(() => result.current[1]("saved"));
    expect(result.current[0]).toBe("saved");
    act(() => vi.advanceTimersByTime(100));
    expect(result.current[0]).toBeNull();
  });

  it("clears now and cancels the pending timer on set(null)", () => {
    const { result } = renderHook(() => useFlash<"saved">(100));
    act(() => result.current[1]("saved"));
    act(() => result.current[1](null));
    expect(result.current[0]).toBeNull();
    act(() => vi.advanceTimersByTime(200));
    expect(result.current[0]).toBeNull();
  });

  it("stays sticky with autoClear=false (error notices)", () => {
    const { result } = renderHook(() => useFlash<"err">(100));
    act(() => result.current[1]("err", false));
    act(() => vi.advanceTimersByTime(5000));
    expect(result.current[0]).toBe("err");
  });

  it("replaces an older timer when set again", () => {
    const { result } = renderHook(() => useFlash<"a" | "b">(100));
    act(() => result.current[1]("a"));
    act(() => vi.advanceTimersByTime(50));
    act(() => result.current[1]("b"));
    act(() => vi.advanceTimersByTime(99));
    expect(result.current[0]).toBe("b");
    act(() => vi.advanceTimersByTime(1));
    expect(result.current[0]).toBeNull();
  });
});
