import type * as React from "react";
import { cn } from "@/lib/utils";

type Props = Omit<React.ComponentProps<"button">, "children"> & {
  active: boolean;
  label: string;
};

/** Settings nav button. A hidden medium-weight copy of the label reserves the
 *  active width, so switching tabs doesn't shift the row. */
export function SettingsNavItem({ active, label, className, ...props }: Props) {
  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      className={cn(
        "inline-grid shrink-0 rounded-lg px-3 py-2.5 text-left text-sm whitespace-nowrap transition-colors",
        active
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
        className,
      )}
      {...props}
    >
      <span className={cn("col-start-1 row-start-1", active && "font-medium")}>{label}</span>
      <span aria-hidden className="invisible col-start-1 row-start-1 font-medium">
        {label}
      </span>
    </button>
  );
}
