import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { AuthLayout } from "@/components/auth-layout";
import { FormField } from "@/components/form-field";
import { PasswordBox } from "@/components/password-box";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/auth-context";
import { useSetup } from "@/context/setup-context";
import { useToast } from "@/context/toast-context";
import { useInvitePreview } from "@/features/company-settings/use-invite-preview";
import { inviteTokenFromPath } from "@/lib/invite-path";
import { mapApiError } from "@/lib/map-api-error";
import { safeInternalPath } from "@/lib/safe-internal-path";
import { isValidEmail } from "@/lib/simple-email";

export function RegisterPage() {
  const { t } = useTranslation();
  const { register, user, loading } = useAuth();
  const { status: setupStatus, loading: setupLoading, deploymentMode } = useSetup();
  const { showError } = useToast();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const nextPath = safeInternalPath(params.get("next")) ?? "/";
  const inviteToken = inviteTokenFromPath(nextPath);
  const { preview, status: previewStatus } = useInvitePreview(inviteToken);
  const invitePending = Boolean(inviteToken) && previewStatus === "loading";
  const emailLocked = previewStatus === "ok" && Boolean(preview);
  const loginHref = nextPath === "/" ? "/login" : `/login?next=${encodeURIComponent(nextPath)}`;
  const [displayName, setDisplayName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (preview?.email) setEmail(preview.email);
  }, [preview]);

  if (!loading && user) return <Navigate to={nextPath} replace />;

  // On-prem self-serve register is invite-only (ADR 0026). Fresh installs route
  // to the setup wizard; later visitors without an invite go back to login.
  if (!setupLoading && deploymentMode === "onprem" && !inviteToken) {
    if (setupStatus?.setup_required) return <Navigate to="/setup" replace />;
    return <Navigate to="/login" replace />;
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

    const errors: Record<string, string> = {};
    if (!displayName.trim()) errors.displayName = t("errors.displayNameRequired");
    if (!email.trim()) errors.email = t("errors.emailRequired");
    else if (!isValidEmail(email)) errors.email = t("errors.invalidEmail");
    if (!password) errors.password = t("errors.passwordRequired");
    else if (password.length < 8) errors.password = t("errors.passwordTooShort");
    if (!confirmPassword) errors.confirmPassword = t("errors.confirmPasswordRequired");
    else if (password && confirmPassword !== password)
      errors.confirmPassword = t("errors.passwordMismatch");
    setFieldErrors(errors);
    const firstId = Object.keys(errors)[0];
    if (firstId) {
      document.getElementById(firstId)?.focus();
      return;
    }

    setSubmitting(true);
    try {
      await register({
        email: emailLocked && preview ? preview.email : email,
        password,
        display_name: displayName,
        organization_name: emailLocked ? undefined : organizationName || undefined,
        invite_token: inviteToken ?? undefined,
      });
      navigate(nextPath, { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : t("errors.registrationFailed");
      showError(mapApiError(message, t));
    } finally {
      setSubmitting(false);
    }
  }

  const subtitle =
    emailLocked && preview
      ? t("auth.register.subtitleInvite", {
          email: preview.email,
          company: preview.company_name,
        })
      : t("auth.register.subtitle");

  return (
    <AuthLayout
      title={t("auth.register.title")}
      subtitle={subtitle}
      craftSignal
      footer={
        <>
          {t("auth.register.hasAccount")}{" "}
          <Link to={loginHref} className="text-primary hover:underline">
            {t("auth.register.loginLink")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <FormField
          id="displayName"
          label={t("auth.register.displayName")}
          error={fieldErrors.displayName}
          required
        >
          <Input
            id="displayName"
            value={displayName}
            onChange={(e) => {
              setDisplayName(e.target.value);
              clearFieldError("displayName");
            }}
            autoComplete="name"
            required
            aria-invalid={Boolean(fieldErrors.displayName)}
            aria-describedby={fieldErrors.displayName ? "displayName-error" : undefined}
          />
        </FormField>
        {!(emailLocked || invitePending) && (
          <FormField id="organizationName" label={t("auth.register.organizationName")}>
            <Input
              id="organizationName"
              value={organizationName}
              onChange={(e) => setOrganizationName(e.target.value)}
              autoComplete="organization"
            />
          </FormField>
        )}
        <FormField id="email" label={t("common.email")} error={fieldErrors.email} required>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
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
          label={t("auth.register.passwordHint")}
          value={password}
          onChange={(v) => {
            setPassword(v);
            clearFieldError("password");
          }}
          autoComplete="new-password"
          required
          error={fieldErrors.password}
        />
        <PasswordBox
          id="confirmPassword"
          label={t("auth.register.confirmPassword")}
          value={confirmPassword}
          onChange={(v) => {
            setConfirmPassword(v);
            clearFieldError("confirmPassword");
          }}
          autoComplete="new-password"
          required
          error={fieldErrors.confirmPassword}
        />
        <Button type="submit" disabled={submitting || invitePending} className="w-full">
          {submitting ? t("auth.register.submitting") : t("auth.register.submit")}
        </Button>
      </form>
    </AuthLayout>
  );
}
