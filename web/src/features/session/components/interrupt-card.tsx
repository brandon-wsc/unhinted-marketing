import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

type Props = {
  sending: boolean;
  onResume: () => void;
  onDiscard: () => void;
};

export function InterruptCard({ sending, onResume, onDiscard }: Props) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 text-sm shadow-sm">
      <div>
        <p className="font-medium text-foreground">{t("chat.agent.interrupt.title")}</p>
        <p className="mt-0.5 text-muted-foreground">{t("chat.agent.interrupt.subtitle")}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={sending} onClick={onDiscard}>
          {t("chat.agent.interrupt.discard")}
        </Button>
        <Button type="button" loading={sending} className="shrink-0" onClick={() => onResume()}>
          {sending ? t("chat.agent.interrupt.working") : t("chat.agent.interrupt.confirm")}
        </Button>
      </div>
    </div>
  );
}
