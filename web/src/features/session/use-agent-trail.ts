import { useCallback, useState } from "react";
import {
  isUserFacingAgentNode,
  newActionId,
  OUTCOME_NODE,
  parseAgentProgress,
} from "./session-helpers";
import type { AgentActionRecord, AgentProgress } from "./types";

export function useAgentTrail(turnAnchorRef: { current: string | null }) {
  // Latest agent.progress while a graph turn runs; null when idle.
  const [agentProgress, setAgentProgress] = useState<AgentProgress | null>(null);
  // Cursor-style action trail — accumulates across turns for this session.
  const [agentActions, setAgentActions] = useState<AgentActionRecord[]>([]);

  const finishRunningActions = useCallback(() => {
    setAgentActions((prev) =>
      prev.map((a) => (a.status === "running" ? { ...a, status: "done" as const } : a)),
    );
    setAgentProgress(null);
  }, []);

  const appendAgentAction = useCallback(
    (progress: AgentProgress, afterMessageId: string | null) => {
      if (!isUserFacingAgentNode(progress.node)) return;
      const anchor = afterMessageId ?? turnAnchorRef.current;
      setAgentActions((prev) => {
        const marked = prev.map((a) =>
          a.status === "running" ? { ...a, status: "done" as const } : a,
        );
        const last = marked[marked.length - 1];
        if (last && last.node === progress.node && last.afterMessageId === anchor) {
          return [
            ...marked.slice(0, -1),
            {
              ...last,
              model_tier: progress.model_tier,
              model: progress.model,
              status: "running" as const,
            },
          ];
        }
        // Dedupe identical completed node already recorded for this turn (REST replay).
        if (
          marked.some(
            (a) => a.node === progress.node && a.afterMessageId === anchor && a.status === "done",
          )
        ) {
          return marked;
        }
        return [
          ...marked,
          {
            id: newActionId(progress.node),
            node: progress.node,
            model_tier: progress.model_tier,
            model: progress.model,
            status: "running" as const,
            afterMessageId: anchor,
          },
        ];
      });
      setAgentProgress(progress);
    },
    [turnAnchorRef],
  );

  const ensureOutcomeActions = useCallback(
    (events: { type: string; data?: Record<string, unknown> }[], afterMessageId: string | null) => {
      if (!afterMessageId) return;
      // Prefer explicit agent.progress from the turn response.
      const progressFromEvents = events
        .filter((ev) => ev.type === "agent.progress")
        .map((ev) => parseAgentProgress((ev.data ?? {}) as Record<string, unknown>))
        .filter((p): p is AgentProgress => !!p && isUserFacingAgentNode(p.node));
      if (progressFromEvents.length > 0) {
        setAgentActions((prev) => {
          const withoutTurn = prev.filter((a) => a.afterMessageId !== afterMessageId);
          const built: AgentActionRecord[] = progressFromEvents.map((p) => ({
            id: newActionId(p.node),
            node: p.node,
            model_tier: p.model_tier,
            model: p.model,
            status: "done" as const,
            afterMessageId,
          }));
          // Keep live SSE rows for this turn if REST somehow omitted progress.
          if (prev.some((a) => a.afterMessageId === afterMessageId) && built.length === 0) {
            return prev.map((a) =>
              a.status === "running" ? { ...a, status: "done" as const } : a,
            );
          }
          // Merge: if we already have live rows, mark done and fill any missing nodes.
          const existingForTurn = prev.filter((a) => a.afterMessageId === afterMessageId);
          if (existingForTurn.length > 0) {
            const seen = new Set(existingForTurn.map((a) => a.node));
            const extras = built.filter((a) => !seen.has(a.node));
            return [
              ...withoutTurn,
              ...existingForTurn.map((a) => ({ ...a, status: "done" as const })),
              ...extras,
            ];
          }
          return [...withoutTurn, ...built];
        });
        return;
      }
      setAgentActions((prev) => {
        const hasForTurn = prev.some((a) => a.afterMessageId === afterMessageId);
        if (hasForTurn) {
          return prev.map((a) => (a.status === "running" ? { ...a, status: "done" as const } : a));
        }
        const seen = new Set<string>();
        const synthesized: AgentActionRecord[] = [];
        for (const ev of events) {
          const node = OUTCOME_NODE[ev.type];
          if (!node || seen.has(node)) continue;
          seen.add(node);
          synthesized.push({
            id: newActionId(node),
            node,
            model_tier: null,
            model: null,
            status: "done",
            afterMessageId,
          });
        }
        return [...prev, ...synthesized];
      });
    },
    [],
  );

  return {
    agentProgress,
    agentActions,
    setAgentProgress,
    setAgentActions,
    finishRunningActions,
    appendAgentAction,
    ensureOutcomeActions,
  };
}
