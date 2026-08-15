import { ChevronLeft } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@/components/icon-button";
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
import type { ConfirmSessionResponse, DraftCopy, PreviewDraft } from "@/features/session/types";

type Props = {
  draft: PreviewDraft;
  confirmed: boolean;
  confirmReceipt: ConfirmSessionResponse | null;
  draftSaving: boolean;
  confirming: boolean;
  companyId?: string;
  canPromoteExemplar?: boolean;
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
  const canConfirm = !!draft.approval_token && !confirmed && local.caption.trim().length > 0;
  const showPromote =
    canPromoteExemplar &&
    !!companyId &&
    (confirmReceipt || confirmed) &&
    local.caption.trim().length > 0;
  const previewUrls = useMemo(() => {
    const fromMedia = [...(draft.media ?? [])]
      .sort((a, b) => a.seq - b.seq)
      .map((m) => m.url)
      .filter(isRenderableImageUrl);
    if (fromMedia.length > 0) return fromMedia;
    return isRenderableImageUrl(draft.image_url) ? [draft.image_url] : [];
  }, [draft.media, draft.image_url]);

  async function handleApply() {
    if (!dirty || busy) return;
    await onApply(local);
  }

  async function handleConfirm() {
    if (!canConfirm || busy) return;
    await onConfirm(local);
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

  return (
    <aside
      className={`flex min-h-0 flex-1 flex-col overflow-hidden border-border bg-background ${
        paged ? "" : "border-l"
      }`}
    >
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
        {dirty && !confirmed && (
          <span className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
            {t("preview.dirty")}
          </span>
        )}
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
        {confirmReceipt || confirmed ? (
          <div className="space-y-2">
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5 text-sm">
              <p className="font-medium">{t("preview.confirmDone")}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t("preview.confirmReceipt", {
                  status: confirmReceipt?.status ?? "confirmed",
                })}
              </p>
            </div>
            {showPromote && (
              <div className="flex flex-col gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  disabled={promoting}
                  onClick={() => void handlePromoteExemplar()}
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
        ) : (
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
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          {t("preview.confirmHint")}
        </p>
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
