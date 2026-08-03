import { fetchEventSource } from "@microsoft/fetch-event-source";

import { API_BASE } from "@/lib/api-base";

export class SseAuthError extends Error {
  constructor() {
    super("sse-unauthorized");
    this.name = "SseAuthError";
  }
}

type SubscribeOptions = {
  sessionId: string;
  accessToken: string;
  signal: AbortSignal;
  onEvent: (type: string, data: Record<string, unknown>) => void;
  onOpen?: () => void;
};

// Native EventSource cannot send Authorization headers, so SSE goes through fetch.
// All retries are disabled (onerror rethrows): reconnects are owned by the caller,
// which must re-enter with a fresh token after a 401.
export function subscribeSessionEvents({
  sessionId,
  accessToken,
  signal,
  onEvent,
  onOpen,
}: SubscribeOptions): Promise<void> {
  return fetchEventSource(`${API_BASE}/sessions/${sessionId}/events`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
    openWhenHidden: true,
    async onopen(res) {
      if (res.status === 401) throw new SseAuthError();
      if (!res.ok) throw new Error(`sse-open-failed-${res.status}`);
      onOpen?.();
    },
    onmessage(msg) {
      if (msg.event === "heartbeat") return;
      let data: Record<string, unknown> = {};
      try {
        data = msg.data ? (JSON.parse(msg.data) as Record<string, unknown>) : {};
      } catch {
        // Malformed event payload — skip rather than kill the stream.
        return;
      }
      onEvent(msg.event, data);
    },
    onerror(err) {
      throw err;
    },
  });
}
