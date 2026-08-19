import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/auth-context";
import {
  apiAddSessionImage,
  apiConfirmSession,
  apiCreateSession,
  apiDeleteSession,
  apiGetSessionMessages,
  apiListSessions,
  apiPostSessionMessage,
  apiRegenImage,
  apiRemoveImage,
  apiResumeSessionImage,
  apiStopSessionTurn,
  apiUpdateImagePlan,
  apiUpdateSession,
  apiUpdateSessionDraft,
  apiUploadImage,
} from "./api";
import {
  agentActionsFromMessages,
  isUserFacingAgentNode,
  MAX_QUEUED_SESSION_MESSAGES,
  mergePreviewDraft,
  newActionId,
  newQueuedChatMessage,
  OUTCOME_NODE,
  parseAgentProgress,
  parseBrief,
  parseDraftCopy,
  parseMediaItems,
  previewAnchorFromActions,
  waitForSseReady,
} from "./session-helpers";
import { getRememberedSessionId, setRememberedSessionId } from "./session-storage";
import { SseAuthError, subscribeSessionEvents } from "./sse";
import type {
  AgentActionRecord,
  AgentProgress,
  ChatMessage,
  ConfirmSessionResponse,
  DraftCopy,
  PreviewDraft,
  PreviewMediaMutationResponse,
  QueuedChatMessage,
  Session,
  SessionBrief,
  SessionListItem,
} from "./types";

export { parseBrief } from "./session-helpers";

type SseReadyHandle = { promise: Promise<void>; resolve: () => void };

