import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@/components/icon-button";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";

/** Content-based split breakpoint for admin record pages (Penpot System master-detail). */
export const ADMIN_SPLIT_MIN_WIDTH = 1100;

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
  children,
}: {
  title: string;
  loading: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <IconButton
          size="icon"
          className="size-7"
          onClick={onClose}
          aria-label={t("admin.detail.close")}
        >
          <X className="size-4" />
        </IconButton>
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
  children,
}: {
  title: string;
  loading: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
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
