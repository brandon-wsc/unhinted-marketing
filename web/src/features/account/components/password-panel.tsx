import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PasswordBox } from "@/components/password-box";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/auth-context";
import { useFlash } from "@/hooks/use-flash";
import { apiChangePassword, apiVerifyPassword } from "@/lib/api";
import { mapApiError } from "@/lib/map-api-error";
import { errorMessage } from "@/lib/utils";

const MIN_PASSWORD_LENGTH = 8;

export function PasswordPanel() {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [verified, setVerified] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useFlash<boolean>();
  const [currentError, setCurrentError] = useState<string | null>(null);
  const [newError, setNewError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  async function verify(event: React.FormEvent) {
    event.preventDefault();
    if (!current) {
      setCurrentError(t("errors.currentPasswordRequired"));
      return;
    }
    setVerifying(true);
    setApiError(null);
    try {
      await apiVerifyPassword(accessToken, current);
      setCurrentError(null);
      setVerified(true);
    } catch (err) {
      // A wrong current password is a field error, not a form-level one.
      setCurrentError(mapApiError(errorMessage(err), t));
    } finally {
      setVerifying(false);
    }
  }

  function reset() {
    setCurrent("");
    setNext("");
    setConfirm("");
    setVerified(false);
    setCurrentError(null);
    setNewError(null);
    setConfirmError(null);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (next.length < MIN_PASSWORD_LENGTH) {
      setNewError(t("errors.passwordTooShort"));
      return;
    }
    if (confirm !== next) {
      setConfirmError(t("errors.passwordMismatch"));
      return;
    }
    setSaving(true);
    setApiError(null);
    try {
      await apiChangePassword(accessToken, {
        current_password: current,
        new_password: next,
      });
      setSaved(true);
      reset();
    } catch (err) {
      // The server re-checks current_password — route its failures to the fields.
      const raw = errorMessage(err);
      const message = mapApiError(raw, t);
      if (raw === "Current password is incorrect") {
        // Back to step 1: the current password must be proved again.
        setNext("");
        setConfirm("");
        setNewError(null);
        setConfirmError(null);
        setVerified(false);
        setCurrentError(message);
      } else if (
        raw === "Password must be at least 8 characters" ||
        raw === "New password must be different from the current password"
      ) {
        setNewError(message);
      } else {
        setApiError(message);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-6">
      <h2 className="text-base font-semibold text-foreground">{t("account.password.title")}</h2>
      {saved && (
        <Alert variant="success">
          <AlertDescription>{t("account.password.saved")}</AlertDescription>
        </Alert>
      )}
      {apiError && (
        <Alert variant="destructive">
          <AlertDescription>{apiError}</AlertDescription>
        </Alert>
      )}
      {verified ? (
        <form noValidate onSubmit={(e) => void submit(e)} className="space-y-5">
          <PasswordBox
            id="password-new"
            label={t("account.password.newLabel")}
            value={next}
            onChange={(value) => {
              setNext(value);
              if (newError) setNewError(null);
              setSaved(null);
            }}
            autoComplete="new-password"
            required
            error={newError}
          />
          <PasswordBox
            id="password-confirm"
            label={t("account.password.confirmLabel")}
            value={confirm}
            onChange={(value) => {
              setConfirm(value);
              if (confirmError) setConfirmError(null);
              setSaved(null);
            }}
            autoComplete="new-password"
            required
            error={confirmError}
          />
          <div className="flex gap-2">
            <Button type="submit" disabled={saving}>
              {saving ? t("account.password.saving") : t("account.password.submit")}
            </Button>
            <Button type="button" variant="outline" onClick={reset}>
              {t("common.cancel")}
            </Button>
          </div>
        </form>
      ) : (
        <form noValidate onSubmit={(e) => void verify(e)} className="space-y-5">
          <PasswordBox
            id="password-current"
            label={t("account.password.currentLabel")}
            value={current}
            onChange={(value) => {
              setCurrent(value);
              if (currentError) setCurrentError(null);
              setSaved(null);
            }}
            autoComplete="current-password"
            required
            error={currentError}
          />
          <Button type="submit" disabled={verifying}>
            {verifying ? t("account.password.verifying") : t("account.password.verify")}
          </Button>
        </form>
      )}
    </section>
  );
}
