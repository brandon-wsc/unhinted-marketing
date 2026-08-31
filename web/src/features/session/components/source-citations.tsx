import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { CitedSignal } from "@/features/session/types";

type Props = {
  signals: CitedSignal[];
};

export function SourceCitations({ signals }: Props) {
  const { t } = useTranslation();
  if (signals.length === 0) return null;

  return (
    <section className="rounded-xl border border-border bg-card p-4 text-sm shadow-sm">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("preview.sources.title")}
      </h2>
      <ul className="flex flex-col gap-3">
        {signals.map((signal) => (
          <li key={signal.signal_id} className="min-w-0">
            {signal.url ? (
              <a
                href={signal.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex max-w-full items-start gap-1.5 font-medium text-foreground hover:text-voice"
              >
                <span className="min-w-0 break-words">{signal.title}</span>
                <ExternalLink
                  className="mt-0.5 size-3.5 shrink-0 text-muted-foreground"
                  aria-hidden
                />
                <span className="sr-only">{t("preview.sources.open")}</span>
              </a>
            ) : (
              <p className="font-medium text-foreground">{signal.title}</p>
            )}
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {signal.source || t("preview.sources.unknownSource")}
            </p>
            {signal.excerpt ? (
              <p className="mt-1 leading-relaxed text-muted-foreground">{signal.excerpt}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
