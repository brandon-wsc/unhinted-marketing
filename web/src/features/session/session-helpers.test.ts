import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  agentActionsFromMessages,
  agentNodeFallbackKey,
  agentNodeLabelKey,
  agentTrailHeader,
  asStringList,
  bumpSessionInHistory,
  EMPTY_COMPOSER_DRAFT,
  isUserFacingAgentNode,
  MAX_QUEUED_SESSION_MESSAGES,
  mergePreviewDraft,
  newActionId,
  newQueuedChatMessage,
  OUTCOME_NODE,
  parseAgentProgress,
  parseBrief,
  parseDraftCopy,
  parseTurnDurationMs,
  previewAnchorFromActions,
  readComposerDraft,
  sortSessionHistory,
  stashComposerDraft,
  waitForSseReady,
} from "@/features/session/session-helpers";
import type {
  AgentActionRecord,
  ChatMessage,
  ComposerDraft,
  PreviewDraft,
  SessionListItem,
} from "@/features/session/types";

describe("asStringList", () => {
  it("keeps only string entries", () => {
    expect(asStringList(["a", 1, null, "b"])).toEqual(["a", "b"]);
  });

  it("returns empty for non-arrays", () => {
    expect(asStringList(null)).toEqual([]);
    expect(asStringList("x")).toEqual([]);
  });
});

describe("parseBrief", () => {
  it("returns null for empty / invalid payloads", () => {
    expect(parseBrief(null)).toBeNull();
    expect(parseBrief("x")).toBeNull();
    expect(parseBrief({})).toBeNull();
    expect(parseBrief({ summary: "", can_do: [], cannot_do: [], angles: [] })).toBeNull();
  });

  it("parses fields and coerces bad list items", () => {
    expect(
      parseBrief({
        summary: "Hello",
        can_do: ["post", 2],
        cannot_do: "nope",
        angles: ["a"],
        persona: "founder",
      }),
    ).toEqual({
      summary: "Hello",
      can_do: ["post"],
      cannot_do: [],
      angles: ["a"],
      persona: "founder",
    });
  });

  it("accepts list-only briefs without summary", () => {
    expect(parseBrief({ can_do: ["x"] })).toEqual({
      summary: "",
      can_do: ["x"],
      cannot_do: [],
      angles: [],
      persona: null,
    });
  });
});

describe("parseDraftCopy", () => {
  it("returns null for empty / invalid payloads", () => {
    expect(parseDraftCopy(null)).toBeNull();
    expect(parseDraftCopy({})).toBeNull();
    expect(parseDraftCopy({ caption: "", hashtags: [], cta: "" })).toBeNull();
  });

  it("parses caption / hashtags / cta", () => {
    expect(parseDraftCopy({ caption: "hi", hashtags: ["#hk", 1], cta: "go" })).toEqual({
      caption: "hi",
      hashtags: ["#hk"],
      cta: "go",
    });
  });
});

describe("parseAgentProgress", () => {
  it("requires a non-empty node", () => {
    expect(parseAgentProgress({})).toBeNull();
    expect(parseAgentProgress({ node: "" })).toBeNull();
  });

  it("parses node with optional model fields", () => {
    expect(parseAgentProgress({ node: "brainstormer", model_tier: "fast", model: 1 })).toEqual({
      node: "brainstormer",
      model_tier: "fast",
      model: null,
    });
  });
});

describe("parseTurnDurationMs", () => {
  it("reads a non-negative integer from metadata", () => {
    expect(parseTurnDurationMs({ duration_ms: 41_250 })).toBe(41250);
    expect(parseTurnDurationMs({ duration_ms: 0 })).toBe(0);
  });

  it("rejects missing or invalid values", () => {
    expect(parseTurnDurationMs(undefined)).toBeNull();
    expect(parseTurnDurationMs({})).toBeNull();
    expect(parseTurnDurationMs({ duration_ms: -1 })).toBeNull();
    expect(parseTurnDurationMs({ duration_ms: "41" })).toBeNull();
  });
});

describe("OUTCOME_NODE", () => {
  it("maps outcome events to graph nodes", () => {
    expect(OUTCOME_NODE["brief.updated"]).toBe("brainstormer");
    expect(OUTCOME_NODE["preview.updated"]).toBe("executor_image_gen");
    expect(OUTCOME_NODE["draft.awaiting_image_ok"]).toBe("executor_post");
  });
});

describe("isUserFacingAgentNode", () => {
  it("hides internal graph nodes", () => {
    expect(isUserFacingAgentNode("fast_rule_checker")).toBe(false);
    expect(isUserFacingAgentNode("persist_preview")).toBe(false);
    expect(isUserFacingAgentNode("route_intent")).toBe(true);
  });
});

describe("agentNodeLabelKey", () => {
  it("nests running vs done under nodes", () => {
    expect(agentNodeLabelKey("route_intent", "running")).toBe(
      "chat.agent.nodes.running.route_intent",
    );
    expect(agentNodeLabelKey("query_generator", "done")).toBe(
      "chat.agent.nodes.done.query_generator",
    );
    expect(agentNodeFallbackKey("running")).toBe("chat.agent.nodes.running.working");
    expect(agentNodeFallbackKey("done")).toBe("chat.agent.nodes.done.working");
  });
});

