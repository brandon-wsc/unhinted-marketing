import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { DraftCopy, PreviewDraft } from "@/features/session/types";

type Props = {
  copy: DraftCopy;
  imageUrl: string | null;
  accountName?: string;
};

function isRenderableImageUrl(url: string | null): url is string {
  if (!url) return false;
  return url.startsWith("http://") || url.startsWith("https://") || url.startsWith("/");
}

export function IgPreviewMock({ copy, imageUrl, accountName = "unhinted" }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const captionBody = useMemo(() => {
    const parts = [copy.caption.trim()];
    if (copy.cta.trim()) parts.push(copy.cta.trim());
    if (copy.hashtags.length) parts.push(copy.hashtags.join(" "));
    return parts.filter(Boolean).join("\n\n");
  }, [copy]);

  const collapsed = captionBody.length > 120 && !expanded;
  const shown = collapsed ? `${captionBody.slice(0, 120).trimEnd()}…` : captionBody;
  const showImage = isRenderableImageUrl(imageUrl);

  return (
    <div className="mx-auto w-full max-w-[340px]">
      <div className="overflow-hidden rounded-[28px] border border-[var(--color-border)] bg-[var(--color-card)] shadow-sm">
        <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-3 py-2.5">
          <div className="h-8 w-8 rounded-full bg-gradient-to-br from-amber-400 via-rose-500 to-violet-600 p-[2px]">
            <div className="h-full w-full rounded-full bg-[var(--color-card)]" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{accountName}</p>
            <p className="truncate text-[11px] text-[var(--color-muted)]">
              {t("preview.mock.sponsored")}
            </p>
          </div>
        </div>

        <div className="relative aspect-square w-full bg-[var(--color-background)]">
          {showImage ? (
            <img src={imageUrl} alt="" className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full w-full flex-col items-center justify-center gap-2 px-6 text-center">
              <div className="h-16 w-16 rounded-2xl border border-dashed border-[var(--color-border)] bg-[var(--color-card)]" />
              <p className="text-xs text-[var(--color-muted)]">{t("preview.mock.placeholder")}</p>
            </div>
          )}
        </div>

        <div className="space-y-2 px-3 py-3">
          <div className="flex gap-3 text-[var(--color-muted)]">
            <HeartIcon />
            <CommentIcon />
            <ShareIcon />
          </div>
          <p className="text-sm leading-relaxed">
            <span className="font-semibold">{accountName}</span>{" "}
            <span className="whitespace-pre-wrap">{shown}</span>
            {collapsed && (
              <button
                type="button"
                className="ml-1 text-[var(--color-muted)]"
                onClick={() => setExpanded(true)}
              >
                {t("preview.mock.more")}
              </button>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

export function draftEquals(a: DraftCopy, b: DraftCopy): boolean {
  return (
    a.caption === b.caption &&
    a.cta === b.cta &&
    a.hashtags.join("\0") === b.hashtags.join("\0")
  );
}

export function toEditableCopy(draft: PreviewDraft | null): DraftCopy {
  return {
    caption: draft?.copy.caption ?? "",
    hashtags: draft?.copy.hashtags ?? [],
    cta: draft?.copy.cta ?? "",
  };
}

function HeartIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 21s-6.5-4.2-9-8.2C1.2 9.9 2.4 6.5 5.5 5.4 7.4 4.7 9.5 5.3 12 7.5c2.5-2.2 4.6-2.8 6.5-2.1 3.1 1.1 4.3 4.5 2.5 7.4C18.5 16.8 12 21 12 21Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}

function CommentIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M7 18.5 4 21V7.5A3.5 3.5 0 0 1 7.5 4h9A3.5 3.5 0 0 1 20 7.5v7a3.5 3.5 0 0 1-3.5 3.5H7Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}

function ShareIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 12v6.5A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V12M12 3v12M8 7l4-4 4 4"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
