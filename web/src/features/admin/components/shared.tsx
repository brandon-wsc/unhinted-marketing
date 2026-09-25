import { X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@/components/icon-button";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { useContainerWidth } from "@/hooks/use-container-width";

/** Content-based split breakpoint for admin record pages (Penpot System master-detail). */
export const ADMIN_SPLIT_MIN_WIDTH = 1100;

/** Pane floors for the resizable record split; detail opens at ≤300px. */
const ADMIN_SPLIT = { listMin: 320, detailMin: 260, detailDefaultMax: 300 } as const;
const SPLIT_HIT_TARGET = { coarse: 7, fine: 7 } as const;

function splitRatioKey(key: string): string {
  return `unhinted.adminDetailSplit.${key}`;
}

function readSplitRatio(key: string): number | null {
  if (typeof localStorage === "undefined") return null;
  try {
    const raw = localStorage.getItem(splitRatioKey(key));
    const ratio = raw == null ? Number.NaN : Number(raw);
    return Number.isFinite(ratio) && ratio > 0 && ratio < 1 ? ratio : null;
  } catch {
    return null;
  }
}

/**
 * Resizable master-detail split for wide admin containers. The detail
 * pane mounts only on row selection at min(300px, ⅓ container); its card
 * border is the visible seam and the transparent handle next to it is the
 * drag target. The dragged ratio persists per `storageKey`.
 */
export function DetailSplit({
  list,
  detail,
  storageKey,
}: {
  list: ReactNode;
  /** Detail card content; `null` leaves the list at full width. */
  detail: ReactNode | null;
  /** localStorage key suffix for the persisted detail width ratio. */
  storageKey: string;
}) {
  const { t } = useTranslation();
  const { ref, width } = useContainerWidth();
  const [ratio, setRatio] = useState<number | null>(() => readSplitRatio(storageKey));
  const detailPx = Math.min(
    Math.max(
      ratio == null ? Math.min(ADMIN_SPLIT.detailDefaultMax, width / 3) : width * ratio,
      ADMIN_SPLIT.detailMin,
    ),
    Math.max(ADMIN_SPLIT.detailMin, width - ADMIN_SPLIT.listMin),
  );

  return (
    <div ref={ref}>
      <ResizablePanelGroup
        id={`admin-split-${storageKey}`}
        orientation="horizontal"
        resizeTargetMinimumSize={SPLIT_HIT_TARGET}
        onLayoutChanged={(layout, meta) => {
          if (!meta.isUserInteraction) return;
          const listSize = layout["admin-list"] ?? 0;
          const detailSize = layout["admin-detail"] ?? 0;
          const sum = listSize + detailSize;
          if (sum <= 0) return;
          const next = detailSize / sum;
          setRatio(next);
          try {
            localStorage.setItem(splitRatioKey(storageKey), String(next));
          } catch {}
        }}
      >
        <ResizablePanel id="admin-list" minSize={ADMIN_SPLIT.listMin} className="min-w-0">
          <div className={detail ? "pr-3" : undefined}>{list}</div>
        </ResizablePanel>
        {detail ? (
          <>
            <ResizableHandle aria-label={t("admin.detail.resize")} className="bg-transparent" />
            <ResizablePanel
              id="admin-detail"
              minSize={ADMIN_SPLIT.detailMin}
              defaultSize={detailPx}
              className="min-w-0"
            >
              {detail}
            </ResizablePanel>
          </>
        ) : null}
      </ResizablePanelGroup>
    </div>
  );
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-HK", { hour12: false });
}

export function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 4)}…${id.slice(-4)}` : id;
}

export function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-[13px] font-medium text-foreground">{children}</dd>
    </div>
  );
}

export function DetailBlock({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
      <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-secondary p-3 text-xs text-foreground">
        {value}
      </pre>
    </div>
  );
}

/** Inline detail card used in desktop master-detail splits. */
export function DetailShell({
  title,
  loading,
  onClose,
  actions,
  children,
}: {
  title: string;
  loading: boolean;
  onClose: () => void;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <div className="flex items-center gap-2">
          {actions}
          <IconButton
            size="icon"
            className="size-7"
            onClick={onClose}
            aria-label={t("admin.detail.close")}
          >
            <X className="size-4" />
          </IconButton>
        </div>
      </div>
      {loading ? (
        <div className="flex justify-center py-10">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      ) : (
        children
      )}
    </section>
  );
}

/** Right-sheet detail for narrow/mobile master-detail layouts. */
export function DetailSheetShell({
  title,
  loading,
  open,
  onOpenChange,
  actions,
  children,
}: {
  title: string;
  loading: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[92vw] overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          {actions}
        </SheetHeader>
        {loading ? (
          <div className="flex justify-center py-10">
            <Spinner className="size-5 text-muted-foreground" />
          </div>
        ) : (
          <div className="mt-4">{children}</div>
        )}
      </SheetContent>
    </Sheet>
  );
}

export function DetailPager({
  offset,
  count,
  pageSize,
  loading,
  onOffset,
}: {
  offset: number;
  count: number;
  pageSize: number;
  loading: boolean;
  onOffset: (offset: number) => void;
}) {
  const { t } = useTranslation();
  const from = count > 0 ? offset + 1 : 0;
  const to = offset + count;
  return (
    <div className="mt-3 flex items-center justify-between">
      <p className="text-xs text-muted-foreground">{t("admin.pagination.showing", { from, to })}</p>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={offset === 0 || loading}
          onClick={() => onOffset(Math.max(0, offset - pageSize))}
        >
          {t("admin.pagination.prev")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={count < pageSize || loading}
          onClick={() => onOffset(offset + pageSize)}
        >
          {t("admin.pagination.next")}
        </Button>
      </div>
    </div>
  );
}
