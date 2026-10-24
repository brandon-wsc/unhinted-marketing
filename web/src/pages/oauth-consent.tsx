import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useSearchParams } from "react-router-dom";
import { AppShell } from "@/components/app-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/context/auth-context";
import { API_BASE } from "@/lib/api-base";
import { apiJson } from "@/lib/api-fetch";

type ConsentDetails = {
  client_id: string;
  client_name: string;
  client_host: string;
  scopes: string[];
  step_up_scopes: string[];
  companies: { id: string; name: string }[];
};

/** ADR 0051 §3 — the user picks one company and approves; redirect goes back
 * to the external app. Approve/deny are plain HTTP, never an LLM path. */
export function OAuthConsentPage() {
  const { t } = useTranslation();
  const { user, accessToken, loading } = useAuth();
  const [params] = useSearchParams();
  const requestId = params.get("request_id") ?? "";
  const [details, setDetails] = useState<ConsentDetails | null>(null);
  const [companyId, setCompanyId] = useState("");
  const [includeImages, setIncludeImages] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<"approve" | "deny" | null>(null);

  useEffect(() => {
    if (!accessToken || !requestId) return;
    let cancelled = false;
    apiJson<ConsentDetails>(
      accessToken,
      `${API_BASE}/oauth/authorize/request?request_id=${encodeURIComponent(requestId)}`,
    )
      .then((res) => {
        if (cancelled) return;
        setDetails(res);
        setCompanyId(res.companies[0]?.id ?? "");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, requestId]);

  if (loading) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <p className="text-muted-foreground">{t("common.loading")}</p>
      </AppShell>
    );
  }
  if (!user) {
    const next = `/oauth/consent?request_id=${encodeURIComponent(requestId)}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  if (!requestId) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <Alert variant="destructive">
          <AlertDescription>{t("oauth.consent.invalidRequest")}</AlertDescription>
        </Alert>
      </AppShell>
    );
  }

  async function decide(approve: boolean) {
    if (submitting) return;
    setSubmitting(approve ? "approve" : "deny");
    setError(null);
    try {
      const extraScopes =
        approve && includeImages ? (["images:generate"] as const) : ([] as const);
      const res = await apiJson<{ redirect: string }>(accessToken, `${API_BASE}/oauth/authorize`, {
        method: "POST",
        json: {
          request_id: requestId,
          company_id: companyId || null,
          approve,
          extra_scopes: [...extraScopes],
        },
      });
      window.location.assign(res.redirect);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(null);
    }
  }

  const asksImages = details?.scopes.includes("images:generate") ?? false;
  const canOptInImages = details?.step_up_scopes.includes("images:generate") ?? false;

  return (
    <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-sm">
        <h1 className="text-lg font-semibold text-foreground">{t("oauth.consent.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("oauth.consent.subtitle", {
            client: details?.client_name || details?.client_host || "",
          })}
        </p>
        {error && (
          <Alert variant="destructive" className="mt-4">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {!details && !error && (
          <p className="mt-4 text-sm text-muted-foreground">{t("common.loading")}</p>
        )}
        {details && (
          <div className="mt-5 space-y-5">
            {/* ADR 0051 §3 — the CIMD host is the app's verifiable identity. */}
            <div className="rounded-lg border border-border bg-secondary px-3 py-2">
              <p className="text-xs text-muted-foreground">{t("oauth.consent.appLabel")}</p>
              <p className="truncate text-sm font-medium text-foreground">
                {details.client_name || details.client_host}
              </p>
              {details.client_name && (
                <p className="truncate text-xs text-muted-foreground">{details.client_host}</p>
              )}
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                {t("oauth.consent.scopesLabel")}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {details.scopes.map((scope) => (
                  <Badge key={scope} variant="secondary">
                    {t(`oauth.consent.scope.${scope.replace(":", "_")}`)}
                  </Badge>
                ))}
              </div>
              {asksImages && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("oauth.consent.imagesNote")}
                </p>
              )}
              {canOptInImages && (
                <label
                  htmlFor="oauth-consent-images"
                  className="mt-3 flex items-start gap-2 text-sm text-foreground"
                >
                  <Checkbox
                    id="oauth-consent-images"
                    className="mt-0.5"
                    checked={includeImages}
                    onCheckedChange={(checked) => setIncludeImages(checked === true)}
                  />
                  <span>
                    <span className="font-medium">{t("oauth.consent.imagesOptIn")}</span>
                    <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
                      {t("oauth.consent.imagesNote")}
                    </span>
                  </span>
                </label>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="oauth-consent-company">{t("oauth.consent.companyLabel")}</Label>
              {details.companies.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("oauth.consent.noCompanies")}</p>
              ) : (
                <Select value={companyId} onValueChange={setCompanyId}>
                  <SelectTrigger id="oauth-consent-company" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {details.companies.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                className="flex-1"
                disabled={submitting !== null || !companyId}
                onClick={() => void decide(true)}
              >
                {submitting === "approve" ? t("oauth.consent.working") : t("oauth.consent.approve")}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={submitting !== null}
                onClick={() => void decide(false)}
              >
                {t("oauth.consent.deny")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
