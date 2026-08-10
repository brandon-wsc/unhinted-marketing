import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { AppShell } from "@/components/app-header";
import { useAuth } from "@/context/auth-context";
import { ProductsPanel } from "@/features/company-settings/components/products-panel";
import { VoiceForm } from "@/features/company-settings/components/voice-form";
import { cn } from "@/lib/utils";

type SettingsTab = "voice" | "products";

function parseTab(raw: string | null): SettingsTab {
  if (raw === "products") return raw;
  return "voice";
}

function parseScope(raw: string | null): "org" | "mine" {
  return raw === "mine" ? "mine" : "org";
}

/** Approvals (K6) stays out of nav until promote UX ships. */
const NAV: SettingsTab[] = ["voice", "products"];

export function CompanySettingsPage() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = parseTab(params.get("tab"));
  const scope = parseScope(params.get("scope"));
  const companyId = user?.organizations[0]?.id;

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

  return (
    <AppShell mainClassName="overflow-y-auto">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:flex-row sm:gap-8 sm:px-6">
        <aside className="w-full shrink-0 sm:w-56">
          <p className="mb-3 px-3 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("settings.navLabel")}
          </p>
          <nav className="flex gap-1 sm:flex-col" aria-label={t("settings.title")}>
            {NAV.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={cn(
                  "rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                  tab === id
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
          {tab === "voice" && <VoiceForm companyId={companyId} />}
          {tab === "products" && (
            <ProductsPanel
              companyId={companyId}
              scope={scope}
              onScopeChange={(next) => setTab("products", next)}
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
