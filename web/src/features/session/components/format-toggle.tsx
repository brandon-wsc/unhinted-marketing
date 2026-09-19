import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { ImageFormat } from "@/features/session/session-helpers";

export type { ImageFormat };

type Props = {
  value: ImageFormat;
  onChange: (format: ImageFormat) => void;
  disabled?: boolean;
  groupLabel: string;
};

export function FormatToggle({ value, onChange, disabled, groupLabel }: Props) {
  const { t } = useTranslation();
  return (
    <fieldset className="m-0 flex min-w-0 flex-wrap gap-2 border-0 p-0">
      <legend className="sr-only">{groupLabel}</legend>
      <Button
        type="button"
        size="sm"
        variant={value === "single" ? "default" : "outline"}
        disabled={disabled}
        onClick={() => onChange("single")}
        aria-pressed={value === "single"}
      >
        {t("chat.agent.interrupt.formatSingle")}
      </Button>
      <Button
        type="button"
        size="sm"
        variant={value === "comic_4panel" ? "default" : "outline"}
        disabled={disabled}
        onClick={() => onChange("comic_4panel")}
        aria-pressed={value === "comic_4panel"}
      >
        {t("chat.agent.interrupt.formatComic")}
      </Button>
    </fieldset>
  );
}
