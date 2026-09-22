import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/auth-context";
import {
  apiAddSessionImage,
  apiChooseSessionAngle,
  apiConfirmSession,
  apiCreateSession,
  apiDeleteSession,
  apiForkSession,
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
  anglePickParkFromEvents,
  bumpSessionInHistory,
  EMPTY_COMPOSER_DRAFT,
  filterOfferedAngles,
  filterOfferedPersonas,
  type ImageFormat,
  isConfirmSuccessStatus,
  isUserFacingAgentNode,
  MAX_QUEUED_SESSION_MESSAGES,
  mergePreviewDraft,
  newActionId,
  newQueuedChatMessage,
  OUTCOME_NODE,
  parseAgentProgress,
  parseBrief,
  parseConfirmReceipt,
  parseDraftCopy,
  parseImageFormat,
  parseMediaItems,
  previewAnchorFromActions,
  previewDraftFromPayload,
  readComposerDraft,
  sortSessionHistory,
  stashComposerDraft,
  waitForSseReady,
} from "./session-helpers";
import { getRememberedSessionId, setRememberedSessionId } from "./session-storage";
import { SseAuthError, subscribeSessionEvents } from "./sse";
import type {
  AgentActionRecord,
  AgentProgress,
  AudiencePersonaOption,
  ChatMessage,
  ComposerDraft,
  ConfirmSessionResponse,
  DraftCopy,
  ForkOrigin,
  ForkPreviewNote,
  PreviewDraft,
  PreviewMediaMutationResponse,
  QueuedChatMessage,
  Session,
  SessionBrief,
  SessionListItem,
} from "./types";

export { parseBrief } from "./session-helpers";

type SseReadyHandle = { promise: Promise<void>; resolve: () => void };

