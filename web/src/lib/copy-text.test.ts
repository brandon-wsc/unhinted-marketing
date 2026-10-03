import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "@/lib/copy-text";

const originalExecCommand = document.execCommand;
const originalClipboard = navigator.clipboard;

function stubClipboard(writeText?: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    value: writeText ? { writeText } : undefined,
    configurable: true,
  });
}

function stubExecCommand(result: boolean) {
  const execCommand = vi.fn().mockReturnValue(result);
  document.execCommand = execCommand as unknown as typeof document.execCommand;
  return execCommand;
}

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(document, "execCommand", {
    value: originalExecCommand,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(navigator, "clipboard", {
    value: originalClipboard,
    configurable: true,
  });
});

describe("copyText", () => {
  it("writes via navigator.clipboard when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    const execCommand = stubExecCommand(true);

    await expect(copyText("hello")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
    expect(execCommand).not.toHaveBeenCalled();
  });

  it("falls back to execCommand when clipboard is unavailable (plain HTTP)", async () => {
    stubClipboard();
    const execCommand = stubExecCommand(true);

    await expect(copyText("hello")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("falls back when writeText rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    stubClipboard(writeText);
    const execCommand = stubExecCommand(true);

    await expect(copyText("hello")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("returns false when execCommand reports failure", async () => {
    stubClipboard();
    stubExecCommand(false);

    await expect(copyText("hello")).resolves.toBe(false);
  });

  it("returns false and cleans up when execCommand throws", async () => {
    stubClipboard();
    document.execCommand = vi.fn(() => {
      throw new Error("not supported");
    }) as unknown as typeof document.execCommand;

    await expect(copyText("hello")).resolves.toBe(false);
    expect(document.querySelector("textarea")).toBeNull();
  });
});
