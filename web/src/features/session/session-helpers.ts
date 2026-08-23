import type {
  AgentActionRecord,
  AgentProgress,
  ChatMessage,
  DraftCopy,
  PreviewDraft,
  PreviewMediaItem,
  QueuedChatMessage,
  SessionBrief,
} from "./types";

export function asStringList(value: unknown): string[] {
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

export function parseDraftCopy(data: unknown): DraftCopy | null {
  if (!data || typeof data !== "object") return null;
  const raw = data as Record<string, unknown>;
  const caption = typeof raw.caption === "string" ? raw.caption : "";
  const hashtags = asStringList(raw.hashtags);
  const cta = typeof raw.cta === "string" ? raw.cta : "";
  if (!caption && !hashtags.length && !cta) return null;
  return { caption, hashtags, cta };
}

export function parseAgentProgress(data: Record<string, unknown>): AgentProgress | null {
  if (typeof data.node !== "string" || !data.node) return null;
  return {
    node: data.node,
    model_tier: typeof data.model_tier === "string" ? data.model_tier : null,
    model: typeof data.model === "string" ? data.model : null,
  };
}

/** Internal graph nodes — keep out of the chat action trail. */
const INTERNAL_AGENT_NODES = new Set(["fast_rule_checker", "persist_preview"]);

export function isUserFacingAgentNode(node: string): boolean {
  return !INTERNAL_AGENT_NODES.has(node);
}

/** SPA-only follow-up Sends while a turn is in flight (ADR 0016). */
export const MAX_QUEUED_SESSION_MESSAGES = 3;

/** Queue card tucked under the composer top edge. */
export const QUEUE_TUCK_PX = 12;

export function newQueuedChatMessage(content: string): QueuedChatMessage {
  return {
    id: `local-q-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    content: content.trim(),
  };
}

/** Outcome events → node names, used when SSE missed live agent.progress. */
export const OUTCOME_NODE: Record<string, string> = {
  "brief.updated": "brainstormer",
  "draft.copy_updated": "executor_post",
  "draft.image_plan_updated": "executor_image_plan",
  "draft.updated": "executor_image_gen",
  "preview.updated": "executor_image_gen",
  "draft.awaiting_image_ok": "executor_post",
};

export function newActionId(node: string): string {
  return `action-${Date.now()}-${node}-${Math.random().toString(36).slice(2, 7)}`;
}

/** Rebuild Cursor-style action trail from persisted user-message metadata. */
export function agentActionsFromMessages(messages: ChatMessage[]): AgentActionRecord[] {
  const out: AgentActionRecord[] = [];
  for (const m of messages) {
    if (m.role !== "user") continue;
    const raw = m.metadata?.agent_actions;
    if (!Array.isArray(raw)) continue;
    for (const item of raw) {
      if (!item || typeof item !== "object") continue;
      const progress = parseAgentProgress(item as Record<string, unknown>);
      if (!progress || !isUserFacingAgentNode(progress.node)) continue;
      out.push({
        id: `persisted-${m.id}-${progress.node}-${out.length}`,
        node: progress.node,
        model_tier: progress.model_tier,
        model: progress.model,
        status: "done",
        afterMessageId: m.id,
      });
    }
  }
  return out;
}

/** User message id that owns the preview turn (`executor_image_gen`), else last user. */
export function previewAnchorFromActions(
  actions: AgentActionRecord[],
  messages: ChatMessage[],
): string | null {
  for (let i = actions.length - 1; i >= 0; i -= 1) {
    const a = actions[i];
    if (a?.node === "executor_image_gen" && a.afterMessageId) {
      return a.afterMessageId;
    }
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === "user") return messages[i]!.id;
  }
  return null;
}

export function mergePreviewDraft(
  prev: PreviewDraft | null,
  patch: {
    copy?: DraftCopy | null;
    image_url?: string | null;
    media?: PreviewMediaItem[] | null;
    revision?: number | null;
    approval_token?: string | null;
    platform?: string | null;
  },
): PreviewDraft | null {
  const copy = patch.copy ?? prev?.copy ?? null;
  const approval_token =
    typeof patch.approval_token === "string"
      ? patch.approval_token
      : (prev?.approval_token ?? null);
  const revision = typeof patch.revision === "number" ? patch.revision : (prev?.revision ?? null);
  const media =
    patch.media !== undefined && patch.media !== null ? patch.media : (prev?.media ?? []);
  if (!copy || !approval_token || revision == null) {
    if (copy && prev) {
      return {
        ...prev,
        copy,
        image_url: patch.image_url !== undefined ? patch.image_url : prev.image_url,
        media,
        platform: patch.platform || prev.platform,
      };
    }
    return prev;
  }
  return {
    copy,
    image_url: patch.image_url !== undefined ? patch.image_url : (prev?.image_url ?? null),
    media,
    revision,
    approval_token,
    platform: patch.platform || prev?.platform || "instagram",
  };
}

export function parseMediaItems(raw: unknown): PreviewMediaItem[] | null {
  if (!Array.isArray(raw)) return null;
  const out: PreviewMediaItem[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const rec = item as Record<string, unknown>;
    if (typeof rec.id !== "string") continue;
    out.push({
      id: rec.id,
      url: typeof rec.url === "string" ? rec.url : null,
      plan:
        rec.plan && typeof rec.plan === "object" && !Array.isArray(rec.plan)
          ? (rec.plan as Record<string, unknown>)
          : {},
      format: typeof rec.format === "string" ? rec.format : "single",
      role: typeof rec.role === "string" ? rec.role : "primary",
      seq: typeof rec.seq === "number" ? rec.seq : out.length,
      status: typeof rec.status === "string" ? rec.status : "ready",
    });
  }
  return out;
}

type SseReadyHandle = { promise: Promise<void>; resolve: () => void };

// The event bus does not replay: deltas published before the SSE subscriber
// attaches are lost. After creating a session, wait for the stream to open
// before posting so the first turn also streams from the start. On timeout we
// post anyway — the REST response still delivers the complete reply at the end.
export async function waitForSseReady(
  ref: { current: SseReadyHandle | null },
  timeoutMs = 1500,
): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const handle = ref.current;
    if (handle) {
      const remaining = Math.max(0, timeoutMs - (Date.now() - start));
      await Promise.race([handle.promise, new Promise<void>((r) => setTimeout(r, remaining))]);
      return;
    }
    await new Promise<void>((r) => setTimeout(r, 25));
  }
}
