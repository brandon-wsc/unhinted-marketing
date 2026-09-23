import { ChevronLeft } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { IconButton } from "@/components/icon-button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/context/auth-context";
import { apiPromoteVoiceExemplar } from "@/features/company-settings/api";
import { EditCopyDialog } from "@/features/session/components/edit-copy-dialog";
import { EditImageDialog } from "@/features/session/components/edit-image-dialog";
import {
  draftEquals,
  IgPreviewMock,
  isRenderableImageUrl,
  toEditableCopy,
} from "@/features/session/components/ig-preview-mock";
import { isConfirmSuccessStatus } from "@/features/session/session-helpers";
import type {
  ConfirmSessionResponse,
  DraftCopy,
  PreviewDraft,
  PreviewMediaItem,
} from "@/features/session/types";

type PreviewPhase = "accepted" | "pending" | "generating";

type Props = {
  draft: PreviewDraft;
  confirmed: boolean;
  confirmReceipt: ConfirmSessionResponse | null;
  draftSaving: boolean;
  confirming: boolean;
  companyId?: string;
  canPromoteExemplar?: boolean;
  confirmError?: string | null;
  onApply: (copy: DraftCopy) => Promise<unknown>;
  onConfirm: (copy: DraftCopy) => Promise<unknown>;
  onSavePlan: (
    imageId: string,
    plan: Record<string, unknown>,
  ) => Promise<PreviewDraft | null | unknown>;
  onRegenImage: (imageId: string) => Promise<unknown>;
  onAddImage: (format?: "single" | "comic_4panel") => Promise<PreviewDraft | null | unknown>;
  onRemoveImage: (imageId: string) => Promise<PreviewDraft | null | unknown>;
  onUploadImage: (imageId: string, file: File) => Promise<PreviewDraft | null | unknown>;
  /** When true, show back affordance (paged shell); split shell hides it. */
  paged?: boolean;
  onBack?: () => void;
  /**
   * Session is parked at image OK (`awaiting_image_ok`). With no ready primary
   * image, the Instagram frame stays and the image slot waits (待出圖).
   */
  awaitingImage?: boolean;
  /** Execute / resume-image is in flight. Spinner inside the same image slot. */
  imageGenerating?: boolean;
};

