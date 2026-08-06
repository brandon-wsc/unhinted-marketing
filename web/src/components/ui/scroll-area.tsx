import { ScrollArea as ScrollAreaPrimitive } from "radix-ui";
import type * as React from "react";

import { cn } from "@/lib/utils";

function ScrollArea({
  className,
  children,
  hideScrollbar = false,
  viewportRef,
  onViewportScroll,
  viewportClassName,
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.Root> & {
  /** When true, keep native/touch scroll but render no visible scrollbar. */
  hideScrollbar?: boolean;
  viewportRef?: React.Ref<HTMLDivElement>;
  onViewportScroll?: React.UIEventHandler<HTMLDivElement>;
  viewportClassName?: string;
}) {
  return (
    <ScrollAreaPrimitive.Root
      data-slot="scroll-area"
      className={cn("relative", className)}
      {...props}
    >
      <ScrollAreaPrimitive.Viewport
        data-slot="scroll-area-viewport"
        ref={viewportRef}
        onScroll={onViewportScroll}
        // Radix defaults to inline overflow:hidden (breaks arrow scrollBy).
        // Force auto so horizontal strips can scroll; hide visible bars via CSS.
        style={
          hideScrollbar
            ? {
                // Override Radix's overflowX/Y:hidden when no visible scrollbar is mounted.
                overflowX: "auto",
                overflowY: "hidden",
              }
            : undefined
        }
        className={cn(
          "size-full rounded-[inherit] transition-[color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1",
          hideScrollbar &&
            "[scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden",
          viewportClassName,
        )}
      >
        {children}
      </ScrollAreaPrimitive.Viewport>
      {hideScrollbar ? (
        // Enables Radix scrollbarXEnabled (content metrics) without showing a bar.
        <ScrollBar
          orientation="horizontal"
          className="pointer-events-none absolute h-0 max-h-0 border-0 p-0 opacity-0"
          aria-hidden
        />
      ) : (
        <>
          <ScrollBar />
          <ScrollBar orientation="horizontal" />
        </>
      )}
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  );
}

function ScrollBar({
  className,
  orientation = "vertical",
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>) {
  return (
    <ScrollAreaPrimitive.ScrollAreaScrollbar
      data-slot="scroll-area-scrollbar"
      orientation={orientation}
      className={cn(
        "flex touch-none p-px transition-colors select-none",
        orientation === "vertical" && "h-full w-2.5 border-l border-l-transparent",
        orientation === "horizontal" && "h-2.5 flex-col border-t border-t-transparent",
        className,
      )}
      {...props}
    >
      <ScrollAreaPrimitive.ScrollAreaThumb
        data-slot="scroll-area-thumb"
        className="relative flex-1 rounded-full bg-border"
      />
    </ScrollAreaPrimitive.ScrollAreaScrollbar>
  );
}

export { ScrollArea, ScrollBar };
