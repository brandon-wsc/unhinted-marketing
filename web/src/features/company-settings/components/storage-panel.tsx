import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
  apiCleanStorageMigration,
  apiFlipStorageMigration,
  apiGetStorageConfig,
  apiPutStorageConfig,
  apiRollbackStorageMigration,
  apiStartStorageMigration,
  apiTestStorageConnection,
  type StorageConfig,
  type StorageConfigUpdate,
  type StorageMigrationState,
} from "@/features/company-settings/api";
import { mapApiError } from "@/lib/map-api-error";

type StoragePanelProps = {
  companyId: string;
};

type FormState = {
  bucket: string;
  endpoint_url: string;
  region: string;
  public_base_url: string;
  access_key: string;
  secret_key: string;
};

export const STORAGE_POLL_MS = 1500;

const LOCKED_STATES = new Set<StorageMigrationState>([
  "validating",
  "copying",
  "verifying",
  "flipping",
  "cleaning",
]);

const COPYING_STATES = new Set<StorageMigrationState>(["validating", "copying", "verifying"]);

const EMPTY_FORM: FormState = {
  bucket: "",
  endpoint_url: "",
  region: "us-east-1",
  public_base_url: "",
  access_key: "",
  secret_key: "",
};

function formFromConfig(cfg: StorageConfig | null): FormState {
  if (!cfg) return { ...EMPTY_FORM };
  return {
    bucket: cfg.bucket ?? "",
    endpoint_url: cfg.endpoint_url ?? "",
    region: cfg.region || "us-east-1",
    public_base_url: cfg.public_base_url ?? "",
    access_key: cfg.access_key ?? "",
    secret_key: "",
  };
}

function updateBody(form: FormState): StorageConfigUpdate {
  const body: StorageConfigUpdate = {
    bucket: form.bucket.trim(),
    endpoint_url: form.endpoint_url.trim() || null,
    region: form.region.trim() || null,
    public_base_url: form.public_base_url.trim() || null,
    access_key: form.access_key.trim() || null,
  };
  if (form.secret_key.trim()) body.secret_key = form.secret_key.trim();
  return body;
}

export function formatStorageBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  const mb = bytes / (1024 * 1024);
  return `${mb >= 10 ? Math.round(mb) : mb.toFixed(1)} MB`;
}

function shouldPoll(state: StorageMigrationState | undefined): boolean {
  return Boolean(state && LOCKED_STATES.has(state));
}

