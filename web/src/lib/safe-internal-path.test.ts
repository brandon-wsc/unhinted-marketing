import { describe, expect, it } from "vitest";
import { safeInternalPath } from "@/lib/safe-internal-path";

describe("safeInternalPath", () => {
  it("allows invite and settings paths", () => {
    expect(safeInternalPath("/invite/abc")).toBe("/invite/abc");
    expect(safeInternalPath("/settings?tab=members")).toBe("/settings?tab=members");
  });

  it("rejects open redirects", () => {
    expect(safeInternalPath("https://evil.example")).toBeNull();
    expect(safeInternalPath("//evil.example")).toBeNull();
    expect(safeInternalPath("/\\evil.example")).toBeNull();
    expect(safeInternalPath("invite/abc")).toBeNull();
    expect(safeInternalPath("")).toBeNull();
    expect(safeInternalPath(null)).toBeNull();
  });
});
