import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
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

const STATUS_OPTIONS = ["ok", "empty_response", "provider_error", "cancelled", "error"];

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-HK", { hour12: false });
}

function formatLatency(ms: number | null): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "ok"
      ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
      : status === "provider_error" || status === "error"
        ? "bg-[var(--color-destructive-soft)] text-[var(--color-destructive-text)]"
        : "bg-amber-500/10 text-amber-600 dark:text-amber-400";
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      {status}
    </span>
  );
}

function Flags({ row }: { row: LlmCallRecordSummary }) {
  const { t } = useTranslation();
  return (
    <span className="flex flex-wrap gap-1">
      {row.parse_ok === false && (
        <span className="rounded-full bg-[var(--color-destructive-soft)] px-2 py-0.5 text-xs font-medium text-[var(--color-destructive-text)]">
          {t("admin.badges.parseFailed")}
        </span>
      )}
      {row.fallback_used && (
        <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-600 dark:text-amber-400">
          {t("admin.badges.fallback")}
        </span>
      )}
    </span>
  );
}

function DetailBlock({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
      <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border bg-hover/40 p-3 text-xs text-foreground">
        {value}
      </pre>
    </div>
  );
}

function DetailSheet({
  detail,
  loading,
  open,
  onOpenChange,
}: {
  detail: LlmCallRecordDetail | null;
  loading: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{t("admin.detail.title")}</SheetTitle>
        </SheetHeader>

        {loading && (
          <div className="flex justify-center py-10">
            <Spinner className="size-5 text-muted-foreground" />
          </div>
        )}

        {detail && !loading && (
          <div className="mt-4 space-y-3">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <div>
                <dt className="text-muted-foreground">{t("admin.table.time")}</dt>
                <dd className="text-foreground">{formatTime(detail.created_at)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t("admin.table.status")}</dt>
                <dd>
                  <StatusBadge status={detail.status} />
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t("admin.table.latency")}</dt>
                <dd className="text-foreground">{formatLatency(detail.latency_ms)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t("admin.detail.temperature")}</dt>
                <dd className="text-foreground">{detail.temperature ?? "—"}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-muted-foreground">{t("admin.table.tokens")}</dt>
                <dd className="flex flex-wrap gap-x-4 text-foreground">
                  <span>
                    {t("admin.detail.tokensPrompt")}{" "}
                    <span className="font-medium">{detail.prompt_tokens ?? "—"}</span>
                  </span>
                  <span>
                    {t("admin.detail.tokensCompletion")}{" "}
                    <span className="font-medium">{detail.completion_tokens ?? "—"}</span>
                  </span>
                  <span>
                    {t("admin.detail.tokensTotal")}{" "}
                    <span className="font-medium">{detail.total_tokens ?? "—"}</span>
                  </span>
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t("admin.detail.parseOk")}</dt>
                <dd className="text-foreground">
                  {detail.parse_ok == null
                    ? "—"
                    : detail.parse_ok
                      ? "OK"
                      : t("admin.badges.parseFailed")}
                </dd>
              </div>
              {detail.session_id && (
                <div className="col-span-2">
                  <dt className="text-muted-foreground">{t("admin.detail.session")}</dt>
                  <dd className="font-mono text-[10px] text-foreground">{detail.session_id}</dd>
                </div>
              )}
              {detail.user_id && (
                <div className="col-span-2">
                  <dt className="text-muted-foreground">{t("admin.detail.user")}</dt>
                  <dd className="font-mono text-[10px] text-foreground">{detail.user_id}</dd>
                </div>
              )}
            </dl>

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
        )}
      </SheetContent>
    </Sheet>
  );
}

export function LlmCallRecords() {
  const { t } = useTranslation();
  const { accessToken } = useAuth();

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

  useEffect(() => {
    setOffset(0);
  }, [filters]);

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

  const from = items.length > 0 ? offset + 1 : 0;
  const to = offset + items.length;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          {t("admin.filters.node")}
          <input
            type="text"
            value={nodeInput}
            onChange={(e) => setNodeInput(e.target.value)}
            placeholder={t("admin.filters.nodePlaceholder")}
            className="w-40 rounded-lg border border-input bg-card px-2.5 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          {t("admin.filters.status")}
          <select
            value={filters.status ?? ""}
            onChange={(e) =>
              setFilters((f) => ({ ...f, status: e.target.value || undefined }))
            }
            className="rounded-lg border border-input bg-card px-2.5 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
          >
            <option value="">{t("admin.filters.statusAll")}</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={filters.fallbackOnly ?? false}
            onChange={(e) =>
              setFilters((f) => ({ ...f, fallbackOnly: e.target.checked || undefined }))
            }
            className="h-4 w-4 accent-[var(--color-primary)]"
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
        <p className="mb-3 rounded-lg bg-[var(--color-destructive-soft)] px-3 py-2 text-sm text-[var(--color-destructive-text)]">
          {t("admin.loadFailed")}: {error}
        </p>
      )}

      <div className="relative min-h-[18rem] overflow-hidden rounded-xl border border-border bg-card">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-card/70 backdrop-blur-[1px]">
            <Spinner className="size-6 text-primary" />
          </div>
        )}
        <Table className="min-w-[52rem]">
          <TableHeader>
            <TableRow>
              <TableHead>{t("admin.table.time")}</TableHead>
              <TableHead>{t("admin.table.node")}</TableHead>
              <TableHead>{t("admin.table.caller")}</TableHead>
              <TableHead>{t("admin.table.kind")}</TableHead>
              <TableHead>{t("admin.table.model")}</TableHead>
              <TableHead>{t("admin.table.status")}</TableHead>
              <TableHead>{t("admin.table.tokens")}</TableHead>
              <TableHead>{t("admin.table.latency")}</TableHead>
              <TableHead>{t("admin.table.flags")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {!loading && items.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="py-8 text-center text-muted-foreground">
                  {t("admin.empty")}
                </TableCell>
              </TableRow>
            )}
            {items.map((row) => (
              <TableRow
                key={row.id}
                data-state={selectedId === row.id ? "selected" : undefined}
                className="cursor-pointer"
                onClick={() => setSelectedId(row.id)}
              >
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                  {formatTime(row.created_at)}
                </TableCell>
                <TableCell className="text-foreground">{row.node ?? "—"}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{row.caller}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{row.kind}</TableCell>
                <TableCell className="max-w-[10rem] truncate text-xs text-muted-foreground">
                  {row.model ?? "—"}
                </TableCell>
                <TableCell>
                  <StatusBadge status={row.status} />
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {row.total_tokens ?? "—"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatLatency(row.latency_ms)}
                </TableCell>
                <TableCell>
                  <Flags row={row} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {t("admin.pagination.showing", { from, to })}
        </p>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={offset === 0 || loading}
            onClick={() => setOffset(Math.max(0, offset - LLM_CALL_PAGE_SIZE))}
          >
            {t("admin.pagination.prev")}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={items.length < LLM_CALL_PAGE_SIZE || loading}
            onClick={() => setOffset(offset + LLM_CALL_PAGE_SIZE)}
          >
            {t("admin.pagination.next")}
          </Button>
        </div>
      </div>

      <DetailSheet
        detail={detail}
        loading={detailLoading}
        open={selectedId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
      />
    </div>
  );
}
