import { describe, expect, it } from "vitest";
import en from "./en.json";
import zhHK from "./zh-HK.json";

function flattenKeys(value: unknown, prefix = ""): string[] {
  if (value === null || typeof value !== "object") {
    return prefix ? [prefix] : [];
  }
  return Object.entries(value as Record<string, unknown>).flatMap(([key, nested]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (nested !== null && typeof nested === "object" && !Array.isArray(nested)) {
      return flattenKeys(nested, path);
    }
    return [path];
  });
}

describe("i18n locale catalogs", () => {
  it("keeps the same keys across zh-HK and en", () => {
    expect(flattenKeys(en).sort()).toEqual(flattenKeys(zhHK).sort());
  });
});
