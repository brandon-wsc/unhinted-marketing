import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  apiAdminGetLlmCall,
  apiAdminListLlmCalls,
  LLM_CALL_PAGE_SIZE,
  type LlmCallFilters,
  type LlmCallRecordDetail,
  type LlmCallRecordSummary,
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

const STATUS_OPTIONS = ["ok", "empty_response", "provider_error", "cancelled", "error"];
const SPLIT_MIN_WIDTH = ADMIN_SPLIT_MIN_WIDTH;
function formatLatency(ms: number | null): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

function formatUsd(usd: number | null): string {
  if (usd == null) return "—";
  return `$${usd.toFixed(4)}`;
}

function StatusBadge({ status }: { status: string }) {
  const className =
    status === "ok"
      ? "bg-success-soft text-success-foreground"
      : status === "provider_error" || status === "error"
        ? "bg-destructive-soft text-destructive-foreground"
        : "bg-voice-soft text-voice";
  return (
    <Badge variant="secondary" className={className}>
      {status}
    </Badge>
  );
}

function Flags({ row }: { row: LlmCallRecordSummary }) {
  const { t } = useTranslation();
  return (
    <span className="flex flex-wrap gap-1">
      {row.parse_ok === false && (
        <Badge className="border-transparent bg-destructive-soft text-destructive-foreground">
          {t("admin.badges.parseFailed")}
        </Badge>
      )}
      {row.fallback_used && (
        <Badge className="border-transparent bg-voice-soft text-voice">
          {t("admin.badges.fallback")}
        </Badge>
      )}
    </span>
  );
}

function DetailContent({
  detail,
  onOpenTurn,
  onOpenSession,
  onOpenResearch,
}: {
  detail: LlmCallRecordDetail;
  onOpenTurn?: (turnId: string) => void;
  onOpenSession?: (sessionId: string) => void;
  onOpenResearch?: (sessionId: string) => void;
}) {
  const { t } = useTranslation();
  const hasFlags = detail.parse_ok === false || detail.fallback_used;
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
        <Meta label={t("admin.table.time")}>{formatTime(detail.created_at)}</Meta>
        <Meta label={t("admin.detail.ttft")}>{formatLatency(detail.ttft_ms)}</Meta>
        <Meta label={t("admin.table.status")}>
          <StatusBadge status={detail.status} />
        </Meta>
        <Meta label={t("admin.detail.temperature")}>{detail.temperature ?? "—"}</Meta>
        <Meta label={t("admin.table.latency")}>{formatLatency(detail.latency_ms)}</Meta>
        <Meta label={t("admin.detail.usd")}>{formatUsd(detail.usd)}</Meta>
        <Meta label={t("admin.table.model")}>{detail.model ?? "—"}</Meta>
        <Meta label={t("admin.table.kind")}>{detail.kind}</Meta>
        <Meta label={t("admin.table.caller")}>{detail.caller}</Meta>
        <Meta label={t("admin.table.flags")}>{hasFlags ? <Flags row={detail} /> : "—"}</Meta>
      </dl>

      <div className="flex flex-wrap gap-x-6 rounded-lg bg-secondary px-3 py-2 text-xs text-muted-foreground">
        <span>
          {t("admin.detail.tokensPrompt")}{" "}
          <span className="font-medium text-foreground">{detail.prompt_tokens ?? "—"}</span>
        </span>
        <span>
          {t("admin.detail.tokensCompletion")}{" "}
          <span className="font-medium text-foreground">{detail.completion_tokens ?? "—"}</span>
        </span>
        <span>
          {t("admin.detail.tokensTotal")}{" "}
          <span className="font-medium text-foreground">{detail.total_tokens ?? "—"}</span>
        </span>
        <span>
          {t("admin.detail.tokensCached")}{" "}
          <span className="font-medium text-foreground">{detail.cached_tokens ?? "—"}</span>
        </span>
      </div>

      {detail.turn_id && (
        <div className="flex items-center justify-between gap-2">
          <div>
            <dt className="text-xs text-muted-foreground">{t("admin.table.turnId")}</dt>
            <dd className="mt-0.5 font-mono text-[10px] text-foreground" title={detail.turn_id}>
              {shortId(detail.turn_id)}
            </dd>
          </div>
          {onOpenTurn && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => onOpenTurn(detail.turn_id!)}
            >
              {t("admin.openNodeSteps")}
            </Button>
          )}
        </div>
      )}
      {detail.session_id && (
        <div className="flex items-center justify-between gap-2">
          <div>
            <dt className="text-xs text-muted-foreground">{t("admin.detail.session")}</dt>
            <dd className="mt-0.5 font-mono text-[10px] text-foreground" title={detail.session_id}>
              {shortId(detail.session_id)}
            </dd>
          </div>
          <div className="flex gap-2">
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
            {onOpenResearch && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => onOpenResearch(detail.session_id!)}
              >
                {t("admin.openResearch")}
              </Button>
            )}
          </div>
        </div>
      )}
      {detail.user_id && (
        <div>
          <dt className="text-xs text-muted-foreground">{t("admin.detail.user")}</dt>
          <dd className="mt-0.5 font-mono text-[10px] text-foreground" title={detail.user_id}>
            {shortId(detail.user_id)}
          </dd>
        </div>
      )}

      <DetailBlock label={t("admin.detail.systemPrompt")} value={detail.system_prompt} />
      <DetailBlock label={t("admin.detail.userPrompt")} value={detail.user_prompt} />
      <DetailBlock label={t("admin.detail.response")} value={detail.response_text} />
      {detail.error && (
        <DetailBlock
          label={t("admin.detail.error")}
          value={JSON.stringify(detail.error, null, 2)}
        />
      )}
    </div>
  );
}

