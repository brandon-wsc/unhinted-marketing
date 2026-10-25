export const SUPPORTED_LOCALES = ["zh-HK", "zh-TW", "zh-CN", "en"] as const;

export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = "zh-HK";

/**
 * Menu labels stay in the locale’s own script so the picker is recognisable in any UI language.
 */
export const LOCALE_LABELS: Record<SupportedLocale, string> = {
  "zh-HK": "繁體中文（香港）",
  "zh-TW": "繁體中文（台灣）",
  "zh-CN": "简体中文",
  en: "English",
};
