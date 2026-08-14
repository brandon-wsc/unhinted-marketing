import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { AppShell } from "@/components/app-header";
import { useAuth } from "@/context/auth-context";
import { ApprovalsPanel } from "@/features/company-settings/components/approvals-panel";
import { MembersPanel } from "@/features/company-settings/components/members-panel";
import { ProductsPanel } from "@/features/company-settings/components/products-panel";
import { VoiceForm } from "@/features/company-settings/components/voice-form";
import { cn } from "@/lib/utils";

type SettingsTab = "voice" | "products" | "members" | "approvals";

function parseTab(raw: string | null): SettingsTab {
  if (raw === "products" || raw === "members" || raw === "approvals") return raw;
  return "voice";
}

function parseScope(raw: string | null): "org" | "mine" {
  return raw === "mine" ? "mine" : "org";
}

function canManageTeam(role: string | undefined): boolean {
  return role === "owner" || role === "admin";
}

export function CompanySettingsPage() {
  const { t } = useTranslation();
  const { user, loading, refreshAccessToken } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = parseTab(params.get("tab"));
  const scope = parseScope(params.get("scope"));
  const org = user?.organizations[0];
  const companyId = org?.id;

  const setTab = useMemo(
    () => (next: SettingsTab, nextScope?: "org" | "mine") => {
      const nextParams = new URLSearchParams(params);
      nextParams.set("tab", next);
      if (next === "products") {
        nextParams.set("scope", nextScope ?? scope);
      } else {
        nextParams.delete("scope");
      }
      setParams(nextParams, { replace: true });
    },
    [params, scope, setParams],
  );

  if (loading) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <p className="text-muted-foreground">{t("common.loading")}</p>
      </AppShell>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  if (!companyId) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <div className="text-center">
          <h1 className="text-lg font-semibold text-foreground">{t("settings.noCompany.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("settings.noCompany.body")}</p>
          <Link
            to="/"
            className="mt-4 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90"
          >
            {t("settings.noCompany.back")}
          </Link>
        </div>
      </AppShell>
    );
  }

  const editor = canManageTeam(org?.role);
  const nav: SettingsTab[] = editor
    ? ["voice", "products", "members", "approvals"]
    : ["voice", "products", "members"];
  const activeTab = tab === "approvals" && !editor ? "voice" : tab;

  return (
    <AppShell mainClassName="overflow-y-auto">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:flex-row sm:gap-8 sm:px-6">
        <aside className="w-full shrink-0 sm:w-56">
          <p className="mb-3 px-3 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("settings.navLabel")}
          </p>
          <nav className="flex gap-1 sm:flex-col" aria-label={t("settings.title")}>
            {nav.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={cn(
                  "rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                  activeTab === id
                    ? "bg-accent font-medium text-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )}
              >
                {t(`settings.nav.${id}`)}
              </button>
            ))}
          </nav>
        </aside>

        <div className="min-w-0 flex-1">
          {activeTab === "voice" && <VoiceForm companyId={companyId} />}
          {activeTab === "products" && (
            <ProductsPanel
              companyId={companyId}
              scope={scope}
              onScopeChange={(next) => setTab("products", next)}
            />
          )}
          {activeTab === "members" && (
            <MembersPanel
              companyId={companyId}
              companyName={org?.name ?? ""}
              canManageTeam={editor}
              onCompanyRenamed={refreshAccessToken}
            />
          )}
          {activeTab === "approvals" && <ApprovalsPanel companyId={companyId} />}
        </div>
      </div>
    </AppShell>
  );
}
