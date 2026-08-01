import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getRememberedSessionId,
  rememberedSessionKey,
  setRememberedSessionId,
} from "@/features/session/session-storage";

describe("session-storage", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("builds key as unhinted-session:{companyId}", () => {
    expect(rememberedSessionKey("co-1")).toBe("unhinted-session:co-1");
  });

  it("get/set/clear session id for a company", () => {
    expect(getRememberedSessionId("co-1")).toBeNull();

    setRememberedSessionId("co-1", "sess-abc");
    expect(getRememberedSessionId("co-1")).toBe("sess-abc");
    expect(localStorage.getItem("unhinted-session:co-1")).toBe("sess-abc");

    setRememberedSessionId("co-1", null);
    expect(getRememberedSessionId("co-1")).toBeNull();
    expect(localStorage.getItem("unhinted-session:co-1")).toBeNull();
  });

  it("no-ops when companyId is missing", () => {
    setRememberedSessionId(undefined, "sess-abc");
    expect(localStorage.length).toBe(0);
    expect(getRememberedSessionId(undefined)).toBeNull();
  });

  it("swallows localStorage errors on get and set", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(getRememberedSessionId("co-1")).toBeNull();

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => setRememberedSessionId("co-1", "sess-abc")).not.toThrow();
  });
});
