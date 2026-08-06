import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
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
  const [local, setLocal] = useState<DraftCopy>(() => toEditableCopy(draft));
  const [editImageOpen, setEditImageOpen] = useState(false);
  const [editCopyOpen, setEditCopyOpen] = useState(false);

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
  const busy = draftSaving || confirming;
  const canConfirm = !!draft.approval_token && !confirmed && local.caption.trim().length > 0;
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

  return (
    <aside
      className={`flex min-h-0 flex-1 flex-col overflow-hidden border-border bg-background ${
        paged ? "" : "border-l"
      }`}
    >
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          {paged && onBack && (
            <button
              type="button"
              onClick={onBack}
              className="flex h-8 shrink-0 items-center gap-1 rounded-full px-2 text-sm text-muted-foreground transition hover:bg-accent hover:text-foreground"
              aria-label={t("chat.mobile.back")}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                <path
                  d="M10 3.5 5.5 8 10 12.5"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              {t("chat.mobile.back")}
            </button>
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
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5 text-sm">
            <p className="font-medium">{t("preview.confirmDone")}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t("preview.confirmReceipt", {
                status: confirmReceipt?.status ?? "confirmed",
              })}
            </p>
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
