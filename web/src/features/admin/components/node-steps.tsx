import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  apiAdminGetNodeStep,
  apiAdminListNodeSteps,
  NODE_STEP_PAGE_SIZE,
  type NodeStepDetail,
  type NodeStepFilters,
  type NodeStepSummary,
} from "@/features/admin/api";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-HK", { hour12: false });
}

type Props = {
  initialTurnId?: string;
  onOpenSession?: (sessionId: string) => void;
};

export function NodeStepsPanel({ initialTurnId = "", onOpenSession }: Props) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();

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

  useEffect(() => {
    setOffset(0);
  }, [filters]);

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

  const from = items.length > 0 ? offset + 1 : 0;
  const to = offset + items.length;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          {t("admin.filters.node")}
          <Input
            type="text"
            value={nodeInput}
            onChange={(e) => setNodeInput(e.target.value)}
            placeholder={t("admin.filters.nodePlaceholder")}
            className="w-36"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          {t("admin.filters.sessionId")}
          <Input
            type="text"
            value={sessionInput}
            onChange={(e) => setSessionInput(e.target.value)}
            className="w-56 font-mono text-xs"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          {t("admin.filters.turnId")}
          <Input
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

      <div className="relative min-h-[18rem] overflow-hidden rounded-xl border border-border bg-card">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-card/70 backdrop-blur-[1px]">
            <Spinner className="size-6 text-primary" />
          </div>
        )}
        <Table className="min-w-[48rem]">
          <TableHeader>
            <TableRow>
              <TableHead>{t("admin.table.time")}</TableHead>
              <TableHead>{t("admin.table.seq")}</TableHead>
              <TableHead>{t("admin.table.node")}</TableHead>
              <TableHead>{t("admin.table.mode")}</TableHead>
              <TableHead>{t("admin.table.intent")}</TableHead>
              <TableHead>{t("admin.table.turnId")}</TableHead>
              <TableHead>{t("admin.table.outputKeys")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {!loading && items.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                  {t("admin.nodeStepsEmpty")}
                </TableCell>
              </TableRow>
            )}
            {items.map((row) => (
              <TableRow
                key={row.id}
                className="cursor-pointer"
                data-state={selectedId === row.id ? "selected" : undefined}
                onClick={() => setSelectedId(row.id)}
              >
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                  {formatTime(row.created_at)}
                </TableCell>
                <TableCell className="text-xs">{row.seq}</TableCell>
                <TableCell>{row.node}</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {row.mode_in ?? "—"} → {row.mode_out ?? "—"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {row.intent_out ?? "—"}
                </TableCell>
                <TableCell className="max-w-[10rem] truncate font-mono text-[10px] text-muted-foreground">
                  {row.turn_id}
                </TableCell>
                <TableCell className="max-w-[12rem] truncate text-xs text-muted-foreground">
                  {(row.output_keys as string[]).join(", ") || "—"}
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
            onClick={() => setOffset(Math.max(0, offset - NODE_STEP_PAGE_SIZE))}
          >
            {t("admin.pagination.prev")}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={items.length < NODE_STEP_PAGE_SIZE || loading}
            onClick={() => setOffset(offset + NODE_STEP_PAGE_SIZE)}
          >
            {t("admin.pagination.next")}
          </Button>
        </div>
      </div>

      <Sheet open={selectedId !== null} onOpenChange={(open) => !open && setSelectedId(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle>{t("admin.nodeStepDetail.title")}</SheetTitle>
          </SheetHeader>
          {detailLoading && (
            <div className="flex justify-center py-10">
              <Spinner className="size-5 text-muted-foreground" />
            </div>
          )}
          {detail && !detailLoading && (
            <div className="mt-4 space-y-3 text-sm">
              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <dt className="text-muted-foreground">{t("admin.table.node")}</dt>
                  <dd>{detail.node}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{t("admin.table.seq")}</dt>
                  <dd>{detail.seq}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-muted-foreground">{t("admin.table.turnId")}</dt>
                  <dd className="font-mono text-[10px]">{detail.turn_id}</dd>
                </div>
                {detail.session_id && (
                  <div className="col-span-2">
                    <dt className="text-muted-foreground">{t("admin.filters.sessionId")}</dt>
                    <dd className="flex items-center gap-2">
                      <span className="font-mono text-[10px]">{detail.session_id}</span>
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
                    </dd>
                  </div>
                )}
              </dl>
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  {t("admin.nodeStepDetail.output")}
                </p>
                <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border bg-accent/40 p-3 text-xs">
                  {JSON.stringify(detail.output, null, 2)}
                </pre>
              </div>
              {detail.llm_calls.length > 0 && (
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                    {t("admin.nodeStepDetail.llmCalls")}
                  </p>
                  <ul className="space-y-1 text-xs">
                    {detail.llm_calls.map((c) => (
                      <li key={c.id} className="rounded border border-border px-2 py-1">
                        {c.status} · {c.kind} · {c.model ?? "—"} · {c.total_tokens ?? "—"} tok
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
