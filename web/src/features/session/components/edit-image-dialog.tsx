import { RefreshCw, Sparkles, Trash2, Upload } from "lucide-react";
import { type DragEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { MediaSlotStrip } from "@/features/session/components/media-slot-strip";
import type { PreviewDraft, PreviewMediaItem } from "@/features/session/types";

type PlanFormat = "single" | "comic_4panel";

type PlanFields = {
  prompt: string;
  style: string;
  composition: string;
  format: PlanFormat;
  panels: string[];
};

const DEFAULT_COMIC_PANELS = [
  "hook scene — instant everyday recognition; no product",
  "escalate human friction / absurdity",
  "peak pain — still no hard sell",
  "product as soft remedy; attitude, not feature list",
];
const COMIC_COMPOSITION = "2x2 comic grid, equal panels, reading L→R then top→bottom";
const COMIC_STYLE = "clean line comic, contemporary HK urban";
const SINGLE_COMPOSITION = "subject centered, negative space for optional caption overlay";
const SINGLE_STYLE = "bright, contemporary, editorial";
const COMIC_VEHICLE =
  /4-panel|four-panel|4\s*panel|comic strip|2x2 comic|comic grid|4\s*格|四格|漫畫分格/i;
const INSPIRED_BY = /inspired by:\s*(.+?)(?:,\s*(?:clear gutters|no logos)|$)/i;
const SINGLE_PROMPT =
  "Clean modern social media image, Hong Kong urban mood, no logos, no unreadable text";

// Mirrors _single_prompt_from_comic in internal/session/image_format.py —
// keeps the "inspired by" seed when dropping the comic vehicle.
function singlePromptFromComic(prompt: string): string {
  const seed = INSPIRED_BY.exec(prompt)?.[1]?.trim().replace(/,+$/, "");
  return seed
    ? `Clean modern social media image, Hong Kong urban mood, inspired by: ${seed}, no logos, no unreadable text`
    : SINGLE_PROMPT;
}

function normalizeFormat(raw: string | undefined, fallback: string): PlanFormat {
  if (raw === "comic_4panel" || raw === "single") return raw;
  return fallback === "comic_4panel" ? "comic_4panel" : "single";
}

function planFromMedia(item: PreviewMediaItem | null): PlanFields {
  const plan = item?.plan ?? {};
  const panelsRaw = Array.isArray(plan.panels) ? plan.panels : [];
  const panels = [0, 1, 2, 3].map((i) => {
    const p = panelsRaw[i];
    if (p && typeof p === "object" && "beat" in p) {
      return String((p as { beat?: unknown }).beat ?? "");
    }
    return "";
  });
  const format = normalizeFormat(
    typeof plan.format === "string" ? plan.format : undefined,
    item?.format ?? "single",
  );
  return {
    prompt: typeof plan.prompt === "string" ? plan.prompt : "",
    style: typeof plan.style === "string" ? plan.style : "",
    composition: typeof plan.composition === "string" ? plan.composition : "",
    format,
    panels,
  };
}

function planToPayload(fields: PlanFields): Record<string, unknown> {
  const out: Record<string, unknown> = {
    prompt: fields.prompt,
    style: fields.style,
    format: fields.format,
  };
  if (fields.format === "comic_4panel") {
    out.composition =
      fields.composition.trim() || "2x2 comic grid, equal panels, reading L→R then top→bottom";
    const beats = fields.panels.map((beat, i) => beat.trim() || DEFAULT_COMIC_PANELS[i]);
    out.panels = beats.map((beat, i) => ({
      index: i + 1,
      beat,
    }));
  } else {
    out.composition = fields.composition;
    out.panels = [];
  }
  return out;
}

function isRenderableImageUrl(url: string | null): url is string {
  if (!url) return false;
  return (
    url.startsWith("http://") ||
    url.startsWith("https://") ||
    url.startsWith("data:image/") ||
    url.startsWith("/")
  );
}

function matchBySeq(media: PreviewMediaItem[], seq: number): PreviewMediaItem | null {
  return media.find((m) => m.seq === seq) ?? media[0] ?? null;
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  draft: PreviewDraft;
  busy: boolean;
  onSavePlan: (
    imageId: string,
    plan: Record<string, unknown>,
  ) => Promise<PreviewDraft | null | unknown>;
  onRegenImage: (imageId: string) => Promise<unknown>;
  onAddImage: (format?: "single" | "comic_4panel") => Promise<PreviewDraft | null | unknown>;
  onRemoveImage: (imageId: string) => Promise<PreviewDraft | null | unknown>;
  onUploadImage: (imageId: string, file: File) => Promise<PreviewDraft | null | unknown>;
};

export function EditImageDialog({
  open,
  onOpenChange,
  draft,
  busy,
  onSavePlan,
  onRegenImage,
  onAddImage,
  onRemoveImage,
  onUploadImage,
}: Props) {
  const { t } = useTranslation();
  const primary = draft.media?.find((m) => m.role === "primary") ?? draft.media?.[0] ?? null;
  const [selectedId, setSelectedId] = useState<string | null>(primary?.id ?? null);
  const [planFields, setPlanFields] = useState<PlanFields>(() => planFromMedia(primary));
  const [dragOver, setDragOver] = useState(false);
  const pendingSelectIdRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const selected = draft.media?.find((m) => m.id === selectedId) ?? primary;
  // Only this slot's URL — never fall back to primary/draft, or pending
  // slots incorrectly show Regenerate + another image's preview.
  const previewUrl = selected?.url ?? null;
  const hasRenderable = isRenderableImageUrl(previewUrl);
  const isComic = planFields.format === "comic_4panel";
  const mediaList = draft.media ?? [];
  const canDelete = mediaList.length >= 2 && !!selected;

  useEffect(() => {
    if (!open) return;
    const prefer = pendingSelectIdRef.current;
    if (prefer && draft.media?.some((m) => m.id === prefer)) {
      pendingSelectIdRef.current = null;
      const item = draft.media.find((m) => m.id === prefer) ?? null;
      setSelectedId(item?.id ?? null);
      setPlanFields(planFromMedia(item));
      return;
    }
    const next =
      draft.media?.find((m) => m.id === selectedId) ??
      draft.media?.find((m) => m.role === "primary") ??
      draft.media?.[0] ??
      null;
    setSelectedId(next?.id ?? null);
    setPlanFields(planFromMedia(next));
  }, [open, draft.revision]);

  const serverPlan = planFromMedia(selected);
  const planDirty =
    !!selected &&
    (planFields.prompt !== serverPlan.prompt ||
      planFields.style !== serverPlan.style ||
      planFields.composition !== serverPlan.composition ||
      planFields.format !== serverPlan.format ||
      planFields.panels.join("\0") !== serverPlan.panels.join("\0"));

  function setFormat(format: PlanFormat) {
    setPlanFields((prev) => {
      if (format === "comic_4panel") {
        const panels = prev.panels.some((p) => p.trim()) ? prev.panels : [...DEFAULT_COMIC_PANELS];
        return {
          ...prev,
          format,
          panels,
          composition:
            prev.composition.trim() && !/subject centered/i.test(prev.composition)
              ? prev.composition
              : COMIC_COMPOSITION,
          style: prev.style.trim() && prev.style !== SINGLE_STYLE ? prev.style : COMIC_STYLE,
        };
      }
      return {
        ...prev,
        format,
        panels: [],
        composition:
          !prev.composition.trim() || COMIC_VEHICLE.test(prev.composition)
            ? SINGLE_COMPOSITION
            : prev.composition,
        style: /comic/i.test(prev.style) ? SINGLE_STYLE : prev.style,
        prompt: COMIC_VEHICLE.test(prev.prompt) ? singlePromptFromComic(prev.prompt) : prev.prompt,
      };
    });
  }

  function handleCancel() {
    onOpenChange(false);
  }

  async function handleSavePlan() {
    if (!selected || !planDirty || busy) return;
    await onSavePlan(selected.id, planToPayload(planFields));
  }

  async function handleGenerate() {
    if (!selected || busy) return;
    let imageId = selected.id;
    const seq = selected.seq;
    if (planDirty) {
      const saved = await onSavePlan(selected.id, planToPayload(planFields));
      if (saved && typeof saved === "object" && "media" in saved) {
        const media = (saved as PreviewDraft).media ?? [];
        const match = matchBySeq(media, seq);
        if (match) imageId = match.id;
      }
    }
    await onRegenImage(imageId);
  }

  async function handleAddImage() {
    if (busy) return;
    const format = planFields.format;
    const prevIds = new Set(mediaList.map((m) => m.id));
    const result = await onAddImage(format);
    if (!result || typeof result !== "object" || !("media" in result)) return;
    const media = (result as PreviewDraft).media ?? [];
    const added =
      [...media].reverse().find((m) => !prevIds.has(m.id)) ?? media[media.length - 1] ?? null;
    if (!added) return;
    pendingSelectIdRef.current = added.id;
    setSelectedId(added.id);
    setPlanFields(planFromMedia(added));
  }

  async function handleDelete() {
    if (!selected || !canDelete || busy) return;
    const idx = mediaList.findIndex((m) => m.id === selected.id);
    const result = await onRemoveImage(selected.id);
    if (!result || typeof result !== "object" || !("media" in result)) return;
    const media = (result as PreviewDraft).media ?? [];
    const next =
      media[Math.min(Math.max(idx, 0), Math.max(media.length - 1, 0))] ?? media[0] ?? null;
    if (next) {
      pendingSelectIdRef.current = next.id;
      setSelectedId(next.id);
      setPlanFields(planFromMedia(next));
    }
  }

  async function handleUploadFile(file: File | undefined) {
    if (!selected || !file || busy) return;
    if (!file.type.startsWith("image/")) return;
    const seq = selected.seq;
    const result = await onUploadImage(selected.id, file);
    if (!result || typeof result !== "object" || !("media" in result)) return;
    const media = (result as PreviewDraft).media ?? [];
    const match = matchBySeq(media, seq);
    if (match) {
      pendingSelectIdRef.current = match.id;
      setSelectedId(match.id);
      setPlanFields(planFromMedia(match));
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    void handleUploadFile(file);
  }

  const primaryLabel = hasRenderable ? t("preview.media.regen") : t("preview.media.generate");

  const previewPane = (
    <div
      className={
        "overflow-hidden rounded-lg border transition-colors " +
        (hasRenderable ? "border-border" : dragOver ? "border-ring" : "border-border")
      }
    >
      <div className="relative aspect-square w-full">
        {hasRenderable ? (
          <img src={previewUrl} alt="" className="h-full w-full object-cover" />
        ) : (
          <div
            role="button"
            tabIndex={0}
            className="flex h-full cursor-pointer flex-col items-center justify-center gap-2 px-6 text-center"
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => {
              if (!busy && selected) fileInputRef.current?.click();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                if (!busy && selected) fileInputRef.current?.click();
              }
            }}
          >
            <Upload className="size-8 text-muted-foreground" aria-hidden />
            <p className="text-sm text-muted-foreground">{t("preview.media.uploadHint")}</p>
            <Input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              className="sr-only"
              tabIndex={-1}
              disabled={busy || !selected}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                void handleUploadFile(file);
              }}
            />
          </div>
        )}
      </div>
    </div>
  );

  const formFields = selected ? (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="image-plan-format">{t("preview.media.title")}</Label>
        <Select
          value={planFields.format}
          disabled={busy}
          onValueChange={(v) => setFormat(v as PlanFormat)}
        >
          <SelectTrigger id="image-plan-format" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="single">{t("preview.media.formatSingle")}</SelectItem>
            <SelectItem value="comic_4panel">{t("preview.media.formatComic")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isComic ? (
        <>
          {planFields.panels.map((beat, i) => (
            <div key={i} className="flex flex-col gap-1.5">
              <Label htmlFor={`image-plan-panel-${i}`}>
                {t("preview.media.panel", { n: i + 1 })}
              </Label>
              <Textarea
                id={`image-plan-panel-${i}`}
                value={beat}
                onChange={(e) =>
                  setPlanFields((prev) => {
                    const panels = [...prev.panels];
                    panels[i] = e.target.value;
                    return { ...prev, panels };
                  })
                }
                disabled={busy}
                rows={2}
              />
            </div>
          ))}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="image-plan-style">{t("preview.media.style")}</Label>
            <Textarea
              id="image-plan-style"
              value={planFields.style}
              onChange={(e) => setPlanFields((prev) => ({ ...prev, style: e.target.value }))}
              disabled={busy}
              rows={2}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="image-plan-prompt">{t("preview.media.additionalPrompt")}</Label>
            <Textarea
              id="image-plan-prompt"
              value={planFields.prompt}
              onChange={(e) => setPlanFields((prev) => ({ ...prev, prompt: e.target.value }))}
              disabled={busy}
              rows={3}
            />
          </div>
        </>
      ) : (
        <>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="image-plan-prompt">{t("preview.media.prompt")}</Label>
            <Textarea
              id="image-plan-prompt"
              value={planFields.prompt}
              onChange={(e) => setPlanFields((prev) => ({ ...prev, prompt: e.target.value }))}
              disabled={busy}
              rows={4}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="image-plan-style">{t("preview.media.style")}</Label>
            <Textarea
              id="image-plan-style"
              value={planFields.style}
              onChange={(e) => setPlanFields((prev) => ({ ...prev, style: e.target.value }))}
              disabled={busy}
              rows={2}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="image-plan-composition">{t("preview.media.composition")}</Label>
            <Textarea
              id="image-plan-composition"
              value={planFields.composition}
              onChange={(e) =>
                setPlanFields((prev) => ({
                  ...prev,
                  composition: e.target.value,
                }))
              }
              disabled={busy}
              rows={2}
            />
          </div>
        </>
      )}
    </div>
  ) : (
    <p className="text-sm text-muted-foreground">{t("preview.media.empty")}</p>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[min(92dvh,820px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="shrink-0 border-b border-border px-6 py-4 pr-12 text-left">
          <DialogTitle>{t("preview.media.editTitle")}</DialogTitle>
          <DialogDescription>{t("preview.media.editHint")}</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden px-6 py-4">
          {/* Top: image slot navbar */}
          <div className="shrink-0">
            <MediaSlotStrip
              media={mediaList}
              selectedId={selected?.id ?? null}
              busy={busy}
              onSelect={(m) => {
                setSelectedId(m.id);
                setPlanFields(planFromMedia(m));
              }}
              onAdd={() => void handleAddImage()}
            />
          </div>

          {/* Bottom: form (left) + preview (right) */}
          <div className="grid min-h-0 flex-1 gap-4 overflow-hidden md:grid-cols-2">
            <div className="flex min-h-0 min-w-0 flex-col gap-3">
              <div className="min-h-0 flex-1 overflow-y-auto">{formFields}</div>
              <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-border pt-3">
                <Button
                  type="button"
                  size="sm"
                  disabled={!selected || busy}
                  onClick={() => void handleGenerate()}
                >
                  {hasRenderable ? (
                    <RefreshCw className="size-4" aria-hidden />
                  ) : (
                    <Sparkles className="size-4" aria-hidden />
                  )}
                  {busy ? t("preview.media.regenWorking") : primaryLabel}
                </Button>
                {canDelete ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => void handleDelete()}
                  >
                    <Trash2 className="size-4 text-destructive" />
                    <span className="text-destructive">{t("preview.media.delete")}</span>
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="min-w-0 shrink-0 md:overflow-y-auto">{previewPane}</div>
          </div>
        </div>

        <DialogFooter className="shrink-0 border-t border-border px-6 py-4">
          <div className="flex w-full flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={handleCancel}>
              {t("preview.media.cancel")}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!selected || !planDirty || busy}
              onClick={() => void handleSavePlan()}
            >
              {t("preview.media.savePlan")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
