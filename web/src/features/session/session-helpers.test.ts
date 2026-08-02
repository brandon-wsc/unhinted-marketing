import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  agentActionsFromMessages,
  asStringList,
  mergePreviewDraft,
  newActionId,
  OUTCOME_NODE,
  parseAgentProgress,
  parseBrief,
  parseDraftCopy,
  waitForSseReady,
} from "@/features/session/session-helpers";
import type { ChatMessage, PreviewDraft } from "@/features/session/types";

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
    expect(
      parseDraftCopy({ caption: "hi", hashtags: ["#hk", 1], cta: "go" }),
    ).toEqual({ caption: "hi", hashtags: ["#hk"], cta: "go" });
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

describe("OUTCOME_NODE", () => {
  it("maps outcome events to graph nodes", () => {
    expect(OUTCOME_NODE["brief.updated"]).toBe("brainstormer");
    expect(OUTCOME_NODE["preview.updated"]).toBe("executor_image_gen");
    expect(OUTCOME_NODE["draft.awaiting_image_ok"]).toBe("executor_post");
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

describe("mergePreviewDraft", () => {
  const full: PreviewDraft = {
    copy: { caption: "c", hashtags: ["#a"], cta: "go" },
    image_url: "https://img",
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
