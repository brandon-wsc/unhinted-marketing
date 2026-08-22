import type * as React from "react";

import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-16 w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-2 text-base break-words shadow-xs transition-[color,box-shadow,border-color] outline-none placeholder:text-muted-foreground not-read-only:hover:border-voice-border not-read-only:focus-visible:border-ring not-read-only:focus-visible:ring-1 not-read-only:focus-visible:ring-ring not-read-only:focus-visible:hover:border-ring read-only:cursor-default read-only:resize-none read-only:bg-secondary disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-input aria-invalid:border-destructive aria-invalid:ring-destructive/20 md:text-sm dark:bg-input/30 dark:read-only:bg-secondary dark:aria-invalid:ring-destructive/40",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
