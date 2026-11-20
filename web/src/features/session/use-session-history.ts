import { useCallback, useRef, useState } from "react";
import { apiListSessions } from "./api";
import { bumpSessionInHistory } from "./session-helpers";
import type { SessionListItem } from "./types";

export function useSessionHistory(
  accessToken: string | null | undefined,
  companyId: string | undefined,
) {
  const [history, setHistory] = useState<SessionListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  // Guards against out-of-order history list/search responses.
  const historyReqSeq = useRef(0);
  // Active server-side history search ("" = browse mode). Ref so that
  // refreshHistory re-applies it — opening a result must not drop the
  // sidebar back to the plain list.
  const historyQueryRef = useRef("");

  const fetchHistory = useCallback(
    async (q: string, { keepOnError = false }: { keepOnError?: boolean } = {}) => {
      const seq = ++historyReqSeq.current;
      if (!accessToken || !companyId) {
        setHistory([]);
        return;
      }
      setHistoryLoading(true);
      try {
        const rows = q
          ? await apiListSessions(accessToken, companyId, q)
          : await apiListSessions(accessToken, companyId);
        if (seq === historyReqSeq.current) setHistory(rows);
      } catch {
        // Search failure keeps the previous list — a transient error should
        // not blank out the sidebar mid-typing.
        if (!keepOnError && seq === historyReqSeq.current) setHistory([]);
      } finally {
        if (seq === historyReqSeq.current) setHistoryLoading(false);
      }
    },
    [accessToken, companyId],
  );

  const refreshHistory = useCallback(() => fetchHistory(historyQueryRef.current), [fetchHistory]);

  const bumpHistoryRecency = useCallback((targetSessionId: string) => {
    const now = new Date().toISOString();
    setHistory((prev) => bumpSessionInHistory(prev, targetSessionId, now));
  }, []);

  const searchHistory = useCallback(
    async (query: string) => {
      historyQueryRef.current = query.trim();
      await fetchHistory(historyQueryRef.current, { keepOnError: true });
    },
    [fetchHistory],
  );

  return {
    history,
    historyLoading,
    setHistory,
    refreshHistory,
    bumpHistoryRecency,
    searchHistory,
  };
}
