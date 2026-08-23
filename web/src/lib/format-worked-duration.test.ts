import { describe, expect, it } from "vitest";
import { formatWorkedDuration, workedDurationLocale } from "@/lib/format-worked-duration";

describe("workedDurationLocale", () => {
  it("treats zh* as zh-HK", () => {
    expect(workedDurationLocale("zh-HK")).toBe("zh-HK");
    expect(workedDurationLocale("zh")).toBe("zh-HK");
    expect(workedDurationLocale("en")).toBe("en");
    expect(workedDurationLocale("en-US")).toBe("en");
  });
});

describe("formatWorkedDuration", () => {
  it("uses seconds under one minute", () => {
    expect(formatWorkedDuration(0, "zh-HK")).toBe("0秒");
    expect(formatWorkedDuration(999, "en")).toBe("0s");
    expect(formatWorkedDuration(41_000, "zh-HK")).toBe("41秒");
    expect(formatWorkedDuration(41_000, "en")).toBe("41s");
    expect(formatWorkedDuration(59_999, "zh-HK")).toBe("59秒");
  });

  it("uses minutes and leftover seconds under one hour", () => {
    expect(formatWorkedDuration(60_000, "zh-HK")).toBe("1分");
    expect(formatWorkedDuration(60_000, "en")).toBe("1m");
    expect(formatWorkedDuration(83_000, "zh-HK")).toBe("1分23秒");
    expect(formatWorkedDuration(83_000, "en")).toBe("1m 23s");
  });

  it("uses hours and leftover minutes", () => {
    expect(formatWorkedDuration(3_600_000, "zh-HK")).toBe("1小時");
    expect(formatWorkedDuration(3_600_000, "en")).toBe("1h");
    expect(formatWorkedDuration(3_723_000, "zh-HK")).toBe("1小時2分");
    expect(formatWorkedDuration(3_723_000, "en")).toBe("1h 2m");
  });
});
