import { fetchWithAuth } from "@/context/auth-context";
import { parseApiErrorResponse } from "@/lib/parse-api-error";
import type { PostMessageResponse, RecommendedQuestionsResponse, Session } from "./types";

export async function apiCreateSession(
  accessToken: string | null,
  companyId: string,
): Promise<Session> {
  const res = await fetchWithAuth(accessToken, "/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company_id: companyId }),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiPostSessionMessage(
  accessToken: string | null,
  sessionId: string,
  content: string,
): Promise<PostMessageResponse> {
  const res = await fetchWithAuth(accessToken, `/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
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
    `/companies/${companyId}/recommended-questions`,
  );
  // 404 = worker has not generated a batch yet — empty landing, not an error toast.
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}
