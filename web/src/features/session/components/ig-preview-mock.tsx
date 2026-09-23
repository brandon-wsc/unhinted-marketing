import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Spinner } from "@/components/ui/spinner";
import type { DraftCopy, PreviewDraft } from "@/features/session/types";

/** Parked image wait inside the IG frame. Absent on an accepted preview. */
export type IgImageSlot = "pending" | "generating";

type Props = {
  copy: DraftCopy;
  /** All carousel slides (primary + extras). Empty → placeholder. */
  imageUrls: string[];
  accountName?: string;
  /** When set, image area is interactive — click opens editor. */
  onEditImage?: () => void;
  /** When set, caption area is clickable — opens copy editor. */
  onEditCopy?: () => void;
  /**
   * Honest wait in the image square. `pending` is a dashed empty slot;
   * `generating` is that same slot with a spinner.
   */
  imageSlot?: IgImageSlot;
};

export function isRenderableImageUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  // OpenRouter / LiteLLM often return data: URLs (b64) instead of https.
  return (
    url.startsWith("http://") ||
    url.startsWith("https://") ||
    url.startsWith("data:image/") ||
    url.startsWith("/")
  );
}

export function IgPreviewMock({
  copy,
  imageUrls,
  accountName = "unhinted",
  onEditImage,
  onEditCopy,
  imageSlot,
}: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [slide, setSlide] = useState(0);

  const urls = useMemo(() => imageUrls.filter(isRenderableImageUrl), [imageUrls]);

  useEffect(() => {
    setSlide((i) => (urls.length === 0 ? 0 : Math.min(i, urls.length - 1)));
  }, [urls]);

  const captionBody = useMemo(() => {
    const parts = [copy.caption.trim()];
    if (copy.cta.trim()) parts.push(copy.cta.trim());
    if (copy.hashtags.length) parts.push(copy.hashtags.join(" "));
    return parts.filter(Boolean).join("\n\n");
  }, [copy]);

  const besideAccount = useMemo(
    () => captionBesideAccount(captionBody, accountName),
    [captionBody, accountName],
  );
  const collapsed = besideAccount.length > 120 && !expanded;
  const shown = collapsed ? `${besideAccount.slice(0, 120).trimEnd()}…` : besideAccount;
  const captionEmpty = captionBody.trim().length === 0;
  const waiting = imageSlot === "pending" || imageSlot === "generating";
  const multi = !waiting && urls.length > 1;
  const imageEditable = !waiting && typeof onEditImage === "function";
  const copyEditable = typeof onEditCopy === "function";

  return (
    <div className="mx-auto w-full max-w-[340px]">
      <div className="overflow-hidden rounded-[28px] border border-border bg-card shadow-sm">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
          <div className="h-8 w-8 rounded-full bg-gradient-to-br from-amber-400 via-rose-500 to-violet-600 p-[2px]">
            <div className="h-full w-full rounded-full bg-card" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{accountName}</p>
            <p className="truncate text-[11px] text-muted-foreground">
              {t("preview.mock.sponsored")}
            </p>
          </div>
        </div>

        <div
          className={`relative aspect-square w-full bg-background${
            imageEditable
              ? " cursor-pointer transition hover:brightness-[0.97] focus-within:ring-2 focus-within:ring-ring focus-within:ring-inset"
              : ""
          }`}
        >
          {imageSlot ? (
            <WaitingImageSlot mode={imageSlot} />
          ) : urls.length > 0 ? (
            <div className="absolute inset-0 overflow-hidden">
              <div
                className="flex h-full transition-transform duration-300 ease-out"
                style={{ transform: `translateX(-${slide * 100}%)` }}
              >
                {urls.map((url, i) => (
                  <img
                    key={`${url}-${i}`}
                    src={url}
                    alt=""
                    className="h-full w-full shrink-0 object-cover"
                    draggable={false}
                  />
                ))}
              </div>
            </div>
          ) : (
            <div className="flex h-full w-full flex-col items-center justify-center gap-2 px-6 text-center">
              <div className="h-16 w-16 rounded-2xl border border-dashed border-border bg-card" />
              <p className="text-xs text-muted-foreground">{t("preview.mock.placeholder")}</p>
            </div>
          )}

          {imageEditable && (
            <button
              type="button"
              onClick={onEditImage}
              className="absolute inset-0 z-[1] bg-transparent focus-visible:outline-none"
              aria-label={t("preview.media.edit")}
            />
          )}

          {multi && (
            <>
              {slide > 0 && (
                <button
                  type="button"
                  className="absolute left-2 top-1/2 z-10 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full bg-black/45 text-white transition hover:bg-black/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                  aria-label={t("preview.media.scrollPrev")}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSlide((i) => Math.max(0, i - 1));
                  }}
                >
                  <ChevronLeftIcon />
                </button>
              )}
              {slide < urls.length - 1 && (
                <button
                  type="button"
                  className="absolute right-2 top-1/2 z-10 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full bg-black/45 text-white transition hover:bg-black/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                  aria-label={t("preview.media.scrollNext")}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSlide((i) => Math.min(urls.length - 1, i + 1));
                  }}
                >
                  <ChevronRightIcon />
                </button>
              )}
              <div className="absolute bottom-2.5 left-0 right-0 z-10 flex justify-center gap-1.5">
                {urls.map((_, i) => (
                  <button
                    key={i}
                    type="button"
                    aria-label={t("preview.media.slot", { n: i + 1 })}
                    aria-current={i === slide ? "true" : undefined}
                    className={`h-1.5 w-1.5 rounded-full transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white ${
                      i === slide ? "bg-white" : "bg-white/45 hover:bg-white/70"
                    }`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSlide(i);
                    }}
                  />
                ))}
              </div>
            </>
          )}
        </div>

        <div className="space-y-2 px-3 py-3">
          <div className="flex gap-3 text-muted-foreground">
            <HeartIcon />
            <CommentIcon />
            <ShareIcon />
          </div>
          {copyEditable ? (
            <div className="text-sm leading-relaxed">
              <button
                type="button"
                onClick={onEditCopy}
                className="-mx-1 w-[calc(100%+0.5rem)] rounded-md px-1 py-0.5 text-left transition hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={t("preview.copy.edit")}
              >
                <CaptionLine
                  accountName={accountName}
                  body={shown}
                  emptyLabel={captionEmpty ? t("preview.copy.empty") : undefined}
                />
              </button>
              {collapsed && (
                <button
                  type="button"
                  className="ml-1 text-muted-foreground"
                  onClick={() => setExpanded(true)}
                >
                  {t("preview.mock.more")}
                </button>
              )}
            </div>
          ) : (
            <p className="text-sm leading-relaxed">
              <CaptionLine accountName={accountName} body={shown} />
              {collapsed && (
                <button
                  type="button"
                  className="ml-1 text-muted-foreground"
                  onClick={() => setExpanded(true)}
                >
                  {t("preview.mock.more")}
                </button>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function draftEquals(a: DraftCopy, b: DraftCopy): boolean {
  return (
    a.caption === b.caption && a.cta === b.cta && a.hashtags.join("\0") === b.hashtags.join("\0")
  );
}

export function toEditableCopy(draft: PreviewDraft | null): DraftCopy {
  return {
    caption: draft?.copy.caption ?? "",
    hashtags: draft?.copy.hashtags ?? [],
    cta: draft?.copy.cta ?? "",
  };
}

/**
 * IG puts the account in bold, then the caption. If the copy already leads
 * with that same display name, peel it off so it is not repeated in plain text.
 */
export function captionBesideAccount(body: string, accountName: string): string {
  const name = accountName.trim();
  const text = body.trimStart();
  if (!name || text.length < name.length) return text;
  if (text.slice(0, name.length).toLocaleLowerCase() !== name.toLocaleLowerCase()) return text;
  const boundary = text[name.length];
  if (boundary !== undefined && !/[\s:：,，.。!！?？]/u.test(boundary)) return text;
  return text.slice(name.length).replace(/^[\s:：,，.。]+/u, "");
}

function CaptionLine({
  accountName,
  body,
  emptyLabel,
}: {
  accountName: string;
  body: string;
  emptyLabel?: string;
}) {
  const text = body || emptyLabel || "";
  return (
    <>
      <span className="font-bold">{accountName}</span>
      {text ? (
        <>
          {" "}
          <span className="whitespace-pre-wrap">{text}</span>
        </>
      ) : null}
    </>
  );
}

function WaitingImageSlot({ mode }: { mode: IgImageSlot }) {
  const { t } = useTranslation();
  const generating = mode === "generating";
  return (
    <div
      data-preview-state={mode}
      aria-busy={generating || undefined}
      className="absolute inset-3 flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-foreground/40 bg-card px-6 text-center text-foreground"
    >
      {generating ? <Spinner className="size-5 text-foreground" /> : null}
      <p className="text-sm font-semibold text-foreground">
        {generating ? t("preview.awaiting.slotGenerating") : t("preview.awaiting.slotEmpty")}
      </p>
    </div>
  );
}

function ChevronLeftIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M10 3.5 5.5 8 10 12.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChevronRightIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M6 3.5 10.5 8 6 12.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
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
        d="M21.4 3.6 3.2 10.4l7.2 2.9 2.9 7.2 8.1-16.9ZM21.4 3.6 10.4 13.3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