describe("agentTrailHeader", () => {
  it("uses the static working line while in flight — no live seconds", () => {
    expect(agentTrailHeader(true, null)).toEqual({ kind: "working" });
    expect(agentTrailHeader(true, 12_000)).toEqual({ kind: "working" });
  });

  it("shows worked-for only after the turn ends and at least 1s elapsed", () => {
    expect(agentTrailHeader(false, null)).toBeNull();
    expect(agentTrailHeader(false, 999)).toBeNull();
    expect(agentTrailHeader(false, 1000)).toEqual({ kind: "workedFor", durationMs: 1000 });
    expect(agentTrailHeader(false, 41_250)).toEqual({ kind: "workedFor", durationMs: 41250 });
  });
});

describe("agent node locale copy", () => {
  it("keeps running/done keys aligned across locales", async () => {
    const en = (await import("@/i18n/locales/en.json")).default;
    const zh = (await import("@/i18n/locales/zh-HK.json")).default;
    expect(zh.chat.agent.working).toBe("幫緊你幫緊你");
    expect(en.chat.agent.working).toBe("Working");
    expect(Object.keys(en.chat.agent.nodes.running).sort()).toEqual(
      Object.keys(en.chat.agent.nodes.done).sort(),
    );
    expect(Object.keys(en.chat.agent.nodes.running).sort()).toEqual(
      Object.keys(zh.chat.agent.nodes.running).sort(),
    );
    expect(Object.keys(en.chat.agent.nodes.done).sort()).toEqual(
      Object.keys(zh.chat.agent.nodes.done).sort(),
    );
    for (const [node, label] of Object.entries(en.chat.agent.nodes.running)) {
      expect(label.endsWith("…"), node).toBe(true);
      expect(
        String(en.chat.agent.nodes.done[node as keyof typeof en.chat.agent.nodes.done]).endsWith(
          "…",
        ),
        node,
      ).toBe(false);
    }
  });
});

describe("MAX_QUEUED_SESSION_MESSAGES", () => {
  it("caps the in-flight send queue at 3", () => {
    expect(MAX_QUEUED_SESSION_MESSAGES).toBe(3);
  });
});

describe("newQueuedChatMessage", () => {
  it("trims content and uses a local-q id", () => {
    const item = newQueuedChatMessage("  hi  ");
    expect(item.content).toBe("hi");
    expect(item.id).toMatch(/^local-q-/);
  });
});

describe("newActionId", () => {
  it("embeds the node name", () => {
    expect(newActionId("brainstormer")).toMatch(/^action-\d+-brainstormer-[a-z0-9]+$/);
  });
});

describe("agentActionsFromMessages", () => {
  it("rebuilds done actions from user-message metadata", () => {
    const messages: ChatMessage[] = [
      {
        id: "a1",
        session_id: "s1",
        role: "assistant",
        content: "hi",
        created_at: "2026-01-01T00:00:00Z",
        metadata: { agent_actions: [{ node: "ignored" }] },
      },
      {
        id: "u1",
        session_id: "s1",
        role: "user",
        content: "go",
        created_at: "2026-01-01T00:00:01Z",
        metadata: {
          agent_actions: [
            { node: "brainstormer", model_tier: "fast", model: "gpt" },
            { node: "fast_rule_checker" },
            { node: "" },
            null,
            { node: "executor_post" },
          ],
        },
      },
    ];

    expect(agentActionsFromMessages(messages)).toEqual([
      {
        id: "persisted-u1-brainstormer-0",
        node: "brainstormer",
        model_tier: "fast",
        model: "gpt",
        status: "done",
        afterMessageId: "u1",
      },
      {
        id: "persisted-u1-executor_post-1",
        node: "executor_post",
        model_tier: null,
        model: null,
        status: "done",
        afterMessageId: "u1",
      },
    ]);
  });

  it("skips messages without agent_actions arrays", () => {
    expect(
      agentActionsFromMessages([
        {
          id: "u1",
          session_id: "s1",
          role: "user",
          content: "x",
          created_at: "2026-01-01T00:00:00Z",
        },
      ]),
    ).toEqual([]);
  });
});

