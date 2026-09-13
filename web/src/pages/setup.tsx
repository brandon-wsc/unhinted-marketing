import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router-dom";
import { AuthLayout } from "@/components/auth-layout";
import { FormField } from "@/components/form-field";
import { PasswordBox } from "@/components/password-box";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/context/auth-context";
import { useSetup } from "@/context/setup-context";
import { useToast } from "@/context/toast-context";
import {
  apiCreateByokModel,
  apiCreateByokProvider,
  apiPutByokRouting,
  type ByokProviderType,
} from "@/features/company-settings/api";
import { BYOK_PROVIDER_TYPES } from "@/features/company-settings/byok-helpers";
import { apiRunSetup, type SetupEmailBackend } from "@/features/setup/api";
import { mapApiError } from "@/lib/map-api-error";
import { isValidEmail } from "@/lib/simple-email";
import { cn } from "@/lib/utils";

const STEP_KEYS = ["account", "instance", "llm"] as const;
type Step = "welcome" | (typeof STEP_KEYS)[number] | "done";

function SetupStepper({ step }: { step: (typeof STEP_KEYS)[number] }) {
  const { t } = useTranslation();
  const index = STEP_KEYS.indexOf(step);
  return (
    <div className="flex items-center gap-1.5">
      {STEP_KEYS.map((key, i) => (
        <span
          key={key}
          aria-hidden="true"
          className={cn("h-[3px] flex-1 rounded-full", i <= index ? "bg-foreground" : "bg-border")}
        />
      ))}
      <span className="pl-1 text-xs whitespace-nowrap text-muted-foreground">
        {t("setup.stepIndicator", {
          step: index + 1,
          total: STEP_KEYS.length,
          label: t(`setup.stepLabels.${step}`),
        })}
      </span>
    </div>
  );
}

