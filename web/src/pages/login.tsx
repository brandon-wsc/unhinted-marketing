import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AuthLayout, Button, ErrorAlert, Field } from "@/components/auth-layout";
import { PasswordBox } from "@/components/password-box";
import { useAuth } from "@/context/auth-context";
import { mapApiError } from "@/lib/map-api-error";
import { getRememberedUser, patchRememberedUser } from "@/lib/remembered-user";

export function LoginPage() {
  const { t } = useTranslation();
  const { login, user, loading } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState(() => getRememberedUser()?.email ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!loading && user) return <Navigate to="/" replace />;

  function onEmailChange(value: string) {
    setEmail(value);
    patchRememberedUser({ email: value });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : t("errors.loginFailed");
      setError(mapApiError(message, t));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title={t("auth.login.title")}
      subtitle={t("auth.login.subtitle")}
      footer={
        <>
          {t("auth.login.noAccount")}{" "}
          <Link to="/register" className="text-[var(--color-primary-hover)] hover:underline">
            {t("auth.login.registerLink")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        {error && <ErrorAlert message={error} />}
        <Field
          id="email"
          label={t("common.email")}
          type="email"
          value={email}
          onChange={onEmailChange}
          autoComplete="email"
          required
        />
        <PasswordBox
          id="password"
          label={t("common.password")}
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          required
        />
        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? t("auth.login.submitting") : t("auth.login.submit")}
        </Button>
      </form>
    </AuthLayout>
  );
}
