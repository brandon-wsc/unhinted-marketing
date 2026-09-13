import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { AuthLayout } from "@/components/auth-layout";
import { FormField } from "@/components/form-field";
import { PasswordBox } from "@/components/password-box";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/auth-context";
import { useSetup } from "@/context/setup-context";
import { useInvitePreview } from "@/features/company-settings/use-invite-preview";
import { inviteTokenFromPath } from "@/lib/invite-path";
import { mapApiError } from "@/lib/map-api-error";
import { getRememberedUser, patchRememberedUser } from "@/lib/remembered-user";
import { safeInternalPath } from "@/lib/safe-internal-path";
import { isValidEmail } from "@/lib/simple-email";

export function LoginPage() {
  const { t } = useTranslation();
  const { login, user, loading } = useAuth();
  const { status: setupStatus, loading: setupLoading, deploymentMode } = useSetup();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const nextPath = safeInternalPath(params.get("next")) ?? "/";
  const inviteToken = inviteTokenFromPath(nextPath);
  const { preview, status: previewStatus } = useInvitePreview(inviteToken);
  const invitePending = Boolean(inviteToken) && previewStatus === "loading";
  const emailLocked = previewStatus === "ok" && Boolean(preview);
  const registerHref =
    nextPath === "/" ? "/register" : `/register?next=${encodeURIComponent(nextPath)}`;
  const [email, setEmail] = useState(() => (inviteToken ? "" : (getRememberedUser()?.email ?? "")));
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (preview?.email) setEmail(preview.email);
  }, [preview]);

  // On-prem first run: no accounts exist yet — send visitors to the wizard.
  if (!setupLoading && setupStatus?.setup_required) {
    return <Navigate to="/setup" replace />;
  }

  if (!loading && user) return <Navigate to={nextPath} replace />;

  function onEmailChange(value: string) {
    setEmail(value);
    patchRememberedUser({ email: value });
  }

  function clearFieldError(id: string) {
    setFieldErrors((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (invitePending) return;
    setError("");
    const errors: Record<string, string> = {};
    if (!email.trim()) errors.email = t("errors.emailRequired");
    else if (!isValidEmail(email)) errors.email = t("errors.invalidEmail");
    if (!password) errors.password = t("errors.passwordRequired");
    setFieldErrors(errors);
    const firstId = Object.keys(errors)[0];
    if (firstId) {
      document.getElementById(firstId)?.focus();
      return;
    }
    setSubmitting(true);
    try {
      await login(emailLocked && preview ? preview.email : email, password);
      navigate(nextPath, { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : t("errors.loginFailed");
      setError(mapApiError(message, t));
    } finally {
      setSubmitting(false);
    }
  }

  const subtitle =
    emailLocked && preview
      ? t("auth.login.subtitleInvite", { email: preview.email, company: preview.company_name })
      : t("auth.login.subtitle");

  return (
    <AuthLayout
      title={t("auth.login.title")}
      subtitle={subtitle}
      craftSignal
      footer={
        deploymentMode === "cloud" || inviteToken ? (
          <>
            {t("auth.login.noAccount")}{" "}
            <Link to={registerHref} className="text-primary hover:underline">
              {t("auth.login.registerLink")}
            </Link>
          </>
        ) : undefined
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {error && (
          <Alert
            variant="destructive"
            className="border-destructive/30 bg-destructive-soft text-destructive-foreground"
          >
            <AlertDescription className="text-destructive-foreground">{error}</AlertDescription>
          </Alert>
        )}
        <FormField id="email" label={t("common.email")} error={fieldErrors.email} required>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => {
              onEmailChange(e.target.value);
              clearFieldError("email");
            }}
            autoComplete="email"
            readOnly={emailLocked || invitePending}
            required
            aria-invalid={Boolean(fieldErrors.email)}
            aria-describedby={fieldErrors.email ? "email-error" : undefined}
          />
        </FormField>
        <PasswordBox
          id="password"
          label={t("common.password")}
          value={password}
          onChange={(v) => {
            setPassword(v);
            clearFieldError("password");
          }}
          autoComplete="current-password"
          required
          error={fieldErrors.password}
        />
        <Button type="submit" disabled={submitting || invitePending} className="w-full">
          {submitting ? t("auth.login.submitting") : t("auth.login.submit")}
        </Button>
      </form>
    </AuthLayout>
  );
}
