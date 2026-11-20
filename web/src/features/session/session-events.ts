import type { Dispatch, SetStateAction } from "react";
import {
  agentActionsFromMessages,
  filterOfferedAngles,
  filterOfferedPersonas,
  type ImageFormat,
  isConfirmSuccessStatus,
  mergePreviewDraft,
  parseAgentProgress,
  parseAngleIndex,
  parseBrief,
  parseConfirmReceipt,
  parseDraftCopy,
  parseImageFormat,
  parseMediaItems,
  parseSourceSignals,
  previewAnchorFromActions,
  previewDraftFromPayload,
} from "./session-helpers";
import type {
  AgentActionRecord,
  AgentProgress,
  AudiencePersonaOption,
  ChatMessage,
  ConfirmSessionResponse,
  PreviewDraft,
  Session,
  SessionBrief,
} from "./types";

// Everything the event interpreter touches outside itself — grouped so the
// seam reads as three roles: live refs, the in-flight kernel, and UI setters.
export type SessionEventContext = {
  refs: {
    sessionIdRef: { current: string | null };
    suppressLiveTurnEventsRef: { current: boolean };
    turnAnchorRef: { current: string | null };
    awaitingImageOkRef: { current: boolean };
    awaitingAnglePickRef: { current: boolean };
    messagesRef: { current: ChatMessage[] };
    stoppingRef: { current: boolean };
  };
  kernel: {
    bumpEpoch: (id: string) => number;
    dropInFlight: (id: string | null | undefined) => void;
    lastUserMessageId: () => string | null;
  };
  trail: {
    setAgentProgress: Dispatch<SetStateAction<AgentProgress | null>>;
    setAgentActions: Dispatch<SetStateAction<AgentActionRecord[]>>;
    finishRunningActions: () => void;
    appendAgentAction: (progress: AgentProgress, afterMessageId: string | null) => void;
  };
  ui: {
    setMode: Dispatch<SetStateAction<string>>;
    setSession: Dispatch<SetStateAction<Session | null>>;
    setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
    setStreamingText: Dispatch<SetStateAction<string | null>>;
    setBrief: Dispatch<SetStateAction<SessionBrief | null>>;
    setBriefAfterMessageId: Dispatch<SetStateAction<string | null>>;
    setInterruptAfterMessageId: Dispatch<SetStateAction<string | null>>;
    setPreviewAfterMessageId: Dispatch<SetStateAction<string | null>>;
    setAwaitingImageOk: Dispatch<SetStateAction<boolean>>;
    setAwaitingAnglePick: Dispatch<SetStateAction<boolean>>;
    setAngleOptions: Dispatch<SetStateAction<string[]>>;
    setAnglePersonas: Dispatch<SetStateAction<AudiencePersonaOption[]>>;
    setRecommendedPersona: Dispatch<SetStateAction<string | null>>;
    setRecommendedAngleIndex: Dispatch<SetStateAction<number | null>>;
    setRecommendedImageFormat: Dispatch<SetStateAction<ImageFormat | null>>;
    setDraft: Dispatch<SetStateAction<PreviewDraft | null>>;
    setConfirmReceipt: Dispatch<SetStateAction<ConfirmSessionResponse | null>>;
    setLlmError: Dispatch<SetStateAction<string | null>>;
    setStopping: Dispatch<SetStateAction<boolean>>;
  };
};

// Shared reducer for turn events — SSE delivers them live mid-turn, while the
// POST /messages response repeats them at the end for the no-SSE path.
export function applyTurnEvent(
  ctx: SessionEventContext,
  type: string,
  data: Record<string, unknown>,
) {
  const {
    sessionIdRef,
    suppressLiveTurnEventsRef,
    turnAnchorRef,
    awaitingImageOkRef,
    awaitingAnglePickRef,
    messagesRef,
    stoppingRef,
  } = ctx.refs;
  const { bumpEpoch, dropInFlight, lastUserMessageId } = ctx.kernel;
  const { setAgentProgress, setAgentActions, finishRunningActions, appendAgentAction } = ctx.trail;
  const {
    setInterruptAfterMessageId,
    setStreamingText,
    setMessages,
    setAwaitingImageOk,
    setAwaitingAnglePick,
    setDraft,
    setBrief,
    setBriefAfterMessageId,
    setAngleOptions,
    setAnglePersonas,
    setRecommendedPersona,
    setRecommendedAngleIndex,
    setRecommendedImageFormat,
    setPreviewAfterMessageId,
    setConfirmReceipt,
    setSession,
    setLlmError,
    setStopping,
  } = ctx.ui;

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
        setAgentActions((prev) => prev.filter((a) => !a.afterMessageId || !drop(a.afterMessageId)));
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
    const rec = typeof data.recommended_persona === "string" ? data.recommended_persona.trim() : "";
    setRecommendedPersona(rec || null);
    setRecommendedAngleIndex(parseAngleIndex(data.recommended_angle_index));
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
        source_signals: parseSourceSignals(data.source_signals),
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
  if (type === "message.assistant" || type === "review.failed" || type === "confirm.completed") {
    finishRunningActions();
  }
}

// SSE-only dispatch — snapshot + live message rows exist only on the stream;
// everything else shares the turn-event reducer with the REST replay path.
export function applySessionSseEvent(
  ctx: SessionEventContext,
  sessionId: string,
  type: string,
  data: Record<string, unknown>,
) {
  const { suppressLiveTurnEventsRef, awaitingImageOkRef, awaitingAnglePickRef, messagesRef } =
    ctx.refs;
  const { lastUserMessageId } = ctx.kernel;
  const {
    setMode,
    setSession,
    setConfirmReceipt,
    setBrief,
    setBriefAfterMessageId,
    setDraft,
    setPreviewAfterMessageId,
    setAwaitingImageOk,
    setAwaitingAnglePick,
    setAngleOptions,
    setAnglePersonas,
    setRecommendedPersona,
    setRecommendedAngleIndex,
    setRecommendedImageFormat,
    setInterruptAfterMessageId,
    setStreamingText,
    setMessages,
  } = ctx.ui;

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
        source_signals: parseSourceSignals(data.source_signals),
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
      const sticky = typeof state?.chosen_persona === "string" ? state.chosen_persona.trim() : "";
      const briefPersona = (state?.brief as { persona?: unknown } | undefined)?.persona;
      const rec = sticky || (typeof briefPersona === "string" ? briefPersona.trim() : "");
      setRecommendedPersona(rec || null);
      const snapBrief = state?.brief as { recommended_angle_index?: unknown } | undefined;
      setRecommendedAngleIndex(parseAngleIndex(snapBrief?.recommended_angle_index));
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
  applyTurnEvent(ctx, type, data);
}
