import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/auth-context";
import { useFlash } from "@/hooks/use-flash";

function formatDay(iso: string): string {
  return iso.slice(0, 10);
}

function roleBadgeVariant(role: string): "default" | "secondary" | "outline" {
  if (role === "owner") return "default";
  if (role === "admin") return "secondary";
  return "outline";
}

export function ProfilePanel() {
  const { t } = useTranslation();
  const { user, updateDisplayName } = useAuth();
  const [name, setName] = useState(user?.display_name ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useFlash<boolean>();
  const [error, setError] = useState<string | null>(null);

  if (!user) return null;

  const trimmed = name.trim();
  const canSave = trimmed !== user.display_name && !saving;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!trimmed) {
      setError(t("errors.displayNameRequired"));
      return;
    }
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      await updateDisplayName(trimmed);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-6">
      <h2 className="text-base font-semibold text-foreground">{t("account.profile.title")}</h2>
      <form noValidate onSubmit={(e) => void submit(e)} className="space-y-5">
        <FormField
          id="profile-display-name"
          label={t("auth.register.displayName")}
          required
          error={error}
        >
          <div className="flex gap-2">
            <Input
              id="profile-display-name"
              value={name}
              required
              maxLength={120}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "profile-display-name-error" : undefined}
              onChange={(e) => {
                setName(e.target.value);
                if (error) setError(null);
                setSaved(null);
              }}
            />
            <Button type="submit" disabled={!canSave} className="shrink-0">
              {saving ? t("account.profile.saving") : t("account.profile.save")}
            </Button>
          </div>
        </FormField>
        {saved && <p className="text-sm text-success">{t("account.profile.saved")}</p>}
        <FormField id="profile-email" label={t("common.email")}>
          <Input id="profile-email" value={user.email} readOnly />
        </FormField>
        <FormField id="profile-joined" label={t("account.profile.joined")}>
          <Input id="profile-joined" value={formatDay(user.created_at)} readOnly />
        </FormField>
      </form>
      <div className="space-y-2">
        <p className="text-sm font-medium">{t("account.profile.organizations")}</p>
        <ul className="space-y-1.5">
          {user.organizations.map((org) => (
            <li key={org.id} className="flex items-center justify-between gap-2">
              <span className="truncate text-sm">{org.name}</span>
              <Badge variant={roleBadgeVariant(org.role)}>
                {t(`settings.members.roles.${org.role}`)}
              </Badge>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
