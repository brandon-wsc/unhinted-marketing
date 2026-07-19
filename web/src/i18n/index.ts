import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { DEFAULT_LOCALE, SUPPORTED_LOCALES } from "@/i18n/locales";
import en from "@/i18n/locales/en.json";
import zhHK from "@/i18n/locales/zh-HK.json";

const STORAGE_KEY = "unhinted-locale";

function resolveInitialLocale(): string {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && SUPPORTED_LOCALES.includes(stored as (typeof SUPPORTED_LOCALES)[number])) {
    return stored;
  }
  return DEFAULT_LOCALE;
}

void i18n.use(initReactI18next).init({
  resources: {
    "zh-HK": { translation: zhHK },
    en: { translation: en },
  },
  lng: resolveInitialLocale(),
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: [...SUPPORTED_LOCALES],
  interpolation: {
    escapeValue: false,
  },
});

i18n.on("languageChanged", (lng) => {
  localStorage.setItem(STORAGE_KEY, lng);
  document.documentElement.lang = lng;
});

document.documentElement.lang = i18n.language;

export default i18n;