function DetailCard({
  detail,
  loading,
  onClose,
  onOpenTurn,
  onOpenSession,
  onOpenResearch,
}: {
  detail: LlmCallRecordDetail | null;
  loading: boolean;
  onClose: () => void;
  onOpenTurn?: (turnId: string) => void;
  onOpenSession?: (sessionId: string) => void;
  onOpenResearch?: (sessionId: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <DetailShell title={t("admin.detail.title")} loading={loading} onClose={onClose}>
      {detail && (
        <DetailContent
          detail={detail}
          onOpenTurn={onOpenTurn}
          onOpenSession={onOpenSession}
          onOpenResearch={onOpenResearch}
        />
      )}
    </DetailShell>
  );
}

function DetailSheet({
  detail,
  loading,
  open,
  onOpenChange,
  onOpenTurn,
  onOpenSession,
  onOpenResearch,
}: {
  detail: LlmCallRecordDetail | null;
  loading: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenTurn?: (turnId: string) => void;
  onOpenSession?: (sessionId: string) => void;
  onOpenResearch?: (sessionId: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <DetailSheetShell
      title={t("admin.detail.title")}
      loading={loading}
      open={open}
      onOpenChange={onOpenChange}
    >
      {detail && (
        <DetailContent
          detail={detail}
          onOpenTurn={onOpenTurn}
          onOpenSession={onOpenSession}
          onOpenResearch={onOpenResearch}
        />
      )}
    </DetailSheetShell>
  );
}

function CallTable({
  items,
  loading,
  selectedId,
  onSelect,
}: {
  items: LlmCallRecordSummary[];
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
            <TableHead>{t("admin.table.node")}</TableHead>
            <TableHead>{t("admin.table.status")}</TableHead>
            <TableHead>{t("admin.table.latency")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {!loading && items.length === 0 && (
            <TableRow>
              <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                {t("admin.empty")}
              </TableCell>
            </TableRow>
          )}
          {items.map((row) => (
            <TableRow
              key={row.id}
              data-state={selectedId === row.id ? "selected" : undefined}
              className="cursor-pointer"
              onClick={() => onSelect(row.id)}
            >
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {formatTime(row.created_at)}
              </TableCell>
              <TableCell className="text-foreground">{row.node ?? "—"}</TableCell>
              <TableCell>
                <StatusBadge status={row.status} />
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatLatency(row.latency_ms)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

type LlmCallRecordsProps = {
  onOpenTurn?: (turnId: string) => void;
  onOpenSession?: (sessionId: string) => void;
  onOpenResearch?: (sessionId: string) => void;
};

export function LlmCallRecords({
  onOpenTurn,
  onOpenSession,
  onOpenResearch,
}: LlmCallRecordsProps = {}) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const { ref, width } = useContainerWidth();
  const split = width >= SPLIT_MIN_WIDTH;

  const [nodeInput, setNodeInput] = useState("");
  const [filters, setFilters] = useState<LlmCallFilters>({});
  const [offset, setOffset] = useState(0);

  const [items, setItems] = useState<LlmCallRecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<LlmCallRecordDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Debounce the node text search into filters; status/checkbox apply instantly.
  useEffect(() => {
    const handle = setTimeout(() => {
      setFilters((f) => {
        const node = nodeInput.trim() || undefined;
        return f.node === node ? f : { ...f, node };
      });
    }, 350);
    return () => clearTimeout(handle);
  }, [nodeInput]);

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
      const data = await apiAdminListLlmCalls(accessToken, filters, offset);
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
    setDetail(null);
    apiAdminGetLlmCall(accessToken, selectedId)
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
          htmlFor="admin-llm-filter-node"
          className="flex flex-col gap-1 text-xs text-muted-foreground"
        >
          {t("admin.filters.node")}
          <Input
            id="admin-llm-filter-node"
            type="text"
            value={nodeInput}
            onChange={(e) => setNodeInput(e.target.value)}
            placeholder={t("admin.filters.nodePlaceholder")}
            className="w-40"
          />
        </label>
        <label
          htmlFor="admin-llm-filter-status"
          className="flex flex-col gap-1 text-xs text-muted-foreground"
        >
          {t("admin.filters.status")}
          <Select
            value={filters.status ?? "all"}
            onValueChange={(value) =>
              setFilters((f) => ({
                ...f,
                status: !value || value === "all" ? undefined : value,
              }))
            }
          >
            <SelectTrigger id="admin-llm-filter-status" className="w-40">
              <SelectValue placeholder={t("admin.filters.statusAll")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("admin.filters.statusAll")}</SelectItem>
              {STATUS_OPTIONS.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={filters.fallbackOnly ?? false}
            onChange={(e) =>
              setFilters((f) => ({ ...f, fallbackOnly: e.target.checked || undefined }))
            }
            className="h-4 w-4 accent-primary"
          />
          {t("admin.filters.fallbackOnly")}
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
          storageKey="llm-calls"
          list={
            <>
              <CallTable
                items={items}
                loading={loading}
                selectedId={selectedId}
                onSelect={selectRow}
              />
              <DetailPager
                offset={offset}
                count={items.length}
                pageSize={LLM_CALL_PAGE_SIZE}
                loading={loading}
                onOffset={setOffset}
              />
            </>
          }
          detail={
            selectedId ? (
              <DetailCard
                detail={detail}
                loading={detailLoading}
                onClose={() => setSelectedId(null)}
                onOpenTurn={onOpenTurn}
                onOpenSession={onOpenSession}
                onOpenResearch={onOpenResearch}
              />
            ) : null
          }
        />
      ) : (
        <>
          <CallTable items={items} loading={loading} selectedId={selectedId} onSelect={selectRow} />
          <DetailPager
            offset={offset}
            count={items.length}
            pageSize={LLM_CALL_PAGE_SIZE}
            loading={loading}
            onOffset={setOffset}
          />
        </>
      )}

      {!split && (
        <DetailSheet
          detail={detail}
          loading={detailLoading}
          open={selectedId !== null}
          onOpenChange={(open) => {
            if (!open) setSelectedId(null);
          }}
          onOpenTurn={onOpenTurn}
          onOpenSession={onOpenSession}
          onOpenResearch={onOpenResearch}
        />
      )}
    </div>
  );
}
