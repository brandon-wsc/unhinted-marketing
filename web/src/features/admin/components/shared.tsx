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

/** Pane floors for the resizable record split; list starts at `defaultListSize` px. */
const ADMIN_SPLIT = { listMin: 320, detailMin: 340 } as const;
const SPLIT_HIT_TARGET = { coarse: 7, fine: 7 } as const;

function splitRatioKey(key: string): string {
  return `unhinted.adminSplit.${key}`;
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
 * Persistent resizable master-detail split for wide admin containers.
 * Both panes stay mounted (empty detail renders a placeholder) so picking
 * a row never reflows the list; the divider drag ratio persists per key.
 */
export function DetailSplit({
  list,
  detail,
  storageKey,
  defaultListSize,
}: {
  list: ReactNode;
  /** Detail card content; `null` renders an empty-selection placeholder. */
  detail: ReactNode | null;
  /** localStorage key suffix for the persisted list/detail width ratio. */
  storageKey: string;
  /** Resting list width in px before the user drags the divider. */
  defaultListSize: number;
}) {
  const { t } = useTranslation();
  const { ref, width } = useContainerWidth();
  const [ratio, setRatio] = useState<number | null>(() => readSplitRatio(storageKey));
  const listPx = Math.min(
    Math.max(ratio == null ? defaultListSize : width * ratio, ADMIN_SPLIT.listMin),
    Math.max(ADMIN_SPLIT.listMin, width - ADMIN_SPLIT.detailMin),
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
          const next = listSize / sum;
          setRatio(next);
          try {
            localStorage.setItem(splitRatioKey(storageKey), String(next));
          } catch {}
        }}
      >
        <ResizablePanel
          id="admin-list"
          minSize={ADMIN_SPLIT.listMin}
          defaultSize={listPx}
          className="min-w-0"
        >
          <div className="pr-3">{list}</div>
        </ResizablePanel>
        <ResizableHandle withHandle aria-label={t("admin.detail.resize")} />
        <ResizablePanel id="admin-detail" minSize={ADMIN_SPLIT.detailMin} className="min-w-0">
          <div className="pl-3">
            {detail ?? (
              <section className="rounded-xl border border-dashed border-border p-5">
                <p className="text-sm text-muted-foreground">{t("admin.detail.selectRow")}</p>
              </section>
            )}
          </div>
        </ResizablePanel>
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
