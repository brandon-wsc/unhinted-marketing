import { describe, expect, it } from "vitest";
import { inviteTokenFromPath } from "@/lib/invite-path";

describe("inviteTokenFromPath", () => {
  it("reads the token from an invite next path", () => {
    expect(inviteTokenFromPath("/invite/abc-123")).toBe("abc-123");
  });

  it("returns null for other paths", () => {
    expect(inviteTokenFromPath("/login")).toBeNull();
    expect(inviteTokenFromPath(null)).toBeNull();
  });
});
