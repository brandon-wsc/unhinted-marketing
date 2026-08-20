import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { AppShell } from "@/components/app-header";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

type AuthLayoutProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  /** Login / register only — one corner craft pulse. Invite states stay ink. */
  craftSignal?: boolean;
};

export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
  craftSignal = false,
}: AuthLayoutProps) {
  const { t } = useTranslation();
  return (
    <AppShell mainClassName="flex items-center justify-center overflow-y-auto p-4">
      <div className="w-full max-w-md">
        {craftSignal ? (
          <p className="mb-3 flex items-center gap-1.5 text-xs text-voice">
            <span aria-hidden="true">✳</span>
            <span>{t("auth.craftTagline")}</span>
          </p>
        ) : null}
        <Card
          className="gap-4 py-7 shadow-xl"
          style={{ boxShadow: `0 20px 40px var(--shadow-color)` }}
        >
          <CardHeader className="gap-1.5 px-7">
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {subtitle ? <CardDescription>{subtitle}</CardDescription> : null}
          </CardHeader>
          <CardContent className="px-7">{children}</CardContent>
        </Card>

        {footer && <div className="mt-6 text-sm text-muted-foreground">{footer}</div>}
      </div>
    </AppShell>
  );
}
