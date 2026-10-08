import { fetchWithAuth } from "@/context/auth-context";
import { parseApiErrorResponse } from "@/lib/parse-api-error";

/** RequestInit plus a `json` shortcut that sets Content-Type and stringifies. */
export type ApiRequestInit = RequestInit & {
  json?: unknown;
};

/** Maps a failed Response to the Error a call site wants thrown. */
export type ApiErrorMapper = (res: Response) => Promise<Error>;

export const defaultApiErrorMapper: ApiErrorMapper = async (res) =>
  new Error(await parseApiErrorResponse(res));

function toRequestInit(init?: ApiRequestInit): RequestInit | undefined {
  if (init?.json === undefined) return init;
  const { json, ...rest } = init;
  return {
    ...rest,
    headers: { "Content-Type": "application/json", ...rest.headers },
    body: JSON.stringify(json),
  };
}

/**
 * Standard transport envelope for API stubs: fetchWithAuth → throw the mapped
 * error on !ok → return the Response for the caller to handle (usually .json(),
 * or ignored for void endpoints). Endpoints whose status codes carry semantics
 * (404 → null, 202 → generating) stay hand-rolled on fetchWithAuth.
 */
export async function apiFetch(
  accessToken: string | null,
  input: RequestInfo,
  init?: ApiRequestInit,
  mapError: ApiErrorMapper = defaultApiErrorMapper,
): Promise<Response> {
  const res = await fetchWithAuth(accessToken, input, toRequestInit(init));
  if (!res.ok) throw await mapError(res);
  return res;
}

/** Same envelope, plus JSON parsing for endpoints that return a body. */
export async function apiJson<T>(
  accessToken: string | null,
  input: RequestInfo,
  init?: ApiRequestInit,
  mapError?: ApiErrorMapper,
): Promise<T> {
  const res = await apiFetch(accessToken, input, init, mapError);
  return res.json();
}
