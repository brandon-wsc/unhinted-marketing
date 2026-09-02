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

const sessionB: Session = {
  ...sessionFixture,
  id: "sess-2",
  created_at: "2026-01-02T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const sessionC: Session = {
  ...sessionFixture,
  id: "sess-3",
  created_at: "2026-01-03T00:00:00Z",
  updated_at: "2026-01-03T00:00:00Z",
};

const msgA = {
  id: "u-a",
  session_id: "sess-1",
  role: "user",
  content: "from A",
  created_at: "2026-01-01T00:00:01Z",
};

const msgB = {
  id: "u-b",
  session_id: "sess-2",
  role: "user",
  content: "from B",
  created_at: "2026-01-02T00:00:01Z",
};

const msgC = {
  id: "u-c",
  session_id: "sess-3",
  role: "user",
  content: "from C",
  created_at: "2026-01-03T00:00:01Z",
};

const idleTurn = {
  interrupted: false,
  mode: "CHAT",
  revision: null,
  pending_confirm: false,
  approval_token: null,
  events: [] as { type: string; data?: Record<string, unknown> }[],
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

  it("searchHistory queries the server and restores the list on clear", async () => {
    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.history).toEqual([historyItem]));

    const hit: SessionListItem = {
      ...historyItem,
      id: "sess-hit",
      matched_snippet: "…中秋月餅禮盒…",
    };
    apiListSessions.mockResolvedValue([hit]);
    await act(async () => {
      await result.current.searchHistory("月餅");
    });
    expect(apiListSessions).toHaveBeenLastCalledWith("tok", "co-1", "月餅");
    expect(result.current.history).toEqual([hit]);

    apiListSessions.mockResolvedValue([historyItem]);
    await act(async () => {
      await result.current.searchHistory("   ");
    });
    expect(apiListSessions).toHaveBeenLastCalledWith("tok", "co-1");
    expect(result.current.history).toEqual([historyItem]);
  });

  it("refreshHistory re-applies the active search query", async () => {
    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.history).toEqual([historyItem]));

    const hit: SessionListItem = { ...historyItem, id: "sess-hit" };
    apiListSessions.mockResolvedValue([hit]);
    await act(async () => {
      await result.current.searchHistory("月餅");
    });
    // Opening a session triggers refreshHistory — results must stay filtered.
    await act(async () => {
      await result.current.refreshHistory();
    });
    expect(apiListSessions).toHaveBeenLastCalledWith("tok", "co-1", "月餅");
    expect(result.current.history).toEqual([hit]);
  });

  it("ignores out-of-order search responses", async () => {
    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.history).toEqual([historyItem]));

    let resolveSlow: ((rows: SessionListItem[]) => void) | undefined;
    const slow = new Promise<SessionListItem[]>((res) => {
      resolveSlow = res;
    });
    const fast: SessionListItem = { ...historyItem, id: "sess-fast" };
    apiListSessions.mockImplementation((_tok: string | null, _co: string, q?: string) =>
      q === "slow" ? slow : Promise.resolve([fast]),
    );

    await act(async () => {
      void result.current.searchHistory("slow");
      await result.current.searchHistory("fast");
    });
    expect(result.current.history).toEqual([fast]);

    await act(async () => {
      resolveSlow?.([{ ...historyItem, id: "sess-slow" }]);
      await slow;
    });
    expect(result.current.history).toEqual([fast]);
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
    // No sessions.state.brief on hydrate → no BriefCard anchor.
    expect(result.current.brief).toBeNull();
    expect(result.current.briefAfterMessageId).toBeNull();
    expect(setRememberedSessionId).toHaveBeenCalledWith("co-1", "sess-1");
  });

  it("clears remembered id and starts fresh when restore fails", async () => {
    getRememberedSessionId.mockReturnValue("sess-gone");
    apiGetSessionMessages.mockRejectedValue(new Error("not found"));
    const fresh = {
      ...sessionFixture,
      id: "sess-fresh",
      created_at: "2026-01-02T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
    };
    apiCreateSession.mockResolvedValue(fresh);

    const { result } = renderHook(() => useSession("co-1"));

    await waitFor(() => expect(result.current.restoring).toBe(false));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-fresh"));
    expect(setRememberedSessionId).toHaveBeenCalledWith("co-1", null);
    expect(apiCreateSession).toHaveBeenCalledWith("tok", "co-1");
    expect(setRememberedSessionId).toHaveBeenCalledWith("co-1", "sess-fresh");
  });

  it("startNewChat creates a backend session immediately", async () => {
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
    const fresh = {
      ...sessionFixture,
      id: "sess-new",
      created_at: "2026-01-02T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
    };
    apiCreateSession.mockResolvedValue(fresh);
    apiListSessions.mockResolvedValue([
      {
        ...historyItem,
        id: "sess-new",
        title: null,
        created_at: fresh.created_at,
        updated_at: fresh.updated_at,
      },
      historyItem,
    ]);

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    await act(async () => {
      await result.current.startNewChat();
    });

    expect(apiCreateSession).toHaveBeenCalledWith("tok", "co-1");
    expect(result.current.session?.id).toBe("sess-new");
    expect(result.current.messages).toEqual([]);
    expect(setRememberedSessionId).toHaveBeenCalledWith("co-1", "sess-new");
    expect(result.current.history.some((s) => s.id === "sess-new")).toBe(true);
  });

  it("startNewChat on empty session does not create another row", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [],
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    await act(async () => {
      await result.current.startNewChat();
    });

    expect(apiCreateSession).not.toHaveBeenCalled();
    expect(result.current.session?.id).toBe("sess-1");
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

  it("shows optimistic route progress while the turn POST is in flight", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [],
    });
    let resolvePost: (value: unknown) => void = () => {};
    apiPostSessionMessage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePost = resolve;
        }),
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    let sendPromise: Promise<void> = Promise.resolve();
    act(() => {
      sendPromise = result.current.sendMessage("plan a post");
    });

    await waitFor(() => {
      expect(
        result.current.agentActions.some(
          (a) => a.node === "route_intent" && a.status === "running",
        ),
      ).toBe(true);
    });

    await act(async () => {
      resolvePost({
        session: { ...sessionFixture, mode: "CHAT" },
        messages: [
          {
            id: "u-server",
            session_id: "sess-1",
            role: "user",
            content: "plan a post",
            created_at: "2026-01-01T00:00:01Z",
          },
        ],
        interrupted: false,
        mode: "CHAT",
        revision: null,
        pending_confirm: false,
        approval_token: null,
        events: [
          { type: "agent.progress", data: { node: "fast_rule_checker" } },
          { type: "agent.progress", data: { node: "route_intent", model_tier: "cheap" } },
        ],
      });
      await sendPromise;
    });

    expect(result.current.agentActions.some((a) => a.node === "fast_rule_checker")).toBe(false);
    expect(
      result.current.agentActions.some((a) => a.node === "route_intent" && a.status === "done"),
    ).toBe(true);
  });

  it("bumps an old session to the top of history as soon as you send", async () => {
    const newer: SessionListItem = {
      ...historyItem,
      id: "sess-new",
      title: "Newer",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    };
    getRememberedSessionId.mockReturnValue("sess-1");
    apiListSessions.mockResolvedValue([newer, historyItem]);
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [],
    });
    let resolvePost: (value: unknown) => void = () => {};
    apiPostSessionMessage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePost = resolve;
        }),
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() =>
      expect(result.current.history.map((s) => s.id)).toEqual(["sess-new", "sess-1"]),
    );

    act(() => {
      void result.current.sendMessage("hello again");
    });

    await waitFor(() => {
      expect(result.current.history[0]?.id).toBe("sess-1");
    });

    await act(async () => {
      resolvePost({
        session: sessionFixture,
        messages: [
          {
            id: "u-server",
            session_id: "sess-1",
            role: "user",
            content: "hello again",
            created_at: "2026-08-23T00:00:01Z",
          },
        ],
        ...idleTurn,
      });
    });
  });

  it("queues a follow-up send until the in-flight turn finishes", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [],
    });
    let resolveFirst: (value: unknown) => void = () => {};
    apiPostSessionMessage
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValueOnce({
        session: sessionFixture,
        messages: [
          {
            id: "u-b",
            session_id: "sess-1",
            role: "user",
            content: "follow up",
            created_at: "2026-01-01T00:00:03Z",
          },
        ],
        interrupted: false,
        mode: "CHAT",
        revision: null,
        pending_confirm: false,
        approval_token: null,
        events: [],
      });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    act(() => {
      void result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.sending).toBe(true));
    expect(result.current.composerLocked).toBe(false);

    await act(async () => {
      await result.current.sendMessage("follow up");
    });
    expect(apiPostSessionMessage).toHaveBeenCalledTimes(1);
    expect(result.current.queuedMessages.map((q) => q.content)).toEqual(["follow up"]);

    await act(async () => {
      resolveFirst({
        session: sessionFixture,
        messages: [
          {
            id: "u-a",
            session_id: "sess-1",
            role: "user",
            content: "first",
            created_at: "2026-01-01T00:00:01Z",
          },
        ],
        interrupted: false,
        mode: "CHAT",
        revision: null,
        pending_confirm: false,
        approval_token: null,
        events: [],
      });
    });

    await waitFor(() => expect(apiPostSessionMessage).toHaveBeenCalledTimes(2));
    expect(apiPostSessionMessage.mock.calls[1]?.[2]).toBe("follow up");
    await waitFor(() => expect(result.current.queuedMessages).toEqual([]));
  });

  it("inserts a follow-up at queueIndex instead of appending", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [],
    });
    apiPostSessionMessage.mockImplementation(() => new Promise(() => {}));

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    act(() => {
      void result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.sending).toBe(true));

    await act(async () => {
      await result.current.sendMessage("tail");
      await result.current.sendMessage("head", { queueIndex: 0 });
    });

    expect(result.current.queuedMessages.map((q) => q.content)).toEqual(["head", "tail"]);
  });

  it("enqueueQueuedMessage inserts at an index", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [],
    });
    apiPostSessionMessage.mockImplementation(() => new Promise(() => {}));

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    act(() => {
      void result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.sending).toBe(true));

    await act(async () => {
      await result.current.sendMessage("b");
      expect(result.current.enqueueQueuedMessage("a", 0)).toBe(true);
    });

    expect(result.current.queuedMessages.map((q) => q.content)).toEqual(["a", "b"]);
  });

  it("does not drain the queue while parked at image OK", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [],
    });
    let resolveFirst: (value: unknown) => void = () => {};
    apiPostSessionMessage.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve;
        }),
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    act(() => {
      void result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.sending).toBe(true));
    await act(async () => {
      await result.current.sendMessage("queued while running");
    });

    await act(async () => {
      resolveFirst({
        session: sessionFixture,
        messages: [
          {
            id: "u-a",
            session_id: "sess-1",
            role: "user",
            content: "first",
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
    });

    await waitFor(() => expect(result.current.awaitingImageOk).toBe(true));
    expect(apiPostSessionMessage).toHaveBeenCalledTimes(1);
    expect(result.current.queuedMessages.map((q) => q.content)).toEqual(["queued while running"]);
  });

  it("keeps the queue across Stop and drains after unlock", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: sessionFixture,
      messages: [],
    });
    let resolveFirst: (value: unknown) => void = () => {};
    apiPostSessionMessage
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValueOnce({
        session: sessionFixture,
        messages: [
          {
            id: "u-b",
            session_id: "sess-1",
            role: "user",
            content: "after stop",
            created_at: "2026-01-01T00:00:04Z",
          },
        ],
        interrupted: false,
        mode: "CHAT",
        revision: null,
        pending_confirm: false,
        approval_token: null,
        events: [],
      });
    apiStopSessionTurn.mockResolvedValue({
      status: "cancelled",
      interrupted: false,
      awaiting_image_ok: false,
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    act(() => {
      void result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.sending).toBe(true));
    await act(async () => {
      await result.current.sendMessage("after stop");
    });

    await act(async () => {
      await result.current.stopTurn();
      resolveFirst({
        session: sessionFixture,
        messages: [],
        interrupted: false,
        mode: "CHAT",
        revision: null,
        pending_confirm: false,
        approval_token: null,
        events: [],
      });
    });

    await waitFor(() => expect(apiPostSessionMessage).toHaveBeenCalledTimes(2));
    expect(apiPostSessionMessage.mock.calls[1]?.[2]).toBe("after stop");
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

  it("does not mark the session confirmed when confirm returns failed", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: { ...sessionFixture, mode: "PREVIEW" },
      messages: [],
    });
    apiUpdateSessionDraft.mockResolvedValue({
      revision: 1,
      approval_token: "tok-fail",
      copy: { caption: "hi", hashtags: [], cta: "" },
      image_url: "https://cdn.example/a.png",
      platform: "instagram",
      mode: "PREVIEW",
    });
    apiConfirmSession.mockResolvedValue({
      receipt_id: "r-fail",
      status: "failed",
      tool_name: "publish_social_post",
      idempotency_key: "idem-fail",
      error_kind: "platform_error",
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));
    expect(result.current.session?.status).toBe("active");

    await act(async () => {
      await result.current.updateDraft({ caption: "hi", hashtags: [], cta: "" });
    });
    await act(async () => {
      await result.current.confirmPost();
    });

    expect(result.current.confirmReceipt?.status).toBe("failed");
    expect(result.current.confirmReceipt?.error_kind).toBe("platform_error");
    expect(result.current.session?.status).toBe("active");
  });

  it("hydrates confirm receipt permalink from session.snapshot", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: { ...sessionFixture, mode: "PREVIEW", status: "confirmed" },
      messages: [],
    });
    const handlers = new Map<string, (type: string, data: Record<string, unknown>) => void>();
    subscribeSessionEvents.mockImplementation(
      (opts: {
        sessionId: string;
        onOpen?: () => void;
        onEvent: (type: string, data: Record<string, unknown>) => void;
      }) => {
        handlers.set(opts.sessionId, opts.onEvent);
        opts.onOpen?.();
        return new Promise<void>(() => {});
      },
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    await act(async () => {
      handlers.get("sess-1")?.("session.snapshot", {
        status: "confirmed",
        confirm_receipt: {
          receipt_id: "r-pub",
          status: "published",
          permalink: "https://www.instagram.com/p/ABC/",
        },
      });
    });

    expect(result.current.session?.status).toBe("confirmed");
    expect(result.current.confirmReceipt).toEqual(
      expect.objectContaining({
        receipt_id: "r-pub",
        status: "published",
        permalink: "https://www.instagram.com/p/ABC/",
      }),
    );
  });

  it("parses permalink and error_kind from confirm.completed without treating failed as confirmed", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: { ...sessionFixture, mode: "PREVIEW" },
      messages: [],
    });
    const handlers = new Map<string, (type: string, data: Record<string, unknown>) => void>();
    subscribeSessionEvents.mockImplementation(
      (opts: {
        sessionId: string;
        onOpen?: () => void;
        onEvent: (type: string, data: Record<string, unknown>) => void;
      }) => {
        handlers.set(opts.sessionId, opts.onEvent);
        opts.onOpen?.();
        return new Promise<void>(() => {});
      },
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    await act(async () => {
      handlers.get("sess-1")?.("confirm.completed", {
        receipt_id: "r-fail",
        status: "failed",
        error_kind: "token_expired",
      });
    });
    expect(result.current.confirmReceipt?.error_kind).toBe("token_expired");
    expect(result.current.session?.status).toBe("active");

    await act(async () => {
      handlers.get("sess-1")?.("confirm.completed", {
        receipt_id: "r-pub",
        status: "published",
        permalink: "https://www.instagram.com/p/XYZ/",
      });
    });
    expect(result.current.confirmReceipt?.permalink).toBe("https://www.instagram.com/p/XYZ/");
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

    let onEvent: ((type: string, data: Record<string, unknown>) => void) | undefined;
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
    // Parked image-OK keeps the composer editable — only a running turn locks it.
    expect(result.current.composerLocked).toBe(false);

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
    expect(result.current.previewAfterMessageId).toBe("u1");
  });

  it("keeps previewAfterMessageId on the preview turn after a later send", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockResolvedValue({
      session: { ...sessionFixture, mode: "PREVIEW" },
      messages: [
        {
          id: "u1",
          session_id: "sess-1",
          role: "user",
          content: "make a post",
          created_at: "2026-01-01T00:00:01Z",
          metadata: {
            agent_actions: [{ node: "executor_image_gen", model: "img" }],
          },
        },
      ],
    });
    apiPostSessionMessage
      .mockResolvedValueOnce({
        session: { ...sessionFixture, mode: "PREVIEW" },
        messages: [
          {
            id: "u1",
            session_id: "sess-1",
            role: "user",
            content: "make a post",
            created_at: "2026-01-01T00:00:01Z",
            metadata: {
              agent_actions: [{ node: "executor_image_gen", model: "img" }],
            },
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
      })
      .mockResolvedValueOnce({
        session: { ...sessionFixture, mode: "PREVIEW" },
        messages: [
          {
            id: "u1",
            session_id: "sess-1",
            role: "user",
            content: "make a post",
            created_at: "2026-01-01T00:00:01Z",
            metadata: {
              agent_actions: [{ node: "executor_image_gen", model: "img" }],
            },
          },
          {
            id: "u2",
            session_id: "sess-1",
            role: "user",
            content: "tweak caption",
            created_at: "2026-01-01T00:00:02Z",
          },
        ],
        interrupted: false,
        mode: "PREVIEW",
        revision: 1,
        pending_confirm: false,
        approval_token: "tok-1",
        events: [
          {
            type: "agent.progress",
            data: { node: "brainstormer", model_tier: "cheap", model: "m" },
          },
        ],
      });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));
    // openSession with PREVIEW + executor_image_gen metadata
    expect(result.current.previewAfterMessageId).toBe("u1");

    await act(async () => {
      await result.current.sendMessage("seed preview");
    });
    expect(result.current.previewAfterMessageId).toBe("u1");

    await act(async () => {
      await result.current.sendMessage("tweak caption");
    });
    expect(result.current.previewAfterMessageId).toBe("u1");
    expect(result.current.messages.some((m) => m.id === "u2")).toBe(true);
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
    apiStopSessionTurn.mockResolvedValue({
      status: "cancelled",
      interrupted: false,
      awaiting_image_ok: false,
    });

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

  it("stopTurn restores BriefCard from hydrated session brief", async () => {
    const brief = {
      summary: "Keep this brief",
      can_do: ["a"],
      cannot_do: [],
      angles: [],
      persona: null,
    };
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
        brief,
        awaiting_image_ok: true,
      })
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
        brief,
        awaiting_image_ok: true,
      });
    apiResumeSessionImage.mockImplementation(
      () =>
        new Promise(() => {
          /* hang until stop */
        }),
    );
    apiStopSessionTurn.mockResolvedValue({
      status: "cancelled",
      interrupted: true,
      awaiting_image_ok: true,
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));
    expect(result.current.brief?.summary).toBe("Keep this brief");
    expect(result.current.awaitingImageOk).toBe(true);

    await act(async () => {
      void result.current.resumeImage();
    });
    await waitFor(() => expect(result.current.sending).toBe(true));

    await act(async () => {
      await result.current.stopTurn();
    });

    expect(result.current.awaitingImageOk).toBe(true);
    expect(result.current.brief?.summary).toBe("Keep this brief");
    expect(result.current.briefAfterMessageId).toBe("u1");
    expect(result.current.sending).toBe(false);
  });

  it("stopTurn mid resume-image keeps Generate-image CTA", async () => {
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

    let resolveResume: (value: unknown) => void = () => {};
    apiResumeSessionImage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveResume = resolve;
        }),
    );
    apiStopSessionTurn.mockResolvedValue({
      status: "cancelled",
      interrupted: true,
      awaiting_image_ok: true,
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));

    await act(async () => {
      await result.current.sendMessage("park me");
    });
    expect(result.current.awaitingImageOk).toBe(true);

    let resumePromise: Promise<void>;
    await act(async () => {
      resumePromise = result.current.resumeImage();
    });
    await waitFor(() => expect(result.current.sending).toBe(true));

    await act(async () => {
      await result.current.stopTurn();
    });

    // Unblock stalled resume (aborted / discarded).
    await act(async () => {
      resolveResume({
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
        events: [],
      });
      await resumePromise!;
    });

    expect(result.current.awaitingImageOk).toBe(true);
    // Parked image-OK no longer locks the composer — Send stays available.
    expect(result.current.composerLocked).toBe(false);
    expect(result.current.sending).toBe(false);
  });

  it("ignores late sendMessage response after stop", async () => {
    const priorAssistant = {
      id: "a1",
      session_id: "sess-1",
      role: "assistant",
      content: "prior reply",
      created_at: "2026-01-01T00:00:00Z",
    };
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages
      .mockResolvedValueOnce({
        session: sessionFixture,
        messages: [priorAssistant],
      })
      .mockResolvedValueOnce({
        session: sessionFixture,
        messages: [priorAssistant],
      });

    let resolveSend: (value: unknown) => void = () => {};
    apiPostSessionMessage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSend = resolve;
        }),
    );
    apiStopSessionTurn.mockResolvedValue({
      status: "cancelled",
      interrupted: false,
      awaiting_image_ok: false,
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.restoring).toBe(false));
    expect(result.current.messages).toEqual([priorAssistant]);

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage("OK，幫我生成圖片。");
    });
    await waitFor(() => expect(result.current.sending).toBe(true));

    await act(async () => {
      await result.current.stopTurn();
    });
    expect(result.current.messages).toEqual([priorAssistant]);
    expect(result.current.sending).toBe(false);

    // Late POST /messages resolve must not resurrect the discarded turn.
    await act(async () => {
      resolveSend({
        session: sessionFixture,
        messages: [
          priorAssistant,
          {
            id: "u-discarded",
            session_id: "sess-1",
            role: "user",
            content: "OK，幫我生成圖片。",
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
            type: "agent.progress",
            data: {
              node: "executor_image_gen",
              model_tier: null,
              model: "x",
            },
          },
        ],
      });
      await sendPromise!;
    });

    expect(result.current.messages).toEqual([priorAssistant]);
    expect(result.current.agentActions).toEqual([]);
    expect(result.current.composerLocked).toBe(false);
  });

  it("does not paint an in-flight turn onto another session", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockImplementation((_tok: string | null, id: string) =>
      Promise.resolve(
        id === "sess-2"
          ? { session: sessionB, messages: [msgB] }
          : { session: sessionFixture, messages: [msgA] },
      ),
    );
    let resolvePost: (value: unknown) => void = () => {};
    apiPostSessionMessage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePost = resolve;
        }),
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    act(() => {
      void result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.sending).toBe(true));

    await act(async () => {
      await result.current.openSession("sess-2");
    });
    expect(result.current.session?.id).toBe("sess-2");
    expect(result.current.sending).toBe(false);
    expect(result.current.messages).toEqual([msgB]);

    await act(async () => {
      resolvePost({
        session: sessionFixture,
        messages: [
          msgA,
          {
            id: "u-a2",
            session_id: "sess-1",
            role: "user",
            content: "first",
            created_at: "2026-01-01T00:00:02Z",
          },
        ],
        ...idleTurn,
      });
    });

    expect(result.current.session?.id).toBe("sess-2");
    expect(result.current.messages).toEqual([msgB]);
    expect(result.current.sending).toBe(false);
  });

  it("restores sending when returning to a session with a live POST", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockImplementation((_tok: string | null, id: string) =>
      Promise.resolve(
        id === "sess-2"
          ? { session: sessionB, messages: [msgB] }
          : { session: sessionFixture, messages: [msgA] },
      ),
    );
    let resolvePost: (value: unknown) => void = () => {};
    apiPostSessionMessage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePost = resolve;
        }),
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    act(() => {
      void result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.sending).toBe(true));

    await act(async () => {
      await result.current.openSession("sess-2");
    });
    expect(result.current.sending).toBe(false);

    await act(async () => {
      await result.current.openSession("sess-1");
    });
    expect(result.current.session?.id).toBe("sess-1");
    expect(result.current.sending).toBe(true);
    expect(result.current.messages.some((m) => m.content === "first")).toBe(true);

    await act(async () => {
      resolvePost({
        session: sessionFixture,
        messages: [
          msgA,
          {
            id: "u-a2",
            session_id: "sess-1",
            role: "user",
            content: "first",
            created_at: "2026-01-01T00:00:02Z",
          },
        ],
        ...idleTurn,
      });
    });

    await waitFor(() => expect(result.current.sending).toBe(false));
    expect(result.current.messages.some((m) => m.content === "first")).toBe(true);
  });

  it("saves and restores queue plus textarea across session switch", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockImplementation((_tok: string | null, id: string) =>
      Promise.resolve(
        id === "sess-2"
          ? { session: sessionB, messages: [msgB] }
          : { session: sessionFixture, messages: [msgA] },
      ),
    );
    apiPostSessionMessage.mockImplementation(() => new Promise(() => {}));

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    act(() => {
      result.current.setComposerInput("half typed");
      void result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.sending).toBe(true));
    await act(async () => {
      await result.current.sendMessage("queued on A");
    });

    await act(async () => {
      await result.current.openSession("sess-2");
    });
    expect(result.current.queuedMessages).toEqual([]);
    expect(result.current.composerInput).toBe("");

    act(() => {
      result.current.setComposerInput("from B");
    });

    await act(async () => {
      await result.current.openSession("sess-1");
    });
    expect(result.current.composerInput).toBe("half typed");
    expect(result.current.queuedMessages.map((q) => q.content)).toEqual(["queued on A"]);
  });

  it("ignores a slower openSession hydrate", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    let resolveB: ((value: unknown) => void) | undefined;
    apiGetSessionMessages.mockImplementation((_tok: string | null, id: string) => {
      if (id === "sess-2") {
        return new Promise((resolve) => {
          resolveB = resolve;
        });
      }
      if (id === "sess-3") {
        return Promise.resolve({ session: sessionC, messages: [msgC] });
      }
      return Promise.resolve({ session: sessionFixture, messages: [msgA] });
    });

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    await act(async () => {
      void result.current.openSession("sess-2");
      await result.current.openSession("sess-3");
    });
    expect(result.current.session?.id).toBe("sess-3");
    expect(result.current.messages).toEqual([msgC]);

    await act(async () => {
      resolveB?.({ session: sessionB, messages: [msgB] });
    });
    expect(result.current.session?.id).toBe("sess-3");
    expect(result.current.messages).toEqual([msgC]);
  });

  it("startNewChat stashes the previous session composer draft", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockImplementation((_tok: string | null, id: string) =>
      Promise.resolve(
        id === "sess-new"
          ? { session: { ...sessionFixture, id: "sess-new" }, messages: [] }
          : { session: sessionFixture, messages: [msgA] },
      ),
    );
    const fresh = {
      ...sessionFixture,
      id: "sess-new",
      created_at: "2026-01-02T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
    };
    apiCreateSession.mockResolvedValue(fresh);

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    act(() => {
      result.current.setComposerInput("keep me");
    });

    await act(async () => {
      await result.current.startNewChat();
    });
    expect(result.current.session?.id).toBe("sess-new");
    expect(result.current.composerInput).toBe("");
    expect(result.current.messages).toEqual([]);

    await act(async () => {
      await result.current.openSession("sess-1");
    });
    expect(result.current.session?.id).toBe("sess-1");
    expect(result.current.composerInput).toBe("keep me");
  });

  it("does not apply the previous session SSE onto the chat after switch", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockImplementation((_tok: string | null, id: string) =>
      Promise.resolve(
        id === "sess-2"
          ? { session: sessionB, messages: [msgB] }
          : { session: sessionFixture, messages: [msgA] },
      ),
    );
    const handlers = new Map<string, (type: string, data: Record<string, unknown>) => void>();
    subscribeSessionEvents.mockImplementation(
      (opts: {
        sessionId: string;
        onOpen?: () => void;
        onEvent: (type: string, data: Record<string, unknown>) => void;
      }) => {
        handlers.set(opts.sessionId, opts.onEvent);
        opts.onOpen?.();
        return new Promise<void>(() => {});
      },
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    await act(async () => {
      await result.current.openSession("sess-2");
    });
    expect(result.current.messages).toEqual([msgB]);

    await act(async () => {
      handlers.get("sess-1")?.("message.delta", { content: "leak from A" });
      handlers.get("sess-1")?.("message.assistant", {
        id: "a-leak",
        content: "leak from A",
      });
    });

    expect(result.current.session?.id).toBe("sess-2");
    expect(result.current.messages).toEqual([msgB]);
    expect(result.current.streamingText).toBeNull();
    expect(result.current.messages.some((m) => m.id === "a-leak")).toBe(false);
  });

  it("does not show the Generate-image card when snapshot interrupted is only an in-flight graph", async () => {
    getRememberedSessionId.mockReturnValue("sess-1");
    apiGetSessionMessages.mockImplementation((_tok: string | null, id: string) =>
      Promise.resolve(
        id === "sess-2"
          ? { session: sessionB, messages: [msgB], awaiting_image_ok: false }
          : { session: sessionFixture, messages: [msgA], awaiting_image_ok: false },
      ),
    );
    const handlers = new Map<string, (type: string, data: Record<string, unknown>) => void>();
    subscribeSessionEvents.mockImplementation(
      (opts: {
        sessionId: string;
        onOpen?: () => void;
        onEvent: (type: string, data: Record<string, unknown>) => void;
      }) => {
        handlers.set(opts.sessionId, opts.onEvent);
        opts.onOpen?.();
        return new Promise<void>(() => {});
      },
    );

    const { result } = renderHook(() => useSession("co-1"));
    await waitFor(() => expect(result.current.session?.id).toBe("sess-1"));

    await act(async () => {
      await result.current.openSession("sess-2");
    });
    expect(result.current.awaitingImageOk).toBe(false);

    await act(async () => {
      handlers.get("sess-2")?.("session.snapshot", {
        interrupted: true,
        state: {},
        mode: "AGENT",
      });
    });
    expect(result.current.awaitingImageOk).toBe(false);

    await act(async () => {
      handlers.get("sess-2")?.("session.snapshot", {
        interrupted: true,
        state: { awaiting_image_ok: true },
        mode: "AGENT",
      });
    });
    expect(result.current.awaitingImageOk).toBe(true);
    expect(result.current.interruptAfterMessageId).toBe("u-b");
  });
});
