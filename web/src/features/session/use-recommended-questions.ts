import { useEffect, useState } from "react";
import { useAuth } from "@/context/auth-context";
import { apiGetRecommendedQuestions } from "./api";
import type { RecommendedQuestion } from "./types";

export function useRecommendedQuestions(companyId: string | undefined) {
  const { accessToken } = useAuth();
  const [questions, setQuestions] = useState<RecommendedQuestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [isStale, setIsStale] = useState(false);

  useEffect(() => {
    if (!companyId || !accessToken) {
      setQuestions([]);
      setIsStale(false);
      return;
    }

    let cancelled = false;
    setLoading(true);

    apiGetRecommendedQuestions(accessToken, companyId)
      .then((res) => {
        if (cancelled) return;
        setQuestions(res?.questions ?? []);
        setIsStale(Boolean(res?.is_stale));
      })
      .catch(() => {
        if (cancelled) return;
        // Soft-fail: landing still works with free-form composer.
        setQuestions([]);
        setIsStale(false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [companyId, accessToken]);

  return { questions, loading, isStale };
}
