import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/auth-context";
import { apiGetRecommendedQuestions, apiRefreshRecommendedQuestions } from "./api";
import type { RecommendedQuestion } from "./types";

const POLL_MS = [2000, 3000, 5000, 8000, 8000];
const POLL_DEADLINE_MS = 7 * 60 * 1000;

export function useRecommendedQuestions(companyId: string | undefined) {
  const { accessToken } = useAuth();
  const [questions, setQuestions] = useState<RecommendedQuestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [failed, setFailed] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attempts = useRef(0);
  const cancelled = useRef(false);

  const clearPoll = useCallback(() => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const applyReady = useCallback(
    (data: { questions: RecommendedQuestion[] }) => {
      setQuestions(data.questions ?? []);
      setGenerating(false);
      setFailed(false);
      setLoading(false);
      attempts.current = 0;
      clearPoll();
    },
    [clearPoll],
  );

  const poll = useCallback(
    (startedAt = Date.now()) => {
      if (!companyId || !accessToken || cancelled.current) return;
      const wait = POLL_MS[Math.min(attempts.current, POLL_MS.length - 1)] ?? 8000;
      attempts.current += 1;
      pollTimer.current = setTimeout(() => {
        void apiGetRecommendedQuestions(accessToken, companyId)
          .then((res) => {
            if (cancelled.current) return;
            if (res?.kind === "failed") {
              setFailed(true);
              setGenerating(false);
              setLoading(false);
              clearPoll();
              return;
            }
            if (res?.kind === "ready") {
              applyReady(res.data);
              return;
            }
            if (Date.now() - startedAt >= POLL_DEADLINE_MS) {
              setFailed(true);
              setGenerating(false);
              setLoading(false);
              return;
            }
            poll(startedAt);
          })
          .catch(() => {
            if (cancelled.current) return;
            if (Date.now() - startedAt >= POLL_DEADLINE_MS) {
              setFailed(true);
              setGenerating(false);
              setLoading(false);
              return;
            }
            poll(startedAt);
          });
      }, wait);
    },
    [accessToken, applyReady, clearPoll, companyId],
  );

  useEffect(() => {
    cancelled.current = false;
    if (!companyId || !accessToken) {
      setQuestions([]);
      setGenerating(false);
      setFailed(false);
      setLoading(false);
      return;
    }

    setLoading(true);
    setFailed(false);
    attempts.current = 0;

    apiGetRecommendedQuestions(accessToken, companyId)
      .then((res) => {
        if (cancelled.current) return;
        if (res?.kind === "ready") {
          applyReady(res.data);
          return;
        }
        if (res?.kind === "failed") {
          setQuestions([]);
          setFailed(true);
          setGenerating(false);
          setLoading(false);
          return;
        }
        setGenerating(true);
        setLoading(true);
        poll();
      })
      .catch(() => {
        if (cancelled.current) return;
        setQuestions([]);
        setGenerating(false);
        setFailed(false);
        setLoading(false);
      });

    return () => {
      cancelled.current = true;
      clearPoll();
    };
  }, [accessToken, applyReady, clearPoll, companyId, poll]);

  const refresh = useCallback(async () => {
    if (!companyId || !accessToken) return;
    setFailed(false);
    setGenerating(true);
    setLoading(true);
    attempts.current = 0;
    try {
      await apiRefreshRecommendedQuestions(accessToken, companyId);
      poll();
    } catch {
      setGenerating(false);
      setFailed(true);
      setLoading(false);
    }
  }, [accessToken, companyId, poll]);

  return { questions, loading, generating, failed, refresh };
}
