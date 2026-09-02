import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { PasswordBox } from "@/components/password-box";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/auth-context";
import {
  apiDisconnectInstagramAccount,
  apiListSocialAccounts,
  apiUpsertInstagramAccount,
  type SocialAccountItem,
} from "@/features/company-settings/api";
import { mapApiError } from "@/lib/map-api-error";

type InstagramPanelProps = {
  companyId: string;
};

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) return false;
  const stamp = new Date(expiresAt);
  return !Number.isNaN(stamp.getTime()) && stamp.getTime() <= Date.now();
}

function toDatetimeLocal(iso: string | null): string {
  if (!iso) return "";
  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())}T${pad(stamp.getHours())}:${pad(stamp.getMinutes())}`;
}

function fromDatetimeLocal(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  const stamp = new Date(value);
  if (Number.isNaN(stamp.getTime())) return null;
  return stamp.toISOString();
}

export function InstagramPanel({ companyId }: InstagramPanelProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [account, setAccount] = useState<SocialAccountItem | null>(null);
  const [igUserId, setIgUserId] = useState("");
  const [token, setToken] = useState("");
  const [expiresLocal, setExpiresLocal] = useState("");
  const [editing, setEditing] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<"saved" | "disconnected" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await apiListSocialAccounts(accessToken, companyId);
      const row = items.find((item) => item.platform === "instagram") ?? null;
      setAccount(row);
      setIgUserId(row?.ig_user_id ?? "");
      setExpiresLocal(toDatetimeLocal(row?.expires_at ?? null));
      setToken("");
      setEditing(!row);
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.instagram.loadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [accessToken, companyId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const expired = isExpired(account?.expires_at ?? null);
  const showForm = !account || editing || expired;

  const expiresLabel = useMemo(() => {
    if (!account?.expires_at) return t("common.notAvailable");
    const stamp = new Date(account.expires_at);
    if (Number.isNaN(stamp.getTime())) return t("common.notAvailable");
    return stamp.toLocaleString();
  }, [account?.expires_at, t]);

  async function onSave() {
    if (!igUserId.trim() || token.trim().length < 8) return;
    setSaving(true);
    setError(null);
    setFlash(null);
    try {
      const row = await apiUpsertInstagramAccount(accessToken, companyId, {
        ig_user_id: igUserId.trim(),
        access_token: token.trim(),
        expires_at: fromDatetimeLocal(expiresLocal),
      });
      setAccount(row);
      setIgUserId(row.ig_user_id);
      setExpiresLocal(toDatetimeLocal(row.expires_at));
      setToken("");
      setEditing(false);
      setFlash("saved");
      window.setTimeout(() => setFlash(null), 2500);
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.instagram.saveFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  async function onDisconnect() {
    setSaving(true);
    setError(null);
    setFlash(null);
    try {
      await apiDisconnectInstagramAccount(accessToken, companyId);
      setAccount(null);
      setIgUserId("");
      setToken("");
      setExpiresLocal("");
      setEditing(true);
      setDisconnectOpen(false);
      setFlash("disconnected");
      window.setTimeout(() => setFlash(null), 2500);
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.instagram.saveFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("settings.instagram.title")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("settings.instagram.subtitle")}</p>
      </div>

      <div className="space-y-5 rounded-xl border border-border bg-card p-6">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {flash === "saved" && (
          <Alert variant="success">
            <AlertDescription>{t("settings.instagram.saved")}</AlertDescription>
          </Alert>
        )}
        {flash === "disconnected" && (
          <Alert variant="success">
            <AlertDescription>{t("settings.instagram.disconnected")}</AlertDescription>
          </Alert>
        )}
        {account && expired && (
          <Alert variant="destructive" className="border-destructive/30 bg-destructive-soft">
            <AlertTitle>{t("settings.instagram.expiredTitle")}</AlertTitle>
            <AlertDescription>{t("settings.instagram.expiredBody")}</AlertDescription>
          </Alert>
        )}

        {account && !editing && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className="border-success/30 bg-success-soft text-success-foreground"
              >
                {t("settings.instagram.connected")}
              </Badge>
              {expired && (
                <Badge variant="destructive">{t("settings.instagram.expiredTitle")}</Badge>
              )}
            </div>
            <dl className="grid gap-2 text-sm sm:grid-cols-[8rem_1fr]">
              <dt className="text-muted-foreground">{t("settings.instagram.igUserId")}</dt>
              <dd className="font-medium text-foreground">{account.ig_user_id}</dd>
              <dt className="text-muted-foreground">{t("settings.instagram.tokenMasked")}</dt>
              <dd className="font-medium text-foreground">••••{account.token_last4}</dd>
              <dt className="text-muted-foreground">{t("settings.instagram.expiresAt")}</dt>
              <dd className="text-foreground">{expiresLabel}</dd>
            </dl>
          </div>
        )}

        {showForm && (
          <div className="space-y-4">
            <FormField id="ig-user-id" label={t("settings.instagram.igUserId")}>
              <Input
                id="ig-user-id"
                value={igUserId}
                onChange={(e) => setIgUserId(e.target.value)}
                autoComplete="off"
              />
            </FormField>
            <PasswordBox
              id="ig-access-token"
              label={t("settings.instagram.accessToken")}
              value={token}
              onChange={setToken}
              autoComplete="off"
            />
            <FormField id="ig-expires" label={t("settings.instagram.expiresAt")}>
              <Input
                id="ig-expires"
                type="datetime-local"
                value={expiresLocal}
                onChange={(e) => setExpiresLocal(e.target.value)}
              />
            </FormField>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2">
          {account && !editing && !expired && (
            <Button type="button" variant="outline" onClick={() => setEditing(true)}>
              {t("settings.instagram.rotate")}
            </Button>
          )}
          {account && (
            <Button
              type="button"
              variant="outline"
              className="border-destructive/40 text-destructive hover:enabled:bg-destructive-soft"
              onClick={() => setDisconnectOpen(true)}
            >
              {t("settings.instagram.disconnect")}
            </Button>
          )}
          {showForm && (
            <Button
              type="button"
              disabled={saving || !igUserId.trim() || token.trim().length < 8}
              onClick={() => void onSave()}
            >
              {saving
                ? t("common.saving")
                : expired
                  ? t("settings.instagram.update")
                  : account
                    ? t("settings.instagram.update")
                    : t("settings.instagram.save")}
            </Button>
          )}
        </div>
      </div>

      <AlertDialog open={disconnectOpen} onOpenChange={setDisconnectOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.instagram.disconnectTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.instagram.disconnectBody")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void onDisconnect()}>
              {t("settings.instagram.disconnect")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
