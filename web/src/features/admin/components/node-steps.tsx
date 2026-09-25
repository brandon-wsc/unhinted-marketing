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
  apiAdminGetNodeStep,
  apiAdminListNodeSteps,
  NODE_STEP_PAGE_SIZE,
  type NodeStepDetail,
  type NodeStepFilters,
  type NodeStepSummary,
} from "@/features/admin/api";
import {
  ADMIN_SPLIT_MIN_WIDTH,
  DetailBlock,
  DetailPager,
  DetailSheetShell,
  DetailShell,
  DetailSplit,
  formatTime,
  Meta,
  shortId,
} from "@/features/admin/components/shared";
import { useContainerWidth } from "@/hooks/use-container-width";

function StepDetailContent({
  detail,
  onOpenSession,
}: {
  detail: NodeStepDetail;
  onOpenSession?: (sessionId: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
        <Meta label={t("admin.table.node")}>{detail.node}</Meta>
        <Meta label={t("admin.table.seq")}>{detail.seq}</Meta>
        <Meta label={t("admin.table.time")}>{formatTime(detail.created_at)}</Meta>
        <Meta label={t("admin.table.mode")}>
          {detail.mode_in ?? "—"} → {detail.mode_out ?? "—"}
        </Meta>
      </dl>

      <div>
        <dt className="text-xs text-muted-foreground">{t("admin.table.turnId")}</dt>
        <dd className="mt-0.5 font-mono text-[10px] text-foreground" title={detail.turn_id}>
          {shortId(detail.turn_id)}
        </dd>
      </div>
      {detail.session_id && (
        <div className="flex items-center justify-between gap-2">
          <div>
            <dt className="text-xs text-muted-foreground">{t("admin.filters.sessionId")}</dt>
            <dd className="mt-0.5 font-mono text-[10px] text-foreground" title={detail.session_id}>
              {shortId(detail.session_id)}
            </dd>
          </div>
          {onOpenSession && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => onOpenSession(detail.session_id!)}
            >
              {t("admin.openSessionTrace")}
            </Button>
          )}
        </div>
      )}

      <DetailBlock
        label={t("admin.nodeStepDetail.output")}
        value={JSON.stringify(detail.output, null, 2)}
      />

      {detail.llm_calls.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            {t("admin.nodeStepDetail.llmCalls")}
          </p>
          <ul className="space-y-1 text-xs">
            {detail.llm_calls.map((c) => (
              <li key={c.id} className="rounded-lg bg-secondary px-2 py-1.5">
                {c.status} · {c.kind} · {c.model ?? "—"} · {c.total_tokens ?? "—"} tok
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function StepTable({
  items,
  loading,
  selectedId,
  onSelect,
}: {
  items: NodeStepSummary[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
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
            <TableHead>{t("admin.table.seq")}</TableHead>
            <TableHead>{t("admin.table.node")}</TableHead>
            <TableHead>{t("admin.table.mode")}</TableHead>
            <TableHead>{t("admin.table.intent")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {!loading && items.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                {t("admin.nodeStepsEmpty")}
              </TableCell>
            </TableRow>
          )}
          {items.map((row) => (
            <TableRow
              key={row.id}
              className="cursor-pointer"
              data-state={selectedId === row.id ? "selected" : undefined}
              onClick={() => onSelect(row.id)}
            >
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {formatTime(row.created_at)}
              </TableCell>
              <TableCell className="text-xs">{row.seq}</TableCell>
              <TableCell className="text-foreground">{row.node}</TableCell>
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {row.mode_in ?? "—"} → {row.mode_out ?? "—"}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {row.intent_out ?? "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

type Props = {
  initialTurnId?: string;
  onOpenSession?: (sessionId: string) => void;
};

export function NodeStepsPanel({ initialTurnId = "", onOpenSession }: Props) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const { ref, width } = useContainerWidth();
  const split = width >= ADMIN_SPLIT_MIN_WIDTH;

  const [nodeInput, setNodeInput] = useState("");
  const [sessionInput, setSessionInput] = useState("");
  const [turnInput, setTurnInput] = useState(initialTurnId);
  const [filters, setFilters] = useState<NodeStepFilters>({
    turnId: initialTurnId || undefined,
  });
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<NodeStepSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<NodeStepDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (initialTurnId) {
      setTurnInput(initialTurnId);
      setFilters((f) => ({ ...f, turnId: initialTurnId }));
    }
  }, [initialTurnId]);

  useEffect(() => {
    const handle = setTimeout(() => {
      setFilters({
        node: nodeInput.trim() || undefined,
        sessionId: sessionInput.trim() || undefined,
        turnId: turnInput.trim() || undefined,
      });
    }, 350);
    return () => clearTimeout(handle);
  }, [nodeInput, sessionInput, turnInput]);

  // Reset to the first page whenever the applied filters change.
  const [appliedFilters, setAppliedFilters] = useState(filters);
  if (appliedFilters !== filters) {
    setAppliedFilters(filters);
    setOffset(0);
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiAdminListNodeSteps(accessToken, filters, offset);
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [accessToken, filters, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    apiAdminGetNodeStep(accessToken, selectedId)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, selectedId]);

  const selectRow = useCallback((id: string) => {
    setSelectedId((cur) => (cur === id ? null : id));
  }, []);

  return (
    <div ref={ref}>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label
          htmlFor="admin-steps-filter-node"
          className="flex flex-col gap-1 text-xs text-muted-foreground"
        >
          {t("admin.filters.node")}
          <Input
            id="admin-steps-filter-node"
            type="text"
            value={nodeInput}
            onChange={(e) => setNodeInput(e.target.value)}
            placeholder={t("admin.filters.nodePlaceholder")}
            className="w-36"
          />
        </label>
        <label
          htmlFor="admin-steps-filter-session"
          className="flex flex-col gap-1 text-xs text-muted-foreground"
        >
          {t("admin.filters.sessionId")}
          <Input
            id="admin-steps-filter-session"
            type="text"
            value={sessionInput}
            onChange={(e) => setSessionInput(e.target.value)}
            className="w-56 font-mono text-xs"
          />
        </label>
        <label
          htmlFor="admin-steps-filter-turn"
          className="flex flex-col gap-1 text-xs text-muted-foreground"
        >
          {t("admin.filters.turnId")}
          <Input
            id="admin-steps-filter-turn"
            type="text"
            value={turnInput}
            onChange={(e) => setTurnInput(e.target.value)}
            className="w-56 font-mono text-xs"
          />
        </label>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => void load()}
          disabled={loading}
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

      {split ? (
        <DetailSplit
          storageKey="node-steps"
          defaultListSize={460}
          list={
            <>
              <StepTable
                items={items}
                loading={loading}
                selectedId={selectedId}
                onSelect={selectRow}
              />
              <DetailPager
                offset={offset}
                count={items.length}
                pageSize={NODE_STEP_PAGE_SIZE}
                loading={loading}
                onOffset={setOffset}
              />
            </>
          }
          detail={
            selectedId ? (
              <DetailShell
                title={t("admin.nodeStepDetail.title")}
                loading={detailLoading}
                onClose={() => setSelectedId(null)}
              >
                {detail && <StepDetailContent detail={detail} onOpenSession={onOpenSession} />}
              </DetailShell>
            ) : null
          }
        />
      ) : (
        <>
          <StepTable items={items} loading={loading} selectedId={selectedId} onSelect={selectRow} />
          <DetailPager
            offset={offset}
            count={items.length}
            pageSize={NODE_STEP_PAGE_SIZE}
            loading={loading}
            onOffset={setOffset}
          />
        </>
      )}

      {!split && (
        <DetailSheetShell
          title={t("admin.nodeStepDetail.title")}
          loading={detailLoading}
          open={selectedId !== null}
          onOpenChange={(open) => {
            if (!open) setSelectedId(null);
          }}
        >
          {detail && <StepDetailContent detail={detail} onOpenSession={onOpenSession} />}
        </DetailSheetShell>
      )}
    </div>
  );
}