export function PreviewPanel({
  draft,
  confirmed,
  confirmReceipt,
  draftSaving,
  confirming,
  companyId,
  canPromoteExemplar = false,
  confirmError = null,
  onApply,
  onConfirm,
  onSavePlan,
  onRegenImage,
  onAddImage,
  onRemoveImage,
  onUploadImage,
  paged = false,
  onBack,
  awaitingImage = false,
  imageGenerating = false,
}: Props) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [local, setLocal] = useState<DraftCopy>(() => toEditableCopy(draft));
  const [editImageOpen, setEditImageOpen] = useState(false);
  const [editCopyOpen, setEditCopyOpen] = useState(false);
  const [promoting, setPromoting] = useState(false);
  const [promoteFlash, setPromoteFlash] = useState<"ok" | "dup" | "err" | null>(null);
  const [promoteError, setPromoteError] = useState<string | null>(null);

  // Server wins on SSE / AI revise — reset local dirty state.
  useEffect(() => {
    setLocal(toEditableCopy(draft));
  }, [
    draft.revision,
    draft.approval_token,
    draft.copy.caption,
    draft.copy.cta,
    draft.copy.hashtags,
  ]);

  useEffect(() => {
    if (confirmed) {
      setEditImageOpen(false);
      setEditCopyOpen(false);
    }
  }, [confirmed]);

  const dirty = !draftEquals(local, draft.copy);
  const busy = draftSaving || confirming || promoting;
  const previewUrls = useMemo(() => {
    const fromMedia = [...(draft.media ?? [])]
      .sort((a, b) => a.seq - b.seq)
      .map((m) => m.url)
      .filter(isRenderableImageUrl);
    if (fromMedia.length > 0) return fromMedia;
    return isRenderableImageUrl(draft.image_url) ? [draft.image_url] : [];
  }, [draft.media, draft.image_url]);
  const hasImage =
    (draft.media ?? []).some((item) => isRenderableImageUrl(item.url)) ||
    isRenderableImageUrl(draft.image_url);
  const canConfirm =
    !!draft.approval_token && !confirmed && local.caption.trim().length > 0 && hasImage;
  const failedReceipt = confirmReceipt?.status === "failed";
  const showReceipt =
    confirmed || (!!confirmReceipt && isConfirmSuccessStatus(confirmReceipt.status));
  const showFailed = failedReceipt && !confirmed;
  const showPromote =
    canPromoteExemplar && !!companyId && showReceipt && local.caption.trim().length > 0;
  const phase: PreviewPhase =
    !showReceipt && !showFailed && awaitingImage && !primaryImageReady(draft)
      ? imageGenerating
        ? "generating"
        : "pending"
      : "accepted";
  const actionsLocked = phase !== "accepted";

  async function handleApply() {
    if (actionsLocked || !dirty || busy) return;
    await onApply(local);
  }

  async function handleConfirm() {
    if (actionsLocked || busy) return;
    if (showFailed || canConfirm) await onConfirm(local);
  }

  async function handleSaveCopy(copy: DraftCopy) {
    setLocal(copy);
    await onApply(copy);
  }

  async function handlePromoteExemplar() {
    if (!showPromote || !companyId || promoting) return;
    setPromoting(true);
    setPromoteFlash(null);
    setPromoteError(null);
    try {
      const res = await apiPromoteVoiceExemplar(accessToken, companyId, local.caption);
      setPromoteFlash(res.added ? "ok" : "dup");
      window.setTimeout(() => setPromoteFlash(null), 3000);
    } catch (err) {
      setPromoteFlash("err");
      setPromoteError(err instanceof Error ? err.message : String(err));
    } finally {
      setPromoting(false);
    }
  }

  const hint = actionsLocked
    ? t("preview.awaiting.status")
    : !hasImage
      ? t("preview.gate.imageRequired")
      : confirmError === "social_account_not_connected"
        ? t("preview.gate.notConnected")
        : t("preview.confirmHint");
  const title =
    phase === "generating"
      ? t("preview.awaiting.generatingTitle")
      : phase === "pending"
        ? t("preview.awaiting.title")
        : t("preview.title");

  return (
    <aside className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          {paged && onBack && (
            <Tooltip>
              <TooltipTrigger asChild>
                <IconButton
                  type="button"
                  className="size-8"
                  onClick={onBack}
                  aria-label={t("chat.mobile.back")}
                >
                  <ChevronLeft />
                </IconButton>
              </TooltipTrigger>
              <TooltipContent side="bottom">{t("chat.mobile.back")}</TooltipContent>
            </Tooltip>
          )}
          <div className="min-w-0">
            <p className="text-sm font-semibold">{title}</p>
            <p className="text-xs text-muted-foreground">
              {t("preview.revision", { n: draft.revision })} · {draft.platform}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {showReceipt && (
            <span className="rounded-md border border-success/30 bg-success-soft px-2 py-0.5 text-[11px] text-success-foreground">
              {t("preview.receipt.publishedBadge")}
            </span>
          )}
          {dirty && !confirmed && phase === "accepted" && (
            <span className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
              {t("preview.dirty")}
            </span>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex flex-col gap-5 px-4 py-5">
          <IgPreviewMock
            copy={local}
            imageUrls={phase === "accepted" ? previewUrls : []}
            imageSlot={phase === "accepted" ? undefined : phase}
            onEditImage={
              phase === "accepted" && !confirmed ? () => setEditImageOpen(true) : undefined
            }
            onEditCopy={
              phase === "accepted" && !confirmed ? () => setEditCopyOpen(true) : undefined
            }
          />
          {phase !== "accepted" && <ImagePlanSummary draft={draft} />}
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-card px-4 py-3">
        {showReceipt ? (
          <div className="space-y-2">
            <ReceiptSuccess receipt={confirmReceipt} />
            {showPromote && (
              <div className="flex flex-col gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  disabled={promoting}
                  onClick={() => void handlePromoteExemplar()}
                  className="border-voice-border text-voice hover:enabled:bg-voice-soft hover:enabled:text-voice"
                >
                  {promoting ? t("preview.exemplar.working") : t("preview.exemplar.save")}
                </Button>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  {t("preview.exemplar.hint")}
                </p>
                {promoteFlash === "ok" && (
                  <p className="text-xs text-foreground">{t("preview.exemplar.saved")}</p>
                )}
                {promoteFlash === "dup" && (
                  <p className="text-xs text-muted-foreground">{t("preview.exemplar.already")}</p>
                )}
                {promoteFlash === "err" && (
                  <p className="text-xs text-destructive">{promoteError}</p>
                )}
              </div>
            )}
          </div>
        ) : showFailed ? (
          <div className="space-y-2">
            <Alert variant="destructive" className="border-destructive/30 bg-destructive-soft">
              <AlertTitle>{t("preview.receipt.failedTitle")}</AlertTitle>
              <AlertDescription>
                <p>
                  {confirmReceipt?.error_kind
                    ? t(`preview.receipt.error.${confirmReceipt.error_kind}`, {
                        defaultValue: t("preview.receipt.failedHint"),
                      })
                    : t("preview.receipt.failedHint")}
                </p>
              </AlertDescription>
            </Alert>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button
                type="button"
                disabled={busy || !hasImage}
                onClick={() => void handleConfirm()}
              >
                {confirming ? t("preview.confirmWorking") : t("preview.receipt.retry")}
              </Button>
            </div>
          </div>
        ) : actionsLocked && confirmError !== "social_account_not_connected" ? null : (
          <div className="space-y-2">
            {confirmError === "social_account_not_connected" && (
              <Alert variant="destructive" className="border-destructive/30 bg-destructive-soft">
                <AlertDescription>
                  <span>{t("preview.gate.notConnected")} </span>
                  <Link
                    to="/settings?tab=instagram"
                    className="font-medium text-destructive-foreground underline-offset-4 hover:underline"
                  >
                    {t("preview.gate.openSettings")}
                  </Link>
                </AlertDescription>
              </Alert>
            )}
            {!actionsLocked && (
              <div className="flex flex-wrap items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  disabled={!dirty || busy}
                  onClick={() => void handleApply()}
                >
                  {draftSaving ? t("preview.applySaving") : t("preview.apply")}
                </Button>
                <Button
                  type="button"
                  disabled={!canConfirm || busy}
                  onClick={() => void handleConfirm()}
                >
                  {confirming ? t("preview.confirmWorking") : t("preview.confirm")}
                </Button>
              </div>
            )}
          </div>
        )}
        {!showReceipt && confirmError !== "social_account_not_connected" && (
          <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{hint}</p>
        )}
      </div>

      {!confirmed && (
        <>
          <EditImageDialog
            open={editImageOpen}
            onOpenChange={setEditImageOpen}
            draft={draft}
            busy={busy}
            onSavePlan={onSavePlan}
            onRegenImage={onRegenImage}
            onAddImage={onAddImage}
            onRemoveImage={onRemoveImage}
            onUploadImage={onUploadImage}
          />
          <EditCopyDialog
            open={editCopyOpen}
            onOpenChange={setEditCopyOpen}
            copy={local}
            busy={busy}
            onSave={handleSaveCopy}
          />
        </>
      )}
    </aside>
  );
}

function sortedMedia(draft: PreviewDraft): PreviewMediaItem[] {
  return [...(draft.media ?? [])].sort((a, b) => a.seq - b.seq);
}

function primaryMediaItem(draft: PreviewDraft): PreviewMediaItem | null {
  const media = sortedMedia(draft);
  if (media.length === 0) return null;
  return media.find((item) => item.role === "primary") ?? media[0];
}

/** A parked primary (`status: pending` or no renderable url) is not a ready post. */
function primaryImageReady(draft: PreviewDraft): boolean {
  const primary = primaryMediaItem(draft);
  if (primary) {
    if (primary.status === "pending") return false;
    return isRenderableImageUrl(primary.url);
  }
  return isRenderableImageUrl(draft.image_url);
}

function planSummary(draft: PreviewDraft): {
  format: "single" | "comic_4panel" | null;
  prompt: string;
  beats: string[];
} {
  const primary = primaryMediaItem(draft);
  const plan = primary?.plan ?? {};
  const fromPlan = typeof plan.format === "string" ? plan.format : "";
  const raw = primary?.format || fromPlan;
  const format = raw === "comic_4panel" || raw === "single" ? raw : null;
  const prompt = typeof plan.prompt === "string" ? plan.prompt.trim() : "";
  const beats: string[] = [];
  if (Array.isArray(plan.panels)) {
    for (const panel of plan.panels) {
      if (panel && typeof panel === "object" && "beat" in panel) {
        const beat = String((panel as { beat?: unknown }).beat ?? "").trim();
        if (beat) beats.push(beat);
      }
    }
  }
  return { format, prompt, beats };
}

function ImagePlanSummary({ draft }: { draft: PreviewDraft }) {
  const { t } = useTranslation();
  const plan = planSummary(draft);
  const formatLabel =
    plan.format === "comic_4panel"
      ? t("preview.awaiting.formatComic")
      : plan.format === "single"
        ? t("preview.awaiting.formatSingle")
        : null;
  const hasPlan = Boolean(formatLabel || plan.prompt || plan.beats.length);
  if (!hasPlan) return null;

  return (
    <details className="mx-auto w-full max-w-[340px] rounded-lg border border-border bg-card px-3 py-2.5 text-sm">
      <summary className="cursor-pointer select-none text-xs font-medium text-muted-foreground">
        {t("preview.awaiting.plan")}
      </summary>
      <div className="mt-2 space-y-1.5 leading-relaxed">
        {formatLabel ? <p>{formatLabel}</p> : null}
        {plan.prompt ? (
          <p className="whitespace-pre-wrap text-muted-foreground">{plan.prompt}</p>
        ) : null}
        {plan.beats.length > 0 ? (
          <ol className="list-decimal space-y-0.5 pl-5 text-muted-foreground">
            {plan.beats.map((beat, index) => (
              <li key={`${index}-${beat}`}>{beat}</li>
            ))}
          </ol>
        ) : null}
      </div>
    </details>
  );
}

function ReceiptSuccess({ receipt }: { receipt: ConfirmSessionResponse | null }) {
  const { t } = useTranslation();
  const published = receipt?.status === "published";
  const permalink = receipt?.permalink;
  return (
    <Alert variant="success">
      <AlertTitle>
        {published ? t("preview.receipt.publishedTitle") : t("preview.confirmDone")}
      </AlertTitle>
      <AlertDescription>
        {published ? (
          <p>{t("preview.receipt.publishedBody")}</p>
        ) : (
          <p>
            {t("preview.confirmReceipt", {
              status: receipt?.status ?? "confirmed",
            })}
          </p>
        )}
        {published && permalink && (
          <a
            href={permalink}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex h-8 items-center rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition hover:bg-accent"
          >
            {t("preview.receipt.viewOnInstagram")}
          </a>
        )}
      </AlertDescription>
    </Alert>
  );
}
