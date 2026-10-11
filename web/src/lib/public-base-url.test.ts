import { describe, expect, it } from "vitest";
import { looksNonPublicBaseUrl } from "@/lib/public-base-url";

describe("looksNonPublicBaseUrl", () => {
  it("flags private / intranet hosts", () => {
    expect(looksNonPublicBaseUrl("http://localhost:8484")).toBe(true);
    expect(looksNonPublicBaseUrl("https://192.168.1.10:8484")).toBe(true);
    expect(looksNonPublicBaseUrl("http://10.0.0.4")).toBe(true);
    expect(looksNonPublicBaseUrl("https://172.16.0.9")).toBe(true);
    expect(looksNonPublicBaseUrl("https://100.64.0.1")).toBe(true);
    expect(looksNonPublicBaseUrl("https://nas.local")).toBe(true);
    expect(looksNonPublicBaseUrl("https://minio.internal")).toBe(true);
    expect(looksNonPublicBaseUrl("https://files.lan")).toBe(true);
    expect(looksNonPublicBaseUrl("https://nas")).toBe(true);
    expect(looksNonPublicBaseUrl("https://[::1]:8443")).toBe(true);
  });

  it("flags non-TLS public hosts", () => {
    expect(looksNonPublicBaseUrl("http://market.example.com")).toBe(true);
  });

  it("accepts public HTTPS", () => {
    expect(looksNonPublicBaseUrl("https://market.example.com")).toBe(false);
    expect(looksNonPublicBaseUrl("https://8.8.8.8")).toBe(false);
    expect(looksNonPublicBaseUrl("https://x.local.evil.com")).toBe(false);
  });

  it("ignores empty or unparseable input", () => {
    expect(looksNonPublicBaseUrl("")).toBe(false);
    expect(looksNonPublicBaseUrl("   ")).toBe(false);
    expect(looksNonPublicBaseUrl("not a url")).toBe(false);
  });
});
