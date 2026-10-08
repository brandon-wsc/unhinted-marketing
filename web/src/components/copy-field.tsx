import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copyText } from "@/lib/copy-text";
import { cn } from "@/lib/utils";

/**
 * Read-only value + copy button with copied feedback. Wrap in `FormField`
 * for label/hint. Stacks above `sm`; pass `className="flex-row"` to keep
 * the button beside the input.
 */
export function CopyField({
  id,
  value,
  className,
  copyLabel,
  copiedLabel,
}: {
  id?: string;
  value: string;
  className?: string;
  copyLabel?: string;
  copiedLabel?: string;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <div className={cn("flex flex-col gap-2 sm:flex-row", className)}>
      <Input id={id} value={value} readOnly className="flex-1" />
      <Button
        type="button"
        variant="outline"
        className={copied ? "text-success" : undefined}
        onClick={() => {
          void copyText(value).then(setCopied);
        }}
      >
        {copied ? (copiedLabel ?? t("common.copied")) : (copyLabel ?? t("common.copy"))}
      </Button>
    </div>
  );
}
