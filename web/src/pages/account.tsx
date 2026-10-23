import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import { AppShell } from "@/components/app-header";
import { useAuth } from "@/context/auth-context";
import { ConnectAppCard } from "@/features/account/components/connect-app-card";
import { ConnectedAppsPanel } from "@/features/account/components/connected-apps-panel";
import { ProfilePanel } from "@/features/account/components/profile-panel";

export function AccountPage() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <p className="text-muted-foreground">{t("common.loading")}</p>
      </AppShell>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  return (
    <AppShell mainClassName="overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
        <h1 className="text-lg font-semibold text-foreground">{t("account.title")}</h1>
        <ProfilePanel />
        <ConnectAppCard />
        <ConnectedAppsPanel />
      </div>
    </AppShell>
  );
}
