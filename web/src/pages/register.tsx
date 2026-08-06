import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { AuthLayout } from "@/components/auth-layout";
import { FormField } from "@/components/form-field";
import { PasswordBox } from "@/components/password-box";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
          <Link to="/login" className="text-primary hover:underline">
            {t("auth.register.loginLink")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <FormField id="displayName" label={t("auth.register.displayName")}>
          <Input
            id="displayName"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            autoComplete="name"
            required
          />
        </FormField>
        <FormField id="organizationName" label={t("auth.register.organizationName")}>
          <Input
            id="organizationName"
            value={organizationName}
            onChange={(e) => setOrganizationName(e.target.value)}
            autoComplete="organization"
          />
        </FormField>
        <FormField id="email" label={t("common.email")}>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
        </FormField>
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
