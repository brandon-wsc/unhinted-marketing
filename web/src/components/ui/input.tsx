import * as React from "react";

import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        data-slot="input"
        className={cn(
          "h-9 w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow,border-color] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground not-read-only:hover:border-voice-border read-only:cursor-default read-only:bg-secondary disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-input md:text-sm dark:bg-input/30 dark:read-only:bg-secondary",
          "not-read-only:focus-visible:border-ring not-read-only:focus-visible:ring-1 not-read-only:focus-visible:ring-ring not-read-only:focus-visible:hover:border-ring",
          "aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40",
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
