import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { RecommendedQuestion } from "@/features/session/types";

type Props = {
  questions: RecommendedQuestion[];
  loading: boolean;
  generating: boolean;
  failed: boolean;
  disabled?: boolean;
  onSelect: (question: RecommendedQuestion) => void;
  onRetry: () => void;
};

export function RecommendedQuestions({
  questions,
  loading,
  generating,
  failed,
  disabled,
  onSelect,
  onRetry,
}: Props) {
  const { t } = useTranslation();

  if (loading && questions.length === 0 && !failed) {
    return <p className="mt-8 text-sm text-muted-foreground">{t("chat.questions.loading")}</p>;
  }

  if (failed && questions.length === 0) {
    return (
      <div className="mt-8 flex flex-col items-center gap-3">
        <p className="text-sm text-muted-foreground">{t("chat.questions.failed")}</p>
        <Button type="button" variant="outline" size="sm" onClick={onRetry} disabled={disabled}>
          {t("chat.questions.retry")}
        </Button>
      </div>
    );
  }

  if (questions.length === 0 && !generating) return null;

  return (
    <div className="mt-8 w-full max-w-xl text-left">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("chat.questions.title")}
        </p>
        {generating ? (
          <p className="text-[11px] text-muted-foreground">{t("chat.questions.generating")}</p>
        ) : null}
      </div>
      {questions.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("chat.questions.loading")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {questions.map((q) => (
            <li key={q.id}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onSelect(q)}
                className="w-full rounded-xl border border-border bg-card px-4 py-3 text-left text-sm leading-relaxed transition hover:border-voice-border hover:bg-accent focus:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="block">{q.text}</span>
                {q.rationale && (
                  <span className="mt-1 block text-xs text-voice">{q.rationale}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