describe("previewAnchorFromActions", () => {
  it("prefers the last executor_image_gen action's afterMessageId", () => {
    const actions: AgentActionRecord[] = [
      {
        id: "1",
        node: "brainstormer",
        model_tier: null,
        model: null,
        status: "done",
        afterMessageId: "u1",
      },
      {
        id: "2",
        node: "executor_image_gen",
        model_tier: null,
        model: null,
        status: "done",
        afterMessageId: "u1",
      },
      {
        id: "3",
        node: "brainstormer",
        model_tier: null,
        model: null,
        status: "running",
        afterMessageId: "u2",
      },
    ];
    const messages: ChatMessage[] = [
      {
        id: "u1",
        session_id: "s1",
        role: "user",
        content: "first",
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "u2",
        session_id: "s1",
        role: "user",
        content: "later",
        created_at: "2026-01-01T00:00:02Z",
      },
    ];
    expect(previewAnchorFromActions(actions, messages)).toBe("u1");
  });

  it("falls back to last user message when no image-gen action", () => {
    expect(
      previewAnchorFromActions(
        [],
        [
          {
            id: "u9",
            session_id: "s1",
            role: "user",
            content: "x",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      ),
    ).toBe("u9");
  });
});

describe("mergePreviewDraft", () => {
  const full: PreviewDraft = {
    copy: { caption: "c", hashtags: ["#a"], cta: "go" },
    image_url: "https://img",
    media: [],
    revision: 1,
    approval_token: "tok",
    platform: "instagram",
  };

  it("returns prev when incomplete and no prior draft", () => {
    expect(mergePreviewDraft(null, { copy: { caption: "x", hashtags: [], cta: "" } })).toBeNull();
  });

  it("patches copy onto an existing incomplete draft", () => {
    expect(
      mergePreviewDraft(full, {
        copy: { caption: "new", hashtags: [], cta: "" },
        image_url: null,
      }),
    ).toEqual({
      ...full,
      copy: { caption: "new", hashtags: [], cta: "" },
      image_url: null,
    });
  });

  it("builds a full draft when copy + token + revision are present", () => {
    expect(
      mergePreviewDraft(null, {
        copy: { caption: "hi", hashtags: [], cta: "" },
        approval_token: "t1",
        revision: 2,
        image_url: "https://x",
      }),
    ).toEqual({
      copy: { caption: "hi", hashtags: [], cta: "" },
      image_url: "https://x",
      media: [],
      revision: 2,
      approval_token: "t1",
      platform: "instagram",
    });
  });

  it("keeps prior image_url when patch omits it", () => {
    expect(
      mergePreviewDraft(full, {
        approval_token: "tok2",
        revision: 3,
      }),
    ).toMatchObject({
      approval_token: "tok2",
      revision: 3,
      image_url: "https://img",
      platform: "instagram",
    });
  });
});

describe("waitForSseReady", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves when the SSE ready handle resolves", async () => {
    let resolveReady!: () => void;
    const ref = {
      current: {
        promise: new Promise<void>((r) => {
          resolveReady = r;
        }),
        resolve: () => resolveReady(),
      },
    };

    const done = waitForSseReady(ref, 1000);
    resolveReady();
    await expect(done).resolves.toBeUndefined();
  });

  it("times out when no handle appears", async () => {
    const ref = { current: null };
    const done = waitForSseReady(ref, 80);
    await vi.advanceTimersByTimeAsync(120);
    await expect(done).resolves.toBeUndefined();
  });
});

describe("session history recency", () => {
  const row = (
    id: string,
    updated_at: string,
    pinned = false,
  ): SessionListItem => ({
    id,
    company_id: "co-1",
    user_id: "u-1",
    mode: "CHAT",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at,
    title: id,
    pinned,
  });

  it("sorts pinned first then newest updated_at", () => {
    const older = row("old", "2026-01-01T00:00:00Z");
    const newer = row("new", "2026-08-01T00:00:00Z");
    const pinned = row("pin", "2026-02-01T00:00:00Z", true);
    expect(sortSessionHistory([older, newer, pinned]).map((s) => s.id)).toEqual([
      "pin",
      "new",
      "old",
    ]);
  });

  it("bumps an existing row to the top of the unpinned group", () => {
    const older = row("old", "2026-01-01T00:00:00Z");
    const newer = row("new", "2026-08-01T00:00:00Z");
    const next = bumpSessionInHistory([newer, older], "old", "2026-08-23T12:00:00Z");
    expect(next.map((s) => s.id)).toEqual(["old", "new"]);
    expect(next[0]?.updated_at).toBe("2026-08-23T12:00:00Z");
  });

  it("leaves the list unchanged when the session is missing", () => {
    const rows = [row("a", "2026-08-01T00:00:00Z")];
    expect(bumpSessionInHistory(rows, "missing", "2026-08-23T12:00:00Z")).toBe(rows);
  });
});

describe("composer draft stash", () => {
  it("saves and restores a per-session snapshot", () => {
    const drafts = new Map<string, ComposerDraft>();
    const current: ComposerDraft = {
      queued: [{ id: "q1", content: "follow up" }],
      input: "half typed",
      editInsertAt: 0,
    };
    stashComposerDraft(drafts, "sess-a", current);
    expect(readComposerDraft(drafts, "sess-a")).toEqual(current);
    expect(readComposerDraft(drafts, "sess-b")).toEqual(EMPTY_COMPOSER_DRAFT);
    expect(readComposerDraft(drafts, null)).toEqual(EMPTY_COMPOSER_DRAFT);
  });

  it("copies so later mutations do not leak across sessions", () => {
    const drafts = new Map<string, ComposerDraft>();
    const queued = [{ id: "q1", content: "follow up" }];
    stashComposerDraft(drafts, "sess-a", {
      queued,
      input: "a",
      editInsertAt: null,
    });
    queued.push({ id: "q2", content: "other" });
    expect(readComposerDraft(drafts, "sess-a").queued).toEqual([
      { id: "q1", content: "follow up" },
    ]);
  });
});
