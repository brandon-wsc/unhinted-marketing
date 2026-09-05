import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
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
import { useAuth } from "@/context/auth-context";
import {
  apiCancelInstagramOAuth,
  apiDisconnectInstagramAccount,
  apiGetInstagramOAuthStatus,
  apiListSocialAccounts,
  apiStartInstagramOAuth,
  type SocialAccountItem,
  type SocialOAuthStatus,
} from "@/features/company-settings/api";
import { mapApiError } from "@/lib/map-api-error";

type InstagramPanelProps = {
  companyId: string;
};

const POLL_INTERVAL_MS = 2500;
export const OAUTH_POLL_TIMEOUT_MS = 10 * 60 * 1000;

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) return false;
  const stamp = new Date(expiresAt);
  return !Number.isNaN(stamp.getTime()) && stamp.getTime() <= Date.now();
}

export function InstagramPanel({ companyId }: InstagramPanelProps) {
  const { t, i18n } = useTranslation();
  const { accessToken } = useAuth();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [account, setAccount] = useState<SocialAccountItem | null>(null);
  const [status, setStatus] = useState<SocialOAuthStatus>("not_connected");
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<"connected" | "disconnected" | null>(null);
  const popupRef = useRef<Window | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortingRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const loadAccounts = useCallback(
    async (withStatus: boolean) => {
      try {
        const [items, oauth] = await Promise.all([
          apiListSocialAccounts(accessToken, companyId),
          withStatus ? apiGetInstagramOAuthStatus(accessToken, companyId) : undefined,
        ]);
        const row = items.find((item) => item.platform === "instagram") ?? null;
        setAccount(row);
        if (withStatus) setStatus(oauth?.status ?? "not_connected");
      } catch (err) {
        setError(
          err instanceof Error ? mapApiError(err.message, t) : t("settings.instagram.loadFailed"),
        );
      }
    },
    [accessToken, companyId, t],
  );

  const abortConnect = useCallback(async () => {
    if (abortingRef.current) return;
    abortingRef.current = true;
    stopPolling();
    if (popupRef.current && !popupRef.current.closed) {
      popupRef.current.close();
    }
    try {
      await apiCancelInstagramOAuth(accessToken, companyId);
    } catch {
      // Still leave the panel so the user can retry even if cancel fails.
    }
    setStatus("not_connected");
    setError(t("settings.instagram.oauthAborted"));
    abortingRef.current = false;
  }, [accessToken, companyId, stopPolling, t]);

  // Poll the OAuth status while a connect is pending; resolve when done/failed.
  const pollStatus = useCallback(() => {
    stopPolling();
    timeoutRef.current = setTimeout(() => {
      void abortConnect();
    }, OAUTH_POLL_TIMEOUT_MS);
    pollRef.current = setInterval(async () => {
      try {
        const oauth = await apiGetInstagramOAuthStatus(accessToken, companyId);
        if (oauth.status === "connected") {
          stopPolling();
          setStatus("connected");
          await loadAccounts(false);
          setFlash("connected");
          window.setTimeout(() => setFlash(null), 2500);
        } else if (oauth.status === "pending") {
          setStatus("pending");
        } else {
          stopPolling();
          setStatus("not_connected");
          setError(t("settings.instagram.oauthAborted"));
        }
      } catch (err) {
        // Transient network error — keep polling.
        setError(
          err instanceof Error ? mapApiError(err.message, t) : t("settings.instagram.loadFailed"),
        );
      }
    }, POLL_INTERVAL_MS);
  }, [abortConnect, accessToken, companyId, loadAccounts, stopPolling, t]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    await loadAccounts(true);
    setLoading(false);
  }, [loadAccounts]);

  useEffect(() => {
    void load();
  }, [load]);

  // Resume polling if a previous flow was left pending (e.g. page refresh mid-connect).
  useEffect(() => {
    if (status === "pending") pollStatus();
    return stopPolling;
  }, [status, pollStatus, stopPolling]);

  const startConnect = useCallback(async () => {
    setBusy(true);
    setError(null);
    setFlash(null);
    try {
      const oauth = await apiStartInstagramOAuth(accessToken, companyId);
      if (!oauth.authorization_url) {
        setError(t("settings.instagram.oauthNotConfigured"));
        return;
      }
      setStatus("pending");
      if (popupRef.current && !popupRef.current.closed) {
        popupRef.current.close();
      }
      popupRef.current = window.open(oauth.authorization_url, "_blank", "noopener,noreferrer");
      pollStatus();
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.instagram.saveFailed"),
      );
    } finally {
      setBusy(false);
    }
  }, [accessToken, companyId, pollStatus, t]);

  async function onDisconnect() {
    setBusy(true);
    setError(null);
    setFlash(null);
    stopPolling();
    try {
      await apiDisconnectInstagramAccount(accessToken, companyId);
      setAccount(null);
      setStatus("not_connected");
      setDisconnectOpen(false);
      setFlash("disconnected");
      window.setTimeout(() => setFlash(null), 2500);
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.instagram.saveFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  const expired = isExpired(account?.expires_at ?? null);
  const connected = status === "connected" || Boolean(account?.ig_user_id?.trim());
  const connecting = status === "pending";

  const expiresLabel = useMemo(() => {
    if (!account?.expires_at) return t("common.notAvailable");
    const stamp = new Date(account.expires_at);
    if (Number.isNaN(stamp.getTime())) return t("common.notAvailable");
    return stamp.toLocaleDateString(i18n.language === "en" ? "en" : "zh-HK", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  }, [account?.expires_at, i18n.language, t]);

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
        {flash === "connected" && (
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

        {connecting && (
          <Alert variant="default">
            <AlertTitle>{t("settings.instagram.connectingTitle")}</AlertTitle>
            <AlertDescription>{t("settings.instagram.connectingBody")}</AlertDescription>
          </Alert>
        )}

        {connected && !connecting && account && (
          <div className="space-y-3">
            {!expired && (
              <Badge
                variant="outline"
                className="border-success/30 bg-success-soft text-success-foreground"
              >
                {t("settings.instagram.connected")}
              </Badge>
            )}
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

        {connecting ? (
          <div className="flex flex-wrap items-center justify-start gap-2">
            <Button type="button" variant="outline" disabled={busy} onClick={() => void abortConnect()}>
              {t("common.cancel")}
            </Button>
          </div>
        ) : (
          <div
            className={
              connected
                ? "flex flex-wrap items-center justify-end gap-2"
                : "flex flex-wrap items-center justify-start gap-2"
            }
          >
            {connected ? (
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => void startConnect()}
              >
                {t("settings.instagram.rotate")}
              </Button>
            ) : (
              <Button
                type="button"
                variant="default"
                disabled={busy}
                onClick={() => void startConnect()}
              >
                {t("settings.instagram.connect")}
              </Button>
            )}
            {connected && (
              <Button
                type="button"
                variant="outline"
                className="border-destructive/40 text-destructive hover:enabled:bg-destructive-soft"
                disabled={busy}
                onClick={() => setDisconnectOpen(true)}
              >
                {t("settings.instagram.disconnect")}
              </Button>
            )}
          </div>
        )}
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
