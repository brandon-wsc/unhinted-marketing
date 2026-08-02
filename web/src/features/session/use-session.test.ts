import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Session, SessionListItem } from "@/features/session/types";

const {
  apiListSessions,
  apiGetSessionMessages,
  apiCreateSession,
  apiPostSessionMessage,
  apiResumeSessionImage,
  apiStopSessionTurn,
  apiUpdateSession,
  apiDeleteSession,
  apiUpdateSessionDraft,
  apiConfirmSession,
  getRememberedSessionId,
  setRememberedSessionId,
  subscribeSessionEvents,
  refreshAccessToken,
} = vi.hoisted(() => ({
  apiListSessions: vi.fn(),
  apiGetSessionMessages: vi.fn(),
  apiCreateSession: vi.fn(),
  apiPostSessionMessage: vi.fn(),
  apiResumeSessionImage: vi.fn(),
  apiStopSessionTurn: vi.fn(),
  apiUpdateSession: vi.fn(),
  apiDeleteSession: vi.fn(),
  apiUpdateSessionDraft: vi.fn(),
  apiConfirmSession: vi.fn(),
  getRememberedSessionId: vi.fn(),
  setRememberedSessionId: vi.fn(),
  subscribeSessionEvents: vi.fn(),
  refreshAccessToken: vi.fn(),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    accessToken: "tok",
    refreshAccessToken,
  }),
}));

vi.mock("@/features/session/api", () => ({
  apiListSessions,
  apiGetSessionMessages,
  apiCreateSession,
  apiPostSessionMessage,
  apiResumeSessionImage,
  apiStopSessionTurn,
  apiUpdateSession,
  apiDeleteSession,
  apiUpdateSessionDraft,
  apiConfirmSession,
}));

vi.mock("@/features/session/session-storage", () => ({
  getRememberedSessionId,
  setRememberedSessionId,
}));

vi.mock("@/features/session/sse", () => ({
  SseAuthError: class SseAuthError extends Error {
    constructor() {
      super("sse-unauthorized");
      this.name = "SseAuthError";
    }
  },
  subscribeSessionEvents,
}));

import { useSession } from "@/features/session/use-session";

