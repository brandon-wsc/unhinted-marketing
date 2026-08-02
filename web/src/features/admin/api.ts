import { fetchWithAuth } from "@/context/auth-context";
import { parseApiErrorResponse } from "@/lib/parse-api-error";

export type LlmCallRecordSummary = {
  id: string;
  created_at: string;
  caller: string;
  node: string | null;
  session_id: string | null;
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
};

export const LLM_CALL_PAGE_SIZE = 50;

export function buildLlmCallQuery(
  filters: LlmCallFilters,
  limit: number,
  offset: number,
): string {
  const params = new URLSearchParams();
  const node = filters.node?.trim();
  if (node) params.set("node", node);
  if (filters.status) params.set("status", filters.status);
  if (filters.fallbackOnly) params.set("fallback_used", "true");
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
  const res = await fetchWithAuth(accessToken, `/admin/llm-calls?${query}`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiAdminGetLlmCall(
  accessToken: string | null,
  id: string,
): Promise<LlmCallRecordDetail> {
  const res = await fetchWithAuth(accessToken, `/admin/llm-calls/${id}`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}
