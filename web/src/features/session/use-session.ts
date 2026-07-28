import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/auth-context";
import { apiCreateSession, apiPostSessionMessage } from "./api";
import { SseAuthError, subscribeSessionEvents } from "./sse";
import type { ChatMessage, Session } from "./types";

type SseReadyHandle = { promise: Promise<void>; resolve: () => void };

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

  const sessionId = session?.id ?? null;
  const sseReadyRef = useRef<SseReadyHandle | null>(null);

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
  }, [sessionId, accessToken, refreshAccessToken]);

  const sendMessage = useCallback(
    async (content: string) => {
      const text = content.trim();
      if (!text || !accessToken || !companyId || sending) return;
      setSending(true);
      setStreamingText(null);

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
      } catch (err) {
        if (optimistic) {
          const failed = optimistic;
          setMessages((prev) => prev.filter((m) => m.id !== failed.id));
        }
        setStreamingText(null);
        throw err;
      } finally {
        setSending(false);
      }
    },
    [accessToken, companyId, sending, session],
  );

  return { session, messages, mode, sending, sseConnected, streamingText, sendMessage };
}
