import type { ReactNode } from "react";
import { AppShell } from "@/components/app-header";
import { Card, CardContent } from "@/components/ui/card";

type AuthLayoutProps = {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
};

export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  return (
    <AppShell mainClassName="flex items-center justify-center overflow-y-auto p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{subtitle}</p>
        </div>

        <Card
          className="gap-0 py-6 shadow-xl"
          style={{ boxShadow: `0 20px 40px var(--shadow-color)` }}
        >
          <CardContent>{children}</CardContent>
        </Card>

        {footer && <div className="mt-6 text-center text-sm text-muted-foreground">{footer}</div>}
      </div>
    </AppShell>
  );
}
