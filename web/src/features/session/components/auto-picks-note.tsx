import { useTranslation } from "react-i18next";
import type { Session } from "@/features/session/types";

type SessionOrigin = NonNullable<Session["origin"]>;

// ADR 0051 §11 — what an external client's auto mode answered at the gates,
// so the user can revise (ADR 0036) or Discard before Confirm.
export function AutoPicksNote({ origin }: { origin: SessionOrigin }) {
  const { t } = useTranslation();
  const picks = origin.auto_picks;
  if (!picks) return null;
  const client = origin.client_name ?? t("chat.autoPicks.unknownClient");
  const parts: string[] = [];
  // angle_index is 0-based on the wire; the card numbers options from 1.
  if (picks.angle_index != null) {
    parts.push(t("chat.autoPicks.angle", { index: picks.angle_index + 1 }));
  }
  if (picks.persona) parts.push(picks.persona);
  if (picks.image_format) {
    parts.push(
      picks.image_format === "comic_4panel"
        ? t("chat.agent.formatComic")
        : t("chat.agent.formatSingle"),
    );
  }
  if (picks.image_approved) parts.push(t("chat.autoPicks.imageApproved"));
  return (
    <p className="rounded-lg border border-border bg-secondary px-3 py-2 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">{t("chat.autoPicks.title", { client })}</span>
      {parts.length > 0 && ` · ${parts.join(" · ")}`}
    </p>
  );
}
