import type { ReactNode } from "react";
import { AppShell } from "@/components/app-header";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

type AuthLayoutProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
};

export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  return (
    <AppShell mainClassName="flex items-center justify-center overflow-y-auto p-4">
      <div className="w-full max-w-md">
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
