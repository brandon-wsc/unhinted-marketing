import { beforeEach, describe, expect, it } from "vitest";
import {
  getRememberedUser,
  patchRememberedUser,
  rememberFromAuthUser,
  setRememberedUser,
} from "@/lib/remembered-user";

const STORAGE_KEY = "unhinted-remembered-user";

describe("remembered-user", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("get returns null when empty", () => {
    expect(getRememberedUser()).toBeNull();
  });

  it("set then get round-trips", () => {
    setRememberedUser({
      email: "a@b.com",
      displayName: "Ada",
      organizationName: "Acme",
    });
    expect(getRememberedUser()).toEqual({
      email: "a@b.com",
      displayName: "Ada",
      organizationName: "Acme",
    });
  });

  it("returns null for invalid JSON", () => {
    localStorage.setItem(STORAGE_KEY, "{not-json");
    expect(getRememberedUser()).toBeNull();
  });

  it("returns null when email is missing or empty", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ displayName: "Ada" }));
    expect(getRememberedUser()).toBeNull();

    localStorage.setItem(STORAGE_KEY, JSON.stringify({ email: "" }));
    expect(getRememberedUser()).toBeNull();
  });

  it("defaults missing name fields to empty strings", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ email: "a@b.com" }));
    expect(getRememberedUser()).toEqual({
      email: "a@b.com",
      displayName: "",
      organizationName: "",
    });
  });

  it("patch merges onto current or empty baseline", () => {
    patchRememberedUser({ email: "x@y.com", displayName: "X" });
    expect(getRememberedUser()).toEqual({
      email: "x@y.com",
      displayName: "X",
      organizationName: "",
    });

    patchRememberedUser({ organizationName: "Org" });
    expect(getRememberedUser()).toEqual({
      email: "x@y.com",
      displayName: "X",
      organizationName: "Org",
    });
  });

  it("rememberFromAuthUser uses first org name or empty fallback", () => {
    rememberFromAuthUser({
      email: "u@example.com",
      display_name: "User",
      organizations: [{ name: "First Co" }],
    });
    expect(getRememberedUser()).toEqual({
      email: "u@example.com",
      displayName: "User",
      organizationName: "First Co",
    });

    rememberFromAuthUser({
      email: "solo@example.com",
      display_name: "Solo",
      organizations: [],
    });
    expect(getRememberedUser()).toEqual({
      email: "solo@example.com",
      displayName: "Solo",
      organizationName: "",
    });
  });
});
