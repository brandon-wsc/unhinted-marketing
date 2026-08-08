import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/context/auth-context";
import {
  apiAdminGetSessionResearch,
  type ResearchTurn,
  type SessionResearch,
} from "@/features/admin/api";

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-HK", { hour12: false });
}

function flag(v: boolean | null | undefined): string {
  if (v === true) return "true";
  if (v === false) return "false";
  return "—";
}

type Props = {
  initialSessionId?: string;
  onOpenTurn?: (turnId: string) => void;
};

export function ResearchPanel({ initialSessionId = "", onOpenTurn }: Props) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [sessionInput, setSessionInput] = useState(initialSessionId);
  const [sessionId, setSessionId] = useState(initialSessionId.trim());
  const [data, setData] = useState<SessionResearch | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ResearchTurn | null>(null);

  useEffect(() => {
    if (initialSessionId.trim()) {
      setSessionInput(initialSessionId);
      setSessionId(initialSessionId.trim());
    }
  }, [initialSessionId]);

  const load = useCallback(async () => {
    const id = sessionId.trim();
    if (!id) {
      setData(null);
      setSelected(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const next = await apiAdminGetSessionResearch(accessToken, id);
      setData(next);
      setSelected(next.turns[0] ?? null);
    } catch (err) {
      setData(null);
      setSelected(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [accessToken, sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <label
          htmlFor="admin-research-filter-session"
          className="flex min-w-[16rem] flex-1 flex-col gap-1 text-xs text-muted-foreground"
        >
          {t("admin.filters.sessionId")}
          <Input
            id="admin-research-filter-session"
            value={sessionInput}
            onChange={(e) => setSessionInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") setSessionId(sessionInput.trim());
            }}
            placeholder={t("admin.research.placeholder")}
            className="font-mono text-xs"
          />
        </label>
        <Button type="button" onClick={() => setSessionId(sessionInput.trim())}>
          {t("admin.research.load")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => void load()}
          disabled={loading || !sessionId}
          aria-label={t("admin.filters.refresh")}
        >
          <RefreshCw className={loading ? "size-4 animate-spin" : "size-4"} />
        </Button>
      </div>

      {error ? (
        <p className="text-sm text-destructive">
          {t("admin.loadFailed")}: {error}
        </p>
      ) : null}

      {!sessionId && !loading ? (
        <p className="text-sm text-muted-foreground">{t("admin.research.empty")}</p>
      ) : null}

      {loading && !data ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : null}

      {data && data.turns.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("admin.research.noTurns")}</p>
      ) : null}

      {data && data.turns.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="overflow-x-auto rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("admin.table.time")}</TableHead>
                  <TableHead>{t("admin.research.semantic")}</TableHead>
                  <TableHead>{t("admin.research.rulePass")}</TableHead>
                  <TableHead>{t("admin.research.queries")}</TableHead>
                  <TableHead>{t("admin.research.hits")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.turns.map((turn) => (
                  <TableRow
                    key={turn.turn_id}
                    className={
                      selected?.turn_id === turn.turn_id
                        ? "cursor-pointer bg-muted/50"
                        : "cursor-pointer"
                    }
                    onClick={() => setSelected(turn)}
                  >
                    <TableCell className="whitespace-nowrap text-xs">
                      {formatTime(turn.created_at)}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {turn.semantic_route ?? "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {flag(turn.research_rule_pass)}
                    </TableCell>
                    <TableCell className="text-xs">
                      {turn.search_queries.length
                        ? turn.search_queries.length
                        : turn.search_query
                          ? 1
                          : 0}
                    </TableCell>
                    <TableCell className="text-xs">{turn.signals.length}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {selected ? (
            <div className="space-y-3 rounded-lg border border-border bg-card p-4 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-semibold">{t("admin.research.turnDetail")}</h2>
                {onOpenTurn ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onOpenTurn(selected.turn_id)}
                  >
                    {t("admin.openNodeSteps")}
                  </Button>
                ) : null}
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                <dt className="text-muted-foreground">{t("admin.table.turnId")}</dt>
                <dd className="break-all font-mono">{selected.turn_id}</dd>
                <dt className="text-muted-foreground">{t("admin.research.semantic")}</dt>
                <dd className="font-mono">{selected.semantic_route ?? "—"}</dd>
                <dt className="text-muted-foreground">{t("admin.research.rulePass")}</dt>
                <dd className="font-mono">{flag(selected.research_rule_pass)}</dd>
                <dt className="text-muted-foreground">{t("admin.research.needFacts")}</dt>
                <dd className="font-mono">{flag(selected.need_facts)}</dd>
                <dt className="text-muted-foreground">{t("admin.research.askClarify")}</dt>
                <dd className="font-mono">{flag(selected.ask_clarify)}</dd>
                <dt className="text-muted-foreground">{t("admin.research.entity")}</dt>
                <dd>{selected.entity_surface ?? "—"}</dd>
                <dt className="text-muted-foreground">{t("admin.research.ingest")}</dt>
                <dd className="font-mono">{flag(selected.ran_research_ingest)}</dd>
              </dl>

              <div>
                <h3 className="mb-1 text-xs font-semibold text-muted-foreground">
                  {t("admin.research.queries")}
                </h3>
                {(selected.search_queries.length
                  ? selected.search_queries
                  : selected.search_query
                    ? [selected.search_query]
                    : []
                ).length === 0 ? (
                  <p className="text-xs text-muted-foreground">{t("admin.research.noQueries")}</p>
                ) : (
                  <ul className="list-inside list-disc space-y-1 font-mono text-xs">
                    {(selected.search_queries.length
                      ? selected.search_queries
                      : [selected.search_query!]
                    ).map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                )}
              </div>

              <div>
                <h3 className="mb-1 text-xs font-semibold text-muted-foreground">
                  {t("admin.research.signals")}
                </h3>
                {selected.signals.length === 0 ? (
                  <p className="text-xs text-muted-foreground">{t("admin.research.noSignals")}</p>
                ) : (
                  <ul className="space-y-2">
                    {selected.signals.map((s) => (
                      <li
                        key={s.signal_id}
                        className="rounded-md border border-border px-2 py-1.5 text-xs"
                      >
                        <div className="flex flex-wrap gap-2">
                          <span className="rounded bg-muted px-1.5 py-0.5 font-mono">
                            {s.source || "?"}
                          </span>
                          <span className="font-medium">{s.title || s.signal_id}</span>
                        </div>
                        {s.query ? (
                          <p className="mt-0.5 font-mono text-muted-foreground">q: {s.query}</p>
                        ) : null}
                        {s.url ? (
                          <a
                            href={s.url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-0.5 block truncate text-primary underline-offset-2 hover:underline"
                          >
                            {s.url}
                          </a>
                        ) : null}
                        {s.excerpt ? (
                          <p className="mt-1 line-clamp-3 text-muted-foreground">{s.excerpt}</p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
