import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AuthLayout } from "@/components/auth-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/auth-context";
import { ApiStatusError, apiAcceptInvite } from "@/features/company-settings/api";

type InviteView = "ready" | "mismatch" | "conflict" | "invalid";

export function InviteAcceptPage() {
  const { t } = useTranslation();
  const { token } = useParams<{ token: string }>();
  const { user, loading, logout, refreshAccessToken, accessToken } = useAuth();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [view, setView] = useState<InviteView>("ready");

  const next = token ? `/invite/${token}` : "/";
  const loginTo = `/login?next=${encodeURIComponent(next)}`;
  const registerTo = `/register?next=${encodeURIComponent(next)}`;

  async function onJoin() {
    if (!token) return;
    setSubmitting(true);
    try {
      await apiAcceptInvite(accessToken, token);
      await refreshAccessToken();
      navigate("/", { replace: true });
    } catch (err) {
      const status = err instanceof ApiStatusError ? err.status : 0;
      if (status === 403) setView("mismatch");
      else if (status === 409) setView("conflict");
      else setView("invalid");
    } finally {
      setSubmitting(false);
    }
  }

  async function onSwitchAccount() {
    await logout();
    navigate(loginTo, { replace: true });
  }

  if (loading) {
    return (
      <AuthLayout title={t("invite.titleJoin")} subtitle={t("common.loading")}>
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      </AuthLayout>
    );
  }

  if (!token) {
    return (
      <AuthLayout title={t("invite.invalidTitle")} subtitle={t("invite.invalidBody")}>
        <Button asChild className="w-full">
          <Link to="/">{t("invite.home")}</Link>
        </Button>
      </AuthLayout>
    );
  }

  if (!user) {
    return (
      <AuthLayout title={t("invite.loggedOutTitle")} subtitle={t("invite.loggedOutBody")}>
        <div className="space-y-4">
          <Button asChild className="w-full">
            <Link to={loginTo}>{t("invite.login")}</Link>
          </Button>
          <p className="text-center text-sm">
            <Link to={registerTo} className="text-primary hover:underline">
              {t("invite.register")}
            </Link>
          </p>
        </div>
        <p className="mt-4 text-center text-xs text-muted-foreground">{t("invite.once")}</p>
      </AuthLayout>
    );
  }

  if (view === "mismatch") {
    return (
      <AuthLayout title={t("invite.mismatchTitle")} subtitle={t("invite.mismatchBody")}>
        <Button type="button" className="w-full" onClick={() => void onSwitchAccount()}>
          {t("invite.logoutRelogin")}
        </Button>
      </AuthLayout>
    );
  }

  if (view === "conflict") {
    return (
      <AuthLayout title={t("invite.conflictTitle")} subtitle={t("invite.conflictBody")}>
        <Button asChild className="w-full">
          <Link to="/">{t("invite.home")}</Link>
        </Button>
      </AuthLayout>
    );
  }

  if (view === "invalid") {
    return (
      <AuthLayout title={t("invite.invalidTitle")} subtitle={t("invite.invalidBody")}>
        <Button asChild className="w-full">
          <Link to="/">{t("invite.home")}</Link>
        </Button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={t("invite.titleJoin")} subtitle={t("invite.loggedInBody")}>
      <div className="space-y-4">
        <Input value={user.email} readOnly className="bg-muted" />
        <Button
          type="button"
          className="w-full"
          disabled={submitting}
          onClick={() => void onJoin()}
        >
          {submitting ? t("invite.joining") : t("invite.join")}
        </Button>
        <p className="text-center text-sm">
          <Link to="/" className="text-primary hover:underline">
            {t("invite.home")}
          </Link>
        </p>
      </div>
    </AuthLayout>
  );
}
