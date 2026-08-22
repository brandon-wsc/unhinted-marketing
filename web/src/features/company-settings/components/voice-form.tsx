import { CircleX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { IconButton } from "@/components/icon-button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/context/auth-context";
import {
  apiGetCompanyVoice,
  apiPatchCompanyVoice,
  type CompanyVoiceSettings,
} from "@/features/company-settings/api";
import { cn } from "@/lib/utils";

const ROAST_LEVELS = [0, 1, 2, 3] as const;
const MAX_EXEMPLARS = 3;
const MAX_EXEMPLAR_CHARS = 150;

type VoiceFormProps = {
  companyId: string;
};

type ExemplarRow = {
  id: number;
  caption: string;
};

function captionsFromRows(rows: ExemplarRow[]): string[] {
  return rows.map((row) => row.caption);
}

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
  const [exemplars, setExemplars] = useState<ExemplarRow[]>([]);
  const [baseline, setBaseline] = useState<CompanyVoiceSettings | null>(null);
  const nextExemplarId = useRef(1);

  function rowsFromCaptions(raw: string[] | undefined): ExemplarRow[] {
    return (raw ?? []).slice(0, MAX_EXEMPLARS).map((caption) => ({
      id: nextExemplarId.current++,
      caption: caption.slice(0, MAX_EXEMPLAR_CHARS),
    }));
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const data = await apiGetCompanyVoice(accessToken, companyId);
        if (cancelled) return;
        applySettings(data);
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
    setExemplars(rowsFromCaptions(data.exemplar_captions));
  }

  function parsePhrases(raw: string): string[] {
    return raw
      .split(/[,，]/)
      .map((p) => p.trim())
      .filter(Boolean)
      .slice(0, 15);
  }

  function parseExemplars(rows: string[]): string[] {
    const out: string[] = [];
    const seen = new Set<string>();
    for (const row of rows) {
      const cap = row.trim().slice(0, MAX_EXEMPLAR_CHARS);
      if (!cap || seen.has(cap)) continue;
      seen.add(cap);
      out.push(cap);
      if (out.length >= MAX_EXEMPLARS) break;
    }
    return out;
  }

  function listEquals(a: string[], b: string[]): boolean {
    return a.join("\0") === b.join("\0");
  }

  const dirty =
    baseline != null &&
    (roastLevel !== baseline.roast_level ||
      (locale.trim() || "zh-HK") !== baseline.locale ||
      !listEquals(parsePhrases(forbiddenText), baseline.forbidden_phrases) ||
      toneNotes.trim() !== baseline.tone_notes ||
      !listEquals(parseExemplars(captionsFromRows(exemplars)), baseline.exemplar_captions));

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
        exemplar_captions: parseExemplars(captionsFromRows(exemplars)),
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
        {!canEdit && (
          <p className="mt-1 text-sm text-muted-foreground">{t("settings.voice.readOnly")}</p>
        )}
      </div>

      <div className="space-y-5 rounded-xl border border-border bg-card p-6">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {savedFlash && (
          <Alert variant="success">
            <AlertDescription>{t("settings.voice.saved")}</AlertDescription>
          </Alert>
        )}

        <fieldset disabled={!canEdit} className="space-y-2">
          <legend className="text-sm font-medium leading-none">
            {t("settings.voice.roast.label")}
          </legend>
          <div className="flex flex-wrap gap-2">
            {ROAST_LEVELS.map((level) => {
              const selected = roastLevel === level;
              return (
                <label
                  key={level}
                  className={cn(
                    "cursor-pointer rounded-md border px-3.5 py-1.5 text-sm font-medium transition-colors has-[:focus-visible]:ring-1 has-[:focus-visible]:ring-ring has-[:disabled]:cursor-not-allowed",
                    selected
                      ? "border-foreground bg-secondary text-foreground"
                      : "border-border text-muted-foreground hover:border-voice-border hover:bg-secondary hover:text-foreground",
                  )}
                >
                  <input
                    type="radio"
                    name="voice-roast"
                    value={level}
                    checked={selected}
                    disabled={saving}
                    onChange={() => setRoastLevel(level)}
                    className="sr-only"
                  />
                  {t(`settings.voice.roast.levels.${level}`)}
                </label>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground">{t("settings.voice.roast.hint")}</p>
        </fieldset>

        <FormField id="voice-locale" label={t("settings.voice.locale.label")}>
          <Input
            id="voice-locale"
            value={locale}
            readOnly={!canEdit}
            disabled={saving}
            onChange={(e) => setLocale(e.target.value)}
            autoComplete="off"
          />
          <p className="text-xs text-muted-foreground">{t("settings.voice.locale.hint")}</p>
        </FormField>

        <FormField id="voice-forbidden" label={t("settings.voice.forbidden.label")}>
          <Input
            id="voice-forbidden"
            value={forbiddenText}
            readOnly={!canEdit}
            disabled={saving}
            onChange={(e) => setForbiddenText(e.target.value)}
            autoComplete="off"
          />
          <p className="text-xs text-muted-foreground">{t("settings.voice.forbidden.hint")}</p>
        </FormField>

        <FormField id="voice-tone" label={t("settings.voice.tone.label")}>
          <Textarea
            id="voice-tone"
            value={toneNotes}
            readOnly={!canEdit}
            disabled={saving}
            onChange={(e) => setToneNotes(e.target.value)}
            rows={4}
            className="min-h-24"
          />
          <p className="text-xs text-muted-foreground">{t("settings.voice.tone.hint")}</p>
        </FormField>

        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium leading-none">
              {t("settings.voice.exemplars.label")}
            </p>
            {canEdit && (
              <p className="mt-1 text-xs text-muted-foreground">
                {t("settings.voice.exemplars.hint")}
              </p>
            )}
          </div>
          {exemplars.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("settings.voice.exemplars.empty")}</p>
          )}
          {exemplars.map((row, index) => (
            <div key={row.id} className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor={`voice-exemplar-${row.id}`}>
                  {t("settings.voice.exemplars.slot", { n: index + 1 })}
                </Label>
                {canEdit && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <IconButton
                        type="button"
                        className="size-8"
                        disabled={saving}
                        aria-label={t("settings.voice.exemplars.remove")}
                        onClick={() =>
                          setExemplars((current) => current.filter((item) => item.id !== row.id))
                        }
                      >
                        <CircleX />
                      </IconButton>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      {t("settings.voice.exemplars.remove")}
                    </TooltipContent>
                  </Tooltip>
                )}
              </div>
              <Textarea
                id={`voice-exemplar-${row.id}`}
                value={row.caption}
                readOnly={!canEdit}
                disabled={saving}
                maxLength={MAX_EXEMPLAR_CHARS}
                onChange={(e) => {
                  const nextCaption = e.target.value.slice(0, MAX_EXEMPLAR_CHARS);
                  setExemplars((current) =>
                    current.map((item) =>
                      item.id === row.id ? { ...item, caption: nextCaption } : item,
                    ),
                  );
                }}
                rows={3}
                className="min-h-20"
              />
              {canEdit && (
                <p className="text-xs text-muted-foreground">
                  {t("settings.voice.exemplars.chars", {
                    used: row.caption.trim().length,
                    max: MAX_EXEMPLAR_CHARS,
                  })}
                </p>
              )}
            </div>
          ))}
          {canEdit &&
            exemplars.length < MAX_EXEMPLARS &&
            exemplars.every((row) => row.caption.trim()) && (
            <Button
              type="button"
              variant="outline"
              disabled={saving}
              onClick={() =>
                setExemplars((current) => [
                  ...current,
                  { id: nextExemplarId.current++, caption: "" },
                ])
              }
            >
              {t("settings.voice.exemplars.add")}
            </Button>
          )}
        </div>

        {canEdit && (
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" disabled={saving || !dirty} onClick={onCancel}>
              {t("common.cancel")}
            </Button>
            <Button type="button" loading={saving} disabled={!dirty} onClick={() => void onSave()}>
              {t("common.save")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
