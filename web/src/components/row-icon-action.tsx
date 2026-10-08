import type { ReactNode } from "react";
import { IconButton } from "@/components/icon-button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** Tooltip-wrapped icon button for table row actions. */
export function RowIconAction({
  label,
  onClick,
  disabled,
  loading,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <IconButton
          type="button"
          className="size-8"
          disabled={disabled}
          loading={loading}
          aria-label={label}
          onClick={onClick}
        >
          {loading ? null : children}
        </IconButton>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}
