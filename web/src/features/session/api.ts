import { fetchWithAuth } from "@/context/auth-context";
import { API_BASE } from "@/lib/api-base";
import { parseApiErrorResponse } from "@/lib/parse-api-error";
import type {
  ConfirmSessionResponse,
  DraftCopy,
  PostMessageResponse,
  PreviewMediaMutationResponse,
  RecommendedQuestionsResponse,
  Session,
  SessionListItem,
  SessionMessagesResponse,
  UpdateDraftResponse,
} from "./types";

export async function apiCreateSession(
  accessToken: string | null,
  companyId: string,
): Promise<Session> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company_id: companyId }),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiListSessions(
  accessToken: string | null,
  companyId: string,
  q?: string,
): Promise<SessionListItem[]> {
  const qs = new URLSearchParams({ company_id: companyId, limit: "40" });
  const query = q?.trim();
  if (query) qs.set("q", query);
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions?${qs}`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  const body = (await res.json()) as { sessions: SessionListItem[] };
  return body.sessions ?? [];
}

export async function apiUpdateSession(
  accessToken: string | null,
  sessionId: string,
  body: { title?: string; pinned?: boolean; clear_title?: boolean },
): Promise<SessionListItem> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiDeleteSession(
  accessToken: string | null,
  sessionId: string,
): Promise<void> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
}

export async function apiGetSessionMessages(
  accessToken: string | null,
  sessionId: string,
): Promise<SessionMessagesResponse> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions/${sessionId}/messages`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiPostSessionMessage(
  accessToken: string | null,
  sessionId: string,
  content: string,
  init?: { signal?: AbortSignal },
): Promise<PostMessageResponse> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
    signal: init?.signal,
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiResumeSessionImage(
  accessToken: string | null,
  sessionId: string,
  init?: { signal?: AbortSignal; imageFormat?: "single" | "comic_4panel" },
): Promise<PostMessageResponse> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions/${sessionId}/resume-image`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      image_format: init?.imageFormat ?? null,
    }),
    signal: init?.signal,
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiStopSessionTurn(
  accessToken: string | null,
  sessionId: string,
): Promise<{
  status: string;
  interrupted?: boolean;
  awaiting_image_ok?: boolean;
}> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions/${sessionId}/stop`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiUpdateSessionDraft(
  accessToken: string | null,
  sessionId: string,
  copy: DraftCopy,
): Promise<UpdateDraftResponse> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions/${sessionId}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      caption: copy.caption,
      hashtags: copy.hashtags,
      cta: copy.cta,
    }),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiUpdateImagePlan(
  accessToken: string | null,
  sessionId: string,
  imageId: string,
  plan: Record<string, unknown>,
): Promise<PreviewMediaMutationResponse> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/sessions/${sessionId}/media/${imageId}/plan`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan }),
    },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiRegenImage(
  accessToken: string | null,
  sessionId: string,
  imageId: string,
): Promise<PreviewMediaMutationResponse> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/sessions/${sessionId}/media/${imageId}/regen`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiAddSessionImage(
  accessToken: string | null,
  sessionId: string,
  body?: { format?: "single" | "comic_4panel"; plan?: Record<string, unknown> },
): Promise<PreviewMediaMutationResponse> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions/${sessionId}/media`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      format: body?.format ?? "single",
      plan: body?.plan ?? null,
    }),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiRemoveImage(
  accessToken: string | null,
  sessionId: string,
  imageId: string,
): Promise<PreviewMediaMutationResponse> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/sessions/${sessionId}/media/${imageId}/remove`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiUploadImage(
  accessToken: string | null,
  sessionId: string,
  imageId: string,
  file: File,
): Promise<PreviewMediaMutationResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/sessions/${sessionId}/media/${imageId}/upload`,
    { method: "POST", body: form },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiConfirmSession(
  accessToken: string | null,
  sessionId: string,
  body: { approval_token: string; idempotency_key: string; platform?: string },
): Promise<ConfirmSessionResponse> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/sessions/${sessionId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      approval_token: body.approval_token,
      idempotency_key: body.idempotency_key,
      platform: body.platform ?? "instagram",
    }),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiGetRecommendedQuestions(
  accessToken: string | null,
  companyId: string,
): Promise<RecommendedQuestionsResponse | null> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/recommended-questions`,
  );
  // 404 = worker has not generated a batch yet — empty landing, not an error toast.
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}