export function SetupPage() {
  const { t } = useTranslation();
  const { status, loading, refresh } = useSetup();
  const { user, refreshAccessToken, accessToken } = useAuth();
  const { showError } = useToast();
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>("welcome");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  // Step 1 — admin account + company
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [organizationName, setOrganizationName] = useState("");

  // Step 2 — site URL + invite email delivery
  const [webBaseUrl, setWebBaseUrl] = useState("");
  const [baseUrlTouched, setBaseUrlTouched] = useState(false);
  const [emailBackend, setEmailBackend] = useState<SetupEmailBackend>("link");
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("587");
  const [smtpUser, setSmtpUser] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [emailFrom, setEmailFrom] = useState("");
  const [smtpTls, setSmtpTls] = useState(true);

  // Step 3 — optional LLM provider (org BYOK)
  const [providerType, setProviderType] = useState<ByokProviderType>("openai");
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [chatModel, setChatModel] = useState("");

  if (loading) {
    return (
      <AuthLayout title={t("setup.title")} subtitle={t("common.loading")}>
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      </AuthLayout>
    );
  }

  // Only bounce pre-submit steps — after POST /setup succeeds the status flips
  // and the wizard must stay mounted for the LLM step.
  if (
    !status?.setup_required &&
    (step === "welcome" || step === "account" || step === "instance")
  ) {
    return <Navigate to="/" replace />;
  }

  const effectiveBaseUrl = (
    baseUrlTouched ? webBaseUrl : status?.web_base_url || window.location.origin
  ).trim();

  function clearFieldError(id: string) {
    setFieldErrors((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  function applyFieldErrors(errors: Record<string, string>) {
    setFieldErrors(errors);
    const firstId = Object.keys(errors)[0];
    if (firstId) document.getElementById(firstId)?.focus();
    return Object.keys(errors).length === 0;
  }

  function onAccountNext(e: FormEvent) {
    e.preventDefault();
    setError("");
    const errors: Record<string, string> = {};
    if (!displayName.trim()) errors["setup-displayName"] = t("errors.displayNameRequired");
    if (!email.trim()) errors["setup-email"] = t("errors.emailRequired");
    else if (!isValidEmail(email)) errors["setup-email"] = t("errors.invalidEmail");
    if (!password) errors["setup-password"] = t("errors.passwordRequired");
    else if (password.length < 8) errors["setup-password"] = t("errors.passwordTooShort");
    if (!confirmPassword) errors["setup-confirm"] = t("errors.confirmPasswordRequired");
    else if (password && confirmPassword !== password)
      errors["setup-confirm"] = t("errors.passwordMismatch");
    if (!applyFieldErrors(errors)) return;
    setStep("instance");
  }

  async function submitSetup(useDefaults: boolean) {
    setError("");
    setSubmitting(true);
    try {
      await apiRunSetup({
        email: email.trim(),
        password,
        display_name: displayName.trim(),
        organization_name: organizationName.trim() || undefined,
        web_base_url: effectiveBaseUrl || undefined,
        email_config:
          !useDefaults && emailBackend === "smtp"
            ? {
                backend: "smtp",
                smtp_host: smtpHost.trim() || undefined,
                smtp_port: Number.parseInt(smtpPort, 10) || 587,
                smtp_user: smtpUser.trim() || undefined,
                smtp_password: smtpPassword || undefined,
                email_from: emailFrom.trim() || undefined,
                smtp_tls: smtpTls,
              }
            : { backend: "link" },
      });
      await refreshAccessToken();
      await refresh();
      setStep("llm");
    } catch (err) {
      const message = err instanceof Error ? err.message : t("errors.setupFailed");
      setError(mapApiError(message, t));
    } finally {
      setSubmitting(false);
    }
  }

  function onInstanceNext(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (emailBackend === "smtp" && !smtpHost.trim()) {
      applyFieldErrors({ "setup-smtp-host": t("errors.smtpHostRequired") });
      return;
    }
    setFieldErrors({});
    void submitSetup(false);
  }

  async function onLlmNext(e: FormEvent) {
    e.preventDefault();
    setError("");
    const errors: Record<string, string> = {};
    if (!apiKey.trim()) errors["setup-llm-key"] = t("settings.apiKeys.errors.keyRequired");
    if (providerType === "openai_compatible" && !apiBase.trim())
      errors["setup-llm-base"] = t("settings.apiKeys.errors.apiBaseRequired");
    if (!chatModel.trim()) errors["setup-chat-model"] = t("errors.chatModelRequired");
    if (!applyFieldErrors(errors)) return;
    const companyId = user?.organizations[0]?.id;
    if (!companyId || !accessToken) {
      setError(t("errors.setupFailed"));
      return;
    }
    setSubmitting(true);
    try {
      const provider = await apiCreateByokProvider(accessToken, companyId, {
        label: t(`settings.apiKeys.providerType.${providerType}`),
        provider_type: providerType,
        api_key: apiKey.trim(),
        api_base: apiBase.trim() || null,
      });
      const chat = await apiCreateByokModel(accessToken, companyId, {
        provider_id: provider.id,
        model_id: chatModel.trim(),
        capability: "chat",
        capability_source: "manual",
      });
      await apiPutByokRouting(accessToken, companyId, {
        cheap_model_id: chat.id,
        medium_model_id: chat.id,
        strong_model_id: chat.id,
        image_model_id: null,
      });
      setStep("done");
    } catch (err) {
      const message = err instanceof Error ? err.message : t("errors.setupFailed");
      showError(mapApiError(message, t));
      setError(mapApiError(message, t));
    } finally {
      setSubmitting(false);
    }
  }

  const title = step === "done" ? t("setup.done.title") : t(`setup.${step}.title`);
  const subtitle = step === "done" ? t("setup.done.subtitle") : t(`setup.${step}.subtitle`);

  return (
    <AuthLayout
      title={title}
      subtitle={subtitle}
      craftSignal
      footer={step === "welcome" ? t("setup.welcome.footer") : undefined}
      headerSlot={
        step === "done" ? (
          <Alert variant="success">
            <AlertDescription>{t("setup.done.banner")}</AlertDescription>
          </Alert>
        ) : step === "welcome" ? null : (
          <SetupStepper step={step} />
        )
      }
    >
      {error && (
        <Alert
          variant="destructive"
          className="mb-4 border-destructive/30 bg-destructive-soft text-destructive-foreground"
        >
          <AlertDescription className="text-destructive-foreground">{error}</AlertDescription>
        </Alert>
      )}

      {step === "welcome" && (
        <div className="space-y-6">
          <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
            <li>
              {t("setup.welcome.itemAccount")}{" "}
              <span aria-hidden="true" className="text-destructive">
                *
              </span>
            </li>
            <li>{t("setup.welcome.itemInstance")}</li>
            <li>{t("setup.welcome.itemLlm")}</li>
          </ul>
          <Button className="w-full" onClick={() => setStep("account")}>
            {t("setup.welcome.cta")}
          </Button>
        </div>
      )}

      {step === "account" && (
        <form onSubmit={onAccountNext} noValidate className="space-y-4">
          <FormField
            id="setup-displayName"
            label={t("auth.register.displayName")}
            error={fieldErrors["setup-displayName"]}
            required
          >
            <Input
              id="setup-displayName"
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                clearFieldError("setup-displayName");
              }}
              autoComplete="name"
              required
              aria-invalid={Boolean(fieldErrors["setup-displayName"])}
              aria-describedby={
                fieldErrors["setup-displayName"] ? "setup-displayName-error" : undefined
              }
            />
          </FormField>
          <FormField
            id="setup-email"
            label={t("common.email")}
            error={fieldErrors["setup-email"]}
            required
          >
            <Input
              id="setup-email"
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                clearFieldError("setup-email");
              }}
              autoComplete="email"
              required
              aria-invalid={Boolean(fieldErrors["setup-email"])}
              aria-describedby={fieldErrors["setup-email"] ? "setup-email-error" : undefined}
            />
          </FormField>
          <PasswordBox
            id="setup-password"
            label={t("auth.register.passwordHint")}
            value={password}
            onChange={(v) => {
              setPassword(v);
              clearFieldError("setup-password");
            }}
            autoComplete="new-password"
            required
            error={fieldErrors["setup-password"]}
          />
          <PasswordBox
            id="setup-confirm"
            label={t("auth.register.confirmPassword")}
            value={confirmPassword}
            onChange={(v) => {
              setConfirmPassword(v);
              clearFieldError("setup-confirm");
            }}
            autoComplete="new-password"
            required
            error={fieldErrors["setup-confirm"]}
          />
          <FormField id="setup-org" label={t("auth.register.organizationName")}>
            <Input
              id="setup-org"
              value={organizationName}
              onChange={(e) => setOrganizationName(e.target.value)}
              autoComplete="organization"
            />
          </FormField>
          <Button type="submit" className="w-full">
            {t("setup.next")}
          </Button>
        </form>
      )}

      {step === "instance" && (
        <form onSubmit={onInstanceNext} noValidate className="space-y-4">
          <FormField id="setup-base-url" label={t("setup.instance.baseUrl")}>
            <Input
              id="setup-base-url"
              value={effectiveBaseUrl}
              onChange={(e) => {
                setBaseUrlTouched(true);
                setWebBaseUrl(e.target.value);
              }}
              placeholder="https://"
              autoComplete="off"
            />
          </FormField>
          <FormField id="setup-email-backend" label={t("setup.instance.emailBackend")}>
            <Select
              value={emailBackend}
              onValueChange={(v) => setEmailBackend(v as SetupEmailBackend)}
            >
              <SelectTrigger id="setup-email-backend" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="link">{t("setup.instance.emailLink")}</SelectItem>
                <SelectItem value="smtp">{t("setup.instance.emailSmtp")}</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          {emailBackend === "link" && (
            <Alert variant="info">
              <AlertDescription>{t("setup.instance.linkNote")}</AlertDescription>
            </Alert>
          )}
          {emailBackend === "smtp" && (
            <>
              <div className="grid grid-cols-[1fr_96px] gap-3">
                <FormField
                  id="setup-smtp-host"
                  label={t("setup.instance.smtpHost")}
                  error={fieldErrors["setup-smtp-host"]}
                  required
                >
                  <Input
                    id="setup-smtp-host"
                    value={smtpHost}
                    onChange={(e) => {
                      setSmtpHost(e.target.value);
                      clearFieldError("setup-smtp-host");
                    }}
                    autoComplete="off"
                    required
                    aria-invalid={Boolean(fieldErrors["setup-smtp-host"])}
                    aria-describedby={
                      fieldErrors["setup-smtp-host"] ? "setup-smtp-host-error" : undefined
                    }
                  />
                </FormField>
                <FormField id="setup-smtp-port" label={t("setup.instance.smtpPort")}>
                  <Input
                    id="setup-smtp-port"
                    type="number"
                    value={smtpPort}
                    onChange={(e) => setSmtpPort(e.target.value)}
                    autoComplete="off"
                  />
                </FormField>
              </div>
              <FormField id="setup-smtp-user" label={t("setup.instance.smtpUser")}>
                <Input
                  id="setup-smtp-user"
                  value={smtpUser}
                  onChange={(e) => setSmtpUser(e.target.value)}
                  autoComplete="off"
                />
              </FormField>
              <FormField id="setup-smtp-pass" label={t("setup.instance.smtpPassword")}>
                <Input
                  id="setup-smtp-pass"
                  type="password"
                  value={smtpPassword}
                  onChange={(e) => setSmtpPassword(e.target.value)}
                  autoComplete="new-password"
                />
              </FormField>
              <FormField id="setup-email-from" label={t("setup.instance.emailFrom")}>
                <Input
                  id="setup-email-from"
                  type="email"
                  value={emailFrom}
                  onChange={(e) => setEmailFrom(e.target.value)}
                  autoComplete="off"
                />
              </FormField>
              <label htmlFor="setup-smtp-tls" className="flex items-center gap-2 text-sm">
                <Checkbox
                  id="setup-smtp-tls"
                  checked={smtpTls}
                  onCheckedChange={(checked) => setSmtpTls(checked === true)}
                />
                <span>{t("setup.instance.smtpTls")}</span>
              </label>
            </>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={() => void submitSetup(true)}
            >
              {t("setup.skip")}
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? t("setup.submitting") : t("setup.next")}
            </Button>
          </div>
        </form>
      )}

      {step === "llm" && (
        <form onSubmit={onLlmNext} noValidate className="space-y-4">
          <FormField id="setup-llm-type" label={t("setup.llm.provider")}>
            <Select
              value={providerType}
              onValueChange={(v) => setProviderType(v as ByokProviderType)}
            >
              <SelectTrigger id="setup-llm-type" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {BYOK_PROVIDER_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {t(`settings.apiKeys.providerType.${type}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField
            id="setup-llm-key"
            label={t("setup.llm.apiKey")}
            error={fieldErrors["setup-llm-key"]}
            required
          >
            <Input
              id="setup-llm-key"
              type="password"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                clearFieldError("setup-llm-key");
              }}
              autoComplete="new-password"
              required
              aria-invalid={Boolean(fieldErrors["setup-llm-key"])}
              aria-describedby={fieldErrors["setup-llm-key"] ? "setup-llm-key-error" : undefined}
            />
          </FormField>
          {providerType === "openai_compatible" && (
            <FormField
              id="setup-llm-base"
              label={t("setup.llm.apiBase")}
              error={fieldErrors["setup-llm-base"]}
              required
            >
              <Input
                id="setup-llm-base"
                value={apiBase}
                onChange={(e) => {
                  setApiBase(e.target.value);
                  clearFieldError("setup-llm-base");
                }}
                autoComplete="off"
                placeholder="https://"
                required
                aria-invalid={Boolean(fieldErrors["setup-llm-base"])}
                aria-describedby={
                  fieldErrors["setup-llm-base"] ? "setup-llm-base-error" : undefined
                }
              />
            </FormField>
          )}
          <FormField
            id="setup-chat-model"
            label={t("setup.llm.chatModel")}
            error={fieldErrors["setup-chat-model"]}
            required
          >
            <Input
              id="setup-chat-model"
              value={chatModel}
              onChange={(e) => {
                setChatModel(e.target.value);
                clearFieldError("setup-chat-model");
              }}
              autoComplete="off"
              placeholder="gpt-4o"
              required
              aria-invalid={Boolean(fieldErrors["setup-chat-model"])}
              aria-describedby={
                fieldErrors["setup-chat-model"] ? "setup-chat-model-error" : undefined
              }
            />
          </FormField>
          <p className="text-xs text-muted-foreground">{t("setup.llm.chatModelHint")}</p>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setStep("done")}>
              {t("setup.skip")}
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? t("setup.submitting") : t("setup.llm.save")}
            </Button>
          </div>
        </form>
      )}

      {step === "done" && (
        <div className="space-y-4">
          <div>
            <p className="mb-2 text-sm font-medium">{t("setup.done.nextTitle")}</p>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
              <li>{t("setup.done.nextModels")}</li>
              <li>{t("setup.done.nextMembers")}</li>
              <li>{t("setup.done.nextInstance")}</li>
            </ul>
          </div>
          <Button className="w-full" onClick={() => navigate("/", { replace: true })}>
            {t("setup.done.cta")}
          </Button>
        </div>
      )}
    </AuthLayout>
  );
}
