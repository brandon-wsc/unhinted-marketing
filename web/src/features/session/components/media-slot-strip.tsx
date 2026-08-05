import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { PreviewMediaItem } from "@/features/session/types";

type Props = {
  media: PreviewMediaItem[];
  selectedId: string | null;
  busy?: boolean;
  onSelect: (item: PreviewMediaItem) => void;
  onAdd: () => void;
};

function readScrollState(el: HTMLDivElement | null) {
  if (!el) return { canLeft: false, canRight: false };
  const { scrollLeft, clientWidth, scrollWidth } = el;
  return {
    canLeft: scrollLeft > 2,
    canRight: scrollLeft + clientWidth < scrollWidth - 2,
  };
}

/** Horizontal media slot strip: ScrollArea (hidden bar) + chevrons + add icon. */
export function MediaSlotStrip({
  media,
  selectedId,
  busy,
  onSelect,
  onAdd,
}: Props) {
  const { t } = useTranslation();
  const viewportRef = useRef<HTMLDivElement>(null);
  const [canLeft, setCanLeft] = useState(false);
  const [canRight, setCanRight] = useState(false);

  function syncScrollState() {
    const next = readScrollState(viewportRef.current);
    setCanLeft(next.canLeft);
    setCanRight(next.canRight);
  }

  useEffect(() => {
    syncScrollState();
    const el = viewportRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => syncScrollState());
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    return () => ro.disconnect();
  }, [media.length, selectedId]);

  function scrollByDir(dir: -1 | 1) {
    viewportRef.current?.scrollBy({ left: dir * 140, behavior: "smooth" });
  }

  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-8 shrink-0"
        disabled={busy || !canLeft}
        aria-label={t("preview.media.scrollPrev")}
        onClick={() => scrollByDir(-1)}
      >
        <ChevronLeft />
      </Button>

      <ScrollArea
        hideScrollbar
        viewportRef={viewportRef}
        onViewportScroll={syncScrollState}
        className="min-h-0 min-w-0 flex-1"
      >
        <div className="flex w-max items-center gap-2 px-0.5 py-0.5">
          {media.length === 0 ? (
            <span className="px-1 text-xs leading-8 text-muted-foreground">
              {t("preview.media.empty")}
            </span>
          ) : (
            media.map((m, i) => (
              <button
                key={m.id}
                type="button"
                disabled={busy}
                onClick={() => onSelect(m)}
                className={`shrink-0 rounded-md border px-2.5 py-1.5 text-xs leading-none transition ${
                  m.id === selectedId
                    ? "border-ring bg-accent"
                    : "border-border text-muted-foreground hover:bg-accent"
                }`}
              >
                {t("preview.media.slot", { n: i + 1 })}
                {m.status === "pending" ? ` · ${t("preview.media.pending")}` : ""}
              </button>
            ))
          )}
        </div>
      </ScrollArea>

      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-8 shrink-0"
        disabled={busy || !canRight}
        aria-label={t("preview.media.scrollNext")}
        onClick={() => scrollByDir(1)}
      >
        <ChevronRight />
      </Button>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            disabled={busy}
            aria-label={t("preview.media.add")}
            onClick={onAdd}
          >
            <Plus />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="top">{t("preview.media.add")}</TooltipContent>
      </Tooltip>
    </div>
  );
}
