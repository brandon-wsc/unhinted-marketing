import type { ReactNode } from "react";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type FormFieldProps = {
  id: string;
  label: ReactNode;
  children: ReactNode;
  className?: string;
  error?: ReactNode;
  /** Marks the label with a required asterisk; pair with `required` on the control. */
  required?: boolean;
};

/** Label + control stack for auth/admin forms. Pass an Input/Select/etc as children. */
export function FormField({ id, label, children, className, error, required }: FormFieldProps) {
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center gap-1">
        <Label htmlFor={id}>{label}</Label>
        {required ? (
          <span aria-hidden="true" className="text-destructive">
            *
          </span>
        ) : null}
      </div>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-sm text-destructive-foreground" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
