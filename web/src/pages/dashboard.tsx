import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AppShell } from "@/components/app-header";
import { useAuth } from "@/context/auth-context";

export function DashboardPage() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <AppShell mainClassName="flex items-center justify-center">
        <p className="text-[var(--color-muted)]">{t("common.loading")}</p>
      </AppShell>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  const org = user.organizations[0];

  return (
    <AppShell mainClassName="mx-auto max-w-5xl px-4 py-12 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">{t("dashboard.title")}</h1>
      <p className="mt-2 max-w-xl text-[var(--color-muted)]">{t("dashboard.description")}</p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5">
          <p className="text-xs uppercase tracking-wider text-[var(--color-muted)]">
            {t("dashboard.workspace")}
          </p>
          <p className="mt-2 font-medium">{org?.name ?? t("common.notAvailable")}</p>
          <p className="text-sm text-[var(--color-muted)]">
            {t("dashboard.role", { role: org?.role ?? t("common.notAvailable") })}
          </p>
        </div>
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5">
          <p className="text-xs uppercase tracking-wider text-[var(--color-muted)]">
            {t("dashboard.account")}
          </p>
          <p className="mt-2 font-medium">{user.email}</p>
          <p className="text-sm text-[var(--color-muted)]">
            {t("dashboard.userId", { id: user.id.slice(0, 8) })}
          </p>
        </div>
      </div>
    </AppShell>
  );
}
