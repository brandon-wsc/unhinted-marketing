import type { ReactNode } from "react";
import type { ImagePlan } from "@/features/session/session-helpers";

type Props = {
  plan: ImagePlan;
  /** Format line — each surface supplies its own label copy. */
  formatLabel?: ReactNode;
};

/** Plan body shared by the preview summary and the chat image-park card. */
export function ImagePlanFields({ plan, formatLabel }: Props) {
  return (
    <div className="space-y-1.5 leading-relaxed">
      {formatLabel}
      {plan.prompt ? (
        <p className="whitespace-pre-wrap text-muted-foreground">{plan.prompt}</p>
      ) : null}
      {plan.beats.length > 0 ? (
        <ol className="list-decimal space-y-0.5 pl-5 text-muted-foreground">
          {plan.beats.map((beat) => (
            <li key={beat}>{beat}</li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}
