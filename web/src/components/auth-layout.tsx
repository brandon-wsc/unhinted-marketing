import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { AppLogo } from "@/components/app-logo";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type AuthLayoutProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  /** Extra classes on the footer wrapper (e.g. text-center). */
  footerClassName?: string;
  /** Rendered at the top of the card, above the title (e.g. setup stepper). */
  headerSlot?: ReactNode;
  /** Login / register / setup — one corner craft pulse. Invite states stay ink. */
  craftSignal?: boolean;
};

export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
  footerClassName,
  headerSlot,
  craftSignal = false,
}: AuthLayoutProps) {
  const { t } = useTranslation();
  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-y-auto p-4">
      <div className="w-full max-w-sm">
        <div className="mb-5 flex justify-center">
          <AppLogo />
        </div>
        <Card
          className="gap-4 py-7 shadow-xl"
          style={{ boxShadow: `0 20px 40px var(--shadow-color)` }}
        >
          {headerSlot ? <div className="px-7">{headerSlot}</div> : null}
          <CardHeader className="gap-1.5 px-7">
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {subtitle ? <CardDescription>{subtitle}</CardDescription> : null}
          </CardHeader>
          <CardContent className="px-7">{children}</CardContent>
        </Card>

        {footer && (
          <div className={cn("mt-6 text-center text-sm text-muted-foreground", footerClassName)}>
            {footer}
          </div>
        )}
      </div>

      {craftSignal ? (
        <div className="pointer-events-none fixed right-6 bottom-6 hidden flex-col items-end gap-1 text-xs sm:flex">
          <span aria-hidden="true" className="text-base leading-none text-voice">
            ✳
          </span>
          <span className="text-muted-foreground">{t("auth.craftCorner")}</span>
        </div>
      ) : null}
    </div>
  );
}
