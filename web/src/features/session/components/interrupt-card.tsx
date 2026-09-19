import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { FormatToggle, type ImageFormat } from "@/features/session/components/format-toggle";

type Props = {
  sending: boolean;
  defaultFormat?: ImageFormat | null;
  onResume: (format?: ImageFormat) => void;
};

function fallbackFormat(recommended: ImageFormat | null | undefined): ImageFormat {
  return recommended === "comic_4panel" ? "comic_4panel" : "single";
}

export function InterruptCard({ sending, defaultFormat = "single", onResume }: Props) {
  const { t } = useTranslation();
  const [format, setFormat] = useState<ImageFormat>(() => fallbackFormat(defaultFormat));
  useEffect(() => {
    setFormat(fallbackFormat(defaultFormat));
  }, [defaultFormat]);
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 text-sm shadow-sm">
      <div>
        <p className="font-medium text-foreground">{t("chat.agent.interrupt.title")}</p>
        <p className="mt-0.5 text-muted-foreground">{t("chat.agent.interrupt.subtitle")}</p>
      </div>
      <FormatToggle
        value={format}
        onChange={setFormat}
        disabled={sending}
        groupLabel={t("chat.agent.interrupt.formatLabel")}
      />
      <p className="text-xs text-muted-foreground">{t("chat.agent.interrupt.lateSwitchHint")}</p>
      <Button
        type="button"
        loading={sending}
        className="shrink-0 self-start"
        onClick={() => onResume(format)}
      >
        {sending ? t("chat.agent.interrupt.working") : t("chat.agent.interrupt.confirm")}
      </Button>
    </div>
  );
}
