export type SessionMode = "CHAT" | "AGENT" | "PREVIEW";

export type Session = {
  id: string;
  company_id: string;
  user_id: string;
  mode: SessionMode | string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string;
  /** Server-persisted extras (e.g. agent_actions on user turns). */
  metadata?: Record<string, unknown>;
};

export type SessionEventData = Record<string, unknown>;

export type SessionEvent = {
  type: string;
  data: SessionEventData;
};

export type AgentProgress = {
  node: string;
  model_tier: string | null;
  model: string | null;
};

/** Persisted-in-UI trail of graph nodes for the current session (Cursor-style). */
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

export type DraftCopy = {
  caption: string;
  hashtags: string[];
  cta: string;
};

export type PreviewDraft = {
  copy: DraftCopy;
  image_url: string | null;
  revision: number;
  approval_token: string;
  platform: string;
};

export type RecommendedQuestion = {
  id: string;
  text: string;
  rationale: string | null;
  source_signal_ids: string[];
  persona_slug: string | null;
};

export type RecommendedQuestionsResponse = {
  company_id: string;
  questions: RecommendedQuestion[];
  source_signal_ids: string[];
  generated_at: string;
  expires_at: string;
  is_stale: boolean;
};

export type SessionListItem = Session & {
  title: string | null;
  pinned?: boolean;
};

export type SessionMessagesResponse = {
  session: Session;
  messages: ChatMessage[];
};

export type PostMessageResponse = {
  session: Session;
  messages: ChatMessage[];
  interrupted: boolean;
  mode: SessionMode | string;
  revision: number | null;
  pending_confirm: boolean;
  approval_token: string | null;
  events: SessionEvent[];
};

export type UpdateDraftResponse = {
  revision: number;
  approval_token: string;
  copy: DraftCopy;
  image_url: string | null;
  platform: string;
  mode: string;
};

export type ConfirmSessionResponse = {
  receipt_id: string;
  status: string;
  tool_name: string;
  idempotency_key: string;
};

export type SessionSnapshot = {
  session_id: string;
  mode: SessionMode | string;
  status: string;
  state: Record<string, unknown>;
  revision: number | null;
  approval_token: string | null;
  image_url: string | null;
  copy?: DraftCopy | Record<string, unknown> | null;
  platform?: string | null;
};
