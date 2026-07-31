import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/auth-layout";
import {
  draftEquals,
  IgPreviewMock,
  toEditableCopy,
} from "@/features/session/components/ig-preview-mock";
import type {
  ConfirmSessionResponse,
  DraftCopy,
  PreviewDraft,
} from "@/features/session/types";

type Props = {
  draft: PreviewDraft;
  confirmed: boolean;
  confirmReceipt: ConfirmSessionResponse | null;
  draftSaving: boolean;
  confirming: boolean;
  onApply: (copy: DraftCopy) => Promise<unknown>;
  onConfirm: (copy: DraftCopy) => Promise<unknown>;
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
  onBack,
}: Props) {
  const { t } = useTranslation();
  const [local, setLocal] = useState<DraftCopy>(() => toEditableCopy(draft));
  const [hashtagsText, setHashtagsText] = useState(() => draft.copy.hashtags.join(" "));

  // Server wins on SSE / AI revise — reset local dirty state.
  useEffect(() => {
    setLocal(toEditableCopy(draft));
    setHashtagsText(draft.copy.hashtags.join(" "));
  }, [draft.revision, draft.approval_token, draft.copy.caption, draft.copy.cta, draft.copy.hashtags]);

  const parsedHashtags = useMemo(
    () =>
      hashtagsText
        .split(/[\s,]+/)
        .map((h) => h.trim())
        .filter(Boolean)
        .map((h) => (h.startsWith("#") ? h : `#${h}`)),
    [hashtagsText],
  );

  const working: DraftCopy = {
    caption: local.caption,
    cta: local.cta,
    hashtags: parsedHashtags,
  };
  const dirty = !draftEquals(working, draft.copy);
  const busy = draftSaving || confirming;
  const canConfirm = !!draft.approval_token && !confirmed && working.caption.trim().length > 0;

  async function handleApply() {
    if (!dirty || busy) return;
    await onApply(working);
  }

  async function handleConfirm() {
    if (!canConfirm || busy) return;
    await onConfirm(working);
  }

  return (
    <aside className="flex min-h-0 flex-1 flex-col overflow-hidden border-[var(--color-border)] bg-[var(--color-background)] lg:border-l">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--color-border)] px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              className="flex h-8 shrink-0 items-center gap-1 rounded-full px-2 text-sm text-[var(--color-muted)] transition hover:bg-[var(--color-hover)] hover:text-[var(--color-foreground)] lg:hidden"
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
            <p className="text-xs text-[var(--color-muted)]">
              {t("preview.revision", { n: draft.revision })} · {draft.platform}
            </p>
          </div>
        </div>
        {dirty && !confirmed && (
          <span className="rounded-md border border-[var(--color-border)] px-2 py-0.5 text-[11px] text-[var(--color-muted)]">
            {t("preview.dirty")}
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex flex-col gap-5 px-4 py-5">
          <IgPreviewMock copy={working} imageUrl={draft.image_url} />

          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-[var(--color-muted)]">
                {t("preview.fields.caption")}
              </span>
              <textarea
                value={local.caption}
                onChange={(e) => setLocal((prev) => ({ ...prev, caption: e.target.value }))}
                rows={5}
                disabled={confirmed || busy}
                className="resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-ring)] focus:ring-2 focus:ring-[var(--color-ring)]/30 disabled:opacity-60"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-[var(--color-muted)]">
                {t("preview.fields.hashtags")}
              </span>
              <input
                value={hashtagsText}
                onChange={(e) => setHashtagsText(e.target.value)}
                disabled={confirmed || busy}
                placeholder="#HongKong #Marketing"
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-ring)] focus:ring-2 focus:ring-[var(--color-ring)]/30 disabled:opacity-60"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-[var(--color-muted)]">
                {t("preview.fields.cta")}
              </span>
              <input
                value={local.cta}
                onChange={(e) => setLocal((prev) => ({ ...prev, cta: e.target.value }))}
                disabled={confirmed || busy}
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-ring)] focus:ring-2 focus:ring-[var(--color-ring)]/30 disabled:opacity-60"
              />
            </label>
          </div>
        </div>
      </div>

      <div className="shrink-0 border-t border-[var(--color-border)] bg-[var(--color-card)] px-4 py-3">
        {confirmReceipt || confirmed ? (
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5 text-sm">
            <p className="font-medium">{t("preview.confirmDone")}</p>
            <p className="mt-0.5 text-xs text-[var(--color-muted)]">
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
            <Button type="button" disabled={!canConfirm || busy} onClick={() => void handleConfirm()}>
              {confirming ? t("preview.confirmWorking") : t("preview.confirm")}
            </Button>
          </div>
        )}
        <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-muted)]">
          {t("preview.confirmHint")}
        </p>
      </div>
    </aside>
  );
}