export function StoragePanel({ companyId }: StoragePanelProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<StorageConfig | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<"saved" | "tested" | null>(null);
  const [flipOpen, setFlipOpen] = useState(false);
  const [cleanOpen, setCleanOpen] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const applyConfig = useCallback((cfg: StorageConfig) => {
    setConfig(cfg);
    setForm(formFromConfig(cfg));
  }, []);

  const load = useCallback(async () => {
    const cfg = await apiGetStorageConfig(accessToken, companyId);
    applyConfig(cfg);
    return cfg;
  }, [accessToken, applyConfig, companyId]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const cfg = await apiGetStorageConfig(accessToken, companyId);
        applyConfig(cfg);
        if (!shouldPoll(cfg.migration?.state)) stopPolling();
      } catch {
        // Keep polling through transient errors.
      }
    }, STORAGE_POLL_MS);
  }, [accessToken, applyConfig, companyId, stopPolling]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const cfg = await load();
        if (!cancelled && shouldPoll(cfg.migration?.state)) startPolling();
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? mapApiError(err.message, t) : t("settings.storage.loadFailed"),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [load, startPolling, stopPolling, t]);

  const migration = config?.migration ?? null;
  const state = migration?.state;
  const locked = Boolean(state && LOCKED_STATES.has(state));
  const copying = Boolean(state && COPYING_STATES.has(state));
  const canSave = form.bucket.trim().length > 0 && !locked && !busy;

  const copyingBody = useMemo(() => {
    const stats = migration?.stats ?? {};
    return t("settings.storage.copyingBody", {
      copied: stats.copied ?? 0,
      scanned: stats.scanned ?? 0,
      size: formatStorageBytes(stats.bytes ?? 0),
      orphans: stats.orphans ?? 0,
    });
  }, [migration?.stats, t]);

  function patch<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onSave() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    setFlash(null);
    try {
      const cfg = await apiPutStorageConfig(accessToken, companyId, updateBody(form));
      applyConfig(cfg);
      setFlash("saved");
      window.setTimeout(() => setFlash(null), 2500);
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.storage.saveFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function onTest() {
    if (!form.bucket.trim() || busy) return;
    setBusy(true);
    setError(null);
    setFlash(null);
    try {
      const result = await apiTestStorageConnection(accessToken, companyId, updateBody(form));
      if (result.ok) {
        setFlash("tested");
        window.setTimeout(() => setFlash(null), 2500);
      } else {
        setError(result.error || t("settings.storage.saveFailed"));
      }
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.storage.saveFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function onStart() {
    setBusy(true);
    setError(null);
    setFlash(null);
    try {
      await apiStartStorageMigration(accessToken, companyId);
      const cfg = await load();
      if (shouldPoll(cfg.migration?.state)) startPolling();
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.storage.saveFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function onFlip() {
    if (!migration) return;
    setBusy(true);
    setError(null);
    try {
      await apiFlipStorageMigration(accessToken, companyId, migration.id);
      setFlipOpen(false);
      const cfg = await load();
      if (shouldPoll(cfg.migration?.state)) startPolling();
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.storage.saveFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function onRollback() {
    if (!migration) return;
    setBusy(true);
    setError(null);
    try {
      await apiRollbackStorageMigration(accessToken, companyId, migration.id);
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.storage.saveFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function onClean() {
    if (!migration) return;
    setBusy(true);
    setError(null);
    try {
      await apiCleanStorageMigration(accessToken, companyId, migration.id);
      setCleanOpen(false);
      const cfg = await load();
      if (shouldPoll(cfg.migration?.state)) startPolling();
    } catch (err) {
      setError(
        err instanceof Error ? mapApiError(err.message, t) : t("settings.storage.saveFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  }

  const showMigrateCard = config != null && !(config.backend === "s3" && !migration);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("settings.storage.title")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("settings.storage.subtitle")}</p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {flash === "saved" && (
        <Alert variant="success">
          <AlertDescription>{t("settings.storage.saved")}</AlertDescription>
        </Alert>
      )}
      {flash === "tested" && (
        <Alert variant="success">
          <AlertDescription>{t("settings.storage.testOk")}</AlertDescription>
        </Alert>
      )}
      {state === "failed" && migration?.error && !error && (
        <Alert variant="destructive">
          <AlertDescription>
            {t("settings.storage.failed")} {migration.error}
          </AlertDescription>
        </Alert>
      )}

      <div className="space-y-5 rounded-xl border border-border bg-card p-6">
        <div className="flex flex-wrap gap-2">
          {config?.backend === "s3" ? (
            <Badge
              variant="outline"
              className="border-success/30 bg-success-soft text-success-foreground"
            >
              {t("settings.storage.badgeS3")}
            </Badge>
          ) : (
            <Badge variant="secondary">{t("settings.storage.badgeLocal")}</Badge>
          )}
          {config?.dual_write && (
            <Badge variant="outline" className="border-info/30 bg-info-soft text-info-foreground">
              {t("settings.storage.badgeDualWrite")}
            </Badge>
          )}
        </div>

        <FormField id="storage-bucket" label={t("settings.storage.bucket")}>
          <Input
            id="storage-bucket"
            value={form.bucket}
            onChange={(e) => patch("bucket", e.target.value)}
            readOnly={locked}
            autoComplete="off"
          />
        </FormField>
        <FormField id="storage-endpoint" label={t("settings.storage.endpoint")}>
          <Input
            id="storage-endpoint"
            value={form.endpoint_url}
            onChange={(e) => patch("endpoint_url", e.target.value)}
            readOnly={locked}
            autoComplete="off"
          />
        </FormField>
        <FormField id="storage-region" label={t("settings.storage.region")}>
          <Input
            id="storage-region"
            value={form.region}
            onChange={(e) => patch("region", e.target.value)}
            readOnly={locked}
            autoComplete="off"
          />
        </FormField>
        <FormField id="storage-public-url" label={t("settings.storage.publicUrl")}>
          <Input
            id="storage-public-url"
            value={form.public_base_url}
            onChange={(e) => patch("public_base_url", e.target.value)}
            readOnly={locked}
            autoComplete="off"
          />
        </FormField>
        <FormField id="storage-access-key" label={t("settings.storage.accessKey")}>
          <Input
            id="storage-access-key"
            value={form.access_key}
            onChange={(e) => patch("access_key", e.target.value)}
            readOnly={locked}
            autoComplete="off"
          />
        </FormField>
        <FormField id="storage-secret" label={t("settings.storage.secret")}>
          <Input
            id="storage-secret"
            type="password"
            value={form.secret_key}
            onChange={(e) => patch("secret_key", e.target.value)}
            readOnly={locked}
            autoComplete="new-password"
            placeholder={
              config?.secret_last4
                ? `••••${config.secret_last4}`
                : t("settings.apiKeys.edit.apiKeyPlaceholder")
            }
          />
        </FormField>

        {locked && (
          <p className="text-sm text-muted-foreground">{t("settings.storage.copyingLocked")}</p>
        )}

        {!locked && (
          <div className="flex flex-wrap items-center justify-start gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy || !form.bucket.trim()}
              onClick={() => void onTest()}
            >
              {t("settings.storage.test")}
            </Button>
            <Button type="button" disabled={!canSave} onClick={() => void onSave()}>
              {t("settings.storage.save")}
            </Button>
          </div>
        )}
      </div>

      {showMigrateCard && (
        <div className="space-y-4 rounded-xl border border-border bg-card p-6">
          {copying && (
            <div
              role="status"
              className="space-y-1 rounded-lg border border-voice-border bg-accent px-4 py-3"
            >
              <div className="flex items-start gap-3">
                <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-voice" aria-hidden />
                <div className="min-w-0 space-y-0.5">
                  <p className="text-sm font-medium tracking-tight text-foreground">
                    {t("settings.storage.copyingTitle")}
                  </p>
                  <p className="text-sm text-muted-foreground">{copyingBody}</p>
                </div>
              </div>
            </div>
          )}

          {state === "flipping" && (
            <div
              role="status"
              className="flex items-start gap-3 rounded-lg border border-voice-border bg-accent px-4 py-3"
            >
              <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-voice" aria-hidden />
              <p className="text-sm font-medium tracking-tight text-foreground">
                {t("settings.storage.flippingTitle")}
              </p>
            </div>
          )}

          {state === "cleaning" && (
            <div
              role="status"
              className="flex items-start gap-3 rounded-lg border border-voice-border bg-accent px-4 py-3"
            >
              <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-voice" aria-hidden />
              <p className="text-sm font-medium tracking-tight text-foreground">
                {t("settings.storage.cleaningTitle")}
              </p>
            </div>
          )}

          {(!state || state === "failed") && (
            <>
              <p className="text-sm text-muted-foreground">
                {config?.can_migrate
                  ? t("settings.storage.startHint")
                  : t("settings.storage.startDisabled")}
              </p>
              <Button
                type="button"
                disabled={busy || !config?.can_migrate}
                onClick={() => void onStart()}
              >
                {state === "failed" ? t("settings.storage.tryAgain") : t("settings.storage.start")}
              </Button>
            </>
          )}

          {state === "ready_to_flip" && (
            <>
              <p className="text-sm text-muted-foreground">{t("settings.storage.readyHint")}</p>
              <Button type="button" disabled={busy} onClick={() => setFlipOpen(true)}>
                {t("settings.storage.flip")}
              </Button>
            </>
          )}

          {state === "completed" && (
            <>
              <p className="text-sm text-muted-foreground">{t("settings.storage.graceHint")}</p>
              <div className="flex flex-wrap items-center justify-start gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void onRollback()}
                >
                  {t("settings.storage.rollback")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="border-destructive/40 text-destructive hover:enabled:bg-destructive-soft"
                  disabled={busy}
                  onClick={() => setCleanOpen(true)}
                >
                  {t("settings.storage.clean")}
                </Button>
              </div>
            </>
          )}

          {state === "done" && (
            <p className="text-sm text-muted-foreground">{t("settings.storage.doneHint")}</p>
          )}
        </div>
      )}

      <AlertDialog open={flipOpen} onOpenChange={setFlipOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.storage.flipTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("settings.storage.flipBody")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void onFlip()}>
              {t("settings.storage.flip")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={cleanOpen} onOpenChange={setCleanOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.storage.cleanTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("settings.storage.cleanBody")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="outline"
              className="border-destructive/40 text-destructive hover:enabled:bg-destructive-soft"
              onClick={() => void onClean()}
            >
              {t("settings.storage.clean")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
