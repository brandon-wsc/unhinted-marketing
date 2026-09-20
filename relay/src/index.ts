/**
 * Unhinted OAuth relay (ADR 0032 §3).
 *
 * Meta Strict Mode requires exact-match redirect URIs, so a vendor app cannot
 * serve arbitrary on-prem domains. This Worker is the single whitelisted
 * callback: Meta 302s here with code+state, we fan the browser out to the
 * customer instance registered in REGISTRY (instance_id -> base URL), exchange
 * the code server-side (the app secret never ships to installs), and hand the
 * long-lived token back via a one-time TICKETS entry the instance redeems
 * server-to-server at /api/social/oauth/relay-finish.
 *
 * Transit-only posture: tokens pass through but are never logged and never
 * persisted beyond the 60s ticket TTL. Do not console.log params.
 */

export interface Env {
  REGISTRY: KVNamespace;
  TICKETS: KVNamespace;
  META_APP_ID: string;
  META_APP_SECRET: string;
  META_GRAPH_API_VERSION: string;
}

const CALLBACK_PATH = "/meta/callback";
const FINISH_PATH = "/api/social/oauth/relay-finish";
const TICKET_TTL_SECONDS = 60;
const SHORT_LIVED_TOKEN_URL = "https://api.instagram.com/oauth/access_token";
const LONG_LIVED_TOKEN_URL = "https://graph.instagram.com/access_token";
const ME_FIELDS = "user_id,id,username,account_type";
const PROFESSIONAL_TYPES = new Set(["BUSINESS", "MEDIA_CREATOR", "CREATOR"]);

class RelayError extends Error {
  constructor(public code: string) {
    super(code);
  }
}

function redirect(location: string): Response {
  return new Response(null, { status: 302, headers: { Location: location } });
}

function text(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}

function asJson(raw: unknown): Record<string, unknown> {
  return raw !== null && typeof raw === "object" && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : {};
}

function graphErrorCode(payload: Record<string, unknown>, status: number): string {
  const err = payload.error;
  if (err !== null && typeof err === "object") {
    const code = (err as Record<string, unknown>).code;
    if (typeof code === "number") return `meta_oauth_graph_error:${code}`;
  }
  if (typeof payload.error_type === "string") return payload.error_type;
  return `meta_oauth_graph_error:${status}`;
}

function scopeList(raw: unknown): string[] {
  if (typeof raw === "string") {
    return raw.split(",").map((s) => s.trim()).filter(Boolean);
  }
  if (Array.isArray(raw)) return raw.map(String).map((s) => s.trim()).filter(Boolean);
  return [];
}

/** Mirror of internal/auth/meta_oauth.py::_parse_short_lived. */
function shortLived(payload: Record<string, unknown>): {
  accessToken: string;
  scopes: string[];
} {
  const data = payload.data;
  const node =
    Array.isArray(data) && data.length > 0 && typeof data[0] === "object"
      ? (data[0] as Record<string, unknown>)
      : payload;
  const accessToken = String(node.access_token ?? "");
  let scopes = scopeList(node.permissions ?? payload.permissions);
  const granted = payload.granted_scopes ?? node.granted_scopes;
  if (granted) scopes = scopeList(granted);
  return { accessToken, scopes };
}

type TicketPayload = {
  instance_id: string;
  ig_user_id: string;
  access_token: string;
  expires_at: string | null;
  missing_scopes: string[];
};

