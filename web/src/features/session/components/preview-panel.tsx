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
import type { ConfirmSessionResponse, DraftCopy, PreviewDraft } from "@/features/session/types";

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

  async function handleApply() {
    if (!dirty || busy) return;
    await onApply(local);
  }

  async function handleConfirm() {
    if (busy) return;
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

  const hint = !hasImage
    ? t("preview.gate.imageRequired")
    : confirmError === "social_account_not_connected"
      ? t("preview.gate.notConnected")
      : t("preview.confirmHint");

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
            <p className="text-sm font-semibold">{t("preview.title")}</p>
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
          {dirty && !confirmed && (
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
            imageUrls={previewUrls}
            onEditImage={confirmed ? undefined : () => setEditImageOpen(true)}
            onEditCopy={confirmed ? undefined : () => setEditCopyOpen(true)}
          />
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
        ) : (
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
