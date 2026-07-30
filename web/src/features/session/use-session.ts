import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/auth-context";
import {
  apiConfirmSession,
  apiCreateSession,
  apiDeleteSession,
  apiGetSessionMessages,
  apiListSessions,
  apiPostSessionMessage,
  apiUpdateSession,
  apiUpdateSessionDraft,
} from "./api";
import { getRememberedSessionId, setRememberedSessionId } from "./session-storage";
import { SseAuthError, subscribeSessionEvents } from "./sse";
import type {
  AgentActionRecord,
  AgentProgress,
  ChatMessage,
  ConfirmSessionResponse,
  DraftCopy,
  PreviewDraft,
  Session,
  SessionBrief,
  SessionListItem,
} from "./types";

type SseReadyHandle = { promise: Promise<void>; resolve: () => void };

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

export function parseBrief(data: unknown): SessionBrief | null {
  if (!data || typeof data !== "object") return null;
  const raw = data as Record<string, unknown>;
  const summary = typeof raw.summary === "string" ? raw.summary : "";
  const canDo = asStringList(raw.can_do);
  const cannotDo = asStringList(raw.cannot_do);
  const angles = asStringList(raw.angles);
  if (!summary && !canDo.length && !cannotDo.length && !angles.length) return null;
  return {
    can_do: canDo,
    cannot_do: cannotDo,
    angles,
    persona: typeof raw.persona === "string" ? raw.persona : null,
    summary,
  };
}

function parseDraftCopy(data: unknown): DraftCopy | null {
  if (!data || typeof data !== "object") return null;
  const raw = data as Record<string, unknown>;
  const caption = typeof raw.caption === "string" ? raw.caption : "";
  const hashtags = asStringList(raw.hashtags);
  const cta = typeof raw.cta === "string" ? raw.cta : "";
  if (!caption && !hashtags.length && !cta) return null;
  return { caption, hashtags, cta };
}

function parseAgentProgress(data: Record<string, unknown>): AgentProgress | null {
  if (typeof data.node !== "string" || !data.node) return null;
  return {
    node: data.node,
    model_tier: typeof data.model_tier === "string" ? data.model_tier : null,
    model: typeof data.model === "string" ? data.model : null,
  };
}

/** Outcome events → node names, used when SSE missed live agent.progress. */
const OUTCOME_NODE: Record<string, string> = {
  "brief.updated": "brainstormer",
  "draft.copy_updated": "executor_post",
  "draft.image_plan_updated": "executor_image_plan",
  "draft.updated": "executor_image_gen",
  "preview.updated": "executor_image_gen",
  "draft.awaiting_image_ok": "executor_post",
};

function newActionId(node: string): string {
  return `action-${Date.now()}-${node}-${Math.random().toString(36).slice(2, 7)}`;
}

/** Rebuild Cursor-style action trail from persisted user-message metadata. */
function agentActionsFromMessages(messages: ChatMessage[]): AgentActionRecord[] {
  const out: AgentActionRecord[] = [];
  for (const m of messages) {
    if (m.role !== "user") continue;
    const raw = m.metadata?.agent_actions;
    if (!Array.isArray(raw)) continue;
    for (const item of raw) {
      if (!item || typeof item !== "object") continue;
      const progress = parseAgentProgress(item as Record<string, unknown>);
      if (!progress) continue;
      out.push({
        id: `persisted-${m.id}-${progress.node}-${out.length}`,
        node: progress.node,
        model_tier: progress.model_tier,
        model: progress.model,
        status: "done",
        afterMessageId: m.id,
      });
    }
  }
  return out;
}

function mergePreviewDraft(
  prev: PreviewDraft | null,
  patch: {
    copy?: DraftCopy | null;
    image_url?: string | null;
    revision?: number | null;
    approval_token?: string | null;
    platform?: string | null;
  },
): PreviewDraft | null {
  const copy = patch.copy ?? prev?.copy ?? null;
  const approval_token =
    typeof patch.approval_token === "string"
      ? patch.approval_token
      : (prev?.approval_token ?? null);
  const revision =
    typeof patch.revision === "number" ? patch.revision : (prev?.revision ?? null);
  if (!copy || !approval_token || revision == null) {
    if (copy && prev) {
      return {
        ...prev,
        copy,
        image_url:
          patch.image_url !== undefined ? patch.image_url : prev.image_url,
        platform: patch.platform || prev.platform,
      };
    }
    return prev;
  }
  return {
    copy,
    image_url:
      patch.image_url !== undefined
        ? patch.image_url
        : (prev?.image_url ?? null),
    revision,
    approval_token,
    platform: patch.platform || prev?.platform || "instagram",
  };
}

