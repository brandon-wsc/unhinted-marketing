import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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
      <p className="mb-1 text-xs font-medium text-[var(--color-muted)]">{label}</p>
      <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border border-[var(--color-border)] bg-[var(--color-hover)]/40 p-3 text-xs text-[var(--color-foreground)]">
        {value}
      </pre>
    </div>
  );
}

function DetailPanel({
  detail,
  loading,
  onClose,
}: {
  detail: LlmCallRecordDetail | null;
  loading: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <aside className="fixed inset-0 z-50 overflow-y-auto bg-[var(--color-card)] p-4 lg:static lg:z-auto lg:w-[26rem] lg:shrink-0 lg:bg-transparent lg:p-0">
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4 lg:sticky lg:top-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--color-foreground)]">
            {t("admin.detail.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-sm text-[var(--color-muted)] transition hover:bg-[var(--color-hover)]"
          >
            {t("admin.detail.close")}
          </button>
        </div>

        {loading && <p className="text-sm text-[var(--color-muted)]">{t("common.loading")}</p>}

        {detail && !loading && (
          <div className="space-y-3">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <div>
                <dt className="text-[var(--color-muted)]">{t("admin.table.time")}</dt>
                <dd className="text-[var(--color-foreground)]">{formatTime(detail.created_at)}</dd>
              </div>
              <div>
                <dt className="text-[var(--color-muted)]">{t("admin.table.status")}</dt>
                <dd>
                  <StatusBadge status={detail.status} />
                </dd>
              </div>
              <div>
                <dt className="text-[var(--color-muted)]">{t("admin.table.latency")}</dt>
                <dd className="text-[var(--color-foreground)]">{formatLatency(detail.latency_ms)}</dd>
              </div>
              <div>
                <dt className="text-[var(--color-muted)]">{t("admin.table.tokens")}</dt>
                <dd className="text-[var(--color-foreground)]">
                  {detail.prompt_tokens ?? "—"} + {detail.completion_tokens ?? "—"} ={" "}
                  {detail.total_tokens ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--color-muted)]">{t("admin.detail.temperature")}</dt>
                <dd className="text-[var(--color-foreground)]">{detail.temperature ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-[var(--color-muted)]">{t("admin.detail.parseOk")}</dt>
                <dd className="text-[var(--color-foreground)]">
                  {detail.parse_ok == null ? "—" : detail.parse_ok ? "OK" : t("admin.badges.parseFailed")}
                </dd>
              </div>
              {detail.session_id && (
                <div className="col-span-2">
                  <dt className="text-[var(--color-muted)]">{t("admin.detail.session")}</dt>
                  <dd className="font-mono text-[10px] text-[var(--color-foreground)]">
                    {detail.session_id}
                  </dd>
                </div>
              )}
              {detail.user_id && (
                <div className="col-span-2">
                  <dt className="text-[var(--color-muted)]">{t("admin.detail.user")}</dt>
                  <dd className="font-mono text-[10px] text-[var(--color-foreground)]">
                    {detail.user_id}
                  </dd>
                </div>
              )}
            </dl>

            <DetailBlock label={t("admin.detail.systemPrompt")} value={detail.system_prompt} />
            <DetailBlock label={t("admin.detail.userPrompt")} value={detail.user_prompt} />
            <DetailBlock label={t("admin.detail.response")} value={detail.response_text} />
            {detail.error && (
              <DetailBlock label={t("admin.detail.error")} value={JSON.stringify(detail.error, null, 2)} />
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

export function LlmCallRecords() {
  const { t } = useTranslation();
  const { accessToken } = useAuth();

  const [draftNode, setDraftNode] = useState("");
  const [draftStatus, setDraftStatus] = useState("");
  const [draftFallbackOnly, setDraftFallbackOnly] = useState(false);
  const [filters, setFilters] = useState<LlmCallFilters>({});
  const [offset, setOffset] = useState(0);

  const [items, setItems] = useState<LlmCallRecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<LlmCallRecordDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

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

  function applyFilters() {
    setFilters({
      node: draftNode || undefined,
      status: draftStatus || undefined,
      fallbackOnly: draftFallbackOnly || undefined,
    });
    setOffset(0);
  }

  const from = items.length > 0 ? offset + 1 : 0;
  const to = offset + items.length;

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
      <div className="min-w-0 flex-1">
        <div className="mb-3 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-[var(--color-muted)]">
            {t("admin.filters.node")}
            <input
              type="text"
              value={draftNode}
              onChange={(e) => setDraftNode(e.target.value)}
              placeholder={t("admin.filters.nodePlaceholder")}
              className="w-40 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-2.5 py-2 text-sm text-[var(--color-foreground)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-[var(--color-muted)]">
            {t("admin.filters.status")}
            <select
              value={draftStatus}
              onChange={(e) => setDraftStatus(e.target.value)}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-2.5 py-2 text-sm text-[var(--color-foreground)] focus:border-[var(--color-primary)] focus:outline-none"
            >
              <option value="">{t("admin.filters.statusAll")}</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 pb-2 text-sm text-[var(--color-foreground)]">
            <input
              type="checkbox"
              checked={draftFallbackOnly}
              onChange={(e) => setDraftFallbackOnly(e.target.checked)}
              className="h-4 w-4 accent-[var(--color-primary)]"
            />
            {t("admin.filters.fallbackOnly")}
          </label>
          <button
            type="button"
            onClick={applyFilters}
            className="rounded-lg bg-[var(--color-primary)] px-3 py-2 text-sm font-medium text-white transition hover:opacity-90"
          >
            {t("admin.filters.apply")}
          </button>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-2 text-sm text-[var(--color-foreground)] transition hover:bg-[var(--color-hover)]"
          >
            {t("admin.filters.refresh")}
          </button>
        </div>

        {error && (
          <p className="mb-3 rounded-lg bg-[var(--color-destructive-soft)] px-3 py-2 text-sm text-[var(--color-destructive-text)]">
            {t("admin.loadFailed")}: {error}
          </p>
        )}

        <div className="overflow-x-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]">
          <table className="w-full min-w-[52rem] text-left text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-xs text-[var(--color-muted)]">
                <th className="px-3 py-2 font-medium">{t("admin.table.time")}</th>
                <th className="px-3 py-2 font-medium">{t("admin.table.node")}</th>
                <th className="px-3 py-2 font-medium">{t("admin.table.caller")}</th>
                <th className="px-3 py-2 font-medium">{t("admin.table.kind")}</th>
                <th className="px-3 py-2 font-medium">{t("admin.table.model")}</th>
                <th className="px-3 py-2 font-medium">{t("admin.table.status")}</th>
                <th className="px-3 py-2 font-medium">{t("admin.table.tokens")}</th>
                <th className="px-3 py-2 font-medium">{t("admin.table.latency")}</th>
                <th className="px-3 py-2 font-medium">{t("admin.table.flags")}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-[var(--color-muted)]">
                    {t("admin.loading")}
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-[var(--color-muted)]">
                    {t("admin.empty")}
                  </td>
                </tr>
              )}
              {!loading &&
                items.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => setSelectedId(row.id)}
                    className={`cursor-pointer border-b border-[var(--color-border)] transition last:border-0 hover:bg-[var(--color-hover)] ${
                      selectedId === row.id ? "bg-[var(--color-primary)]/5" : ""
                    }`}
                  >
                    <td className="whitespace-nowrap px-3 py-2 text-xs text-[var(--color-muted)]">
                      {formatTime(row.created_at)}
                    </td>
                    <td className="px-3 py-2 text-[var(--color-foreground)]">{row.node ?? "—"}</td>
                    <td className="px-3 py-2 text-xs text-[var(--color-muted)]">{row.caller}</td>
                    <td className="px-3 py-2 text-xs text-[var(--color-muted)]">{row.kind}</td>
                    <td className="max-w-[10rem] truncate px-3 py-2 text-xs text-[var(--color-muted)]">
                      {row.model ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="px-3 py-2 text-xs text-[var(--color-muted)]">
                      {row.total_tokens ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-[var(--color-muted)]">
                      {formatLatency(row.latency_ms)}
                    </td>
                    <td className="px-3 py-2">
                      <Flags row={row} />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>

        <div className="mt-3 flex items-center justify-between text-sm">
          <p className="text-xs text-[var(--color-muted)]">
            {t("admin.pagination.showing", { from, to })}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - LLM_CALL_PAGE_SIZE))}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-1.5 text-[var(--color-foreground)] transition hover:bg-[var(--color-hover)] disabled:opacity-40"
            >
              {t("admin.pagination.prev")}
            </button>
            <button
              type="button"
              disabled={items.length < LLM_CALL_PAGE_SIZE}
              onClick={() => setOffset(offset + LLM_CALL_PAGE_SIZE)}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-1.5 text-[var(--color-foreground)] transition hover:bg-[var(--color-hover)] disabled:opacity-40"
            >
              {t("admin.pagination.next")}
            </button>
          </div>
        </div>
      </div>

      {selectedId && (
        <DetailPanel
          detail={detail}
          loading={detailLoading}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}