type LiveChatSnapshot = {
  messages: ChatMessage[];
  agentActions: AgentActionRecord[];
  streamingText: string | null;
  agentProgress: AgentProgress | null;
  brief: SessionBrief | null;
  briefAfterMessageId: string | null;
  interruptAfterMessageId: string | null;
  previewAfterMessageId: string | null;
  awaitingImageOk: boolean;
  awaitingAnglePick: boolean;
  angleOptions: string[];
  anglePersonas: AudiencePersonaOption[];
  recommendedPersona: string | null;
  recommendedImageFormat: ImageFormat | null;
  lastAnglePick: number | string | null;
  lastPersonaPick: string | null;
  lastImageFormatPick: ImageFormat | null;
  draft: PreviewDraft | null;
  confirmReceipt: ConfirmSessionResponse | null;
  llmError: string | null;
  mode: string;
  turnAnchor: string | null;
};

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
  // Bumped to force the SSE effect to tear down + resubscribe the same session.
  const [sseReconnectNonce, setSseReconnectNonce] = useState(0);
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
  // ADR 0028 — true while parked at angle_gate; options from brief.angles.
  const [awaitingAnglePick, setAwaitingAnglePick] = useState(false);
  const [angleOptions, setAngleOptions] = useState<string[]>([]);
  const [anglePersonas, setAnglePersonas] = useState<AudiencePersonaOption[]>([]);
  const [recommendedPersona, setRecommendedPersona] = useState<string | null>(null);
  const [recommendedImageFormat, setRecommendedImageFormat] = useState<ImageFormat | null>(null);
  // Last pick attempted at the gate — Retry re-issues it; a typed send while
  // parked IS a pick, so re-sending the stale start prompt would be feedback.
  const [lastAnglePick, setLastAnglePick] = useState<number | string | null>(null);
  const [lastPersonaPick, setLastPersonaPick] = useState<string | null>(null);
  const [lastImageFormatPick, setLastImageFormatPick] = useState<ImageFormat | null>(null);
  const [queuedMessages, setQueuedMessages] = useState<QueuedChatMessage[]>([]);
  const [composerInput, setComposerInputState] = useState("");
  const [editInsertAt, setEditInsertAtState] = useState<number | null>(null);
  const [draft, setDraft] = useState<PreviewDraft | null>(null);
  const [confirmReceipt, setConfirmReceipt] = useState<ConfirmSessionResponse | null>(null);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [draftSaving, setDraftSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [history, setHistory] = useState<SessionListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [restoring, setRestoring] = useState(true);
  // Where this session was forked from (ADR 0017); null for non-forked chats.
  const [forkedFrom, setForkedFrom] = useState<ForkOrigin | null>(null);
  const [forking, setForking] = useState(false);
  // Guards against out-of-order history list/search responses.
  const historyReqSeq = useRef(0);
  // Guards against out-of-order openSession / startNewChat hydrates.
  const sessionNavSeq = useRef(0);

  const sessionId = session?.id ?? null;
  const sseReadyRef = useRef<SseReadyHandle | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;
  // Anchor for in-flight agent.progress — set synchronously before POST so SSE
  // does not race React's async setMessages / messagesRef update.
  const turnAnchorRef = useRef<string | null>(null);
  const restoreAttemptedRef = useRef<string | null>(null);
  // Current session id for apply-gating (set synchronously on navigate, before paint).
  const sessionIdRef = useRef<string | null>(null);
  const inFlightBySessionRef = useRef(new Map<string, AbortController>());
  const turnEpochBySessionRef = useRef(new Map<string, number>());
  const composerDraftsRef = useRef(new Map<string, ComposerDraft>());
  const liveChatBySessionRef = useRef(new Map<string, LiveChatSnapshot>());
  const liveUiRef = useRef<LiveChatSnapshot | null>(null);
  const sseAbortRef = useRef<AbortController | null>(null);
  // Mirror of sseConnected for event handlers (visibility/online) that must not
  // close over stale state.
  const sseConnectedRef = useRef(false);
  const sseRetryCountRef = useRef(0);
  const sseRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resyncSeq = useRef(0);
  const composerInputRef = useRef("");
  const editInsertAtRef = useRef<number | null>(null);
  // Bumped per session on Stop / turn.cancelled so late POST responses cannot
  // re-apply a discarded turn. suppressLiveTurnEventsRef drops late SSE until
  // the next send on the session now on screen.
  const suppressLiveTurnEventsRef = useRef(false);
  const sendingRef = useRef(false);
  const stoppingRef = useRef(false);
  const awaitingImageOkRef = useRef(false);
  const awaitingAnglePickRef = useRef(false);
  const lastAnglePickRef = useRef<number | string | null>(null);
  const lastPersonaPickRef = useRef<string | null>(null);
  const lastImageFormatPickRef = useRef<ImageFormat | null>(null);
  const queuedRef = useRef<QueuedChatMessage[]>([]);
  const drainQueueRef = useRef<() => void>(() => {});
  queuedRef.current = queuedMessages;
  sendingRef.current = sending;
  stoppingRef.current = stopping;
  awaitingImageOkRef.current = awaitingImageOk;
  awaitingAnglePickRef.current = awaitingAnglePick;
  lastAnglePickRef.current = lastAnglePick;
  lastPersonaPickRef.current = lastPersonaPick;
  lastImageFormatPickRef.current = lastImageFormatPick;
  liveUiRef.current = {
    messages,
    agentActions,
    streamingText,
    agentProgress,
    brief,
    briefAfterMessageId,
    interruptAfterMessageId,
    previewAfterMessageId,
    awaitingImageOk,
    awaitingAnglePick,
    angleOptions,
    anglePersonas,
    recommendedPersona,
    recommendedImageFormat,
    lastAnglePick,
    lastPersonaPick,
    lastImageFormatPick,
    draft,
    confirmReceipt,
    llmError,
    mode,
    turnAnchor: turnAnchorRef.current,
  };

  const markSseConnected = useCallback((connected: boolean) => {
    sseConnectedRef.current = connected;
    setSseConnected(connected);
  }, []);

  const setComposerInput = useCallback((value: string) => {
    composerInputRef.current = value;
    setComposerInputState(value);
  }, []);

  const setEditInsertAt = useCallback((value: number | null) => {
    editInsertAtRef.current = value;
    setEditInsertAtState(value);
  }, []);

  const currentComposerDraft = useCallback(
    (): ComposerDraft => ({
      queued: queuedRef.current,
      input: composerInputRef.current,
      editInsertAt: editInsertAtRef.current,
    }),
    [],
  );

  const applyComposerDraft = useCallback((draft: ComposerDraft) => {
    queuedRef.current = draft.queued;
    setQueuedMessages(draft.queued);
    composerInputRef.current = draft.input;
    setComposerInputState(draft.input);
    editInsertAtRef.current = draft.editInsertAt;
    setEditInsertAtState(draft.editInsertAt);
  }, []);

  const captureLiveChat = useCallback((id: string | null) => {
    if (!id || !liveUiRef.current) return;
    liveChatBySessionRef.current.set(id, {
      ...liveUiRef.current,
      messages: [...messagesRef.current],
      agentActions: [...liveUiRef.current.agentActions],
      turnAnchor: turnAnchorRef.current,
      awaitingImageOk: awaitingImageOkRef.current,
      awaitingAnglePick: awaitingAnglePickRef.current,
      lastAnglePick: lastAnglePickRef.current,
      lastPersonaPick: lastPersonaPickRef.current,
      lastImageFormatPick: lastImageFormatPickRef.current,
    });
  }, []);

  const restoreLiveChat = useCallback((snap: LiveChatSnapshot) => {
    turnAnchorRef.current = snap.turnAnchor;
    suppressLiveTurnEventsRef.current = false;
    stoppingRef.current = false;
    setStopping(false);
    messagesRef.current = snap.messages;
    setMessages(snap.messages);
    setAgentActions(snap.agentActions);
    setStreamingText(snap.streamingText);
    setAgentProgress(snap.agentProgress);
    setBrief(snap.brief);
    setBriefAfterMessageId(snap.briefAfterMessageId);
    setInterruptAfterMessageId(snap.interruptAfterMessageId);
    setPreviewAfterMessageId(snap.previewAfterMessageId);
    awaitingImageOkRef.current = snap.awaitingImageOk;
    setAwaitingImageOk(snap.awaitingImageOk);
    awaitingAnglePickRef.current = snap.awaitingAnglePick;
    setAwaitingAnglePick(snap.awaitingAnglePick);
    setAngleOptions(snap.angleOptions);
    setAnglePersonas(snap.anglePersonas);
    setRecommendedPersona(snap.recommendedPersona);
    setRecommendedImageFormat(snap.recommendedImageFormat);
    lastAnglePickRef.current = snap.lastAnglePick;
    setLastAnglePick(snap.lastAnglePick);
    lastPersonaPickRef.current = snap.lastPersonaPick;
    setLastPersonaPick(snap.lastPersonaPick);
    lastImageFormatPickRef.current = snap.lastImageFormatPick;
    setLastImageFormatPick(snap.lastImageFormatPick);
    setDraft(snap.draft);
    setConfirmReceipt(snap.confirmReceipt);
    setLlmError(snap.llmError);
    setMode(snap.mode);
    setDraftSaving(false);
    setConfirming(false);
  }, []);

  const disconnectSse = useCallback(() => {
    sseAbortRef.current?.abort();
    sseAbortRef.current = null;
    sseReadyRef.current = null;
    markSseConnected(false);
  }, [markSseConnected]);

  // Dead streams retry with backoff while the tab is visible (2s → 30s cap).
  // Hidden tabs stay disconnected — nobody is watching; the visibility handler
  // reconnects on return.
  const scheduleSseRetry = useCallback(() => {
    if (document.visibilityState !== "visible") return;
    if (sseRetryTimerRef.current) return;
    const attempt = sseRetryCountRef.current++;
    const delay = Math.min(2000 * 2 ** attempt, 30000);
    sseRetryTimerRef.current = setTimeout(() => {
      sseRetryTimerRef.current = null;
      if (document.visibilityState !== "visible") return;
      setSseReconnectNonce((n) => n + 1);
    }, delay);
  }, []);

  const syncSendingForCurrent = useCallback(() => {
    const id = sessionIdRef.current;
    const inflight = !!(id && inFlightBySessionRef.current.has(id));
    sendingRef.current = inflight;
    setSending(inflight);
  }, []);

  const bumpEpoch = useCallback((id: string) => {
    const next = (turnEpochBySessionRef.current.get(id) ?? 0) + 1;
    turnEpochBySessionRef.current.set(id, next);
    return next;
  }, []);

  const epochOf = useCallback((id: string) => turnEpochBySessionRef.current.get(id) ?? 0, []);

  const stillOn = useCallback((id: string | null | undefined) => {
    return !!id && sessionIdRef.current === id;
  }, []);

  const dropInFlight = useCallback((id: string | null | undefined) => {
    if (!id) return;
    inFlightBySessionRef.current.delete(id);
    if (sessionIdRef.current === id) {
      sendingRef.current = false;
      setSending(false);
    }
  }, []);

  const registerInFlight = useCallback((id: string, abort: AbortController) => {
    inFlightBySessionRef.current.set(id, abort);
    if (sessionIdRef.current === id) {
      sendingRef.current = true;
      setSending(true);
    }
  }, []);

  const forgetSessionLocal = useCallback((id: string) => {
    composerDraftsRef.current.delete(id);
    liveChatBySessionRef.current.delete(id);
    inFlightBySessionRef.current.get(id)?.abort();
    inFlightBySessionRef.current.delete(id);
    turnEpochBySessionRef.current.delete(id);
  }, []);

  const resetTransientUi = useCallback(() => {
    turnAnchorRef.current = null;
    suppressLiveTurnEventsRef.current = false;
    stoppingRef.current = false;
    setStopping(false);
    setStreamingText(null);
    setAgentProgress(null);
    setAgentActions([]);
    setBrief(null);
    setBriefAfterMessageId(null);
    setInterruptAfterMessageId(null);
    setPreviewAfterMessageId(null);
    setAwaitingImageOk(false);
    setAwaitingAnglePick(false);
    setAngleOptions([]);
    setAnglePersonas([]);
    setRecommendedPersona(null);
    setRecommendedImageFormat(null);
    setLastAnglePick(null);
    setLastPersonaPick(null);
    setLastImageFormatPick(null);
    setDraft(null);
    setConfirmReceipt(null);
    setLlmError(null);
    setDraftSaving(false);
    setConfirming(false);
    setForkedFrom(null);
    awaitingImageOkRef.current = false;
    awaitingAnglePickRef.current = false;
    lastAnglePickRef.current = null;
    lastPersonaPickRef.current = null;
    lastImageFormatPickRef.current = null;
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
        const currentId = sessionIdRef.current;
        if (currentId) bumpEpoch(currentId);
        suppressLiveTurnEventsRef.current = true;
        const discardedAnchor = turnAnchorRef.current;
        turnAnchorRef.current = null;

        // Mid resume Stop re-parks; keep the parked card (image or angle).
        const stillParkedImage = data.awaiting_image_ok === true;
        const stillParkedAngle = data.awaiting_angle_pick === true;
        awaitingImageOkRef.current = stillParkedImage;
        setAwaitingImageOk(stillParkedImage);
        awaitingAnglePickRef.current = stillParkedAngle;
        setAwaitingAnglePick(stillParkedAngle);
        if (stillParkedImage || stillParkedAngle) {
          setInterruptAfterMessageId(lastUserMessageId());
          setStreamingText(null);
          setAgentProgress(null);
          finishRunningActions();
        } else {
          setInterruptAfterMessageId(null);
          // Keep brief until stopTurn hydrates from sessions.state (may still exist).
          // REST Stop is the source of truth; this paints early when SSE includes it.
          const restored = previewDraftFromPayload(data.preview);
          if (restored) setDraft(restored);
          setStreamingText(null);
          setAgentProgress(null);
          // Optimistic prune — stopTurn hydrate is source of truth right after.
          // kept: interrupt cancels generation but the turn's messages stay
          // in the transcript (ADR 0035) — nothing to prune.
          if (discardedAnchor && data.kept !== true) {
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
        dropInFlight(currentId);
        stoppingRef.current = false;
        setStopping(false);
        return;
      }
      // After Stop, ignore late live events from the discarded turn.
      if (suppressLiveTurnEventsRef.current) {
        if (
          type === "agent.progress" ||
          type === "brief.updated" ||
          type === "draft.awaiting_image_ok" ||
          type === "draft.awaiting_angle_pick" ||
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
        awaitingAnglePickRef.current = false;
        setAwaitingAnglePick(false);
        setInterruptAfterMessageId(lastUserMessageId());
        return;
      }
      if (type === "draft.awaiting_angle_pick") {
        awaitingAnglePickRef.current = true;
        setAwaitingAnglePick(true);
        const offered = filterOfferedAngles(data.angles);
        if (offered.length > 0) setAngleOptions(offered);
        setAnglePersonas(filterOfferedPersonas(data.personas));
        const rec =
          typeof data.recommended_persona === "string" ? data.recommended_persona.trim() : "";
        setRecommendedPersona(rec || null);
        setRecommendedImageFormat(parseImageFormat(data.recommended_image_format));
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
        setAwaitingAnglePick(false);
        setDraft((prev) => mergePreviewDraft(prev, { image_url: imageUrl }));
        return;
      }
      if (type === "preview.updated") {
        // Pending script+plan also emits preview.updated while still parked
        // (ADR 0036). Execute clears the card via interrupted=false / draft.updated.
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
        const receipt = parseConfirmReceipt(data);
        if (receipt) {
          setConfirmReceipt(receipt);
          if (isConfirmSuccessStatus(receipt.status)) {
            setSession((prev) => (prev ? { ...prev, status: "confirmed" } : prev));
          }
        }
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
    [lastUserMessageId, appendAgentAction, finishRunningActions, bumpEpoch, dropInFlight],
  );

  useEffect(() => {
    if (!sessionId || !accessToken) return;
    // Bumped to reconnect the same session (retry / tab becomes visible).
    void sseReconnectNonce;
    const abort = new AbortController();
    let resolveReady!: () => void;
    const readyPromise = new Promise<void>((resolve) => {
      resolveReady = resolve;
    });
    sseReadyRef.current = { promise: readyPromise, resolve: resolveReady };
    sseAbortRef.current = abort;
    subscribeSessionEvents({
      sessionId,
      accessToken,
      signal: abort.signal,
      onOpen: () => {
        if (!abort.signal.aborted && sessionIdRef.current === sessionId) {
          sseRetryCountRef.current = 0;
          markSseConnected(true);
          resolveReady();
        }
      },
      onEvent: (type, data) => {
        if (abort.signal.aborted || sessionIdRef.current !== sessionId) return;
        if (type === "session.snapshot") {
          if (typeof data.mode === "string") setMode(data.mode);
          if (typeof data.status === "string") {
            setSession((prev) => (prev ? { ...prev, status: data.status as string } : prev));
          }
          const snapReceipt = parseConfirmReceipt(data.confirm_receipt);
          setConfirmReceipt(snapReceipt);
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
          const parkedAtImage = state?.awaiting_image_ok === true;
          const parkedAtAngle = state?.awaiting_angle_pick === true;
          setAwaitingImageOk(parkedAtImage);
          awaitingImageOkRef.current = parkedAtImage;
          setAwaitingAnglePick(parkedAtAngle);
          awaitingAnglePickRef.current = parkedAtAngle;
          if (parkedAtAngle) {
            const snapAngles = (state?.brief as { angles?: unknown } | undefined)?.angles;
            const offered = filterOfferedAngles(snapAngles);
            if (offered.length > 0) setAngleOptions(offered);
            setAnglePersonas(filterOfferedPersonas(state?.audience_catalog));
            const sticky =
              typeof state?.chosen_persona === "string" ? state.chosen_persona.trim() : "";
            const briefPersona = (state?.brief as { persona?: unknown } | undefined)?.persona;
            const rec = sticky || (typeof briefPersona === "string" ? briefPersona.trim() : "");
            setRecommendedPersona(rec || null);
            setRecommendedImageFormat(
              parseImageFormat(state?.chosen_image_format) ?? parseImageFormat(state?.image_format),
            );
          }
          if (parkedAtImage || parkedAtAngle) {
            const anchor = lastUserMessageId();
            if (anchor) setInterruptAfterMessageId(anchor);
          } else {
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
      markSseConnected(false);
      // Token rotated out from under the stream — refresh flips accessToken,
      // which re-runs this effect and reconnects.
      if (err instanceof SseAuthError) {
        void refreshAccessToken();
        return;
      }
      scheduleSseRetry();
    });
    return () => {
      if (sseAbortRef.current === abort) sseAbortRef.current = null;
      sseReadyRef.current = null;
      markSseConnected(false);
      abort.abort();
      if (sseRetryTimerRef.current) {
        clearTimeout(sseRetryTimerRef.current);
        sseRetryTimerRef.current = null;
      }
    };
  }, [
    sessionId,
    accessToken,
    refreshAccessToken,
    applyTurnEvent,
    lastUserMessageId,
    markSseConnected,
    scheduleSseRetry,
    sseReconnectNonce,
  ]);

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

  // Transcript + card state from a messages fetch. Shared by session open and
  // post-reconnect resync — deliberately excludes composer draft (the stash for
  // the session on screen is stale next to what the user is typing right now).
  const hydrateTranscript = useCallback(
    (res: {
      session: Session;
      messages: ChatMessage[];
      brief?: unknown;
      awaiting_image_ok?: boolean;
      awaiting_angle_pick?: boolean;
      personas?: unknown;
      recommended_persona?: string | null;
      recommended_image_format?: string | null;
      forked_from?: ForkOrigin | null;
    }) => {
      resetTransientUi();
      syncSendingForCurrent();
      setMessages(res.messages);
      messagesRef.current = res.messages;
      setSession(res.session);
      setMode(res.session.mode);
      setForkedFrom(res.forked_from ?? null);
      setAgentActions(agentActionsFromMessages(res.messages));
      const lastUser = [...res.messages].reverse().find((m) => m.role === "user");
      const parsedBrief = parseBrief(res.brief);
      setBrief(parsedBrief);
      setBriefAfterMessageId(parsedBrief && lastUser ? lastUser.id : null);
      const parkedImage = res.awaiting_image_ok === true;
      const parkedAngle = res.awaiting_angle_pick === true;
      awaitingImageOkRef.current = parkedImage;
      setAwaitingImageOk(parkedImage);
      awaitingAnglePickRef.current = parkedAngle;
      setAwaitingAnglePick(parkedAngle);
      const lockedFormat = parseImageFormat(res.recommended_image_format);
      if ((parkedImage || parkedAngle) && lockedFormat) {
        lastImageFormatPickRef.current = lockedFormat;
        setLastImageFormatPick(lockedFormat);
      }
      if (parkedAngle) {
        setAngleOptions(filterOfferedAngles(parsedBrief?.angles));
        setAnglePersonas(filterOfferedPersonas(res.personas));
        const rec =
          typeof res.recommended_persona === "string" ? res.recommended_persona.trim() : "";
        setRecommendedPersona(rec || null);
        setRecommendedImageFormat(lockedFormat);
      }
      const parked = parkedImage || parkedAngle;
      setInterruptAfterMessageId(parked && lastUser ? lastUser.id : null);
      if (res.session.mode === "PREVIEW") {
        setPreviewAfterMessageId(
          previewAnchorFromActions(agentActionsFromMessages(res.messages), res.messages),
        );
      } else {
        setPreviewAfterMessageId(null);
      }
      // ADR 0016 §5: hold the queue while parked at either gate — queued text
      // was composed before the options existed and must not become a pick.
      if (!sendingRef.current && !stoppingRef.current && !parked) {
        drainQueueRef.current();
      }
    },
    [resetTransientUi, syncSendingForCurrent],
  );

  const applyHydratedSession = useCallback(
    (res: {
      session: Session;
      messages: ChatMessage[];
      brief?: unknown;
      awaiting_image_ok?: boolean;
      awaiting_angle_pick?: boolean;
      recommended_image_format?: string | null;
      forked_from?: ForkOrigin | null;
    }) => {
      disconnectSse();
      sessionIdRef.current = res.session.id;
      applyComposerDraft(readComposerDraft(composerDraftsRef.current, res.session.id));
      hydrateTranscript(res);
    },
    [applyComposerDraft, hydrateTranscript, disconnectSse],
  );

  // REST catch-up after a dead stream reconnects — snapshot carries no
  // messages, so turns committed while disconnected would stay invisible.
  const resyncCurrentSession = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id || !accessToken) return;
    const seq = ++resyncSeq.current;
    try {
      const res = await apiGetSessionMessages(accessToken, id);
      if (seq !== resyncSeq.current || sessionIdRef.current !== id) return;
      if (stoppingRef.current || inFlightBySessionRef.current.has(id)) {
        // An in-flight POST / stopTurn owns the transcript — refreshing the
        // session row only, so the optimistic message + live actions survive.
        setSession(res.session);
        setMode(res.session.mode);
        return;
      }
      hydrateTranscript(res);
    } catch {
      // Snapshot on reconnect still heals mode/draft; transcript stays stale
      // until the next resync — no worse than before.
    }
  }, [accessToken, hydrateTranscript]);

  // Tab returns to foreground / network comes back: if the stream is dead,
  // reconnect immediately and resync — SSE does not replay missed events.
  useEffect(() => {
    const kick = () => {
      if (!sessionIdRef.current || sseConnectedRef.current) return;
      if (sseRetryTimerRef.current) {
        clearTimeout(sseRetryTimerRef.current);
        sseRetryTimerRef.current = null;
      }
      sseRetryCountRef.current = 0;
      setSseReconnectNonce((n) => n + 1);
      void resyncCurrentSession();
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") kick();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", kick);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", kick);
    };
  }, [resyncCurrentSession]);

  const openSession = useCallback(
    async (targetSessionId: string) => {
      if (!accessToken || !companyId) return;
      if (sessionIdRef.current === targetSessionId) return;
      captureLiveChat(sessionIdRef.current);
      stashComposerDraft(composerDraftsRef.current, sessionIdRef.current, currentComposerDraft());
      const seq = ++sessionNavSeq.current;
      const res = await apiGetSessionMessages(accessToken, targetSessionId);
      if (seq !== sessionNavSeq.current) return;
      captureLiveChat(sessionIdRef.current);
      stashComposerDraft(composerDraftsRef.current, sessionIdRef.current, currentComposerDraft());
      const live = liveChatBySessionRef.current.get(targetSessionId);
      const lastLiveId = live?.messages[live.messages.length - 1]?.id;
      const getMissedLive =
        !!live && !!lastLiveId && !res.messages.some((m) => m.id === lastLiveId);
      if (live && (inFlightBySessionRef.current.has(targetSessionId) || getMissedLive)) {
        disconnectSse();
        sessionIdRef.current = res.session.id;
        applyComposerDraft(readComposerDraft(composerDraftsRef.current, targetSessionId));
        restoreLiveChat(live);
        setSession(res.session);
        setForkedFrom(res.forked_from ?? null);
        syncSendingForCurrent();
      } else {
        applyHydratedSession(res);
      }
      setRememberedSessionId(companyId, res.session.id);
      void refreshHistory();
    },
    [
      accessToken,
      companyId,
      currentComposerDraft,
      captureLiveChat,
      restoreLiveChat,
      applyComposerDraft,
      applyHydratedSession,
      disconnectSse,
      syncSendingForCurrent,
      refreshHistory,
    ],
  );

  const forkSession = useCallback(
    async (messageId: string): Promise<ForkPreviewNote> => {
      if (!accessToken || !sessionId || forking) return null;
      setForking(true);
      try {
        const res = await apiForkSession(accessToken, sessionId, messageId);
        // Reuse the open path so composer stash / live capture / remembered id
        // stay consistent with a manual session switch.
        await openSession(res.session.id);
        return res.preview_note ?? null;
      } finally {
        setForking(false);
      }
    },
    [accessToken, sessionId, forking, openSession],
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

    stashComposerDraft(composerDraftsRef.current, sessionIdRef.current, currentComposerDraft());
    captureLiveChat(sessionIdRef.current);

    // Already on an empty draft session — just clear chrome, don't spawn another row.
    if (session && messagesRef.current.length === 0) {
      resetTransientUi();
      applyComposerDraft(readComposerDraft(composerDraftsRef.current, session.id));
      syncSendingForCurrent();
      setMode("CHAT");
      upsertHistoryRow(session);
      return;
    }

    const seq = ++sessionNavSeq.current;
    disconnectSse();
    resetTransientUi();
    setMessages([]);
    messagesRef.current = [];
    setMode("CHAT");
    applyComposerDraft(EMPTY_COMPOSER_DRAFT);
    sessionIdRef.current = null;
    setSession(null);
    syncSendingForCurrent();
    const active = await apiCreateSession(accessToken, companyId);
    if (seq !== sessionNavSeq.current) return;
    sessionIdRef.current = active.id;
    applyComposerDraft(readComposerDraft(composerDraftsRef.current, active.id));
    syncSendingForCurrent();
    setSession(active);
    setRememberedSessionId(companyId, active.id);
    // Optimistic sidebar row — don't wait on SSE before the list updates.
    upsertHistoryRow(active);
    void refreshHistory();
    void waitForSseReady(sseReadyRef);
  }, [
    accessToken,
    companyId,
    session,
    resetTransientUi,
    applyComposerDraft,
    currentComposerDraft,
    captureLiveChat,
    disconnectSse,
    syncSendingForCurrent,
    refreshHistory,
  ]);

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
        sortSessionHistory(prev.map((s) => (s.id === updated.id ? { ...s, ...updated } : s))),
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
        sortSessionHistory(prev.map((s) => (s.id === updated.id ? { ...s, ...updated } : s))),
      );
      return updated;
    },
    [accessToken],
  );

  const deleteSession = useCallback(
    async (targetSessionId: string) => {
      if (!accessToken || !companyId) return;
      await apiDeleteSession(accessToken, targetSessionId);
      forgetSessionLocal(targetSessionId);
      setHistory((prev) => prev.filter((s) => s.id !== targetSessionId));
      if (sessionIdRef.current === targetSessionId) {
        void startNewChat();
      } else if (getRememberedSessionId(companyId) === targetSessionId) {
        setRememberedSessionId(companyId, null);
      }
    },
    [accessToken, companyId, startNewChat, forgetSessionLocal],
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

  const stopTurn = useCallback(
    async (mode: "discard" | "interrupt" = "discard") => {
      if (!accessToken || !sessionId || stoppingRef.current) return;
      if (!sendingRef.current && !awaitingImageOkRef.current && !awaitingAnglePickRef.current)
        return;
      stoppingRef.current = true;
      setStopping(true);
      // Invalidate in-flight send/resume before abort so late resolves are dropped.
      bumpEpoch(sessionId);
      suppressLiveTurnEventsRef.current = true;
      inFlightBySessionRef.current.get(sessionId)?.abort();
      try {
        const stopped = await apiStopSessionTurn(accessToken, sessionId, mode);
        if (!stillOn(sessionId)) return;
        // Parked discard returns the last accepted preview. A missing key
        // (older responses) leaves the in-memory draft alone.
        if ("preview" in stopped) {
          if (stopped.preview === null) {
            setDraft(null);
          } else {
            const restored = previewDraftFromPayload(stopped.preview);
            if (restored) setDraft(restored);
          }
        }
        const stillParkedImage = stopped.awaiting_image_ok === true;
        const stillParkedAngle = stopped.awaiting_angle_pick === true;
        // Reload transcript after stop — discard may drop rows, interrupt keeps them.
        const hydrated = await apiGetSessionMessages(accessToken, sessionId);
        if (!stillOn(sessionId)) return;
        messagesRef.current = hydrated.messages;
        setMessages(hydrated.messages);
        setMode(hydrated.session.mode);
        setSession(hydrated.session);
        const lastUser = [...hydrated.messages].reverse().find((m) => m.role === "user");
        const parsedBrief = parseBrief(hydrated.brief);
        const parkedImage = stillParkedImage || hydrated.awaiting_image_ok === true;
        const parkedAngle = stillParkedAngle || hydrated.awaiting_angle_pick === true;
        awaitingImageOkRef.current = parkedImage;
        setAwaitingImageOk(parkedImage);
        awaitingAnglePickRef.current = parkedAngle;
        setAwaitingAnglePick(parkedAngle);
        const lockedFormat = parseImageFormat(hydrated.recommended_image_format);
        if ((parkedImage || parkedAngle) && lockedFormat) {
          lastImageFormatPickRef.current = lockedFormat;
          setLastImageFormatPick(lockedFormat);
        }
        if (parkedAngle) {
          setAngleOptions(filterOfferedAngles(parsedBrief?.angles));
          setAnglePersonas(filterOfferedPersonas(hydrated.personas));
          const rec =
            typeof hydrated.recommended_persona === "string"
              ? hydrated.recommended_persona.trim()
              : "";
          setRecommendedPersona(rec || null);
          setRecommendedImageFormat(lockedFormat);
        }
        const parked = parkedImage || parkedAngle;
        setInterruptAfterMessageId(parked && lastUser ? lastUser.id : null);
        // Restore BriefCard from sessions.state (Stop must not wipe a surviving brief).
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
        dropInFlight(sessionId);
        if (stillOn(sessionId)) {
          stoppingRef.current = false;
          setStopping(false);
          drainQueueRef.current();
        }
      }
    },
    [
      accessToken,
      sessionId,
      finishRunningActions,
      refreshHistory,
      bumpEpoch,
      stillOn,
      dropInFlight,
    ],
  );

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
    async (content: string, options?: { queueIndex?: number; sourceQuestionId?: string }) => {
      const text = content.trim();
      if (!text || !accessToken || !companyId || stoppingRef.current) {
        return;
      }
      if (sendingRef.current || options?.queueIndex != null) {
        enqueueQueuedAt(text, options?.queueIndex);
        return;
      }
      // Image-park Send is a new script (ADR 0036). Angle park is a typed pick (ADR 0028).
      // A typed reply while angle-parked IS the pick (ADR 0028) — remember it
      // so Retry re-issues the pick; any fresh turn clears the stale one.
      const anglePickText = awaitingAnglePickRef.current ? text : null;
      lastAnglePickRef.current = anglePickText;
      setLastAnglePick(anglePickText);

      let optimistic: ChatMessage | null = null;
      let boundId: string | null = null;
      let abort: AbortController | null = null;
      let epoch = 0;
      try {
        let active = session;
        if (!active) {
          active = await apiCreateSession(accessToken, companyId);
          if (sessionIdRef.current && sessionIdRef.current !== active.id) {
            // Switched away while creating — still run the turn bound to the new
            // session, but do not steal the UI.
          } else {
            sessionIdRef.current = active.id;
            setSession(active);
            setRememberedSessionId(companyId, active.id);
            await waitForSseReady(sseReadyRef);
            void refreshHistory();
          }
        }
        boundId = active.id;
        epoch = bumpEpoch(active.id);
        abort = new AbortController();
        registerInFlight(active.id, abort);
        suppressLiveTurnEventsRef.current = stillOn(active.id)
          ? false
          : suppressLiveTurnEventsRef.current;
        bumpHistoryRecency(active.id);

        if (stillOn(active.id)) {
          setStreamingText(null);
          setAgentProgress(null);
          setLlmError(null);
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
          // A typed pick resumes the parked turn — route_intent is not
          // consulted on resume turns (ADR 0028 §6).
          if (anglePickText === null) {
            appendAgentAction({ node: "route_intent", model_tier: null, model: null }, pending.id);
          }
        }

        const res = await apiPostSessionMessage(accessToken, active.id, text, {
          signal: abort.signal,
          sourceQuestionId: options?.sourceQuestionId,
        });
        // Stop won the race — do not re-apply discarded payload.
        if (abort.signal.aborted || epoch !== epochOf(active.id)) {
          return;
        }
        // Switched away — keep the completed transcript for this session; do
        // not paint it onto the session now on screen.
        if (!stillOn(active.id)) {
          const offscreenPark = anglePickParkFromEvents(res.interrupted, res.events);
          liveChatBySessionRef.current.set(active.id, {
            messages: res.messages,
            agentActions: agentActionsFromMessages(res.messages),
            streamingText: null,
            agentProgress: null,
            brief: parseBrief(res.events?.find((ev) => ev.type === "brief.updated")?.data),
            briefAfterMessageId:
              [...res.messages].reverse().find((m) => m.role === "user")?.id ?? null,
            interruptAfterMessageId: res.interrupted
              ? ([...res.messages].reverse().find((m) => m.role === "user")?.id ?? null)
              : null,
            previewAfterMessageId: res.events?.some((ev) => ev.type === "preview.updated")
              ? ([...res.messages].reverse().find((m) => m.role === "user")?.id ?? null)
              : null,
            awaitingImageOk: res.interrupted && !offscreenPark.parked,
            awaitingAnglePick: offscreenPark.parked,
            angleOptions: offscreenPark.angles,
            anglePersonas: offscreenPark.personas,
            recommendedPersona: offscreenPark.recommendedPersona,
            recommendedImageFormat: offscreenPark.recommendedImageFormat,
            lastAnglePick: anglePickText,
            lastPersonaPick: lastPersonaPickRef.current,
            lastImageFormatPick: lastImageFormatPickRef.current,
            draft: null,
            confirmReceipt: null,
            llmError: null,
            mode: res.mode,
            turnAnchor: null,
          });
          void refreshHistory();
          return;
        }
        messagesRef.current = res.messages;
        setMessages(res.messages);
        setMode(res.mode);
        setStreamingText(null);
        const anglePark = anglePickParkFromEvents(res.interrupted, res.events);
        awaitingImageOkRef.current = res.interrupted && !anglePark.parked;
        setAwaitingImageOk(res.interrupted && !anglePark.parked);
        awaitingAnglePickRef.current = anglePark.parked;
        setAwaitingAnglePick(anglePark.parked);
        if (anglePark.parked) {
          if (anglePark.angles.length > 0) setAngleOptions(anglePark.angles);
          setAnglePersonas(anglePark.personas);
          setRecommendedPersona(anglePark.recommendedPersona);
          setRecommendedImageFormat(anglePark.recommendedImageFormat);
        }
        if (!res.interrupted) setInterruptAfterMessageId(null);

        const pending = optimistic;
        const serverLastUser = [...res.messages].reverse().find((m) => m.role === "user");
        if (serverLastUser) {
          turnAnchorRef.current = serverLastUser.id;
          if (pending) {
            setAgentActions((prev) =>
              prev.map((a) =>
                a.afterMessageId === pending.id || a.afterMessageId?.startsWith("local-")
                  ? { ...a, afterMessageId: serverLastUser.id }
                  : a,
              ),
            );
          }
        }

        for (const ev of res.events ?? []) {
          applyTurnEvent(ev.type, ev.data ?? {});
        }
        if (serverLastUser) {
          const hasBriefEvent = res.events?.some((ev) => ev.type === "brief.updated");
          const hasInterruptEvent = res.events?.some(
            (ev) =>
              ev.type === "draft.awaiting_image_ok" || ev.type === "draft.awaiting_angle_pick",
          );
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
        if (abort?.signal.aborted || (boundId && epoch !== epochOf(boundId))) {
          // Stop path owns UI reset via turn.cancelled / stopTurn refresh.
          return;
        }
        if (!stillOn(boundId)) return;
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
        dropInFlight(boundId);
        if (stillOn(boundId)) drainQueueRef.current();
      }
    },
    [
      accessToken,
      companyId,
      session,
      applyTurnEvent,
      ensureOutcomeActions,
      finishRunningActions,
      refreshHistory,
      appendAgentAction,
      enqueueQueuedAt,
      bumpEpoch,
      epochOf,
      stillOn,
      registerInFlight,
      dropInFlight,
      bumpHistoryRecency,
    ],
  );

  drainQueueRef.current = () => {
    // Angle park holds the queue (ADR 0016). Image park drains as a direction change (ADR 0036).
    if (sendingRef.current || stoppingRef.current || awaitingAnglePickRef.current) {
      return;
    }
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
      const anglePark = anglePickParkFromEvents(res.interrupted, res.events);
      awaitingImageOkRef.current = res.interrupted && !anglePark.parked;
      setAwaitingImageOk(res.interrupted && !anglePark.parked);
      awaitingAnglePickRef.current = anglePark.parked;
      setAwaitingAnglePick(anglePark.parked);
      if (anglePark.parked) {
        if (anglePark.angles.length > 0) setAngleOptions(anglePark.angles);
        setAnglePersonas(anglePark.personas);
        setRecommendedPersona(anglePark.recommendedPersona);
        setRecommendedImageFormat(anglePark.recommendedImageFormat);
      }
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

  const chooseAngle = useCallback(
    async (angle: number | string, persona?: string, imageFormat?: ImageFormat) => {
      if (
        !accessToken ||
        !sessionId ||
        sendingRef.current ||
        stoppingRef.current ||
        !awaitingAnglePickRef.current ||
        (typeof angle === "string" && !angle.trim())
      ) {
        return;
      }
      const boundId = sessionId;
      const epoch = bumpEpoch(boundId);
      suppressLiveTurnEventsRef.current = false;
      const abort = new AbortController();
      registerInFlight(boundId, abort);
      setLlmError(null);
      const pick = typeof angle === "number" ? angle : angle.trim();
      lastAnglePickRef.current = pick;
      setLastAnglePick(pick);
      const personaSlug =
        typeof persona === "string" && persona.trim() ? persona.trim() : undefined;
      if (personaSlug) {
        lastPersonaPickRef.current = personaSlug;
        setLastPersonaPick(personaSlug);
      }
      const pickedFormat = parseImageFormat(imageFormat);
      if (pickedFormat) {
        lastImageFormatPickRef.current = pickedFormat;
        setLastImageFormatPick(pickedFormat);
      }
      bumpHistoryRecency(boundId);
      try {
        const res = await apiChooseSessionAngle(accessToken, boundId, {
          signal: abort.signal,
          angleIndex: typeof angle === "number" ? angle : undefined,
          angle: typeof angle === "string" ? angle.trim() : undefined,
          persona: personaSlug,
          imageFormat: pickedFormat ?? undefined,
        });
        if (abort.signal.aborted || epoch !== epochOf(boundId)) {
          return;
        }
        if (!stillOn(boundId)) {
          void refreshHistory();
          return;
        }
        applyTurnResponse(res);
        void refreshHistory();
      } catch (err) {
        if (abort.signal.aborted || epoch !== epochOf(boundId)) return;
        if (!stillOn(boundId)) return;
        throw err;
      } finally {
        dropInFlight(boundId);
        if (stillOn(boundId)) drainQueueRef.current();
      }
    },
    [
      accessToken,
      sessionId,
      applyTurnResponse,
      refreshHistory,
      bumpEpoch,
      epochOf,
      stillOn,
      registerInFlight,
      dropInFlight,
      bumpHistoryRecency,
    ],
  );

  // Retry at the gate = re-issue the failed pick — never a typed send (that
  // would be read as a NEW pick/feedback, ADR 0028 §3–4).
  const retryAnglePick = useCallback(async () => {
    const pick = lastAnglePickRef.current;
    if (pick === null) return;
    await chooseAngle(
      pick,
      lastPersonaPickRef.current ?? undefined,
      lastImageFormatPickRef.current ?? undefined,
    );
  }, [chooseAngle]);

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
      const boundId = sessionId;
      const epoch = bumpEpoch(boundId);
      suppressLiveTurnEventsRef.current = false;
      const abort = new AbortController();
      registerInFlight(boundId, abort);
      setLlmError(null);
      bumpHistoryRecency(boundId);
      try {
        const res = await apiResumeSessionImage(accessToken, boundId, {
          signal: abort.signal,
          imageFormat,
        });
        if (abort.signal.aborted || epoch !== epochOf(boundId)) {
          return;
        }
        if (!stillOn(boundId)) {
          void refreshHistory();
          return;
        }
        applyTurnResponse(res);
        void refreshHistory();
      } catch (err) {
        if (abort.signal.aborted || epoch !== epochOf(boundId)) return;
        if (!stillOn(boundId)) return;
        throw err;
      } finally {
        dropInFlight(boundId);
        if (stillOn(boundId)) drainQueueRef.current();
      }
    },
    [
      accessToken,
      sessionId,
      applyTurnResponse,
      refreshHistory,
      bumpEpoch,
      epochOf,
      stillOn,
      registerInFlight,
      dropInFlight,
      bumpHistoryRecency,
    ],
  );

  const applyMediaMutation = useCallback(
    (res: PreviewMediaMutationResponse, boundId?: string | null) => {
      if (boundId && !stillOn(boundId)) return null;
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
    },
    [stillOn],
  );

  const updateDraft = useCallback(
    async (copy: DraftCopy) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      const boundId = sessionId;
      setDraftSaving(true);
      try {
        const res = await apiUpdateSessionDraft(accessToken, boundId, copy);
        return applyMediaMutation(res, boundId);
      } finally {
        if (stillOn(boundId)) setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation, stillOn],
  );

  const saveImagePlan = useCallback(
    async (imageId: string, plan: Record<string, unknown>) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      const boundId = sessionId;
      setDraftSaving(true);
      try {
        const res = await apiUpdateImagePlan(accessToken, boundId, imageId, plan);
        const next = applyMediaMutation(res, boundId);
        if (res.awaiting_image_ok && stillOn(boundId)) {
          awaitingImageOkRef.current = true;
          setAwaitingImageOk(true);
        }
        return next;
      } finally {
        if (stillOn(boundId)) setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation, stillOn],
  );

  const regenImage = useCallback(
    async (imageId: string) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      const boundId = sessionId;
      setDraftSaving(true);
      try {
        const res = await apiRegenImage(accessToken, boundId, imageId);
        return applyMediaMutation(res, boundId);
      } finally {
        if (stillOn(boundId)) setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation, stillOn],
  );

  const addImage = useCallback(
    async (format: "single" | "comic_4panel" = "single") => {
      if (!accessToken || !sessionId || draftSaving) return null;
      const boundId = sessionId;
      setDraftSaving(true);
      try {
        const res = await apiAddSessionImage(accessToken, boundId, { format });
        return applyMediaMutation(res, boundId);
      } finally {
        if (stillOn(boundId)) setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation, stillOn],
  );

  const removeImage = useCallback(
    async (imageId: string) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      const boundId = sessionId;
      setDraftSaving(true);
      try {
        const res = await apiRemoveImage(accessToken, boundId, imageId);
        return applyMediaMutation(res, boundId);
      } finally {
        if (stillOn(boundId)) setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation, stillOn],
  );

  const uploadImage = useCallback(
    async (imageId: string, file: File) => {
      if (!accessToken || !sessionId || draftSaving) return null;
      const boundId = sessionId;
      setDraftSaving(true);
      try {
        const res = await apiUploadImage(accessToken, boundId, imageId, file);
        return applyMediaMutation(res, boundId);
      } finally {
        if (stillOn(boundId)) setDraftSaving(false);
      }
    },
    [accessToken, sessionId, draftSaving, applyMediaMutation, stillOn],
  );

  const confirmPost = useCallback(
    async (localCopy?: DraftCopy | null) => {
      if (!accessToken || !sessionId || confirming) return null;
      const boundId = sessionId;
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
          const saved = await apiUpdateSessionDraft(accessToken, boundId, localCopy);
          token = saved.approval_token;
          platform = saved.platform;
          applyMediaMutation(saved, boundId);
        }
        if (!token) throw new Error("Missing approval_token");

        const idempotency_key =
          typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `confirm-${Date.now()}-${Math.random().toString(36).slice(2)}`;

        const receipt = await apiConfirmSession(accessToken, boundId, {
          approval_token: token,
          idempotency_key,
          platform,
        });
        if (!stillOn(boundId)) return receipt;
        setConfirmReceipt(receipt);
        if (isConfirmSuccessStatus(receipt.status)) {
          setSession((prev) => (prev ? { ...prev, status: "confirmed" } : prev));
        }
        return receipt;
      } finally {
        if (stillOn(boundId)) setConfirming(false);
      }
    },
    [accessToken, sessionId, confirming, draft, applyMediaMutation, stillOn],
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
    composerInput,
    setComposerInput,
    editInsertAt,
    setEditInsertAt,
    sseConnected,
    streamingText,
    agentProgress,
    agentActions,
    brief,
    briefAfterMessageId,
    interruptAfterMessageId,
    previewAfterMessageId,
    awaitingImageOk,
    awaitingAnglePick,
    angleOptions,
    anglePersonas,
    recommendedPersona,
    recommendedImageFormat,
    lastImageFormatPick,
    canRetryAnglePick: awaitingAnglePick && lastAnglePick !== null,
    draft,
    confirmReceipt,
    draftSaving,
    confirming,
    llmError,
    history,
    historyLoading,
    restoring,
    forkedFrom,
    forking,
    forkSession,
    sendMessage,
    enqueueQueuedMessage: enqueueQueuedAt,
    dequeueQueuedMessage,
    resumeImage,
    chooseAngle,
    retryAnglePick,
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
    searchHistory,
  };
}