async function exchangeCode(
  env: Env,
  code: string,
  redirectUri: string,
  instanceId: string,
): Promise<TicketPayload> {
  const tokenResp = await fetch(SHORT_LIVED_TOKEN_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: env.META_APP_ID,
      client_secret: env.META_APP_SECRET,
      grant_type: "authorization_code",
      redirect_uri: redirectUri,
      code,
    }),
  });
  const tokenPayload = asJson(await tokenResp.json().catch(() => ({})));
  if (!tokenResp.ok) {
    throw new RelayError(graphErrorCode(tokenPayload, tokenResp.status));
  }
  const { accessToken: shortToken, scopes: grantedScopes } = shortLived(tokenPayload);
  if (!shortToken) throw new RelayError("meta_oauth_exchange_failed");

  const longUrl = new URL(LONG_LIVED_TOKEN_URL);
  longUrl.searchParams.set("grant_type", "ig_exchange_token");
  longUrl.searchParams.set("client_secret", env.META_APP_SECRET);
  longUrl.searchParams.set("access_token", shortToken);
  const longResp = await fetch(longUrl);
  const longPayload = asJson(await longResp.json().catch(() => ({})));
  if (!longResp.ok) {
    throw new RelayError(graphErrorCode(longPayload, longResp.status));
  }
  const accessToken = String(longPayload.access_token ?? "");
  if (!accessToken) throw new RelayError("meta_oauth_exchange_failed");
  const expiresIn = Number(longPayload.expires_in);
  const expiresAt = Number.isFinite(expiresIn)
    ? new Date(Date.now() + expiresIn * 1000).toISOString()
    : null;

  const meUrl = new URL(
    `https://graph.instagram.com/v${env.META_GRAPH_API_VERSION}/me`,
  );
  meUrl.searchParams.set("fields", ME_FIELDS);
  meUrl.searchParams.set("access_token", accessToken);
  const meResp = await fetch(meUrl);
  const mePayload = asJson(await meResp.json().catch(() => ({})));
  if (!meResp.ok) {
    throw new RelayError(graphErrorCode(mePayload, meResp.status));
  }
  const accountType = String(mePayload.account_type ?? "").toUpperCase();
  if (accountType && !PROFESSIONAL_TYPES.has(accountType)) {
    throw new RelayError("meta_oauth_not_professional");
  }
  const igUserId = String(mePayload.user_id ?? "").trim() || String(mePayload.id ?? "").trim();
  if (!igUserId) throw new RelayError("meta_oauth_not_professional");
  if (!grantedScopes.includes("instagram_business_content_publish")) {
    throw new RelayError("meta_oauth_missing_publish");
  }

  const missing = ["instagram_business_basic", "instagram_business_content_publish"].filter(
    (s) => grantedScopes.length > 0 && !grantedScopes.includes(s),
  );
  return {
    instance_id: instanceId,
    ig_user_id: igUserId,
    access_token: accessToken,
    expires_at: expiresAt,
    missing_scopes: missing,
  };
}

function finishUrl(base: string, state: string): URL {
  return new URL(FINISH_PATH, base.endsWith("/") ? base : `${base}/`);
}

async function onCallback(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const state = url.searchParams.get("state") ?? "";
  const instanceId = state.split(":", 1)[0] ?? "";
  const base = instanceId ? await env.REGISTRY.get(instanceId) : null;
  if (!base) {
    return text("unhinted relay: unknown instance", 400);
  }
  const finish = finishUrl(base, state);
  finish.searchParams.set("state", state);

  const metaError = url.searchParams.get("error");
  if (metaError) {
    finish.searchParams.set("error", "access_denied");
    return redirect(finish.toString());
  }
  const code = url.searchParams.get("code");
  if (!code) {
    finish.searchParams.set("error", "meta_oauth_missing_params");
    return redirect(finish.toString());
  }

  try {
    const payload = await exchangeCode(
      env,
      code,
      `${url.origin}${CALLBACK_PATH}`,
      instanceId,
    );
    const ticket = crypto.randomUUID();
    await env.TICKETS.put(ticket, JSON.stringify(payload), {
      expirationTtl: TICKET_TTL_SECONDS,
    });
    finish.searchParams.set("ticket", ticket);
  } catch (err) {
    finish.searchParams.set(
      "error",
      err instanceof RelayError ? err.code : "meta_oauth_exchange_failed",
    );
  }
  return redirect(finish.toString());
}

async function onTicket(request: Request, env: Env, id: string): Promise<Response> {
  const raw = await env.TICKETS.get(id);
  if (raw === null) return text("unhinted relay: unknown or expired ticket", 404);
  await env.TICKETS.delete(id);
  return new Response(raw, {
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/healthz") return text("ok");
    if (url.pathname === CALLBACK_PATH && request.method === "GET") {
      return onCallback(request, env);
    }
    const ticketMatch = /^\/ticket\/([0-9a-f-]{36})$/i.exec(url.pathname);
    if (ticketMatch && request.method === "GET") {
      return onTicket(request, env, ticketMatch[1]);
    }
    return text("unhinted relay: not found", 404);
  },
};
