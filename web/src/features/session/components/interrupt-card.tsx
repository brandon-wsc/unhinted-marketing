import { ChevronDown, Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@/components/icon-button";
import { Button } from "@/components/ui/button";
import { ImagePlanFields } from "@/features/session/components/image-plan-fields";
import type { ImagePlan } from "@/features/session/session-helpers";

type Props = {
  sending: boolean;
  onResume: () => void;
  onDiscard: () => void;
  /** Primary image plan awaiting OK — collapsed summary at the approve point. */
  plan?: ImagePlan | null;
  /** Pending caption, one-line preview — pencil opens the copy dialog. */
  copyPreview?: string | null;
  /** Opens the copy dialog — pending caption edits stay parked. */
  onEditCopy?: () => void;
  /** Opens the image plan dialog — direction changes re-stage and re-park. */
  onEditPlan?: () => void;
};

export function InterruptCard({
  sending,
  onResume,
  onDiscard,
  plan,
  copyPreview,
  onEditCopy,
  onEditPlan,
}: Props) {
  const { t } = useTranslation();
  const formatName =
    plan?.format === "comic_4panel"
      ? t("chat.agent.interrupt.formatComic")
      : plan?.format === "single"
        ? t("chat.agent.interrupt.formatSingle")
        : null;
  const hasPlan = Boolean(formatName || plan?.prompt || plan?.beats.length);
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-voice-border bg-card p-4 text-sm shadow-sm">
      <div>
        <p className="font-medium text-foreground">{t("chat.agent.interrupt.title")}</p>
        <p className="mt-0.5 text-muted-foreground">{t("chat.agent.interrupt.subtitle")}</p>
      </div>
      {onEditCopy ? (
        <div className="flex items-center gap-2 rounded-md border border-input px-3 py-2 text-xs transition hover:border-voice-border">
          <span className="shrink-0 font-medium text-foreground">
            {t("chat.agent.interrupt.copy")}
          </span>
          <span className="min-w-0 flex-1 truncate text-muted-foreground">
            {copyPreview?.trim() || "—"}
          </span>
          <IconButton
            type="button"
            className="-mr-1 size-6"
            disabled={sending}
            onClick={onEditCopy}
            aria-label={t("chat.agent.interrupt.editCopy")}
          >
            <Pencil className="size-3.5" aria-hidden />
          </IconButton>
        </div>
      ) : null}
      {hasPlan && plan ? (
        <details className="group rounded-md border border-input text-xs transition hover:border-voice-border">
          <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-2 font-medium [&::-webkit-details-marker]:hidden">
            <ChevronDown
              className="size-3.5 text-muted-foreground transition-transform group-open:rotate-180"
              aria-hidden
            />
            {t("chat.agent.interrupt.plan")}
            <span className="ml-auto flex items-center gap-1.5">
              {formatName ? (
                <span className="font-normal text-muted-foreground">{formatName}</span>
              ) : null}
              {onEditPlan ? (
                <IconButton
                  type="button"
                  className="size-6"
                  disabled={sending}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    onEditPlan();
                  }}
                  aria-label={t("chat.agent.interrupt.editPlan")}
                >
                  <Pencil className="size-3.5" aria-hidden />
                </IconButton>
              ) : null}
            </span>
          </summary>
          <div className="px-3 pb-2.5 pt-0.5">
            <ImagePlanFields plan={plan} />
          </div>
        </details>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
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
