import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/auth-context";
import { useToast } from "@/context/toast-context";
import { API_BASE } from "@/lib/api-base";
import { apiFetch, apiJson } from "@/lib/api-fetch";

type ConnectedApp = {
  id: string;
  client_id: string;
  client_name: string;
  company_id: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
};

/** ADR 0051 §5 — revocable per-user grants for external MCP clients. */
export function ConnectedAppsPanel() {
  const { t } = useTranslation();
  const { user, accessToken } = useAuth();
  const { showError } = useToast();
  const [apps, setApps] = useState<ConnectedApp[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await apiJson<ConnectedApp[]>(accessToken, `${API_BASE}/auth/me/connected-apps`);
      setApps(body ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [accessToken]);

  useEffect(() => {
    if (accessToken) void load();
  }, [accessToken, load]);

  async function revoke(id: string) {
    if (revokingId) return;
    setRevokingId(id);
    try {
      await apiFetch(accessToken, `${API_BASE}/auth/me/connected-apps/${id}`, {
        method: "DELETE",
      });
      setApps((prev) => prev?.filter((a) => a.id !== id) ?? null);
    } catch (err) {
      showError(err instanceof Error ? err.message : String(err));
    } finally {
      setRevokingId(null);
    }
  }

  function orgName(companyId: string): string {
    return user?.organizations.find((o) => o.id === companyId)?.name ?? "";
  }

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold text-foreground">
        {t("account.connectedApps.title")}
      </h2>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {apps === null && !error && (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      )}
      {apps !== null && apps.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("account.connectedApps.empty")}</p>
      )}
      {apps !== null && apps.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {apps.map((app) => (
            <li key={app.id} className="flex items-start justify-between gap-3 px-4 py-3">
              <div className="min-w-0 space-y-1">
                <p className="truncate text-sm font-medium text-foreground">
                  {app.client_name || app.client_id}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("account.connectedApps.meta", {
                    company: orgName(app.company_id),
                    date: app.created_at.slice(0, 10),
                    lastUsed: app.last_used_at
                      ? app.last_used_at.slice(0, 10)
                      : t("account.connectedApps.neverUsed"),
                  })}
                </p>
                <div className="flex flex-wrap gap-1">
                  {app.scopes.map((scope) => (
                    <Badge key={scope} variant="secondary">
                      {t(`oauth.consent.scope.${scope.replace(":", "_")}`)}
                    </Badge>
                  ))}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                disabled={revokingId !== null}
                onClick={() => void revoke(app.id)}
              >
                {revokingId === app.id
                  ? t("account.connectedApps.revoking")
                  : t("account.connectedApps.revoke")}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
