// Public type surface for the session feature.
// Backend-owned shapes are re-exported from ./generated (AUTO-GENERATED from schemas/).
// Hand-written types here are FE-local contracts not (yet) covered by backend contracts.

// --- Backend-owned, generated from OpenAPI (schemas/ → docs/openapi.json) ---
import type { components } from "./generated/api";
export type Session = components["schemas"]["SessionResponse"];
export type SessionListItem = components["schemas"]["SessionListItem"];
export type SessionMessagesResponse = components["schemas"]["SessionMessagesResponse"];
// POST /messages re-sends the turn events at the end; those are the same
// SessionEvent shape as SSE (backend serializes them as loose dicts).
export type PostMessageResponse = Omit<components["schemas"]["PostMessageResponse"], "events"> & {
  events: SessionEvent[];
};
export type UpdateDraftResponse = components["schemas"]["UpdateDraftResponse"];
export type PreviewMediaMutationResponse = components["schemas"]["PreviewMediaMutationResponse"];
export type ConfirmSessionResponse = components["schemas"]["ConfirmSessionResponse"];
export type RecommendedQuestion = components["schemas"]["RecommendedQuestionItem"];
export type RecommendedQuestionsResponse = components["schemas"]["RecommendedQuestionsResponse"];
// DraftCopy/PreviewMediaItem have backend defaults; FE treats them as always-present.
// Keep the generated base plus these non-null guarantees so consumers don't re-narrow.
export type DraftCopy = components["schemas"]["DraftCopy"];
export type PreviewMediaItem = components["schemas"]["PreviewMediaItem"];

// --- Generated from JSON Schema mirrors (schemas/ → docs/contracts) ---
export type AgentProgress = import("./generated/agent-progress").AgentProgressData;
export type PreviewDraft = import("./generated/preview-updated").PreviewUpdatedData;

// --- FE-local / not-yet-contracted ---
export type SessionMode = "CHAT" | "AGENT" | "PREVIEW";
export type ChatMessage = {
  id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string;
  metadata?: Record<string, unknown>;
};
export type SessionEventData = Record<string, unknown>;
export type SessionEvent = {
  type: string;
  data: SessionEventData;
};
export type AgentActionRecord = {
  id: string;
  node: string;
  model_tier: string | null;
  model: string | null;
  status: "running" | "done";
  afterMessageId: string | null;
};
export type SessionBrief = {
  can_do: string[];
  cannot_do: string[];
  angles: string[];
  persona: string | null;
  summary: string;
};
export type SessionSnapshot = {
  session_id: string;
  mode: SessionMode | string;
  status: string;
  state: Record<string, unknown>;
  revision: number | null;
  approval_token: string | null;
  image_url: string | null;
  media?: PreviewMediaItem[];
  copy?: DraftCopy | Record<string, unknown> | null;
  platform?: string | null;
};
