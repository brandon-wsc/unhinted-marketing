import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Ghost icon button defaults — history toolbar, password toggle, etc.
 *  Hover wash/text follow Button ghost (`accent` = voice). */
export function IconButton({ className, variant = "ghost", size = "icon", ...props }: ButtonProps) {
  return (
    <Button
      variant={variant}
      size={size}
      className={cn("shrink-0 text-muted-foreground", className)}
      {...props}
    />
  );
}
