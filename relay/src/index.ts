/**
 * Unhinted OAuth relay (ADR 0032 §3, hardened by ADR 0034).
 *
 * Meta Strict Mode requires exact-match redirect URIs, so a vendor app cannot
 * serve arbitrary on-prem domains. This Worker is the single whitelisted
 * callback: Meta 302s here with code+state, we fan the browser out to the
 * customer instance registered in REGISTRY (instance_id -> {url, secret}),
 * exchange the code server-side (the app secret never ships to installs), and
 * hand the long-lived token back via a one-time TICKETS entry the instance
 * redeems server-to-server at /api/social/oauth/relay-finish — the redeem
 * must prove the per-install shared secret (ADR 0034), so a leaked redirect
 * URL alone cannot redeem.
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
const AUTHORIZE_PATH = "/authorize";
const FINISH_PATH = "/api/social/oauth/relay-finish";
// ADR 0033 — Meta Live mode also requires deauthorize + data-deletion URLs on
// the vendor app; the relay verifies signed_request and forwards to the
// owning install (it holds no app secret and cannot verify Meta itself).
const DEAUTHORIZE_PATH = "/meta/deauthorize";
const DATA_DELETION_PATH = "/meta/data-deletion";
const DATA_DELETION_STATUS_PATH = "/meta/data-deletion-status";
const INSTANCE_RELAY_PATH = "/api/social/meta/relay";
const TICKET_TTL_SECONDS = 60;
// ig_user_id -> instance_id routing so Meta platform callbacks reach the
// right install. Covers the 60-day long-lived token with headroom.
const USER_MAP_TTL_SECONDS = 90 * 24 * 60 * 60;
const DIALOG_URL = "https://www.instagram.com/oauth/authorize";
const META_OAUTH_SCOPES =
  "instagram_business_basic,instagram_business_content_publish";
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
    const e = err as Record<string, unknown>;
    const code = e.code;
    // Error metadata only — no params, no tokens (transit-only posture).
    console.warn(
      "meta graph error",
      JSON.stringify({
        code,
        subcode: e.error_subcode,
        type: e.type,
        fbtrace: e.fbtrace_id,
      }),
    );
    if (typeof code === "number") return `meta_oauth_graph_error:${code}`;
  }
  if (typeof payload.error_type === "string") return payload.error_type;
  return `meta_oauth_graph_error:${status}`;
}

/** Mirror of meta_oauth.py::_graph_version — META_GRAPH_API_VERSION already
 * carries the "v" prefix, so normalize before embedding it in a path. */
