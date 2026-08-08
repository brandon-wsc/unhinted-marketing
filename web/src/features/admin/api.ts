import { fetchWithAuth } from "@/context/auth-context";
import { API_BASE } from "@/lib/api-base";
import { parseApiErrorResponse } from "@/lib/parse-api-error";

export type LlmCallRecordSummary = {
  id: string;
  created_at: string;
  caller: string;
  node: string | null;
  session_id: string | null;
  turn_id: string | null;
  kind: string;
  tier: string | null;
  model: string | null;
  status: string;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  parse_ok: boolean | null;
  fallback_used: boolean;
};

export type LlmCallRecordDetail = LlmCallRecordSummary & {
  user_id: string | null;
  company_id: string | null;
  temperature: number | null;
  system_prompt: string | null;
  user_prompt: string | null;
  response_text: string | null;
  error: Record<string, unknown> | null;
};

export type LlmCallRecordList = {
  items: LlmCallRecordSummary[];
  limit: number;
  offset: number;
};

export type LlmCallFilters = {
  node?: string;
  status?: string;
  fallbackOnly?: boolean;
  turnId?: string;
  sessionId?: string;
};

export type NodeStepSummary = {
  id: string;
  created_at: string;
  session_id: string | null;
  turn_id: string;
  seq: number;
  node: string;
  mode_in: string | null;
  mode_out: string | null;
  intent_out: string | null;
  source_signal_ids_in: unknown[];
  source_signal_ids_out: unknown[];
  output_keys: unknown[];
};

export type NodeStepDetail = NodeStepSummary & {
  user_id: string | null;
  company_id: string | null;
  output: Record<string, unknown>;
  llm_calls: LlmCallRecordSummary[];
};

export type NodeStepList = {
  items: NodeStepSummary[];
  limit: number;
  offset: number;
};

export type NodeStepFilters = {
  node?: string;
  sessionId?: string;
  turnId?: string;
};

export type SessionTrace = {
  id: string;
  mode: string;
  status: string;
  company_id: string;
  user_id: string;
  title: string | null;
  created_at: string;
  updated_at: string | null;
  messages: Array<{
    id: string;
    role: string;
    content: string;
    metadata: Record<string, unknown> | null;
    created_at: string;
  }>;
  draft_revisions: Array<{
    id: string;
    revision: number;
    draft_copy: Record<string, unknown>;
    image_url: string | null;
    image_plan: Record<string, unknown> | null;
    source_signal_ids: unknown[];
    approval_token: string | null;
    platform: string | null;
    created_at: string;
  }>;
  signals: Array<{
    signal_id: string;
    source: string;
    title: string;
    url: string | null;
    excerpt: string | null;
  }>;
  turns: Array<{
    turn_id: string;
    steps: NodeStepSummary[];
    llm_calls: LlmCallRecordSummary[];
  }>;
};

export type ResearchSignalHit = {
  signal_id: string;
  source: string;
  title: string;
  url: string | null;
  excerpt: string | null;
  query: string | null;
};

export type ResearchTurn = {
  turn_id: string;
  created_at: string | null;
  research_rule_pass: boolean | null;
  semantic_route: string | null;
  need_facts: boolean | null;
  ambiguous: boolean | null;
  ask_clarify: boolean | null;
  entity_surface: string | null;
  search_query: string | null;
  search_queries: string[];
  signals: ResearchSignalHit[];
  source_signal_ids: string[];
  ran_research_ingest: boolean;
};

export type SessionResearch = {
  session_id: string;
  turns: ResearchTurn[];
};

export const LLM_CALL_PAGE_SIZE = 50;
export const NODE_STEP_PAGE_SIZE = 50;

export function buildLlmCallQuery(filters: LlmCallFilters, limit: number, offset: number): string {
  const params = new URLSearchParams();
  const node = filters.node?.trim();
  if (node) params.set("node", node);
  if (filters.status) params.set("status", filters.status);
  if (filters.fallbackOnly) params.set("fallback_used", "true");
  if (filters.turnId?.trim()) params.set("turn_id", filters.turnId.trim());
  if (filters.sessionId?.trim()) params.set("session_id", filters.sessionId.trim());
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return params.toString();
}

export function buildNodeStepQuery(
  filters: NodeStepFilters,
  limit: number,
  offset: number,
): string {
  const params = new URLSearchParams();
  const node = filters.node?.trim();
  if (node) params.set("node", node);
  if (filters.sessionId?.trim()) params.set("session_id", filters.sessionId.trim());
  if (filters.turnId?.trim()) params.set("turn_id", filters.turnId.trim());
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return params.toString();
}

export async function apiAdminListLlmCalls(
  accessToken: string | null,
  filters: LlmCallFilters,
  offset = 0,
): Promise<LlmCallRecordList> {
  const query = buildLlmCallQuery(filters, LLM_CALL_PAGE_SIZE, offset);
  const res = await fetchWithAuth(accessToken, `${API_BASE}/admin/llm-calls?${query}`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiAdminGetLlmCall(
  accessToken: string | null,
  id: string,
): Promise<LlmCallRecordDetail> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/admin/llm-calls/${id}`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiAdminListNodeSteps(
  accessToken: string | null,
  filters: NodeStepFilters,
  offset = 0,
): Promise<NodeStepList> {
  const query = buildNodeStepQuery(filters, NODE_STEP_PAGE_SIZE, offset);
  const res = await fetchWithAuth(accessToken, `${API_BASE}/admin/node-steps?${query}`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiAdminGetNodeStep(
  accessToken: string | null,
  id: string,
): Promise<NodeStepDetail> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/admin/node-steps/${id}`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiAdminGetSessionTrace(
  accessToken: string | null,
  sessionId: string,
): Promise<SessionTrace> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/admin/sessions/${sessionId}/trace`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiAdminGetSessionResearch(
  accessToken: string | null,
  sessionId: string,
): Promise<SessionResearch> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/admin/sessions/${sessionId}/research`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}