const sessionFixture: Session = {
  id: "sess-1",
  company_id: "co-1",
  user_id: "u-1",
  mode: "CHAT",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const historyItem: SessionListItem = {
  ...sessionFixture,
  title: "Hello",
  pinned: false,
};

describe("useSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getRememberedSessionId.mockReturnValue(null);
    apiListSessions.mockResolvedValue([historyItem]);
    subscribeSessionEvents.mockImplementation(({ onOpen }: { onOpen?: () => void }) => {
      onOpen?.();
      return new Promise<void>(() => {});
    });
  });

  it("skips restore and loads history when no remembered session", async () => {
    const { result } = renderHook(() => useSession("co-1"));

    await waitFor(() => expect(result.current.restoring).toBe(false));
    await waitFor(() => expect(result.current.history).toEqual([historyItem]));
    expect(apiGetSessionMessages).not.toHaveBeenCalled();
  });

  it("restores a remembered session and rebuilds agent actions", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [
        {
          id: "u1",
          session_id: "sess-1",
          role: "user",
          content: "hi",
          created_at: "2026-01-01T00:00:00Z",
          metadata: {
            agent_actions: [{ node: "brainstormer", model_tier: "fast", model: "m1" }],
          },
        },
      ],
    });

    const { result } = renderHook(() => useSession("co-1"));

    await waitFor(() => expect(result.current.restoring).toBe(false));
    expect(result.current.session?.id).toBe("sess-1");
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.agentActions).toEqual([
      expect.objectContaining({
        node: "brainstormer",
        status: "done",
        afterMessageId: "u1",
      }),
    ]);
    expect(result.current.briefAfterMessageId).toBe("u1");
    expect(setRememberedSessionId).toHaveBeenCalledWith("co-1", "sess-1");
  });

  it("clears remembered id and starts fresh when restore fails", async () => {
    getRememberedSessionId.mockReturnValue("sess-gone");
    apiGetSessionMessages.mockRejectedValue(new Error("not found"));

    const { result } = renderHook(() => useSession("co-1"));

    await waitFor(() => expect(result.current.restoring).toBe(false));
    expect(result.current.session).toBeNull();
    expect(setRememberedSessionId).toHaveBeenCalledWith("co-1", null);
  });

  it("startNewChat clears session state and remembered id", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [
        {
          id: "u1",
          session_id: "sess-1",
          role: "user",
          content: "hi",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    act(() => {
      result.current.startNewChat();
    });

    expect(result.current.session).toBeNull();
    expect(result.current.messages).toEqual([]);
    expect(setRememberedSessionId).toHaveBeenCalledWith("co-1", null);
  });

  it("sendMessage creates a session, posts, and applies brief events", async () => {
    apiCreateSession.mockResolvedValue(sessionFixture);
    apiPostSessionMessage.mockResolvedValue({
      session: { ...sessionFixture, mode: "AGENT" },
      messages: [
        {
          id: "u-server",
          session_id: "sess-1",
          role: "user",
          content: "plan a post",
          created_at: "2026-01-01T00:00:01Z",
        },
        {
          id: "a1",
          session_id: "sess-1",
          role: "assistant",
          content: "ok",
          created_at: "2026-01-01T00:00:02Z",
        },
      ],
      interrupted: false,
      mode: "AGENT",
      revision: null,
      pending_confirm: false,
      approval_token: null,
      events: [
        {
          type: "brief.updated",
          data: { summary: "Brief", can_do: ["post"], cannot_do: [], angles: [] },
        },
        { type: "agent.progress", data: { node: "brainstormer", model_tier: "fast" } },
        { type: "message.assistant", data: { id: "a1", content: "ok" } },
      ],
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    await act(async () => {
      await result.current.sendMessage("plan a post");
    });

    expect(apiCreateSession).toHaveBeenCalledWith("tok", "co-1");
    expect(apiPostSessionMessage).toHaveBeenCalledWith(
      "tok",
      "sess-1",
      "plan a post",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.session?.id).toBe("sess-1");
    expect(result.current.mode).toBe("AGENT");
    expect(result.current.brief?.summary).toBe("Brief");
    expect(result.current.briefAfterMessageId).toBe("u-server");
    expect(result.current.agentActions.some((a) => a.node === "brainstormer")).toBe(true);
    expect(result.current.sending).toBe(false);
  });

  it("sendMessage rolls back optimistic user message on failure", async () => {
    apiCreateSession.mockResolvedValue(sessionFixture);
    apiPostSessionMessage.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    await act(async () => {
      await expect(result.current.sendMessage("fail me")).rejects.toThrow("boom");
    });

    expect(result.current.messages).toEqual([]);
    expect(result.current.sending).toBe(false);
  });

  it("confirmPost auto-saves dirty copy then confirms", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: { ...sessionFixture, mode: "PREVIEW" },
      messages: [],
    });
    apiUpdateSessionDraft.mockResolvedValue({
      revision: 2,
      approval_token: "tok-new",
      copy: { caption: "edited", hashtags: ["#hk"], cta: "cta" },
      image_url: null,
      platform: "instagram",
      mode: "PREVIEW",
    });
    apiConfirmSession.mockResolvedValue({
      receipt_id: "r1",
      status: "stubbed",
      tool_name: "publish_social_post",
      idempotency_key: "idem-1",
    });

    // Seed draft via sendMessage preview path first is heavy; open then updateDraft.
    apiUpdateSessionDraft
      .mockResolvedValueOnce({
        revision: 1,
        approval_token: "tok-old",
        copy: { caption: "old", hashtags: [], cta: "" },
        image_url: null,
        platform: "instagram",
        mode: "PREVIEW",
      })
      .mockResolvedValueOnce({
        revision: 2,
        approval_token: "tok-new",
        copy: { caption: "edited", hashtags: ["#hk"], cta: "cta" },
        image_url: null,
        platform: "instagram",
        mode: "PREVIEW",
      });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    await act(async () => {
      await result.current.updateDraft({ caption: "old", hashtags: [], cta: "" });
    });
    expect(result.current.draft?.approval_token).toBe("tok-old");

    await act(async () => {
      await result.current.confirmPost({
        caption: "edited",
        hashtags: ["#hk"],
        cta: "cta",
      });
    });

    expect(apiUpdateSessionDraft).toHaveBeenCalledTimes(2);
    expect(apiConfirmSession).toHaveBeenCalledWith(
      "tok",
      "sess-1",
      expect.objectContaining({
        approval_token: "tok-new",
        platform: "instagram",
      }),
    );
    expect(result.current.confirmReceipt?.receipt_id).toBe("r1");
    expect(result.current.session?.status).toBe("confirmed");
  });

  it("renameSession / pinSession / deleteSession update history", async () => {
    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.history).toHaveLength(1));

    apiUpdateSession.mockResolvedValueOnce({
      ...historyItem,
      title: "Renamed",
    });
    await act(async () => {
      await result.current.renameSession("sess-1", "Renamed");
    });
    expect(result.current.history[0]?.title).toBe("Renamed");

    apiUpdateSession.mockResolvedValueOnce({
      ...historyItem,
      title: "Renamed",
      pinned: true,
    });
    await act(async () => {
      await result.current.pinSession("sess-1", true);
    });
    expect(result.current.history[0]?.pinned).toBe(true);

    apiDeleteSession.mockResolvedValueOnce(undefined);
    await act(async () => {
      await result.current.deleteSession("sess-1");
    });
    expect(result.current.history).toEqual([]);
  });

  it("applies SSE message.delta and brief.updated while connected", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [
        {
          id: "u1",
          session_id: "sess-1",
          role: "user",
          content: "hi",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });

    let onEvent:
      | ((type: string, data: Record<string, unknown>) => void)
      | undefined;
    subscribeSessionEvents.mockImplementation(
      (opts: {
        onOpen?: () => void;
        onEvent: (type: string, data: Record<string, unknown>) => void;
      }) => {
        onEvent = opts.onEvent;
        opts.onOpen?.();
        return new Promise<void>(() => {});
      },
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.sseConnected).toBe(true));

    act(() => {
      onEvent?.("message.delta", { content: "Hel" });
      onEvent?.("message.delta", { content: "lo" });
      onEvent?.("brief.updated", {
        summary: "Live brief",
        can_do: ["x"],
        cannot_do: [],
        angles: [],
      });
      onEvent?.("message.assistant", { id: "a-live", content: "Hello" });
    });

    expect(result.current.streamingText).toBeNull();
    expect(result.current.messages.some((m) => m.id === "a-live")).toBe(true);
    expect(result.current.brief?.summary).toBe("Live brief");
  });

  it("resumeImage calls resume-image and clears awaiting when done", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [
        {
          id: "u1",
          session_id: "sess-1",
          role: "user",
          content: "make a post",
          created_at: "2026-01-01T00:00:01Z",
        },
      ],
    });
    apiPostSessionMessage.mockResolvedValue({
      session: { ...sessionFixture, mode: "AGENT" },
      messages: [
        {
          id: "u1",
          session_id: "sess-1",
          role: "user",
          content: "make a post",
          created_at: "2026-01-01T00:00:01Z",
        },
      ],
      interrupted: true,
      mode: "AGENT",
      revision: null,
      pending_confirm: false,
      approval_token: null,
      events: [{ type: "draft.awaiting_image_ok", data: { awaiting: true } }],
    });
    apiResumeSessionImage.mockResolvedValue({
      session: { ...sessionFixture, mode: "PREVIEW" },
      messages: [
        {
          id: "u1",
          session_id: "sess-1",
          role: "user",
          content: "make a post",
          created_at: "2026-01-01T00:00:01Z",
        },
      ],
      interrupted: false,
      mode: "PREVIEW",
      revision: 1,
      pending_confirm: false,
      approval_token: "tok-1",
      events: [
        {
          type: "preview.updated",
          data: {
            revision: 1,
            approval_token: "tok-1",
            copy: { caption: "hi", hashtags: [], cta: "" },
            image_url: "https://example.com/x.png",
            platform: "instagram",
          },
        },
      ],
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    await act(async () => {
      await result.current.sendMessage("park me");
    });
    expect(result.current.awaitingImageOk).toBe(true);
    expect(result.current.composerLocked).toBe(true);

    await act(async () => {
      await result.current.resumeImage();
    });

    expect(apiResumeSessionImage).toHaveBeenCalledWith(
      "tok",
      "sess-1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.awaitingImageOk).toBe(false);
    expect(result.current.mode).toBe("PREVIEW");
  });

  it("stopTurn discards parked turn and reloads messages", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages
      .mockResolvedValueOnce({
        session: sessionFixture,
        messages: [
          {
            id: "u1",
            session_id: "sess-1",
            role: "user",
            content: "make a post",
            created_at: "2026-01-01T00:00:01Z",
          },
        ],
      })
      .mockResolvedValueOnce({
        session: sessionFixture,
        messages: [],
      });
    apiPostSessionMessage.mockResolvedValue({
      session: sessionFixture,
      messages: [
        {
          id: "u1",
          session_id: "sess-1",
          role: "user",
          content: "make a post",
          created_at: "2026-01-01T00:00:01Z",
        },
      ],
      interrupted: true,
      mode: "AGENT",
      revision: null,
      pending_confirm: false,
      approval_token: null,
      events: [{ type: "draft.awaiting_image_ok", data: { awaiting: true } }],
    });
    apiStopSessionTurn.mockResolvedValue({ status: "cancelled" });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    await act(async () => {
      await result.current.sendMessage("make a post");
    });
    expect(result.current.awaitingImageOk).toBe(true);

    await act(async () => {
      await result.current.stopTurn();
    });

    expect(apiStopSessionTurn).toHaveBeenCalledWith("tok", "sess-1");
    expect(result.current.awaitingImageOk).toBe(false);
    expect(result.current.messages).toEqual([]);
    expect(result.current.composerLocked).toBe(false);
  });
});
