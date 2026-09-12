import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

type Props = {
  sending: boolean;
  onResume: (format?: "single" | "comic_4panel") => void;
};

export function InterruptCard({ sending, onResume }: Props) {
  const { t } = useTranslation();
  const [format, setFormat] = useState<"single" | "comic_4panel">("single");
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-primary/40 bg-card p-4 text-sm shadow-sm">
      <div>
        <p className="font-medium text-foreground">{t("chat.agent.interrupt.title")}</p>
        <p className="mt-0.5 text-muted-foreground">{t("chat.agent.interrupt.subtitle")}</p>
      </div>
      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label={t("chat.agent.interrupt.formatLabel")}
      >
        <Button
          type="button"
          variant={format === "single" ? "default" : "outline"}
          disabled={sending}
          className={
            format === "single" ? "ring-2 ring-primary ring-offset-2 ring-offset-card" : undefined
          }
          onClick={() => setFormat("single")}
          aria-pressed={format === "single"}
        >
          {t("chat.agent.interrupt.formatSingle")}
        </Button>
        <Button
          type="button"
          variant={format === "comic_4panel" ? "default" : "outline"}
          disabled={sending}
          className={
            format === "comic_4panel"
              ? "ring-2 ring-primary ring-offset-2 ring-offset-card"
              : undefined
          }
          onClick={() => setFormat("comic_4panel")}
          aria-pressed={format === "comic_4panel"}
        >
          {t("chat.agent.interrupt.formatComic")}
        </Button>
      </div>
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