// REST is the source of truth: POST /messages returns the full transcript plus
// turn events. SSE is an enhancement layer (live assistant messages, mode
// changes, later agent progress) that merges into the same state with dedupe.
export function useSession(companyId: string | undefined) {
  const { accessToken, refreshAccessToken } = useAuth();
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [mode, setMode] = useState<string>("CHAT");
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState(false);
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
  const [interruptAfterMessageId, setInterruptAfterMessageId] = useState<string | null>(null);
  // Mobile preview-ready banner — anchor to the turn that produced preview.updated.
  const [previewAfterMessageId, setPreviewAfterMessageId] = useState<string | null>(null);
  // True while the graph sits at interrupt_before executor_image_plan.
  const [awaitingImageOk, setAwaitingImageOk] = useState(false);
  const [queuedMessages, setQueuedMessages] = useState<QueuedChatMessage[]>([]);
  const [draft, setDraft] = useState<PreviewDraft | null>(null);
  const [confirmReceipt, setConfirmReceipt] = useState<ConfirmSessionResponse | null>(null);
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
  const sendAbortRef = useRef<AbortController | null>(null);
  // Bumped on Stop / turn.cancelled so late POST responses cannot re-apply a
  // discarded turn. suppressLiveTurnEventsRef drops late SSE until the next send.
  const turnEpochRef = useRef(0);
  const suppressLiveTurnEventsRef = useRef(false);
  const sendingRef = useRef(false);
  const stoppingRef = useRef(false);
  const awaitingImageOkRef = useRef(false);
  const queuedRef = useRef<QueuedChatMessage[]>([]);
  const drainQueueRef = useRef<() => void>(() => {});
  queuedRef.current = queuedMessages;
  sendingRef.current = sending;
  stoppingRef.current = stopping;
  awaitingImageOkRef.current = awaitingImageOk;

  const resetTransientUi = useCallback(() => {
    setStreamingText(null);
    setAgentProgress(null);
    setAgentActions([]);
    setBrief(null);
    setBriefAfterMessageId(null);
    setInterruptAfterMessageId(null);
    setPreviewAfterMessageId(null);
    setAwaitingImageOk(false);
    setDraft(null);
    setConfirmReceipt(null);
    setLlmError(null);
    queuedRef.current = [];
    setQueuedMessages([]);
    awaitingImageOkRef.current = false;
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
    [],
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

  // Shared reducer for turn events — SSE delivers them live mid-turn, while the
  // POST /messages response repeats them at the end for the no-SSE path.
  const applyTurnEvent = useCallback(
    (type: string, data: Record<string, unknown>) => {
      if (type === "turn.cancelled") {
        // Invalidate any in-flight send/resume apply + late SSE progress.
        turnEpochRef.current += 1;
        suppressLiveTurnEventsRef.current = true;
        const discardedAnchor = turnAnchorRef.current;
        turnAnchorRef.current = null;

        // Mid resume-image Stop re-parks; keep Generate-image CTA.
        const stillParked = data.awaiting_image_ok === true;
        awaitingImageOkRef.current = stillParked;
        setAwaitingImageOk(stillParked);
        if (stillParked) {
          setInterruptAfterMessageId(lastUserMessageId());
          setStreamingText(null);
          setAgentProgress(null);
          finishRunningActions();
        } else {
          setInterruptAfterMessageId(null);
          // Keep brief until stopTurn hydrates from sessions.state (may still exist).
          setStreamingText(null);
          setAgentProgress(null);
          // Optimistic prune — stopTurn hydrate is source of truth right after.
          if (discardedAnchor) {
            const drop = (id: string) => id === discardedAnchor || id.startsWith("local-");
            messagesRef.current = messagesRef.current.filter((m) => !drop(m.id));
            setMessages(messagesRef.current);
            setAgentActions((prev) =>
              prev.filter((a) => !a.afterMessageId || !drop(a.afterMessageId)),
            );
          } else {
            finishRunningActions();
          }
        }
        sendingRef.current = false;
        stoppingRef.current = false;
        setSending(false);
        setStopping(false);
        return;
      }
      // After Stop, ignore late live events from the discarded turn.
      if (suppressLiveTurnEventsRef.current) {
        if (
          type === "agent.progress" ||
          type === "brief.updated" ||
          type === "draft.awaiting_image_ok" ||
          type === "message.delta" ||
          type === "draft.copy_updated" ||
          type === "draft.updated" ||
          type === "preview.updated"
        ) {
          return;
        }
      }
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
        awaitingImageOkRef.current = true;
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
        const imageUrl = typeof data.image_url === "string" ? data.image_url : null;
        setAwaitingImageOk(false);
        setDraft((prev) => mergePreviewDraft(prev, { image_url: imageUrl }));
        return;
      }
      if (type === "preview.updated") {
        setAwaitingImageOk(false);
        setInterruptAfterMessageId(null);
        setPreviewAfterMessageId(lastUserMessageId());
        const copy = parseDraftCopy(data.copy);
        const media = parseMediaItems(data.media);
        setDraft((prev) =>
          mergePreviewDraft(prev, {
            copy,
            image_url: typeof data.image_url === "string" ? data.image_url : null,
            media,
            revision: typeof data.revision === "number" ? data.revision : null,
            approval_token: typeof data.approval_token === "string" ? data.approval_token : null,
            platform: typeof data.platform === "string" ? data.platform : null,
          }),
        );
        return;
      }
      if (type === "confirm.completed") {
        setConfirmReceipt({
          receipt_id: typeof data.receipt_id === "string" ? data.receipt_id : "",
          status: typeof data.status === "string" ? data.status : "stubbed",
          tool_name: "publish_social_post",
          idempotency_key: typeof data.idempotency_key === "string" ? data.idempotency_key : "",
        });
      }
      if (type === "llm.failed") {
        const err =
          typeof data.error === "string" && data.error ? data.error : "AI service unavailable";
        setLlmError(err);
        finishRunningActions();
        return;
      }
      if (
        type === "message.assistant" ||
        type === "review.failed" ||
        type === "confirm.completed"
      ) {
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
          const copy = parseDraftCopy(data.copy) || parseDraftCopy(state?.draft);
          const media = parseMediaItems(data.media);
          setDraft((prev) =>
            mergePreviewDraft(prev, {
              copy,
              image_url:
                typeof data.image_url === "string"
                  ? data.image_url
                  : typeof state?.image_url === "string"
                    ? state.image_url
                    : null,
              media,
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
              platform: typeof data.platform === "string" ? data.platform : null,
            }),
          );
          if (typeof data.mode === "string" && data.mode === "PREVIEW") {
            setPreviewAfterMessageId((prev) => {
              if (prev && messagesRef.current.some((m) => m.id === prev)) {
                return prev;
              }
              return previewAnchorFromActions(
                // Prefer live actions; fall back to rebuild from messages.
                // agentActions state may be stale in this closure — rebuild.
                agentActionsFromMessages(messagesRef.current),
                messagesRef.current,
              );
            });
          }
          const interrupted = data.interrupted === true || state?.awaiting_image_ok === true;
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
          if (suppressLiveTurnEventsRef.current) return;
          if (typeof data.content === "string" && data.content) {
            setStreamingText((prev) => (prev ?? "") + data.content);
          }
          return;
        }
        if (type === "message.assistant") {
          if (suppressLiveTurnEventsRef.current) return;
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
      const parsedBrief = parseBrief(res.brief);
      setBrief(parsedBrief);
      setBriefAfterMessageId(parsedBrief && lastUser ? lastUser.id : null);
      const parked = res.awaiting_image_ok === true;
      setAwaitingImageOk(parked);
      setInterruptAfterMessageId(parked && lastUser ? lastUser.id : null);
      if (res.session.mode === "PREVIEW") {
        setPreviewAfterMessageId(
          previewAnchorFromActions(agentActionsFromMessages(res.messages), res.messages),
        );
      } else {
        setPreviewAfterMessageId(null);
      }
      void refreshHistory();
    },
    [accessToken, companyId, resetTransientUi, refreshHistory],
  );

  const startNewChat = useCallback(async () => {
    if (!accessToken || !companyId) return;

    const upsertHistoryRow = (row: Session) => {
      setHistory((prev) => {
        if (prev.some((s) => s.id === row.id)) return prev;
        const item: SessionListItem = {
          id: row.id,
          company_id: row.company_id,
          user_id: row.user_id,
          mode: row.mode,
          status: row.status,
          created_at: row.created_at,
          updated_at: row.updated_at,
          title: null,
          pinned: false,
        };
        return [item, ...prev];
      });
    };

    // Already on an empty draft session — just clear chrome, don't spawn another row.
    if (session && messagesRef.current.length === 0) {
      resetTransientUi();
      setMode("CHAT");
      upsertHistoryRow(session);
      return;
    }
    resetTransientUi();
    setMessages([]);
    messagesRef.current = [];
    setMode("CHAT");
    const active = await apiCreateSession(accessToken, companyId);
    setSession(active);
    setRememberedSessionId(companyId, active.id);
    // Optimistic sidebar row — don't wait on SSE before the list updates.
    upsertHistoryRow(active);
    void refreshHistory();
    void waitForSseReady(sseReadyRef);
  }, [accessToken, companyId, session, resetTransientUi, refreshHistory]);

  const renameSession = useCallback(
    async (targetSessionId: string, title: string) => {
      if (!accessToken) return;
      const cleaned = title.trim();
      const updated = await apiUpdateSession(
        accessToken,
        targetSessionId,
        cleaned ? { title: cleaned } : { clear_title: true },
      );
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
        void startNewChat();
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
        void startNewChat();
      })
      .finally(() => {
        setRestoring(false);
        void refreshHistory();
      });
  }, [companyId, accessToken, openSession, refreshHistory, startNewChat]);

  const stopTurn = useCallback(async () => {
    if (!accessToken || !sessionId || stoppingRef.current) return;
    if (!sendingRef.current && !awaitingImageOkRef.current) return;
    stoppingRef.current = true;
    setStopping(true);
    // Invalidate in-flight send/resume before abort so late resolves are dropped.
    turnEpochRef.current += 1;
    suppressLiveTurnEventsRef.current = true;
    sendAbortRef.current?.abort();
    try {
      const stopped = await apiStopSessionTurn(accessToken, sessionId);
      const stillParked = stopped.awaiting_image_ok === true;
      // Reload transcript after discard (user message / draft may be gone).
      const hydrated = await apiGetSessionMessages(accessToken, sessionId);
      messagesRef.current = hydrated.messages;
      setMessages(hydrated.messages);
      setMode(hydrated.session.mode);
      setSession(hydrated.session);
      const lastUser = [...hydrated.messages].reverse().find((m) => m.role === "user");
      const parked = stillParked || hydrated.awaiting_image_ok === true;
      awaitingImageOkRef.current = parked;
      setAwaitingImageOk(parked);
      setInterruptAfterMessageId(parked && lastUser ? lastUser.id : null);
      // Restore BriefCard from sessions.state (Stop must not wipe a surviving brief).
      const parsedBrief = parseBrief(hydrated.brief);
      setBrief(parsedBrief);
      setBriefAfterMessageId(parsedBrief && lastUser ? lastUser.id : null);
      if (!parked) {
        turnAnchorRef.current = null;
      }
      setStreamingText(null);
      setAgentProgress(null);
      const actions = agentActionsFromMessages(hydrated.messages);
      setAgentActions(actions);
      if (hydrated.session.mode === "PREVIEW") {
        setPreviewAfterMessageId(previewAnchorFromActions(actions, hydrated.messages));
      } else {
        setPreviewAfterMessageId(null);
      }
      finishRunningActions();
      void refreshHistory();
    } finally {
      stoppingRef.current = false;
      sendingRef.current = false;
      setStopping(false);
      setSending(false);
      drainQueueRef.current();
    }
  }, [accessToken, sessionId, finishRunningActions, refreshHistory]);

  const enqueueQueuedAt = useCallback((content: string, index?: number): boolean => {
    const text = content.trim();
    if (!text) return false;
    if (queuedRef.current.length >= MAX_QUEUED_SESSION_MESSAGES) return false;
    const item = newQueuedChatMessage(text);
    const next = [...queuedRef.current];
    if (index == null || index >= next.length) {
      next.push(item);
    } else {
      next.splice(Math.max(0, index), 0, item);
    }
    queuedRef.current = next;
    setQueuedMessages(next);
    return true;
  }, []);

  const sendMessage = useCallback(
    async (content: string, options?: { queueIndex?: number }) => {
      const text = content.trim();
      if (!text || !accessToken || !companyId || stoppingRef.current) {
        return;
      }
      if (sendingRef.current || options?.queueIndex != null) {
        enqueueQueuedAt(text, options?.queueIndex);
        return;
      }
      // Backend rejects sends while parked (409) — discard the parked image
      // turn first (Stop semantics), then continue as a normal message.
      if (awaitingImageOkRef.current) {
        await stopTurn();
        if (stoppingRef.current || !accessToken) return;
      }
      sendingRef.current = true;
      setSending(true);
      setStreamingText(null);
      setAgentProgress(null);
      setLlmError(null);

      const epoch = ++turnEpochRef.current;
      suppressLiveTurnEventsRef.current = false;
      const abort = new AbortController();
      sendAbortRef.current = abort;

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
        appendAgentAction({ node: "route_intent", model_tier: null, model: null }, pending.id);

        const res = await apiPostSessionMessage(accessToken, active.id, text, {
          signal: abort.signal,
        });
        // Stop (or a newer turn) won the race — do not re-apply discarded payload.
        if (abort.signal.aborted || epoch !== turnEpochRef.current) {
          return;
        }
        messagesRef.current = res.messages;
        setMessages(res.messages);
        setMode(res.mode);
        setStreamingText(null);
        awaitingImageOkRef.current = res.interrupted;
        setAwaitingImageOk(res.interrupted);
        if (!res.interrupted) setInterruptAfterMessageId(null);

        const serverLastUser = [...res.messages].reverse().find((m) => m.role === "user");
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
          const hasInterruptEvent = res.events?.some((ev) => ev.type === "draft.awaiting_image_ok");
          if (hasBriefEvent) setBriefAfterMessageId(serverLastUser.id);
          if (res.interrupted || hasInterruptEvent) {
            setInterruptAfterMessageId(serverLastUser.id);
          }
          const hasPreviewEvent = res.events?.some((ev) => ev.type === "preview.updated");
          if (hasPreviewEvent) setPreviewAfterMessageId(serverLastUser.id);
          setBriefAfterMessageId((prev) => (prev?.startsWith("local-") ? serverLastUser.id : prev));
          setInterruptAfterMessageId((prev) =>
            prev?.startsWith("local-") ? serverLastUser.id : prev,
          );
          setPreviewAfterMessageId((prev) =>
            prev?.startsWith("local-") ? serverLastUser.id : prev,
          );
          ensureOutcomeActions(res.events ?? [], serverLastUser.id);
        }
        if (res.mode === "PREVIEW" && res.approval_token && typeof res.revision === "number") {
          const previewEv = res.events?.find((ev) => ev.type === "preview.updated");
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
              image_url: (previewEv?.data?.image_url as string | undefined) ?? prev?.image_url,
              media: parseMediaItems(previewEv?.data?.media) ?? prev?.media,
            }),
          );
        }
        finishRunningActions();
        turnAnchorRef.current = null;
        void refreshHistory();
      } catch (err) {
        if (abort.signal.aborted || epoch !== turnEpochRef.current) {
          // Stop path owns UI reset via turn.cancelled / stopTurn refresh.
          return;
        }
        if (optimistic) {
          const failed = optimistic;
          setMessages((prev) => prev.filter((m) => m.id !== failed.id));
          messagesRef.current = messagesRef.current.filter((m) => m.id !== failed.id);
          setAgentActions((prev) => prev.filter((a) => a.afterMessageId !== failed.id));
        }
        setStreamingText(null);
        finishRunningActions();
        turnAnchorRef.current = null;
        throw err;
      } finally {
        if (sendAbortRef.current === abort) sendAbortRef.current = null;
        sendingRef.current = false;
        setSending(false);
        drainQueueRef.current();
      }
    },
    [
      accessToken,
      companyId,
      session,
      stopTurn,
      applyTurnEvent,
      ensureOutcomeActions,
      finishRunningActions,
      refreshHistory,
      appendAgentAction,
      enqueueQueuedAt,
    ],
  );

  drainQueueRef.current = () => {
    if (sendingRef.current || stoppingRef.current || awaitingImageOkRef.current) return;
    const next = queuedRef.current[0];
    if (!next) return;
    queuedRef.current = queuedRef.current.slice(1);
    setQueuedMessages(queuedRef.current);
    void sendMessage(next.content);
  };

  const dequeueQueuedMessage = useCallback((id: string): number => {
    const idx = queuedRef.current.findIndex((q) => q.id === id);
    if (idx < 0) return -1;
    queuedRef.current = queuedRef.current.filter((q) => q.id !== id);
    setQueuedMessages(queuedRef.current);
    return idx;
  }, []);

  const applyTurnResponse = useCallback(
    (res: {
      messages: ChatMessage[];
      mode: string;
      interrupted: boolean;
      events?: { type: string; data?: Record<string, unknown> }[];
      approval_token?: string | null;
      revision?: number | null;
    }) => {
      messagesRef.current = res.messages;
      setMessages(res.messages);
      setMode(res.mode);
      setStreamingText(null);
      awaitingImageOkRef.current = res.interrupted;
      setAwaitingImageOk(res.interrupted);
      if (!res.interrupted) setInterruptAfterMessageId(null);

      const serverLastUser = [...res.messages].reverse().find((m) => m.role === "user");
      if (serverLastUser) {
        turnAnchorRef.current = serverLastUser.id;
        if (res.interrupted) setInterruptAfterMessageId(serverLastUser.id);
        ensureOutcomeActions(res.events ?? [], serverLastUser.id);
      }
      for (const ev of res.events ?? []) {
        applyTurnEvent(ev.type, ev.data ?? {});
      }
      if (res.mode === "PREVIEW" && res.approval_token && typeof res.revision === "number") {
        const previewEv = res.events?.find((ev) => ev.type === "preview.updated");
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
            approval_token: res.approval_token ?? null,
            revision: res.revision ?? null,
            image_url: (previewEv?.data?.image_url as string | undefined) ?? prev?.image_url,
            media: parseMediaItems(previewEv?.data?.media) ?? prev?.media,
          }),
        );
      }
      finishRunningActions();
      turnAnchorRef.current = null;
    },
    [applyTurnEvent, ensureOutcomeActions, finishRunningActions],
  );

  const resumeImage = useCallback(
    async (imageFormat?: "single" | "comic_4panel") => {
      if (
        !accessToken ||
        !sessionId ||
        sendingRef.current ||
        stoppingRef.current ||
        !awaitingImageOkRef.current
      ) {
        return;
      }
      sendingRef.current = true;
      setSending(true);
      setLlmError(null);
      const epoch = ++turnEpochRef.current;
      suppressLiveTurnEventsRef.current = false;
      const abort = new AbortController();
      sendAbortRef.current = abort;
      try {
        const res = await apiResumeSessionImage(accessToken, sessionId, {
          signal: abort.signal,
          imageFormat,
        });
        if (abort.signal.aborted || epoch !== turnEpochRef.current) {
          return;
        }
        applyTurnResponse(res);
        void refreshHistory();
      } catch (err) {
        if (abort.signal.aborted || epoch !== turnEpochRef.current) return;
        throw err;
      } finally {
        if (sendAbortRef.current === abort) sendAbortRef.current = null;
        sendingRef.current = false;
        setSending(false);
        drainQueueRef.current();
      }
    },
    [accessToken, sessionId, applyTurnResponse, refreshHistory],
  );

  const applyMediaMutation = useCallback((res: PreviewMediaMutationResponse) => {
    const next: PreviewDraft = {
      copy: res.copy,
      image_url: res.image_url,
      media: res.media ?? [],
      revision: res.revision,
      approval_token: res.approval_token,
      platform: res.platform,
    };
    setDraft(next);
    setMode(res.mode);
    return next;
  }, []);

  const updateDraft = useCallback(
    async (copy: DraftCopy) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      setDraftSaving(true);
      try {
        const res = await apiUpdateSessionDraft(accessToken, sessionId, copy);
        return applyMediaMutation(res);
      } finally {
        setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation],
  );

  const saveImagePlan = useCallback(
    async (imageId: string, plan: Record<string, unknown>) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      setDraftSaving(true);
      try {
        const res = await apiUpdateImagePlan(accessToken, sessionId, imageId, plan);
        return applyMediaMutation(res);
      } finally {
        setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation],
  );

  const regenImage = useCallback(
    async (imageId: string) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      setDraftSaving(true);
      try {
        const res = await apiRegenImage(accessToken, sessionId, imageId);
        return applyMediaMutation(res);
      } finally {
        setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation],
  );

  const addImage = useCallback(
    async (format: "single" | "comic_4panel" = "single") => {
      if (!accessToken || !sessionId || draftSaving) return null;
      setDraftSaving(true);
      try {
        const res = await apiAddSessionImage(accessToken, sessionId, { format });
        return applyMediaMutation(res);
      } finally {
        setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation],
  );

  const removeImage = useCallback(
    async (imageId: string) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      setDraftSaving(true);
      try {
        const res = await apiRemoveImage(accessToken, sessionId, imageId);
        return applyMediaMutation(res);
      } finally {
        setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation],
  );

  const uploadImage = useCallback(
    async (imageId: string, file: File) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      setDraftSaving(true);
      try {
        const res = await apiUploadImage(accessToken, sessionId, imageId, file);
        return applyMediaMutation(res);
      } finally {
        setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation],
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
          applyMediaMutation(saved);
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
    [accessToken, sessionId, confirming, draft, applyMediaMutation],
  );

  return {
    session,
    messages,
    mode,
    sending,
    stopping,
    composerLocked: stopping,
    queueFull: queuedMessages.length >= MAX_QUEUED_SESSION_MESSAGES,
    queuedMessages,
    sseConnected,
    streamingText,
    agentProgress,
    agentActions,
    brief,
    briefAfterMessageId,
    interruptAfterMessageId,
    previewAfterMessageId,
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
    enqueueQueuedMessage: enqueueQueuedAt,
    dequeueQueuedMessage,
    resumeImage,
    stopTurn,
    updateDraft,
    saveImagePlan,
    regenImage,
    addImage,
    removeImage,
    uploadImage,
    confirmPost,
    openSession,
    startNewChat,
    renameSession,
    pinSession,
    deleteSession,
    refreshHistory,
  };
}
