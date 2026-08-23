export type RelativeTimeUnit = "s" | "m" | "h" | "d";

export type RelativeTimeResult =
  | { kind: "relative"; unit: RelativeTimeUnit; n: number }
  | { kind: "absolute"; text: string }
  | { kind: "invalid" };

const SECOND_MS = 1000;
const MINUTE_MS = 60 * SECOND_MS;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const MONTH_MS = 30 * DAY_MS;

export function formatAbsoluteDateTime(iso: string, timeZone?: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const value = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${value("year")}-${value("month")}-${value("day")} ${value("hour")}:${value("minute")}`;
}

export function classifyRelativeTime(
  iso: string,
  now: Date,
  timeZone?: string,
): RelativeTimeResult {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return { kind: "invalid" };
  const delta = Math.max(0, now.getTime() - then.getTime());
  if (delta < MINUTE_MS) {
    return { kind: "relative", unit: "s", n: Math.floor(delta / SECOND_MS) };
  }
  if (delta < HOUR_MS) {
    return { kind: "relative", unit: "m", n: Math.floor(delta / MINUTE_MS) };
  }
  if (delta < DAY_MS) {
    return { kind: "relative", unit: "h", n: Math.floor(delta / HOUR_MS) };
  }
  if (delta < MONTH_MS) {
    return { kind: "relative", unit: "d", n: Math.floor(delta / DAY_MS) };
  }
  return { kind: "absolute", text: formatAbsoluteDateTime(iso, timeZone) };
}
