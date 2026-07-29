import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/auth-context";
import { apiCreateSession, apiPostSessionMessage } from "./api";
import { SseAuthError, subscribeSessionEvents } from "./sse";
import type { AgentProgress, ChatMessage, Session, SessionBrief } from "./types";

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

function parseAgentProgress(data: Record<string, unknown>): AgentProgress | null {
  if (typeof data.node !== "string" || !data.node) return null;
  return {
    node: data.node,
    model_tier: typeof data.model_tier === "string" ? data.model_tier : null,
    model: typeof data.model === "string" ? data.model : null,
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
  const [brief, setBrief] = useState<SessionBrief | null>(null);
  // True while the graph sits at interrupt_before executor_image_plan.
  const [awaitingImageOk, setAwaitingImageOk] = useState(false);

  const sessionId = session?.id ?? null;
  const sseReadyRef = useRef<SseReadyHandle | null>(null);

  // Shared reducer for turn events — SSE delivers them live mid-turn, while the
  // POST /messages response repeats them at the end for the no-SSE path.
  const applyTurnEvent = useCallback(
    (type: string, data: Record<string, unknown>) => {
      if (type === "agent.progress") {
        const progress = parseAgentProgress(data);
        if (progress) setAgentProgress(progress);
        return;
      }
      if (type === "brief.updated") {
        const parsed = parseBrief(data);
        if (parsed) setBrief(parsed);
        return;
      }
      if (type === "draft.awaiting_image_ok") {
        setAwaitingImageOk(true);
        return;
      }
      if (type === "draft.updated" || type === "preview.updated") {
        // Image gen finished / preview persisted — the interrupt is resolved.
        setAwaitingImageOk(false);
        return;
      }
      if (type === "message.assistant" || type === "review.failed" || type === "confirm.completed") {
        setAgentProgress(null);
      }
    },
    [],
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
          const state = data.state as Record<string, unknown> | undefined;
          const snapshotBrief = parseBrief(state?.brief);
          if (snapshotBrief) setBrief(snapshotBrief);
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
  }, [sessionId, accessToken, refreshAccessToken, applyTurnEvent]);

  const sendMessage = useCallback(
    async (content: string) => {
      const text = content.trim();
      if (!text || !accessToken || !companyId || sending) return;
      setSending(true);
      setStreamingText(null);
      setAgentProgress(null);
      // Any new message resumes an interrupted graph, so the card is stale.
      setAwaitingImageOk(false);

      let optimistic: ChatMessage | null = null;
      try {
        let active = session;
        if (!active) {
          active = await apiCreateSession(accessToken, companyId);
          setSession(active);
          await waitForSseReady(sseReadyRef);
        }

        optimistic = {
          id: `local-${Date.now()}`,
          session_id: active.id,
          role: "user",
          content: text,
          created_at: new Date().toISOString(),
        };
        const pending = optimistic;
        setMessages((prev) => [...prev, pending]);

        const res = await apiPostSessionMessage(accessToken, active.id, text);
        setMessages(res.messages);
        setMode(res.mode);
        setStreamingText(null);
        setAwaitingImageOk(res.interrupted);
        for (const ev of res.events ?? []) {
          applyTurnEvent(ev.type, ev.data ?? {});
        }
        setAgentProgress(null);
      } catch (err) {
        if (optimistic) {
          const failed = optimistic;
          setMessages((prev) => prev.filter((m) => m.id !== failed.id));
        }
        setStreamingText(null);
        setAgentProgress(null);
        throw err;
      } finally {
        setSending(false);
      }
    },
    [accessToken, companyId, sending, session, applyTurnEvent],
  );

  return {
    session,
    messages,
    mode,
    sending,
    sseConnected,
    streamingText,
    agentProgress,
    brief,
    awaitingImageOk,
    sendMessage,
  };
}
