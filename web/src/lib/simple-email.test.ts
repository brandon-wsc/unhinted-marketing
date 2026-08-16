import { describe, expect, it } from "vitest";
import { emailsMatch, isValidEmail } from "@/lib/simple-email";

describe("isValidEmail", () => {
  it("accepts dotted domains and rejects HTML5-only shapes like a@a", () => {
    expect(isValidEmail("user@example.com")).toBe(true);
    expect(isValidEmail("  User@Example.COM  ")).toBe(true);
    expect(isValidEmail("a@a")).toBe(false);
    expect(isValidEmail("user@localhost")).toBe(false);
    expect(isValidEmail("d")).toBe(false);
    expect(isValidEmail("d@")).toBe(false);
    expect(isValidEmail("@example.com")).toBe(false);
    expect(isValidEmail("a@b@c.com")).toBe(false);
    expect(isValidEmail("a @b.com")).toBe(false);
  });
});

describe("emailsMatch", () => {
  it("compares trimmed case-insensitive emails", () => {
    expect(emailsMatch("Ada@Example.com", " ada@example.com ")).toBe(true);
    expect(emailsMatch("ada@example.com", "other@example.com")).toBe(false);
  });
});
