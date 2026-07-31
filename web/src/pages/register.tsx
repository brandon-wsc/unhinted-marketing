import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AuthLayout, Button, Field } from "@/components/auth-layout";
import { PasswordBox } from "@/components/password-box";
import { useAuth } from "@/context/auth-context";
import { useToast } from "@/context/toast-context";
import { mapApiError } from "@/lib/map-api-error";

export function RegisterPage() {
  const { t } = useTranslation();
  const { register, user, loading } = useAuth();
  const { showError } = useToast();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!loading && user) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();

    if (password.length < 8 || confirmPassword.length < 8) {
      showError(t("errors.passwordTooShort"));
      return;
    }

    if (password !== confirmPassword) {
      showError(t("errors.passwordMismatch"));
      return;
    }

    setSubmitting(true);
    try {
      await register({
        email,
        password,
        display_name: displayName,
        organization_name: organizationName || undefined,
      });
      navigate("/", { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : t("errors.registrationFailed");
      showError(mapApiError(message, t));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title={t("auth.register.title")}
      subtitle={t("auth.register.subtitle")}
      footer={
        <>
          {t("auth.register.hasAccount")}{" "}
          <Link to="/login" className="text-[var(--color-primary-hover)] hover:underline">
            {t("auth.register.loginLink")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <Field
          id="displayName"
          label={t("auth.register.displayName")}
          value={displayName}
          onChange={setDisplayName}
          autoComplete="name"
          required
        />
        <Field
          id="organizationName"
          label={t("auth.register.organizationName")}
          value={organizationName}
          onChange={setOrganizationName}
          autoComplete="organization"
        />
        <Field
          id="email"
          label={t("common.email")}
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          required
        />
        <PasswordBox
          id="password"
          label={t("auth.register.passwordHint")}
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          required
        />
        <PasswordBox
          id="confirmPassword"
          label={t("auth.register.confirmPassword")}
          value={confirmPassword}
          onChange={setConfirmPassword}
          autoComplete="new-password"
          required
        />
        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? t("auth.register.submitting") : t("auth.register.submit")}
        </Button>
      </form>
    </AuthLayout>
  );
}