// The event bus does not replay: deltas published before the SSE subscriber
// attaches are lost. After creating a session, wait for the stream to open
// before posting so the first turn also streams from the start. On timeout we
// post anyway — the REST response still delivers the complete reply at the end.
async function waitForSseReady(
  ref: { current: SseReadyHandle | null },
  timeoutMs = 1500,
): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const handle = ref.current;
    if (handle) {
      const remaining = Math.max(0, timeoutMs - (Date.now() - start));
      await Promise.race([
        handle.promise,
        new Promise<void>((r) => setTimeout(r, remaining)),
      ]);
      return;
    }
    await new Promise<void>((r) => setTimeout(r, 25));
  }
}

// REST is the source of truth: POST /messages returns the full transcript plus
// turn events. SSE is an enhancement layer (live assistant messages, mode
// changes, later agent progress) that merges into the same state with dedupe.
export function useSession(companyId: string | undefined) {
  const { accessToken, refreshAccessToken } = useAuth();
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [mode, setMode] = useState<string>("CHAT");
  const [sending, setSending] = useState(false);
  const [sseConnected, setSseConnected] = useState(false);
  // In-flight assistant reply while message.delta events stream in; null when idle.
  const [streamingText, setStreamingText] = useState<string | null>(null);
  // Latest agent.progress while a graph turn runs; null when idle.
  const [agentProgress, setAgentProgress] = useState<AgentProgress | null>(null);
  // Cursor-style action trail — accumulates across turns for this session.
  const [agentActions, setAgentActions] = useState<AgentActionRecord[]>([]);
  const [brief, setBrief] = useState<SessionBrief | null>(null);
  // Anchor cards after the user message that produced them (not after the whole list).
  const [briefAfterMessageId, setBriefAfterMessageId] = useState<string | null>(null);
  const [interruptAfterMessageId, setInterruptAfterMessageId] = useState<string | null>(
    null,
  );
  // True while the graph sits at interrupt_before executor_image_plan.
  const [awaitingImageOk, setAwaitingImageOk] = useState(false);
  const [draft, setDraft] = useState<PreviewDraft | null>(null);
  const [confirmReceipt, setConfirmReceipt] = useState<ConfirmSessionResponse | null>(
    null,
  );
  const [llmError, setLlmError] = useState<string | null>(null);
  const [draftSaving, setDraftSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [history, setHistory] = useState<SessionListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [restoring, setRestoring] = useState(true);

  const sessionId = session?.id ?? null;
  const sseReadyRef = useRef<SseReadyHandle | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;
  // Anchor for in-flight agent.progress — set synchronously before POST so SSE
  // does not race React's async setMessages / messagesRef update.
  const turnAnchorRef = useRef<string | null>(null);
  const restoreAttemptedRef = useRef<string | null>(null);

  const resetTransientUi = useCallback(() => {
    setStreamingText(null);
    setAgentProgress(null);
    setAgentActions([]);
    setBrief(null);
    setBriefAfterMessageId(null);
    setInterruptAfterMessageId(null);
    setAwaitingImageOk(false);
    setDraft(null);
    setConfirmReceipt(null);
    setLlmError(null);
  }, []);

  const lastUserMessageId = useCallback(() => {
    if (turnAnchorRef.current) return turnAnchorRef.current;
    const list = messagesRef.current;
    for (let i = list.length - 1; i >= 0; i -= 1) {
      if (list[i]?.role === "user") return list[i]!.id;
    }
    return null;
  }, []);

  const finishRunningActions = useCallback(() => {
    setAgentActions((prev) =>
      prev.map((a) => (a.status === "running" ? { ...a, status: "done" as const } : a)),
    );
    setAgentProgress(null);
  }, []);

  const appendAgentAction = useCallback(
    (progress: AgentProgress, afterMessageId: string | null) => {
      const anchor = afterMessageId ?? turnAnchorRef.current;
      setAgentActions((prev) => {
        const marked = prev.map((a) =>
          a.status === "running" ? { ...a, status: "done" as const } : a,
        );
        const last = marked[marked.length - 1];
        if (
          last &&
          last.node === progress.node &&
          last.afterMessageId === anchor
        ) {
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
            (a) =>
              a.node === progress.node &&
              a.afterMessageId === anchor &&
              a.status === "done",
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
    [],
  );

  const ensureOutcomeActions = useCallback(
    (events: { type: string; data?: Record<string, unknown> }[], afterMessageId: string | null) => {
      if (!afterMessageId) return;
      // Prefer explicit agent.progress from the turn response.
      const progressFromEvents = events
        .filter((ev) => ev.type === "agent.progress")
        .map((ev) => parseAgentProgress((ev.data ?? {}) as Record<string, unknown>))
        .filter((p): p is AgentProgress => !!p);
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
          return prev.map((a) =>
            a.status === "running" ? { ...a, status: "done" as const } : a,
          );
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

  // Shared reducer for turn events — SSE delivers them live mid-turn, while the
  // POST /messages response repeats them at the end for the no-SSE path.
  const applyTurnEvent = useCallback(
    (type: string, data: Record<string, unknown>) => {
      if (type === "agent.progress") {
        const progress = parseAgentProgress(data);
        if (progress) appendAgentAction(progress, lastUserMessageId());
        return;
      }
      if (type === "brief.updated") {
        const parsed = parseBrief(data);
        if (parsed) {
          setBrief(parsed);
          setBriefAfterMessageId(lastUserMessageId());
        }
        return;
      }
      if (type === "draft.awaiting_image_ok") {
        setAwaitingImageOk(true);
        setInterruptAfterMessageId(lastUserMessageId());
        return;
      }
      if (type === "draft.copy_updated") {
        const copy = parseDraftCopy(data);
        if (copy) {
          setDraft((prev) => mergePreviewDraft(prev, { copy }));
        }
        return;
      }
      if (type === "draft.updated") {
        const imageUrl =
          typeof data.image_url === "string" ? data.image_url : null;
        setAwaitingImageOk(false);
        setDraft((prev) =>
          mergePreviewDraft(prev, { image_url: imageUrl }),
        );
        return;
      }
      if (type === "preview.updated") {
        setAwaitingImageOk(false);
        setInterruptAfterMessageId(null);
        const copy = parseDraftCopy(data.copy);
        setDraft((prev) =>
          mergePreviewDraft(prev, {
            copy,
            image_url:
              typeof data.image_url === "string" ? data.image_url : null,
            revision: typeof data.revision === "number" ? data.revision : null,
            approval_token:
              typeof data.approval_token === "string"
                ? data.approval_token
                : null,
            platform:
              typeof data.platform === "string" ? data.platform : null,
          }),
        );
        return;
      }
      if (type === "confirm.completed") {
        setConfirmReceipt({
          receipt_id: typeof data.receipt_id === "string" ? data.receipt_id : "",
          status: typeof data.status === "string" ? data.status : "stubbed",
          tool_name: "publish_social_post",
          idempotency_key:
            typeof data.idempotency_key === "string" ? data.idempotency_key : "",
        });
      }
      if (type === "llm.failed") {
        const err =
          typeof data.error === "string" && data.error
            ? data.error
            : "AI service unavailable";
        setLlmError(err);
        finishRunningActions();
        return;
      }
      if (type === "message.assistant" || type === "review.failed" || type === "confirm.completed") {
        finishRunningActions();
      }
    },
    [lastUserMessageId, appendAgentAction, finishRunningActions],
  );

  useEffect(() => {
    if (!sessionId || !accessToken) return;
    const abort = new AbortController();
    let resolveReady!: () => void;
    const readyPromise = new Promise<void>((resolve) => {
      resolveReady = resolve;
    });
    sseReadyRef.current = { promise: readyPromise, resolve: resolveReady };
    subscribeSessionEvents({
      sessionId,
      accessToken,
      signal: abort.signal,
      onOpen: () => {
        if (!abort.signal.aborted) {
          setSseConnected(true);
          resolveReady();
        }
      },
      onEvent: (type, data) => {
        if (type === "session.snapshot") {
          if (typeof data.mode === "string") setMode(data.mode);
          if (typeof data.status === "string" && data.status === "confirmed") {
            // Keep draft visible after reconnect; receipt may be unknown.
          }
          const state = data.state as Record<string, unknown> | undefined;
          const snapshotBrief = parseBrief(state?.brief);
          if (snapshotBrief) {
            setBrief(snapshotBrief);
            setBriefAfterMessageId(lastUserMessageId());
          }
          const copy =
            parseDraftCopy(data.copy) || parseDraftCopy(state?.draft);
          setDraft((prev) =>
            mergePreviewDraft(prev, {
              copy,
              image_url:
                typeof data.image_url === "string"
                  ? data.image_url
                  : typeof state?.image_url === "string"
                    ? state.image_url
                    : null,
              revision:
                typeof data.revision === "number"
                  ? data.revision
                  : typeof state?.revision === "number"
                    ? state.revision
                    : null,
              approval_token:
                typeof data.approval_token === "string"
                  ? data.approval_token
                  : typeof state?.approval_token === "string"
                    ? state.approval_token
                    : null,
              platform:
                typeof data.platform === "string" ? data.platform : null,
            }),
          );
          const interrupted =
            data.interrupted === true || state?.awaiting_image_ok === true;
          if (interrupted) {
            setAwaitingImageOk(true);
            const anchor = lastUserMessageId();
            if (anchor) setInterruptAfterMessageId(anchor);
          } else if (data.interrupted === false) {
            setAwaitingImageOk(false);
            setInterruptAfterMessageId(null);
          }
          return;
        }
        if (type === "message.delta") {
          if (typeof data.content === "string" && data.content) {
            setStreamingText((prev) => (prev ?? "") + data.content);
          }
          return;
        }
        if (type === "message.assistant") {
          const id = typeof data.id === "string" ? data.id : null;
          const content = typeof data.content === "string" ? data.content : null;
          if (!id || !content) return;
          setStreamingText(null);
          setMessages((prev) =>
            prev.some((m) => m.id === id)
              ? prev
              : [
                  ...prev,
                  {
                    id,
                    session_id: sessionId,
                    role: "assistant",
                    content,
                    created_at: new Date().toISOString(),
                  },
                ],
          );
        }
        applyTurnEvent(type, data);
      },
    }).catch((err) => {
      if (abort.signal.aborted) return;
      setSseConnected(false);
      // Token rotated out from under the stream — refresh flips accessToken,
      // which re-runs this effect and reconnects.
      if (err instanceof SseAuthError) void refreshAccessToken();
    });
    return () => {
      sseReadyRef.current = null;
      setSseConnected(false);
      abort.abort();
    };
  }, [sessionId, accessToken, refreshAccessToken, applyTurnEvent, lastUserMessageId]);

  const refreshHistory = useCallback(async () => {
    if (!accessToken || !companyId) {
      setHistory([]);
      return;
    }
    setHistoryLoading(true);
    try {
      const rows = await apiListSessions(accessToken, companyId);
      setHistory(rows);
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }, [accessToken, companyId]);

  const openSession = useCallback(
    async (targetSessionId: string) => {
      if (!accessToken || !companyId) return;
      const res = await apiGetSessionMessages(accessToken, targetSessionId);
      resetTransientUi();
      setMessages(res.messages);
      messagesRef.current = res.messages;
      setSession(res.session);
      setMode(res.session.mode);
      setAgentActions(agentActionsFromMessages(res.messages));
      setRememberedSessionId(companyId, res.session.id);
      const lastUser = [...res.messages].reverse().find((m) => m.role === "user");
      if (lastUser) setBriefAfterMessageId(lastUser.id);
      void refreshHistory();
    },
    [accessToken, companyId, resetTransientUi, refreshHistory],
  );

  const startNewChat = useCallback(() => {
    resetTransientUi();
    setSession(null);
    setMessages([]);
    messagesRef.current = [];
    setMode("CHAT");
    setRememberedSessionId(companyId, null);
  }, [companyId, resetTransientUi]);

  const renameSession = useCallback(
    async (targetSessionId: string, title: string) => {
      if (!accessToken) return;
      const cleaned = title.trim();
      const updated = await apiUpdateSession(accessToken, targetSessionId, cleaned
        ? { title: cleaned }
        : { clear_title: true });
      setHistory((prev) =>
        prev
          .map((s) => (s.id === updated.id ? { ...s, ...updated } : s))
          .sort((a, b) => {
            const pin = Number(!!b.pinned) - Number(!!a.pinned);
            if (pin !== 0) return pin;
            return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
          }),
      );
      return updated;
    },
    [accessToken],
  );

  const pinSession = useCallback(
    async (targetSessionId: string, pinned: boolean) => {
      if (!accessToken) return;
      const updated = await apiUpdateSession(accessToken, targetSessionId, { pinned });
      setHistory((prev) =>
        prev
          .map((s) => (s.id === updated.id ? { ...s, ...updated } : s))
          .sort((a, b) => {
            const pin = Number(!!b.pinned) - Number(!!a.pinned);
            if (pin !== 0) return pin;
            return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
          }),
      );
      return updated;
    },
    [accessToken],
  );

  const deleteSession = useCallback(
    async (targetSessionId: string) => {
      if (!accessToken || !companyId) return;
      await apiDeleteSession(accessToken, targetSessionId);
      setHistory((prev) => prev.filter((s) => s.id !== targetSessionId));
      if (session?.id === targetSessionId) {
        startNewChat();
      } else if (getRememberedSessionId(companyId) === targetSessionId) {
        setRememberedSessionId(companyId, null);
      }
    },
    [accessToken, companyId, session?.id, startNewChat],
  );

  useEffect(() => {
    if (!companyId || !accessToken) {
      setRestoring(false);
      return;
    }
    if (restoreAttemptedRef.current === companyId) return;
    restoreAttemptedRef.current = companyId;
    const remembered = getRememberedSessionId(companyId);
    if (!remembered) {
      setRestoring(false);
      void refreshHistory();
      return;
    }
    setRestoring(true);
    void openSession(remembered)
      .catch(() => {
        setRememberedSessionId(companyId, null);
        startNewChat();
      })
      .finally(() => {
        setRestoring(false);
        void refreshHistory();
      });
  }, [companyId, accessToken, openSession, refreshHistory, startNewChat]);

  const sendMessage = useCallback(
    async (content: string) => {
      const text = content.trim();
      if (!text || !accessToken || !companyId || sending) return;
      setSending(true);
      setStreamingText(null);
      setAgentProgress(null);
      setLlmError(null);
      // Keep awaitingImageOk until the response settles — clearing eagerly hides the
      // "Generate image" card, and a dropped request would never bring it back.
      const wasAwaitingImageOk = awaitingImageOk;

      let optimistic: ChatMessage | null = null;
      try {
        let active = session;
        if (!active) {
          active = await apiCreateSession(accessToken, companyId);
          setSession(active);
          setRememberedSessionId(companyId, active.id);
          await waitForSseReady(sseReadyRef);
          void refreshHistory();
        }

        optimistic = {
          id: `local-${Date.now()}`,
          session_id: active.id,
          role: "user",
          content: text,
          created_at: new Date().toISOString(),
        };
        const pending = optimistic;
        turnAnchorRef.current = pending.id;
        messagesRef.current = [...messagesRef.current, pending];
        setMessages(messagesRef.current);

        const res = await apiPostSessionMessage(accessToken, active.id, text);
        messagesRef.current = res.messages;
        setMessages(res.messages);
        setMode(res.mode);
        setStreamingText(null);
        setAwaitingImageOk(res.interrupted);
        if (!res.interrupted) setInterruptAfterMessageId(null);

        const serverLastUser = [...res.messages]
          .reverse()
          .find((m) => m.role === "user");
        if (serverLastUser) {
          turnAnchorRef.current = serverLastUser.id;
          setAgentActions((prev) =>
            prev.map((a) =>
              a.afterMessageId === pending.id || a.afterMessageId?.startsWith("local-")
                ? { ...a, afterMessageId: serverLastUser.id }
                : a,
            ),
          );
        }

        for (const ev of res.events ?? []) {
          applyTurnEvent(ev.type, ev.data ?? {});
        }
        if (serverLastUser) {
          const hasBriefEvent = res.events?.some((ev) => ev.type === "brief.updated");
          const hasInterruptEvent = res.events?.some(
            (ev) => ev.type === "draft.awaiting_image_ok",
          );
          if (hasBriefEvent) setBriefAfterMessageId(serverLastUser.id);
          if (res.interrupted || hasInterruptEvent) {
            setInterruptAfterMessageId(serverLastUser.id);
          }
          setBriefAfterMessageId((prev) =>
            prev?.startsWith("local-") ? serverLastUser.id : prev,
          );
          setInterruptAfterMessageId((prev) =>
            prev?.startsWith("local-") ? serverLastUser.id : prev,
          );
          ensureOutcomeActions(res.events ?? [], serverLastUser.id);
        }
        if (
          res.mode === "PREVIEW" &&
          res.approval_token &&
          typeof res.revision === "number"
        ) {
          const copyFromEvents = res.events
            ?.map((ev) =>
              ev.type === "preview.updated" || ev.type === "draft.copy_updated"
                ? parseDraftCopy(ev.data)
                : null,
            )
            .find(Boolean);
          setDraft((prev) =>
            mergePreviewDraft(prev, {
              copy: copyFromEvents ?? prev?.copy ?? null,
              approval_token: res.approval_token,
              revision: res.revision,
              image_url:
                (res.events?.find((ev) => ev.type === "preview.updated")?.data
                  ?.image_url as string | undefined) ?? prev?.image_url,
            }),
          );
        }
        finishRunningActions();
        turnAnchorRef.current = null;
        void refreshHistory();
      } catch (err) {
        if (optimistic) {
          const failed = optimistic;
          setMessages((prev) => prev.filter((m) => m.id !== failed.id));
          messagesRef.current = messagesRef.current.filter((m) => m.id !== failed.id);
          setAgentActions((prev) =>
            prev.filter((a) => a.afterMessageId !== failed.id),
          );
        }
        setStreamingText(null);
        finishRunningActions();
        // Network / API drop while confirming image — restore the interrupt CTA.
        if (wasAwaitingImageOk) {
          setAwaitingImageOk(true);
        }
        turnAnchorRef.current = null;
        throw err;
      } finally {
        setSending(false);
      }
    },
    [
      accessToken,
      companyId,
      sending,
      session,
      awaitingImageOk,
      applyTurnEvent,
      ensureOutcomeActions,
      finishRunningActions,
      refreshHistory,
    ],
  );

  const updateDraft = useCallback(
    async (copy: DraftCopy) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      setDraftSaving(true);
      try {
        const res = await apiUpdateSessionDraft(accessToken, sessionId, copy);
        const next: PreviewDraft = {
          copy: res.copy,
          image_url: res.image_url,
          revision: res.revision,
          approval_token: res.approval_token,
          platform: res.platform,
        };
        setDraft(next);
        setMode(res.mode);
        return next;
      } finally {
        setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving],
  );

  const confirmPost = useCallback(
    async (localCopy?: DraftCopy | null) => {
      if (!accessToken || !sessionId || confirming) return null;
      setConfirming(true);
      try {
        let token = draft?.approval_token ?? null;
        let platform = draft?.platform ?? "instagram";
        const dirty =
          !!localCopy &&
          !!draft &&
          (localCopy.caption !== draft.copy.caption ||
            localCopy.cta !== draft.copy.cta ||
            localCopy.hashtags.join("\0") !== draft.copy.hashtags.join("\0"));

        // Confirm auto-flushes dirty local fields before binding approval_token.
        if (dirty && localCopy) {
          const saved = await apiUpdateSessionDraft(accessToken, sessionId, localCopy);
          token = saved.approval_token;
          platform = saved.platform;
          setDraft({
            copy: saved.copy,
            image_url: saved.image_url,
            revision: saved.revision,
            approval_token: saved.approval_token,
            platform: saved.platform,
          });
          setMode(saved.mode);
        }
        if (!token) throw new Error("Missing approval_token");

        const idempotency_key =
          typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `confirm-${Date.now()}-${Math.random().toString(36).slice(2)}`;

        const receipt = await apiConfirmSession(accessToken, sessionId, {
          approval_token: token,
          idempotency_key,
          platform,
        });
        setConfirmReceipt(receipt);
        setSession((prev) => (prev ? { ...prev, status: "confirmed" } : prev));
        return receipt;
      } finally {
        setConfirming(false);
      }
    },
    [accessToken, sessionId, confirming, draft],
  );

  return {
    session,
    messages,
    mode,
    sending,
    sseConnected,
    streamingText,
    agentProgress,
    agentActions,
    brief,
    briefAfterMessageId,
    interruptAfterMessageId,
    awaitingImageOk,
    draft,
    confirmReceipt,
    draftSaving,
    confirming,
    llmError,
    history,
    historyLoading,
    restoring,
    sendMessage,
    updateDraft,
    confirmPost,
    openSession,
    startNewChat,
    renameSession,
    pinSession,
    deleteSession,
    refreshHistory,
  };
}
