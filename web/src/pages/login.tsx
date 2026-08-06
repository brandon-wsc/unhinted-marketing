import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AuthLayout } from "@/components/auth-layout";
import { PasswordBox } from "@/components/password-box";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
          <Link to="/register" className="text-primary hover:underline">
            {t("auth.login.registerLink")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        {error && (
          <Alert
            variant="destructive"
            className="border-destructive/30 bg-[var(--color-destructive-soft)] text-[var(--color-destructive-text)]"
          >
            <AlertDescription className="text-[var(--color-destructive-text)]">
              {error}
            </AlertDescription>
          </Alert>
        )}
        <div className="space-y-2">
          <Label htmlFor="email">{t("common.email")}</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => onEmailChange(e.target.value)}
            autoComplete="email"
            required
          />
        </div>
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
