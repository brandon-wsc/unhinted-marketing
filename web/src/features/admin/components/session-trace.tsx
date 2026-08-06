import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/context/auth-context";
import { apiAdminGetSessionTrace, type SessionTrace } from "@/features/admin/api";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-HK", { hour12: false });
}

type Props = {
  initialSessionId?: string;
  onOpenTurn?: (turnId: string) => void;
};

export function SessionTracePanel({ initialSessionId = "", onOpenTurn }: Props) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [sessionInput, setSessionInput] = useState(initialSessionId);
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [trace, setTrace] = useState<SessionTrace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRevision, setSelectedRevision] = useState<number | null>(null);

  useEffect(() => {
    if (initialSessionId) {
      setSessionInput(initialSessionId);
      setSessionId(initialSessionId);
    }
  }, [initialSessionId]);

  const load = useCallback(async () => {
    const id = sessionId.trim();
    if (!id) {
      setTrace(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await apiAdminGetSessionTrace(accessToken, id);
      setTrace(data);
      setSelectedRevision(data.draft_revisions[0]?.revision ?? null);
    } catch (err) {
      setTrace(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [accessToken, sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedDraft =
    trace?.draft_revisions.find((d) => d.revision === selectedRevision) ?? null;
  const grounded =
    selectedDraft == null
      ? []
      : trace?.signals.filter((s) =>
          (selectedDraft.source_signal_ids as string[]).includes(s.signal_id),
        ) ?? [];

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          {t("admin.filters.sessionId")}
          <Input
            type="text"
            value={sessionInput}
            onChange={(e) => setSessionInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") setSessionId(sessionInput.trim());
            }}
            placeholder={t("admin.sessionTrace.placeholder")}
            className="w-80 font-mono text-xs"
          />
        </label>
        <Button
          type="button"
          variant="outline"
          onClick={() => setSessionId(sessionInput.trim())}
        >
          {t("admin.sessionTrace.load")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => void load()}
          disabled={loading || !sessionId}
          aria-label={t("admin.filters.refresh")}
        >
          <RefreshCw className={loading ? "animate-spin" : ""} />
        </Button>
      </div>

      {error && (
        <p className="mb-3 rounded-lg bg-destructive-soft px-3 py-2 text-sm text-destructive-foreground">
          {t("admin.loadFailed")}: {error}
        </p>
      )}

      {loading && (
        <div className="flex justify-center py-16">
          <Spinner className="size-6 text-primary" />
        </div>
      )}

      {!loading && !trace && !error && (
        <p className="py-10 text-center text-sm text-muted-foreground">
          {t("admin.sessionTrace.empty")}
        </p>
      )}

      {trace && !loading && (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="space-y-4">
            <div className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">{t("admin.sessionTrace.summary")}</h2>
              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <dt className="text-muted-foreground">{t("admin.table.mode")}</dt>
                  <dd>
                    {trace.mode} · {trace.status}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{t("admin.sessionTrace.title")}</dt>
                  <dd>{trace.title || "—"}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-muted-foreground">ID</dt>
                  <dd className="font-mono text-[10px]">{trace.id}</dd>
                </div>
              </dl>
            </div>

            <div className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">{t("admin.sessionTrace.messages")}</h2>
              <ul className="max-h-80 space-y-2 overflow-y-auto">
                {trace.messages.length === 0 && (
                  <li className="text-xs text-muted-foreground">{t("admin.sessionTrace.noMessages")}</li>
                )}
                {trace.messages.map((m) => (
                  <li key={m.id} className="rounded-lg border border-border px-3 py-2 text-xs">
                    <div className="mb-1 flex justify-between text-muted-foreground">
                      <span className="font-medium text-foreground">{m.role}</span>
                      <span>{formatTime(m.created_at)}</span>
                    </div>
                    <p className="whitespace-pre-wrap text-foreground">{m.content}</p>
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">{t("admin.sessionTrace.revisions")}</h2>
              <ul className="space-y-2">
                {trace.draft_revisions.length === 0 && (
                  <li className="text-xs text-muted-foreground">{t("admin.sessionTrace.noRevisions")}</li>
                )}
                {trace.draft_revisions.map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedRevision(d.revision)}
                      className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition ${
                        selectedRevision === d.revision
                          ? "border-primary bg-primary/5"
                          : "border-border hover:bg-accent"
                      }`}
                    >
                      <div className="flex justify-between">
                        <span className="font-medium">
                          {t("admin.sessionTrace.revision", { n: d.revision })}
                        </span>
                        <span className="text-muted-foreground">{formatTime(d.created_at)}</span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-muted-foreground">
                        {String(
                          (d.draft_copy as { caption?: string }).caption ??
                            JSON.stringify(d.draft_copy),
                        )}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section className="space-y-4">
            <div className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">{t("admin.sessionTrace.grounding")}</h2>
              {selectedDraft == null ? (
                <p className="text-xs text-muted-foreground">{t("admin.sessionTrace.pickRevision")}</p>
              ) : grounded.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t("admin.sessionTrace.noSignals")}</p>
              ) : (
                <ul className="space-y-2">
                  {grounded.map((s) => (
                    <li key={s.signal_id} className="rounded-lg border border-border px-3 py-2 text-xs">
                      <p className="font-medium">{s.title}</p>
                      <p className="text-muted-foreground">
                        {s.source} · {s.signal_id}
                      </p>
                      {s.url && (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-primary underline-offset-2 hover:underline"
                        >
                          {s.url}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">{t("admin.sessionTrace.turns")}</h2>
              <ul className="space-y-3">
                {trace.turns.length === 0 && (
                  <li className="text-xs text-muted-foreground">{t("admin.sessionTrace.noTurns")}</li>
                )}
                {trace.turns.map((turn) => (
                  <li key={turn.turn_id} className="rounded-lg border border-border p-3 text-xs">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-[10px]">{turn.turn_id}</span>
                      {onOpenTurn && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => onOpenTurn(turn.turn_id)}
                        >
                          {t("admin.openNodeSteps")}
                        </Button>
                      )}
                    </div>
                    <ol className="space-y-1">
                      {turn.steps.map((s) => (
                        <li key={s.id}>
                          #{s.seq} {s.node}
                          {s.intent_out ? ` · ${s.intent_out}` : ""}
                        </li>
                      ))}
                    </ol>
                    {turn.llm_calls.length > 0 && (
                      <p className="mt-2 text-muted-foreground">
                        {t("admin.sessionTrace.llmCount", { n: turn.llm_calls.length })}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
