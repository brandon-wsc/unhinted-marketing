import { CheckIcon, ChevronDown, Moon, Sun, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { FormField } from "@/components/form-field";
import { IconButton } from "@/components/icon-button";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
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
import { Input } from "@/components/ui/input";
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
  const [renameOpen, setRenameOpen] = useState(false);

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

  const openRename = () => setRenameOpen(true);

  if (isMobile) {
    return (
      <>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>{trigger}</DialogTrigger>
          <DialogContent
            showCloseButton={false}
            aria-describedby={undefined}
            className="max-w-xs gap-1 p-3"
          >
            <DialogTitle className="sr-only">{triggerLabel}</DialogTitle>
            <UserMenuBody
              surface="dialog"
              close={() => setDialogOpen(false)}
              onRename={openRename}
            />
          </DialogContent>
        </Dialog>
        <RenameDialog open={renameOpen} onOpenChange={setRenameOpen} />
      </>
    );
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <UserMenuBody surface="dropdown" close={() => undefined} onRename={openRename} />
        </DropdownMenuContent>
      </DropdownMenu>
      <RenameDialog open={renameOpen} onOpenChange={setRenameOpen} />
    </>
  );
}

type Surface = "dropdown" | "dialog";

function UserMenuBody({
  surface,
  close,
  onRename,
}: {
  surface: Surface;
  close: () => void;
  onRename: () => void;
}) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const admin = !!user && isAdmin(user.platform_level);

  const Sep = surface === "dropdown" ? DropdownMenuSeparator : DialogSeparator;
  const Item = surface === "dropdown" ? DropdownAction : DialogAction;

  return (
    <>
      <UserIdentityBlock surface={surface} />
      {user && (
        <>
          <Sep />
          <Item
            onSelect={() => {
              close();
              onRename();
            }}
          >
            {t("header.menu.rename")}
          </Item>
        </>
      )}
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
              navigate("/system");
            }}
          >
            {t("system.menuEntry")}
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

function RenameDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const { user, updateDisplayName } = useAuth();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setName(user?.display_name ?? "");
      setError(null);
    }
  }, [open, user]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t("errors.displayNameRequired"));
      return;
    }
    setSaving(true);
    try {
      await updateDisplayName(trimmed);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined} className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("header.rename.title")}</DialogTitle>
        </DialogHeader>
        <form noValidate onSubmit={(e) => void submit(e)} className="space-y-5">
          <FormField
            id="rename-display-name"
            label={t("auth.register.displayName")}
            required
            error={error}
          >
            <Input
              id="rename-display-name"
              value={name}
              required
              maxLength={120}
              autoFocus
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "rename-display-name-error" : undefined}
              onChange={(e) => {
                setName(e.target.value);
                if (error) setError(null);
              }}
            />
          </FormField>
          <DialogFooter>
            <Button type="submit" disabled={saving}>
              {saving ? t("header.rename.saving") : t("header.rename.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
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
