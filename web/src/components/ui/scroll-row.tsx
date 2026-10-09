import { ChevronLeft, ChevronRight } from "lucide-react";
import type * as React from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import type { HorizontalOverflow } from "@/hooks/use-horizontal-overflow";
import { cn } from "@/lib/utils";

/** Row shell for a horizontally scrolling child: chevrons appear only while it overflows. */
function ScrollRow({
  overflow,
  className,
  children,
}: {
  overflow: Pick<HorizontalOverflow, "start" | "end" | "overflowing" | "scroll">;
  className?: string;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  const chevron = (dir: -1 | 1) => (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      tabIndex={-1}
      className="size-8 shrink-0 text-muted-foreground"
      disabled={dir < 0 ? !overflow.start : !overflow.end}
      aria-label={t(dir < 0 ? "common.scrollLeft" : "common.scrollRight")}
      onClick={() => overflow.scroll(dir)}
    >
      {dir < 0 ? <ChevronLeft /> : <ChevronRight />}
    </Button>
  );
  return (
    <div data-slot="scroll-row" className={cn("flex max-w-full min-w-0 items-center", className)}>
      {overflow.overflowing && chevron(-1)}
      {children}
      {overflow.overflowing && chevron(1)}
    </div>
  );
}

export { ScrollRow };
