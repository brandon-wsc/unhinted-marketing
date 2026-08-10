import { CheckIcon, ChevronDown, Moon, Sun, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { IconButton } from "@/components/icon-button";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/context/auth-context";
import { useTheme } from "@/context/theme-context";
import { useIsMobile } from "@/hooks/use-media-query";
import i18n from "@/i18n";
import { LOCALE_LABELS, SUPPORTED_LOCALES, type SupportedLocale } from "@/i18n/locales";
import { isAdmin } from "@/lib/platform-level";
import { cn } from "@/lib/utils";

/**
 * Single user-menu module: same content everywhere, only the surface diverges —
 * DropdownMenu on desktop, Dialog on mobile (thin wrappers at the bottom).
 */
export function UserMenu() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isMobile = useIsMobile();
  const [dialogOpen, setDialogOpen] = useState(false);

  const triggerLabel = user?.display_name ?? t("header.menu.guest");
  const trigger = (
    <Button
      type="button"
      variant="ghost"
      className="gap-2 px-3 font-medium data-[state=open]:bg-accent"
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
        {user ? user.display_name.charAt(0).toUpperCase() : "?"}
      </span>
      <span className="hidden max-w-[8rem] truncate sm:inline">{triggerLabel}</span>
      <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
    </Button>
  );

  if (isMobile) {
    return (
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogTrigger asChild>{trigger}</DialogTrigger>
        <DialogContent
          showCloseButton={false}
          aria-describedby={undefined}
          className="max-w-xs gap-1 p-3"
        >
          <DialogTitle className="sr-only">{triggerLabel}</DialogTitle>
          <UserMenuBody surface="dialog" close={() => setDialogOpen(false)} />
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <UserMenuBody surface="dropdown" close={() => undefined} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

type Surface = "dropdown" | "dialog";

function UserMenuBody({ surface, close }: { surface: Surface; close: () => void }) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const admin = !!user && isAdmin(user.platform_level);

  const Sep = surface === "dropdown" ? DropdownMenuSeparator : DialogSeparator;
  const Item = surface === "dropdown" ? DropdownAction : DialogAction;

  return (
    <>
      <UserIdentityBlock surface={surface} />
      <Sep />
      <LanguageSection surface={surface} />
      <Sep />
      <MenuLabelText surface={surface}>{t("header.menu.theme")}</MenuLabelText>
      <ThemeSwitchRow />
      {user && (
        <>
          <Sep />
          <Item
            onSelect={() => {
              close();
              navigate("/settings");
            }}
          >
            {t("settings.menuEntry")}
          </Item>
        </>
      )}
      {admin && (
        <>
          <Sep />
          <Item
            onSelect={() => {
              close();
              navigate("/admin");
            }}
          >
            {t("admin.menuEntry")}
          </Item>
        </>
      )}
      {user && (
        <>
          <Sep />
          <Item
            destructive
            onSelect={() => {
              close();
              void logout();
            }}
          >
            {t("auth.logout")}
          </Item>
        </>
      )}
    </>
  );
}

function UserIdentityBlock({ surface }: { surface: Surface }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const identity = (
    <div className="min-w-0">
      <p className="truncate text-sm font-semibold">
        {user?.display_name ?? t("header.menu.guest")}
      </p>
      {user?.email && <p className="truncate text-xs text-muted-foreground">{user.email}</p>}
    </div>
  );
  if (surface === "dialog") {
    return (
      <div className="flex items-center justify-between gap-2 px-2 py-1.5">
        {identity}
        <DialogClose asChild>
          <IconButton aria-label={t("header.menu.close")} className="size-8 rounded-full">
            <X />
          </IconButton>
        </DialogClose>
      </div>
    );
  }
  return <div className="px-2 py-1.5">{identity}</div>;
}

function LanguageSection({ surface }: { surface: Surface }) {
  const { t, i18n: i18nInstance } = useTranslation();
  const currentLocale = i18nInstance.language as SupportedLocale;
  const changeLocale = (locale: SupportedLocale) => void i18n.changeLanguage(locale);

  if (surface === "dropdown") {
    return (
      <>
        <DropdownMenuLabel>{t("header.menu.language")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={currentLocale}
          onValueChange={(locale) => changeLocale(locale as SupportedLocale)}
        >
          {SUPPORTED_LOCALES.map((locale) => (
            <DropdownMenuRadioItem key={locale} value={locale}>
              {LOCALE_LABELS[locale]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </>
    );
  }

  return (
    <>
      <MenuLabelText surface="dialog">{t("header.menu.language")}</MenuLabelText>
      {SUPPORTED_LOCALES.map((locale) => (
        <DialogAction key={locale} onSelect={() => changeLocale(locale)}>
          <span>{LOCALE_LABELS[locale]}</span>
          {locale === currentLocale && <CheckIcon className="size-4 shrink-0" />}
        </DialogAction>
      ))}
    </>
  );
}

function ThemeSwitchRow() {
  const { t } = useTranslation();
  const { mode, setMode } = useTheme();
  return (
    <div className="flex items-center justify-between gap-2 px-2 py-1.5">
      <span className="text-sm">
        {t("theme.light")} / {t("theme.dark")}
      </span>
      <span className="flex items-center gap-2">
        <Sun className="size-4 text-foreground" aria-hidden />
        <Switch
          checked={mode === "dark"}
          onCheckedChange={(checked) => setMode(checked ? "dark" : "light")}
          aria-label={t("theme.label")}
        />
        <Moon className="size-4 text-muted-foreground" aria-hidden />
      </span>
    </div>
  );
}

// --- Thin surface adapters (the only place dialog/dropdown diverge) ---

function DialogSeparator() {
  return <div className="my-1 h-px bg-border" aria-hidden />;
}

function MenuLabelText({ surface, children }: { surface: Surface; children: React.ReactNode }) {
  if (surface === "dropdown") {
    return <DropdownMenuLabel>{children}</DropdownMenuLabel>;
  }
  return <p className="px-2 py-1.5 text-xs text-muted-foreground">{children}</p>;
}

function DropdownAction({
  destructive,
  onSelect,
  children,
}: {
  destructive?: boolean;
  onSelect: () => void;
  children: React.ReactNode;
}) {
  return (
    <DropdownMenuItem variant={destructive ? "destructive" : "default"} onSelect={onSelect}>
      {children}
    </DropdownMenuItem>
  );
}

function DialogAction({
  destructive,
  onSelect,
  children,
}: {
  destructive?: boolean;
  onSelect: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground",
        destructive && "text-destructive hover:bg-destructive/10 hover:text-destructive",
      )}
    >
      {children}
    </button>
  );
}
