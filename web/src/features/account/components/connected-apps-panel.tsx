import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CopyField } from "@/components/copy-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  kind: "oauth" | "pat";
  token_prefix: string | null;
  expires_at: string | null;
};

type MintedToken = { token: string; app: ConnectedApp };

const LIFETIMES = ["never", "30", "90", "365"] as const;

/** ADR 0051 §5 — revocable per-user grants; ADR 0056 adds minted PATs. */
export function ConnectedAppsPanel() {
  const { t } = useTranslation();
  const { user, accessToken } = useAuth();
  const { showError } = useToast();
  const [apps, setApps] = useState<ConnectedApp[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [mintOpen, setMintOpen] = useState(false);
  const [name, setName] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [lifetime, setLifetime] = useState<(typeof LIFETIMES)[number]>("never");
  const [includeImages, setIncludeImages] = useState(false);
  const [minting, setMinting] = useState(false);
  const [mintedToken, setMintedToken] = useState<string | null>(null);

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

  useEffect(() => {
    if (!companyId && user?.organizations.length) {
      setCompanyId(user.organizations[0].id);
    }
  }, [companyId, user]);

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

  async function mint() {
    if (minting || !companyId || !name.trim()) return;
    setMinting(true);
    try {
      const res = await apiFetch(accessToken, `${API_BASE}/auth/me/mcp-tokens`, {
        method: "POST",
        json: {
          name: name.trim(),
          company_id: companyId,
          expires_in_days: lifetime === "never" ? null : Number(lifetime),
          extra_scopes: includeImages ? ["images:generate"] : [],
        },
      });
      const body = (await res.json()) as MintedToken;
      setMintedToken(body.token);
      setApps((prev) => [body.app, ...(prev ?? [])]);
      setName("");
      setIncludeImages(false);
    } catch (err) {
      showError(err instanceof Error ? err.message : String(err));
    } finally {
      setMinting(false);
    }
  }

  function orgName(companyId: string): string {
    return user?.organizations.find((o) => o.id === companyId)?.name ?? "";
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-foreground">
          {t("account.connectedApps.title")}
        </h2>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setMintOpen((open) => !open)}
        >
          {t("account.personalTokens.title")}
        </Button>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {mintOpen && (
        <div className="space-y-4 rounded-lg border border-border bg-card p-4">
          {mintedToken !== null ? (
            <div className="space-y-2">
              <CopyField id="minted-pat" value={mintedToken} className="flex-row" />
              <p className="text-xs text-muted-foreground">
                {t("account.personalTokens.tokenHint")}
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setMintedToken(null);
                  setMintOpen(false);
                }}
              >
                {t("common.close")}
              </Button>
            </div>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="pat-name">{t("account.personalTokens.nameLabel")}</Label>
                <Input
                  id="pat-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t("account.personalTokens.namePlaceholder")}
                  maxLength={200}
                />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="pat-company">{t("oauth.consent.companyLabel")}</Label>
                  <Select value={companyId} onValueChange={setCompanyId}>
                    <SelectTrigger id="pat-company" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(user?.organizations ?? []).map((o) => (
                        <SelectItem key={o.id} value={o.id}>
                          {o.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="pat-lifetime">{t("account.personalTokens.lifetimeLabel")}</Label>
                  <Select
                    value={lifetime}
                    onValueChange={(v) => setLifetime(v as (typeof LIFETIMES)[number])}
                  >
                    <SelectTrigger id="pat-lifetime" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LIFETIMES.map((v) => (
                        <SelectItem key={v} value={v}>
                          {t(`account.personalTokens.lifetime.${v}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <label
                htmlFor="pat-images"
                className="flex items-start gap-2 text-sm text-foreground"
              >
                <Checkbox
                  id="pat-images"
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
              <Button
                type="button"
                disabled={minting || !companyId || !name.trim()}
                onClick={() => void mint()}
              >
                {minting
                  ? t("account.personalTokens.creating")
                  : t("account.personalTokens.create")}
              </Button>
            </>
          )}
        </div>
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
                <p className="flex items-center gap-2 truncate text-sm font-medium text-foreground">
                  <span className="truncate">{app.client_name || app.client_id}</span>
                  {app.kind === "pat" && (
                    <Badge variant="secondary">{t("account.personalTokens.patBadge")}</Badge>
                  )}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("account.connectedApps.meta", {
                    company: orgName(app.company_id),
                    date: app.created_at.slice(0, 10),
                    lastUsed: app.last_used_at
                      ? app.last_used_at.slice(0, 10)
                      : t("account.connectedApps.neverUsed"),
                  })}
                  {app.kind === "pat" &&
                    ` · ${app.token_prefix}… · ${
                      app.expires_at
                        ? t("account.personalTokens.expiresMeta", {
                            date: app.expires_at.slice(0, 10),
                          })
                        : t("account.personalTokens.neverExpires")
                    }`}
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
