import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/context/auth-context";
import {
  apiGetCompanyVoice,
  apiPatchCompanyVoice,
  type CompanyVoiceSettings,
} from "@/features/company-settings/api";
import { cn } from "@/lib/utils";

const ROAST_LEVELS = [0, 1, 2, 3] as const;

type VoiceFormProps = {
  companyId: string;
};

export function VoiceForm({ companyId }: VoiceFormProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const [canEdit, setCanEdit] = useState(false);
  const [roastLevel, setRoastLevel] = useState(1);
  const [locale, setLocale] = useState("zh-HK");
  const [forbiddenText, setForbiddenText] = useState("");
  const [toneNotes, setToneNotes] = useState("");
  const [baseline, setBaseline] = useState<CompanyVoiceSettings | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const data = await apiGetCompanyVoice(accessToken, companyId);
        if (cancelled) return;
        setRoastLevel(data.roast_level);
        setLocale(data.locale);
        setForbiddenText(data.forbidden_phrases.join(", "));
        setToneNotes(data.tone_notes);
        setBaseline(data);
        setCanEdit(data.can_edit);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [accessToken, companyId]);

  function applySettings(data: CompanyVoiceSettings) {
    setRoastLevel(data.roast_level);
    setLocale(data.locale);
    setForbiddenText(data.forbidden_phrases.join(", "));
    setToneNotes(data.tone_notes);
  }

  function parsePhrases(raw: string): string[] {
    return raw
      .split(/[,，]/)
      .map((p) => p.trim())
      .filter(Boolean)
      .slice(0, 15);
  }

  async function onSave() {
    if (!canEdit) return;
    setSaving(true);
    setError(null);
    setSavedFlash(false);
    try {
      const updated = await apiPatchCompanyVoice(accessToken, companyId, {
        roast_level: roastLevel,
        locale: locale.trim() || "zh-HK",
        forbidden_phrases: parsePhrases(forbiddenText),
        tone_notes: toneNotes.trim(),
      });
      applySettings(updated);
      setBaseline(updated);
      setCanEdit(updated.can_edit);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  function onCancel() {
    if (baseline) applySettings(baseline);
    setError(null);
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("settings.voice.title")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("settings.voice.subtitle")}</p>
      </div>

      <div className="space-y-5 rounded-xl border border-border bg-card p-6">
        {!canEdit && (
          <Alert>
            <AlertDescription>{t("settings.voice.readOnly")}</AlertDescription>
          </Alert>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {savedFlash && (
          <Alert>
            <AlertDescription>{t("settings.voice.saved")}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-2">
          <p className="text-sm font-medium leading-none">{t("settings.voice.roast.label")}</p>
          <div className="inline-flex flex-wrap gap-0 rounded-lg bg-accent p-1">
            {ROAST_LEVELS.map((level) => (
              <button
                key={level}
                type="button"
                disabled={!canEdit || saving}
                onClick={() => setRoastLevel(level)}
                className={cn(
                  "rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors",
                  roastLevel === level
                    ? "bg-card text-foreground shadow"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t(`settings.voice.roast.levels.${level}`)}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">{t("settings.voice.roast.hint")}</p>
        </div>

        <FormField id="voice-locale" label={t("settings.voice.locale.label")}>
          <Input
            id="voice-locale"
            value={locale}
            disabled={!canEdit || saving}
            onChange={(e) => setLocale(e.target.value)}
            autoComplete="off"
          />
          <p className="text-xs text-muted-foreground">{t("settings.voice.locale.hint")}</p>
        </FormField>

        <FormField id="voice-forbidden" label={t("settings.voice.forbidden.label")}>
          <Input
            id="voice-forbidden"
            value={forbiddenText}
            disabled={!canEdit || saving}
            onChange={(e) => setForbiddenText(e.target.value)}
            autoComplete="off"
          />
          <p className="text-xs text-muted-foreground">{t("settings.voice.forbidden.hint")}</p>
        </FormField>

        <FormField id="voice-tone" label={t("settings.voice.tone.label")}>
          <Textarea
            id="voice-tone"
            value={toneNotes}
            disabled={!canEdit || saving}
            onChange={(e) => setToneNotes(e.target.value)}
            rows={4}
            className="min-h-24"
          />
          <p className="text-xs text-muted-foreground">{t("settings.voice.tone.hint")}</p>
        </FormField>

        {canEdit && (
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" disabled={saving} onClick={onCancel}>
              {t("common.cancel")}
            </Button>
            <Button type="button" disabled={saving} onClick={() => void onSave()}>
              {saving ? t("common.saving") : t("common.save")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