function graphVersion(env: Env): string {
  return (env.META_GRAPH_API_VERSION || "v22.0").trim().replace(/^[/v]+/, "");
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
    `https://graph.instagram.com/v${graphVersion(env)}/me`,
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

/** ADR 0034 — REGISTRY values are `{"url","secret"}` JSON. Bare-string legacy
 * entries fail closed (re-register). `url` must be https; http is tolerated
 * only for loopback dev hosts. */
type RegistryEntry = { url: string; secret: string };

function parseRegistryEntry(raw: string | null): RegistryEntry | null {
  if (!raw) return null;
  let parsed: Record<string, unknown>;
  try {
    parsed = asJson(JSON.parse(raw));
  } catch {
    return null;
  }
  const url = String(parsed.url ?? "");
  const secret = String(parsed.secret ?? "");
  if (!url || !secret) return null;
  let base: URL;
  try {
    base = new URL(url);
  } catch {
    return null;
  }
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(base.hostname);
  if (base.protocol !== "https:" && !(base.protocol === "http:" && loopback)) {
    return null;
  }
  return { url, secret };
}

async function registryEntry(env: Env, instanceId: string): Promise<RegistryEntry | null> {
  if (!instanceId) return null;
  return parseRegistryEntry(await env.REGISTRY.get(instanceId));
}

function hexToBytes(hex: string): Uint8Array | null {
  if (!/^[0-9a-f]+$/i.test(hex) || hex.length % 2 !== 0) return null;
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

function b64urlToBytes(s: string): Uint8Array {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function toHex(buf: ArrayBuffer): string {
  return [...new Uint8Array(buf)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function hmacSha256(secret: string, msg: string): Promise<ArrayBuffer> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
}

/** Verify Meta's `signed_request` (`<b64url sig>.<b64url json>`, HMAC-SHA256
 * over the encoded payload keyed by the app secret). */
async function parseSignedRequest(
  raw: string,
  secret: string,
): Promise<Record<string, unknown> | null> {
  if (!raw || !secret) return null;
  const dot = raw.indexOf(".");
  if (dot <= 0 || dot === raw.length - 1) return null;
  const sigB64 = raw.slice(0, dot);
  const payloadB64 = raw.slice(dot + 1);
  let payload: Record<string, unknown>;
  try {
    payload = asJson(JSON.parse(new TextDecoder().decode(b64urlToBytes(payloadB64))));
  } catch {
    return null;
  }
  if (String(payload.algorithm ?? "").toUpperCase() !== "HMAC-SHA256") return null;
  const expected = new Uint8Array(await hmacSha256(secret, payloadB64));
  let actual: Uint8Array;
  try {
    actual = b64urlToBytes(sigB64);
  } catch {
    return null;
  }
  return bytesEqual(actual, expected) ? payload : null;
}

/** Forward a verified Meta platform event to the install that owns the IG
 * user (ADR 0033 §3, key updated by ADR 0034). sig re-signs the event with
 * the install's shared secret so the instance can tell it came from the
 * relay — the public routing slug alone proves nothing. */
async function forwardToInstance(
  env: Env,
  kind: "deauthorize" | "data_deletion",
  igUserId: string,
): Promise<Response | null> {
  const instanceId = await env.TICKETS.get(`u:${igUserId}`);
  if (!instanceId) return null;
  const entry = await registryEntry(env, instanceId);
  if (!entry) return null;
  const sig = toHex(await hmacSha256(entry.secret, `${kind}:${igUserId}`));
  return fetch(`${entry.url.replace(/\/+$/, "")}${INSTANCE_RELAY_PATH}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ kind, ig_user_id: igUserId, sig }),
  });
}

/**
 * The instance's OAuth start points the browser here instead of at Instagram
 * directly — this Worker injects the vendor client_id and its own fixed
 * redirect_uri, so installs never need to know the vendor app. The state
 * prefix is validated against REGISTRY so this isn't an open bounce.
 */
async function onAuthorize(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const state = url.searchParams.get("state") ?? "";
  const instanceId = state.split(":", 1)[0] ?? "";
  const entry = await registryEntry(env, instanceId);
  if (!entry) {
    return text("unhinted relay: unknown instance", 400);
  }
  const dialog = new URL(DIALOG_URL);
  dialog.searchParams.set("client_id", env.META_APP_ID);
  dialog.searchParams.set("redirect_uri", `${url.origin}${CALLBACK_PATH}`);
  dialog.searchParams.set("scope", META_OAUTH_SCOPES);
  dialog.searchParams.set("state", state);
  dialog.searchParams.set("response_type", "code");
  return redirect(dialog.toString());
}

async function onCallback(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const state = url.searchParams.get("state") ?? "";
  const instanceId = state.split(":", 1)[0] ?? "";
  const entry = await registryEntry(env, instanceId);
  if (!entry) {
    return text("unhinted relay: unknown instance", 400);
  }
  const finish = finishUrl(entry.url, state);
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
    // ig_user_id -> instance_id so Meta platform callbacks (deauthorize /
    // data-deletion) can be routed to the owning install later.
    await env.TICKETS.put(`u:${payload.ig_user_id}`, instanceId, {
      expirationTtl: USER_MAP_TTL_SECONDS,
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

/** Meta calls this on the vendor app when a user removes it (ADR 0033).
 * Verified here, then forwarded to the owning install so it can drop the
 * stored connection. Meta only needs a 200 back. */
async function onMetaDeauthorize(request: Request, env: Env): Promise<Response> {
  const form = await request.formData().catch(() => null);
  if (!form) return text("invalid signed_request", 400);
  const payload = await parseSignedRequest(
    String(form.get("signed_request") ?? ""),
    env.META_APP_SECRET,
  );
  if (!payload) return text("invalid signed_request", 400);
  const igUserId = String(payload.user_id ?? "").trim();
  if (igUserId) {
    try {
      await forwardToInstance(env, "deauthorize", igUserId);
    } catch {
      // Best effort — Meta only needs a 200; a dead install keeps a dead token.
    }
    await env.TICKETS.delete(`u:${igUserId}`);
  }
  return text("ok");
}

/** Meta data-deletion request on the vendor app (ADR 0033). The instance
 * owns the data, so we proxy its {url, confirmation_code} back to Meta; when
 * no routing record exists (connect predates the map) the relay answers
 * itself — it retains nothing to delete. */
async function onMetaDataDeletion(request: Request, env: Env): Promise<Response> {
  const form = await request.formData().catch(() => null);
  if (!form) return text("invalid signed_request", 400);
  const payload = await parseSignedRequest(
    String(form.get("signed_request") ?? ""),
    env.META_APP_SECRET,
  );
  if (!payload) return text("invalid signed_request", 400);
  const igUserId = String(payload.user_id ?? "").trim();
  // ADR 0034 §5 — the static "completed" answer is only honest when no
  // routing entry exists (the relay retains nothing). When the install owns
  // data but cannot be reached, answer 503 so Meta retries.
  if (igUserId && (await env.TICKETS.get(`u:${igUserId}`))) {
    try {
      const resp = await forwardToInstance(env, "data_deletion", igUserId);
      if (resp && resp.ok) {
        return new Response(await resp.text(), {
          headers: { "content-type": "application/json" },
        });
      }
    } catch {
      // Fall through to the 503.
    }
    return text("unhinted relay: instance unreachable", 503);
  }
  const code = crypto.randomUUID();
  const url = new URL(request.url);
  return new Response(
    JSON.stringify({
      url: `${url.origin}${DATA_DELETION_STATUS_PATH}?code=${code}`,
      confirmation_code: code,
    }),
    { headers: { "content-type": "application/json" } },
  );
}

async function onTicket(request: Request, env: Env, id: string): Promise<Response> {
  const raw = await env.TICKETS.get(id);
  if (raw === null) return text("unhinted relay: unknown or expired ticket", 404);
  // ADR 0034 §2 — redeem must prove the install's shared secret:
  // sig = HMAC-SHA256(secret, "ticket:{id}"). A bad or missing sig neither
  // redeems nor burns the ticket.
  let instanceId = "";
  try {
    instanceId = String(asJson(JSON.parse(raw)).instance_id ?? "");
  } catch {
    // Malformed ticket payload — treated as unbound below.
  }
  const entry = await registryEntry(env, instanceId);
  const provided = hexToBytes(
    (new URL(request.url).searchParams.get("sig") ?? "").trim(),
  );
  const expected = entry
    ? new Uint8Array(await hmacSha256(entry.secret, `ticket:${id}`))
    : null;
  if (!entry || !provided || !expected || !bytesEqual(provided, expected)) {
    return text("unhinted relay: forbidden", 403);
  }
  await env.TICKETS.delete(id);
  return new Response(raw, {
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/healthz") return text("ok");
    if (url.pathname === AUTHORIZE_PATH && request.method === "GET") {
      return onAuthorize(request, env);
    }
    if (url.pathname === CALLBACK_PATH && request.method === "GET") {
      return onCallback(request, env);
    }
    if (url.pathname === DEAUTHORIZE_PATH && request.method === "POST") {
      return onMetaDeauthorize(request, env);
    }
    if (url.pathname === DATA_DELETION_PATH && request.method === "POST") {
      return onMetaDataDeletion(request, env);
    }
    if (url.pathname === DATA_DELETION_STATUS_PATH && request.method === "GET") {
      return text("Data deletion completed. This relay stores no user data.");
    }
    const ticketMatch = /^\/ticket\/([0-9a-f-]{36})$/i.exec(url.pathname);
    if (ticketMatch && request.method === "GET") {
      return onTicket(request, env, ticketMatch[1]);
    }
    return text("unhinted relay: not found", 404);
  },
};
