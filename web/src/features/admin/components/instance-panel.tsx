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
  type SetupEmailBackend,
} from "@/features/setup/api";
import { mapApiError } from "@/lib/map-api-error";
import { isSuperAdmin } from "@/lib/platform-level";

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
      });
      setSettings(next);
      setSmtpPassword("");
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
      {canEdit && (
        <Button type="submit" disabled={saving}>
          {saving ? t("setup.submitting") : t("common.save")}
        </Button>
      )}
    </form>
  );
}
