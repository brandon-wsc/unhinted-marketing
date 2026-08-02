import { Link, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AppShell } from "@/components/app-header";
import { useAuth } from "@/context/auth-context";
import { LlmCallRecords } from "@/features/admin/components/llm-call-records";
import { isAdmin } from "@/lib/platform-level";

export function AdminPage() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <p className="text-[var(--color-muted)]">{t("common.loading")}</p>
      </AppShell>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  if (!isAdmin(user.platform_level)) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <div className="text-center">
          <h1 className="text-lg font-semibold text-[var(--color-foreground)]">
            {t("admin.forbidden.title")}
          </h1>
          <p className="mt-1 text-sm text-[var(--color-muted)]">{t("admin.forbidden.body")}</p>
          <Link
            to="/"
            className="mt-4 inline-block rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-white transition hover:opacity-90"
          >
            {t("admin.forbidden.back")}
          </Link>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell mainClassName="overflow-y-auto">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <h1 className="mb-4 text-lg font-semibold text-[var(--color-foreground)]">
          {t("admin.llmCalls")}
        </h1>
        <LlmCallRecords />
      </div>
    </AppShell>
  );
}
