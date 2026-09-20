import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/context/auth-context";
import { useToast } from "@/context/toast-context";
import {
  apiGetInstanceSettings,
  apiPutInstanceSettings,
  type InstanceSettings,
  type MetaOAuthMode,
  type SetupEmailBackend,
} from "@/features/setup/api";
import { mapApiError } from "@/lib/map-api-error";
import { isSuperAdmin } from "@/lib/platform-level";

function CopyUrlField({
  id,
  label,
  value,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  hint: string;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <FormField id={id} label={label}>
      <div className="flex gap-2">
        <Input id={id} value={value} readOnly className="flex-1" />
        <Button
          type="button"
          variant="outline"
          className={copied ? "text-success" : undefined}
          onClick={() => {
            void navigator.clipboard.writeText(value);
            setCopied(true);
          }}
        >
          {copied ? t("common.copied") : t("common.copy")}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </FormField>
  );
}

/** Platform instance settings (ADR 0026) — view ADMIN+, edit SUPERADMIN. */
export function InstancePanel() {
  const { t } = useTranslation();
  const { user, accessToken } = useAuth();
  const { showInfo } = useToast();
  const canEdit = isSuperAdmin(user?.platform_level);

  const [settings, setSettings] = useState<InstanceSettings | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const [webBaseUrl, setWebBaseUrl] = useState("");
  const [emailBackend, setEmailBackend] = useState<SetupEmailBackend>("link");
  const [emailFrom, setEmailFrom] = useState("");
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("587");
  const [smtpUser, setSmtpUser] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpTls, setSmtpTls] = useState(true);
  const [metaAppId, setMetaAppId] = useState("");
  const [metaAppSecret, setMetaAppSecret] = useState("");
  const [metaMode, setMetaMode] = useState<MetaOAuthMode>("byo");
  const [relaySecret, setRelaySecret] = useState("");
  const [instanceIdCopied, setInstanceIdCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiGetInstanceSettings(accessToken)
      .then((row) => {
        if (cancelled) return;
        setSettings(row);
        setWebBaseUrl(row.web_base_url);
        setEmailBackend(row.email_backend);
        setEmailFrom(row.email_from);
        setSmtpHost(row.smtp_host);
        setSmtpPort(String(row.smtp_port));
        setSmtpUser(row.smtp_user);
        setSmtpTls(row.smtp_tls);
        setMetaAppId(row.meta_app_id);
        setMetaMode(row.meta_oauth_mode);
      })
      .catch((err) => {
        if (!cancelled) setError(mapApiError(err instanceof Error ? err.message : "", t));
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, t]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const next = await apiPutInstanceSettings(accessToken, {
        web_base_url: webBaseUrl.trim(),
        email_config: {
          backend: emailBackend,
          email_from: emailFrom.trim() || undefined,
          smtp_host: smtpHost.trim() || undefined,
          smtp_port: Number.parseInt(smtpPort, 10) || 587,
          smtp_user: smtpUser.trim() || undefined,
          smtp_password: smtpPassword || undefined,
          smtp_tls: smtpTls,
        },
        meta_app_id: metaAppId.trim(),
        meta_app_secret: metaAppSecret || undefined,
        meta_oauth_mode: metaMode,
        meta_oauth_relay_secret: relaySecret || undefined,
      });
      setSettings(next);
      setSmtpPassword("");
      setMetaAppSecret("");
      setRelaySecret("");
      showInfo(t("system.instance.saved"));
    } catch (err) {
      setError(mapApiError(err instanceof Error ? err.message : "", t));
    } finally {
      setSaving(false);
    }
  }

  if (error && !settings) {
    return (
      <Alert
        variant="destructive"
        className="border-destructive/30 bg-destructive-soft text-destructive-foreground"
      >
        <AlertDescription className="text-destructive-foreground">{error}</AlertDescription>
      </Alert>
    );
  }

  if (!settings) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }

  return (
    <form onSubmit={onSave} className="max-w-lg space-y-4">
      {!canEdit && (
        <Alert variant="info">
          <AlertDescription>{t("system.instance.readOnly")}</AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert
          variant="destructive"
          className="border-destructive/30 bg-destructive-soft text-destructive-foreground"
        >
          <AlertDescription className="text-destructive-foreground">{error}</AlertDescription>
        </Alert>
      )}
      <FormField id="inst-base-url" label={t("system.instance.baseUrl")}>
        <Input
          id="inst-base-url"
          value={webBaseUrl}
          onChange={(e) => setWebBaseUrl(e.target.value)}
          readOnly={!canEdit}
          autoComplete="off"
          placeholder="https://"
        />
        <p className="text-xs text-muted-foreground">{t("system.instance.baseUrlHint")}</p>
      </FormField>
      <FormField id="inst-email-backend" label={t("system.instance.emailBackend")}>
        <Select
          value={emailBackend}
          onValueChange={(v) => setEmailBackend(v as SetupEmailBackend)}
          disabled={!canEdit}
        >
          <SelectTrigger id="inst-email-backend" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="link">{t("setup.instance.emailLink")}</SelectItem>
            <SelectItem value="smtp">{t("setup.instance.emailSmtp")}</SelectItem>
            <SelectItem value="console">{t("setup.instance.emailConsole")}</SelectItem>
          </SelectContent>
        </Select>
      </FormField>
      {emailBackend === "smtp" && (
        <>
          <FormField id="inst-email-from" label={t("setup.instance.emailFrom")}>
            <Input
              id="inst-email-from"
              type="email"
              value={emailFrom}
              onChange={(e) => setEmailFrom(e.target.value)}
              readOnly={!canEdit}
              autoComplete="off"
            />
          </FormField>
          <div className="grid grid-cols-[1fr_96px] gap-3">
            <FormField id="inst-smtp-host" label={t("setup.instance.smtpHost")}>
              <Input
                id="inst-smtp-host"
                value={smtpHost}
                onChange={(e) => setSmtpHost(e.target.value)}
                readOnly={!canEdit}
                autoComplete="off"
              />
            </FormField>
            <FormField id="inst-smtp-port" label={t("setup.instance.smtpPort")}>
              <Input
                id="inst-smtp-port"
                type="number"
                value={smtpPort}
                onChange={(e) => setSmtpPort(e.target.value)}
                readOnly={!canEdit}
                autoComplete="off"
              />
            </FormField>
          </div>
          <FormField id="inst-smtp-user" label={t("setup.instance.smtpUser")}>
            <Input
              id="inst-smtp-user"
              value={smtpUser}
              onChange={(e) => setSmtpUser(e.target.value)}
              readOnly={!canEdit}
              autoComplete="off"
            />
          </FormField>
          <FormField id="inst-smtp-pass" label={t("setup.instance.smtpPassword")}>
            <Input
              id="inst-smtp-pass"
              type="password"
              value={smtpPassword}
              onChange={(e) => setSmtpPassword(e.target.value)}
              readOnly={!canEdit}
              autoComplete="new-password"
              placeholder={
                settings.smtp_password_last4
                  ? t("system.instance.smtpPasswordSet", {
                      last4: settings.smtp_password_last4,
                    })
                  : undefined
              }
            />
          </FormField>
          <label
            htmlFor="inst-smtp-tls"
            className="flex items-center justify-between gap-3 text-sm"
          >
            <span>{t("setup.instance.smtpTls")}</span>
            <Switch
              id="inst-smtp-tls"
              checked={smtpTls}
              onCheckedChange={setSmtpTls}
              disabled={!canEdit}
            />
          </label>
        </>
      )}
      <h2 className="pt-2 text-sm font-semibold text-foreground">
        {t("system.instance.metaSection")}
      </h2>
      <FormField id="inst-meta-mode" label={t("system.instance.metaMode")}>
        <Select
          value={metaMode}
          onValueChange={(v) => setMetaMode(v as MetaOAuthMode)}
          disabled={!canEdit}
        >
          <SelectTrigger id="inst-meta-mode" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="byo">{t("system.instance.metaModeByo")}</SelectItem>
            <SelectItem value="relay">{t("system.instance.metaModeRelay")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">{t("system.instance.metaModeHint")}</p>
      </FormField>
      {metaMode === "byo" && (
        <>
          <FormField id="inst-meta-app-id" label={t("system.instance.metaAppId")}>
            <Input
              id="inst-meta-app-id"
              value={metaAppId}
              onChange={(e) => setMetaAppId(e.target.value)}
              readOnly={!canEdit}
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">{t("system.instance.metaAppIdHint")}</p>
            {canEdit && metaAppId.trim() !== settings.meta_app_id && !metaAppSecret && (
              <p className="text-xs text-destructive">{t("system.instance.metaAppIdChanged")}</p>
            )}
          </FormField>
          <FormField id="inst-meta-app-secret" label={t("system.instance.metaAppSecret")}>
            <Input
              id="inst-meta-app-secret"
              type="password"
              value={metaAppSecret}
              onChange={(e) => setMetaAppSecret(e.target.value)}
              readOnly={!canEdit}
              autoComplete="new-password"
              placeholder={
                settings.meta_app_secret_last4
                  ? t("system.instance.metaAppSecretSet", {
                      last4: settings.meta_app_secret_last4,
                    })
                  : undefined
              }
            />
          </FormField>
        </>
      )}
      {metaMode === "relay" && (
        <>
          <FormField id="inst-meta-relay-url" label={t("system.instance.metaRelayUrl")}>
            <Input
              id="inst-meta-relay-url"
              value={settings.meta_oauth_relay_url}
              readOnly
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">{t("system.instance.metaRelayUrlHint")}</p>
          </FormField>
          <FormField id="inst-meta-instance-id" label={t("system.instance.metaInstanceId")}>
            {settings.meta_oauth_instance_id ? (
              <>
                <div className="flex gap-2">
                  <Input
                    id="inst-meta-instance-id"
                    value={settings.meta_oauth_instance_id}
                    readOnly
                    className="flex-1"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    className={instanceIdCopied ? "text-success" : undefined}
                    onClick={() => {
                      void navigator.clipboard.writeText(settings.meta_oauth_instance_id);
                      setInstanceIdCopied(true);
                    }}
                  >
                    {instanceIdCopied ? t("common.copied") : t("common.copy")}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t("system.instance.metaInstanceIdHint")}
                </p>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">
                {t("system.instance.metaCallbackMissing")}
              </p>
            )}
          </FormField>
          <FormField id="inst-meta-relay-secret" label={t("system.instance.metaRelaySecret")}>
            <Input
              id="inst-meta-relay-secret"
              type="password"
              value={relaySecret}
              onChange={(e) => setRelaySecret(e.target.value)}
              readOnly={!canEdit}
              autoComplete="new-password"
              placeholder={
                settings.meta_oauth_relay_secret_last4
                  ? t("system.instance.metaRelaySecretSet", {
                      last4: settings.meta_oauth_relay_secret_last4,
                    })
                  : undefined
              }
            />
            <p className="text-xs text-muted-foreground">
              {t("system.instance.metaRelaySecretHint")}
            </p>
          </FormField>
        </>
      )}
      {settings.meta_oauth_callback_url ? (
        <>
          <CopyUrlField
            id="inst-meta-callback"
            label={t("system.instance.metaCallbackUrl")}
            value={settings.meta_oauth_callback_url}
            hint={t("system.instance.metaCallbackHint")}
          />
          {settings.meta_oauth_deauthorize_url && (
            <CopyUrlField
              id="inst-meta-deauthorize"
              label={t("system.instance.metaDeauthorizeUrl")}
              value={settings.meta_oauth_deauthorize_url}
              hint={t("system.instance.metaDeauthorizeHint")}
            />
          )}
          {settings.meta_oauth_data_deletion_url && (
            <CopyUrlField
              id="inst-meta-data-deletion"
              label={t("system.instance.metaDataDeletionUrl")}
              value={settings.meta_oauth_data_deletion_url}
              hint={t("system.instance.metaDataDeletionHint")}
            />
          )}
        </>
      ) : (
        <p className="text-xs text-muted-foreground">{t("system.instance.metaCallbackMissing")}</p>
      )}
      {canEdit && (
        <Button type="submit" disabled={saving}>
          {saving ? t("setup.submitting") : t("common.save")}
        </Button>
      )}
    </form>
  );
}
