/**
 * Cloudflare Worker — R2 presigned URL gate (P3 optional hardening)
 *
 * Serves private R2 objects after validating a short-lived HMAC token issued
 * by the FastAPI API. Public bucket policy can be removed once this is live.
 *
 * Deploy:
 *   npm i -g wrangler
 *   wrangler r2 bucket create unhinted-media   # if not exists
 *   wrangler secret put MEDIA_SIGNING_SECRET   # shared with API (future endpoint)
 *
 * wrangler.toml (create alongside this file):
 *   name = "unhinted-r2-signed-urls"
 *   main = "r2-signed-urls.js"
 *   compatibility_date = "2024-01-01"
 *   [[r2_buckets]]
 *   binding = "MEDIA_BUCKET"
 *   bucket_name = "unhinted-media"
 *   routes = [{ pattern = "media.example.com/*", zone_name = "example.com" }]
 *
 * Token format (query ?token=): base64url(payload).base64url(hmac-sha256)
 * payload JSON: { "key": "sessions/…/image.png", "exp": unix_seconds }
 */

const encoder = new TextEncoder();

async function verifyToken(token, secret) {
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const [payloadB64, sigB64] = parts;
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const sigBytes = Uint8Array.from(atob(sigB64.replace(/-/g, "+").replace(/_/g, "/")), (c) =>
    c.charCodeAt(0),
  );
  const ok = await crypto.subtle.verify("HMAC", key, sigBytes, encoder.encode(payloadB64));
  if (!ok) return null;
  const json = JSON.parse(atob(payloadB64.replace(/-/g, "+").replace(/_/g, "/")));
  if (!json.key || !json.exp || json.exp < Math.floor(Date.now() / 1000)) return null;
  return json;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const token = url.searchParams.get("token");
    if (!token) return new Response("Missing token", { status: 401 });

    const secret = env.MEDIA_SIGNING_SECRET;
    if (!secret) return new Response("Worker not configured", { status: 500 });

    const payload = await verifyToken(token, secret);
    if (!payload) return new Response("Invalid or expired token", { status: 403 });

    const object = await env.MEDIA_BUCKET.get(payload.key);
    if (!object) return new Response("Not found", { status: 404 });

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("etag", object.httpEtag);
    headers.set("cache-control", "private, max-age=3600");

    return new Response(object.body, { headers });
  },
};
