import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AuthLayout } from "@/components/auth-layout";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/auth-context";
import { ApiStatusError, apiAcceptInvite } from "@/features/company-settings/api";
import { useInvitePreview } from "@/features/company-settings/use-invite-preview";

type InviteView = "ready" | "mismatch" | "conflict" | "invalid";

function ActionRow({ children }: { children: ReactNode }) {
  return <div className="flex justify-end gap-2">{children}</div>;
}

function ReturnHomeButton() {
  const { t } = useTranslation();
  return (
    <Button asChild variant="outline">
      <Link to="/">{t("invite.home")}</Link>
    </Button>
  );
}

export function InviteAcceptPage() {
  const { t } = useTranslation();
  const { token } = useParams<{ token: string }>();
  const { user, loading, logout, refreshAccessToken, accessToken } = useAuth();
  const { preview, status: previewStatus } = useInvitePreview(token);
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [view, setView] = useState<InviteView>("ready");

  const next = token ? `/invite/${token}` : "/";
  const loginTo = `/login?next=${encodeURIComponent(next)}`;
  const registerTo = `/register?next=${encodeURIComponent(next)}`;
  const previewVars = {
    email: preview?.email ?? "",
    company: preview?.company_name ?? "",
  };

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

  if (loading || (token && previewStatus === "loading")) {
    return (
      <AuthLayout title={t("invite.titleJoin")} subtitle={t("common.loading")}>
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      </AuthLayout>
    );
  }

  if (!token || previewStatus === "invalid") {
    return (
      <AuthLayout title={t("invite.invalidTitle")} subtitle={t("invite.invalidBody")}>
        <ActionRow>
          <ReturnHomeButton />
        </ActionRow>
      </AuthLayout>
    );
  }

  if (!user) {
    return (
      <AuthLayout
        title={t("invite.loggedOutTitle")}
        subtitle={t("invite.loggedOutBody", previewVars)}
        footer={t("invite.once")}
      >
        <ActionRow>
          <Button asChild variant="outline">
            <Link to={registerTo}>{t("invite.register")}</Link>
          </Button>
          <Button asChild>
            <Link to={loginTo}>{t("invite.login")}</Link>
          </Button>
        </ActionRow>
      </AuthLayout>
    );
  }

  if (view === "mismatch") {
    return (
      <AuthLayout title={t("invite.mismatchTitle")}>
        <div className="space-y-4">
          <Alert
            variant="destructive"
            className="border-destructive/30 bg-destructive-soft text-destructive-foreground"
          >
            <AlertDescription className="text-destructive-foreground">
              {t("invite.mismatchBody", previewVars)}
            </AlertDescription>
          </Alert>
          <ActionRow>
            <ReturnHomeButton />
            <Button type="button" onClick={() => void onSwitchAccount()}>
              {t("invite.logoutRelogin")}
            </Button>
          </ActionRow>
        </div>
      </AuthLayout>
    );
  }

  if (view === "conflict") {
    return (
      <AuthLayout title={t("invite.conflictTitle")} subtitle={t("invite.conflictBody")}>
        <ActionRow>
          <ReturnHomeButton />
        </ActionRow>
      </AuthLayout>
    );
  }

  if (view === "invalid") {
    return (
      <AuthLayout title={t("invite.invalidTitle")} subtitle={t("invite.invalidBody")}>
        <ActionRow>
          <ReturnHomeButton />
        </ActionRow>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={t("invite.titleJoin")} subtitle={t("invite.loggedInBody", previewVars)}>
      <div className="space-y-4">
        {user.organizations?.length === 1 && user.organizations[0]?.role === "owner" && (
          <Alert variant="info">
            <AlertDescription>{t("invite.replaceWarning", previewVars)}</AlertDescription>
          </Alert>
        )}
        <Input value={user.email} readOnly />
        <ActionRow>
          <ReturnHomeButton />
          <Button type="button" loading={submitting} onClick={() => void onJoin()}>
            {submitting ? t("invite.joining") : t("invite.join")}
          </Button>
        </ActionRow>
      </div>
    </AuthLayout>
  );
}
