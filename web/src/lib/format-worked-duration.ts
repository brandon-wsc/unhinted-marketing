export type WorkedDurationLocale = "en" | "zh-HK";

const SECOND_MS = 1000;
const MINUTE_MS = 60 * SECOND_MS;
const HOUR_MS = 60 * MINUTE_MS;

export function workedDurationLocale(language: string): WorkedDurationLocale {
  return language.toLowerCase().startsWith("zh") ? "zh-HK" : "en";
}

/** Compact elapsed label for a turn (Codex/Cursor buckets). */
export function formatWorkedDuration(ms: number, locale: WorkedDurationLocale): string {
  const totalSec = Math.max(0, Math.floor(ms / SECOND_MS));
  if (totalSec < 60) {
    return locale === "zh-HK" ? `${totalSec}秒` : `${totalSec}s`;
  }
  const totalMin = Math.floor(ms / MINUTE_MS);
  const sec = totalSec % 60;
  if (totalMin < 60) {
    if (locale === "zh-HK") {
      return sec > 0 ? `${totalMin}分${sec}秒` : `${totalMin}分`;
    }
    return sec > 0 ? `${totalMin}m ${sec}s` : `${totalMin}m`;
  }
  const hours = Math.floor(ms / HOUR_MS);
  const min = totalMin % 60;
  if (locale === "zh-HK") {
    return min > 0 ? `${hours}小時${min}分` : `${hours}小時`;
  }
  return min > 0 ? `${hours}h ${min}m` : `${hours}h`;
}
