import { describe, expect, it } from "vitest";
import { classifyRelativeTime, formatAbsoluteDateTime } from "@/lib/format-relative-time";

const NOW = new Date("2026-08-23T12:00:00.000Z");
const TZ = "UTC";

function isoSecondsAgo(seconds: number): string {
  return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

describe("formatAbsoluteDateTime", () => {
  it("formats 24h without seconds", () => {
    expect(formatAbsoluteDateTime("2026-08-23T15:42:59.000Z", TZ)).toBe("2026-08-23 15:42");
  });

  it("returns empty string for invalid input", () => {
    expect(formatAbsoluteDateTime("not-a-date", TZ)).toBe("");
  });
});

describe("classifyRelativeTime", () => {
  it("uses seconds within one minute", () => {
    expect(classifyRelativeTime(isoSecondsAgo(0), NOW, TZ)).toEqual({
      kind: "relative",
      unit: "s",
      n: 0,
    });
    expect(classifyRelativeTime(isoSecondsAgo(59), NOW, TZ)).toEqual({
      kind: "relative",
      unit: "s",
      n: 59,
    });
  });

  it("uses minutes within one hour", () => {
    expect(classifyRelativeTime(isoSecondsAgo(60), NOW, TZ)).toEqual({
      kind: "relative",
      unit: "m",
      n: 1,
    });
    expect(classifyRelativeTime(isoSecondsAgo(59 * 60 + 59), NOW, TZ)).toEqual({
      kind: "relative",
      unit: "m",
      n: 59,
    });
  });

  it("uses hours within one day", () => {
    expect(classifyRelativeTime(isoSecondsAgo(60 * 60), NOW, TZ)).toEqual({
      kind: "relative",
      unit: "h",
      n: 1,
    });
    expect(classifyRelativeTime(isoSecondsAgo(23 * 60 * 60 + 59 * 60), NOW, TZ)).toEqual({
      kind: "relative",
      unit: "h",
      n: 23,
    });
  });

  it("uses days within 30 days", () => {
    expect(classifyRelativeTime(isoSecondsAgo(24 * 60 * 60), NOW, TZ)).toEqual({
      kind: "relative",
      unit: "d",
      n: 1,
    });
    expect(classifyRelativeTime(isoSecondsAgo(29 * 24 * 60 * 60), NOW, TZ)).toEqual({
      kind: "relative",
      unit: "d",
      n: 29,
    });
  });

  it("uses absolute datetime from 30 days onward", () => {
    expect(classifyRelativeTime(isoSecondsAgo(30 * 24 * 60 * 60), NOW, TZ)).toEqual({
      kind: "absolute",
      text: "2026-07-24 12:00",
    });
  });

  it("clamps future timestamps to 0s", () => {
    expect(classifyRelativeTime("2026-08-23T12:00:05.000Z", NOW, TZ)).toEqual({
      kind: "relative",
      unit: "s",
      n: 0,
    });
  });

  it("returns invalid for bad iso", () => {
    expect(classifyRelativeTime("nope", NOW, TZ)).toEqual({ kind: "invalid" });
  });
});
