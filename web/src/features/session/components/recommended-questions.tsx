import { useTranslation } from "react-i18next";
import type { RecommendedQuestion } from "@/features/session/types";

type Props = {
  questions: RecommendedQuestion[];
  loading: boolean;
  isStale: boolean;
  disabled?: boolean;
  onSelect: (question: RecommendedQuestion) => void;
};

export function RecommendedQuestions({
  questions,
  loading,
  isStale,
  disabled,
  onSelect,
}: Props) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <p className="mt-8 text-sm text-muted-foreground">{t("chat.questions.loading")}</p>
    );
  }

  if (questions.length === 0) return null;

  return (
    <div className="mt-8 w-full max-w-xl text-left">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("chat.questions.title")}
        </p>
        {isStale && (
          <p className="text-[11px] text-muted-foreground">{t("chat.questions.stale")}</p>
        )}
      </div>
      <ul className="flex flex-col gap-2">
        {questions.map((q) => (
          <li key={q.id}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onSelect(q)}
              className="w-full rounded-xl border border-border bg-card px-4 py-3 text-left text-sm leading-relaxed transition hover:border-ring hover:bg-background focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="block">{q.text}</span>
              {q.rationale && (
                <span className="mt-1 block text-xs text-muted-foreground">{q.rationale}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
