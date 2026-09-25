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
import {
  ADMIN_SPLIT_MIN_WIDTH,
  DetailSheetShell,
  DetailShell,
  formatTime,
  Meta,
  shortId,
} from "@/features/admin/components/shared";
import { useContainerWidth } from "@/hooks/use-container-width";

function flag(v: boolean | null | undefined): string {
  if (v === true) return "true";
  if (v === false) return "false";
  return "—";
}

function turnQueries(turn: ResearchTurn): string[] {
  if (turn.search_queries.length) return turn.search_queries;
  return turn.search_query ? [turn.search_query] : [];
}

function TurnDetailContent({ turn }: { turn: ResearchTurn }) {
  const { t } = useTranslation();
  const queries = turnQueries(turn);
  return (
    <div className="space-y-3">
      <dl className="flex flex-wrap gap-x-7 gap-y-3">
        <Meta label={t("admin.research.semantic")}>
          <span className="font-mono">{turn.semantic_route ?? "—"}</span>
        </Meta>
        <Meta label={t("admin.research.rulePass")}>
          <span className="font-mono">{flag(turn.research_rule_pass)}</span>
        </Meta>
        <Meta label={t("admin.research.needFacts")}>
          <span className="font-mono">{flag(turn.need_facts)}</span>
        </Meta>
        <Meta label={t("admin.research.querySource")}>
          <span className="font-mono">{turn.query_source ?? "—"}</span>
        </Meta>
        <Meta label={t("admin.table.turnId")}>
          <span className="font-mono" title={turn.turn_id}>
            {shortId(turn.turn_id)}
          </span>
        </Meta>
        <Meta label={t("admin.research.askClarify")}>
          <span className="font-mono">{flag(turn.ask_clarify)}</span>
        </Meta>
        <Meta label={t("admin.research.entity")}>
          <span className="font-mono">{turn.entity_surface ?? "—"}</span>
        </Meta>
        <Meta label={t("admin.research.ingest")}>
          <span className="font-mono">{flag(turn.ran_research_ingest)}</span>
        </Meta>
        <Meta label={t("admin.research.signalsTrusted")}>
          <span className="font-mono">{flag(turn.signals_trusted)}</span>
        </Meta>
      </dl>

      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">
          {t("admin.research.queries")}
        </p>
        {queries.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("admin.research.noQueries")}</p>
        ) : (
          <ul className="list-inside list-disc space-y-1 font-mono text-[13px]">
            {queries.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">
          {t("admin.research.signals")}
        </p>
        {turn.signals.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("admin.research.noSignals")}</p>
        ) : (
          <ul className="space-y-2">
            {turn.signals.map((s) => (
              <li key={s.signal_id} className="rounded-md border border-border px-3 py-2.5 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-secondary px-1.5 py-0.5 font-mono text-secondary-foreground">
                    {s.source || "?"}
                  </span>
                  <span className="font-medium">{s.title || s.signal_id}</span>
                </div>
                {s.query ? (
                  <p className="mt-1 font-mono text-muted-foreground">q: {s.query}</p>
                ) : null}
                {s.url ? (
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 block truncate text-primary underline-offset-2 hover:underline"
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
  );
}

function TurnsTable({
  turns,
  loading,
  selectedId,
  onSelect,
}: {
  turns: ResearchTurn[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (turn: ResearchTurn) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="relative min-h-[18rem] overflow-hidden rounded-xl border border-border bg-card">
      {loading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-card/70 backdrop-blur-[1px]">
          <Spinner className="size-6 text-primary" />
        </div>
      )}
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
          {!loading && turns.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                {t("admin.research.noTurns")}
              </TableCell>
            </TableRow>
          )}
          {turns.map((turn) => (
            <TableRow
              key={turn.turn_id}
              className="cursor-pointer"
              data-state={selectedId === turn.turn_id ? "selected" : undefined}
              onClick={() => onSelect(turn)}
            >
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {turn.created_at ? formatTime(turn.created_at) : "—"}
              </TableCell>
              <TableCell className="font-mono text-xs text-foreground">
                {turn.semantic_route ?? "—"}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {flag(turn.research_rule_pass)}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {turnQueries(turn).length}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">{turn.signals.length}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

type Props = {
  initialSessionId?: string;
  onOpenTurn?: (turnId: string) => void;
};

export function ResearchPanel({ initialSessionId = "", onOpenTurn }: Props) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const { ref, width } = useContainerWidth();
  const split = width >= ADMIN_SPLIT_MIN_WIDTH;

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

  const selectTurn = useCallback((turn: ResearchTurn) => {
    setSelected((cur) => (cur?.turn_id === turn.turn_id ? null : turn));
  }, []);

  const detailActions =
    selected && onOpenTurn ? (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onOpenTurn(selected.turn_id)}
      >
        {t("admin.openNodeSteps")}
      </Button>
    ) : undefined;

  return (
    <div ref={ref} className="space-y-4">
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
        <p className="rounded-lg bg-destructive-soft px-3 py-2 text-sm text-destructive-foreground">
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

      {data ? (
        split && selected ? (
          <div className="flex items-start gap-6">
            <div className="w-[480px] shrink-0">
              <TurnsTable
                turns={data.turns}
                loading={loading}
                selectedId={selected.turn_id}
                onSelect={selectTurn}
              />
            </div>
            <div className="min-w-0 flex-1">
              <DetailShell
                title={t("admin.research.turnDetail")}
                loading={false}
                onClose={() => setSelected(null)}
                actions={detailActions}
              >
                <TurnDetailContent turn={selected} />
              </DetailShell>
            </div>
          </div>
        ) : (
          <TurnsTable
            turns={data.turns}
            loading={loading}
            selectedId={selected?.turn_id ?? null}
            onSelect={selectTurn}
          />
        )
      ) : null}

      {!split && (
        <DetailSheetShell
          title={t("admin.research.turnDetail")}
          loading={false}
          open={selected !== null}
          onOpenChange={(open) => {
            if (!open) setSelected(null);
          }}
          actions={detailActions}
        >
          {selected && <TurnDetailContent turn={selected} />}
        </DetailSheetShell>
      )}
    </div>
  );
}
