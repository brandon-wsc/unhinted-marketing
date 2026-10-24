import { describe, expect, it } from "vitest";
import en from "./en.json";
import zhCN from "./zh-CN.json";
import zhHK from "./zh-HK.json";
import zhTW from "./zh-TW.json";

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
  it("keeps the same keys across all supported locales", () => {
    const base = flattenKeys(zhHK).sort();
    for (const catalog of [zhTW, zhCN, en]) {
      expect(flattenKeys(catalog).sort()).toEqual(base);
    }
  });
});
