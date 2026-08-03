import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import {
  LOCALE_LABELS,
  SUPPORTED_LOCALES,
  type SupportedLocale,
} from "@/i18n/locales";
import { useAuth } from "@/context/auth-context";
import { useTheme, type ThemeMode } from "@/context/theme-context";
import { isAdmin } from "@/lib/platform-level";

const THEME_MODES: ThemeMode[] = ["light", "dark", "system"];

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0" aria-hidden="true">
      <path
        fill="currentColor"
        d="M13.2 4.2a.75.75 0 0 1 0 1.06l-5.5 5.5a.75.75 0 0 1-1.06 0l-2.5-2.5a.75.75 0 1 1 1.06-1.06L7 9.09l4.97-4.97a.75.75 0 0 1 1.23.1Z"
      />
    </svg>
  );
}

function MenuSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="py-1">
      <p className="px-3 py-1.5 text-xs font-medium text-[var(--color-muted)]">{label}</p>
      <div className="px-1">{children}</div>
    </div>
  );
}

function MenuItem({
  active,
  onClick,
  children,
}: {
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={active}
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm transition ${
        active
          ? "bg-[var(--color-primary)]/10 text-[var(--color-foreground)]"
          : "text-[var(--color-foreground)] hover:bg-[var(--color-hover)]"
      }`}
    >
      <span className={`w-4 ${active ? "opacity-100" : "opacity-0"}`}>
        <CheckIcon />
      </span>
      <span className="truncate">{children}</span>
    </button>
  );
}

export function UserMenuDropdown() {
  const { t, i18n: i18nInstance } = useTranslation();
  const { user, logout } = useAuth();
  const { mode, setMode } = useTheme();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const currentLocale = i18nInstance.language as SupportedLocale;
  const triggerLabel = user?.display_name ?? t("header.menu.guest");

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  async function onLogout() {
    setOpen(false);
    await logout();
  }

  function onOpenAdmin() {
    setOpen(false);
    navigate("/admin");
  }

  function onLocaleChange(locale: SupportedLocale) {
    void i18n.changeLanguage(locale);
    setOpen(false);
  }

  function onThemeChange(next: ThemeMode) {
    setMode(next);
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-2 text-sm font-medium transition hover:bg-[var(--color-hover)]"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--color-primary)] text-xs font-semibold text-white">
          {user ? user.display_name.charAt(0).toUpperCase() : "?"}
        </span>
        <span className="hidden sm:inline max-w-[8rem] truncate">{triggerLabel}</span>
        <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0 text-[var(--color-muted)]" aria-hidden="true">
          <path fill="currentColor" d="M4.5 6 8 9.5 11.5 6h-7Z" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-2 w-56 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] py-1 shadow-lg"
          style={{ boxShadow: `0 12px 32px var(--shadow-color)` }}
        >
          <MenuSection label={t("header.menu.language")}>
            {SUPPORTED_LOCALES.map((locale) => (
              <MenuItem
                key={locale}
                active={currentLocale === locale}
                onClick={() => onLocaleChange(locale)}
              >
                {LOCALE_LABELS[locale]}
              </MenuItem>
            ))}
          </MenuSection>

          <div className="my-1 border-t border-[var(--color-border)]" />

          <MenuSection label={t("header.menu.theme")}>
            {THEME_MODES.map((item) => (
              <MenuItem key={item} active={mode === item} onClick={() => onThemeChange(item)}>
                {t(`theme.${item}`)}
              </MenuItem>
            ))}
          </MenuSection>

          {user && isAdmin(user.platform_level) && (
            <>
              <div className="my-1 border-t border-[var(--color-border)]" />
              <div className="px-1 py-1">
                <button
                  type="button"
                  role="menuitem"
                  onClick={onOpenAdmin}
                  className="flex w-full items-center rounded-md px-3 py-2 text-sm text-[var(--color-foreground)] transition hover:bg-[var(--color-hover)]"
                >
                  {t("admin.menuEntry")}
                </button>
              </div>
            </>
          )}

          {user && (
            <>
              <div className="my-1 border-t border-[var(--color-border)]" />
              <div className="px-1 py-1">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => void onLogout()}
                  className="flex w-full items-center rounded-md px-3 py-2 text-sm text-[var(--color-destructive-text)] transition hover:bg-[var(--color-destructive-soft)]"
                >
                  {t("auth.logout")}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
