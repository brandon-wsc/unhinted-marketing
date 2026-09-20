/**
 * Worker handler tests — KV bindings are Map-backed stubs; Meta/instance
 * outbound calls go through a stubbed global fetch. The security contract
 * under test (ADR 0032 §3 + ADR 0034): registry allowlist, fail-closed
 * {url,secret} entries, https enforcement, shared-secret ticket redeem,
 * signed_request verification, and the data-deletion 503 honesty rule.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import worker, { type Env } from "../src/index";

const RELAY = "https://connect.example.com";
const APP_ID = "app-123";
const APP_SECRET = "app-secret-xyz";
const INSTANCE_ID = "inst-abc";
const INSTANCE_URL = "https://marketing.acme.com";
const SHARED_SECRET = "shared-secret-123";
const IG_USER = "17841400000000";

class KVStub {
  store = new Map<string, string>();
  async get(key: string) {
    return this.store.get(key) ?? null;
  }
  async put(key: string, value: string) {
    this.store.set(key, value);
  }
  async delete(key: string) {
    this.store.delete(key);
  }
}

function makeEnv(): Env & { REGISTRY: KVStub; TICKETS: KVStub } {
  return {
    REGISTRY: new KVStub(),
    TICKETS: new KVStub(),
    META_APP_ID: APP_ID,
    META_APP_SECRET: APP_SECRET,
    META_GRAPH_API_VERSION: "v22.0",
  } as Env & { REGISTRY: KVStub; TICKETS: KVStub };
}

function register(env: Env, id = INSTANCE_ID, url = INSTANCE_URL, secret = SHARED_SECRET) {
  return env.REGISTRY.put(id, JSON.stringify({ url, secret }));
}

function b64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function hmacHex(secret: string, msg: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const buf = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function signedRequest(payload: object, secret = APP_SECRET): Promise<string> {
  const body = b64url(new TextEncoder().encode(JSON.stringify(payload)));
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  return `${b64url(new Uint8Array(sig))}.${body}`;
}

function metaForm(signed: string): Request {
  return new Request(`${RELAY}/meta/deauthorize`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ signed_request: signed }),
  });
}

/** Stub Meta's three exchange calls; returns a recorder for assertions. */
function stubMetaExchange() {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url === "https://api.instagram.com/oauth/access_token") {
      return Response.json({
        access_token: "short-tok",
        granted_scopes:
          "instagram_business_basic,instagram_business_content_publish",
      });
    }
    if (url.startsWith("https://graph.instagram.com/access_token")) {
      return Response.json({ access_token: "long-tok", expires_in: 5184000 });
    }
    if (url.startsWith("https://graph.instagram.com/v22.0/me")) {
      return Response.json({
        user_id: IG_USER,
        id: "x",
        username: "acme",
        account_type: "BUSINESS",
      });
    }
    return new Response("unexpected fetch", { status: 500 });
  });
  return calls;
}

/** Drive a full authorize→callback flow; returns the ticket UUID plus the
 * recorded Meta fetch calls. */
async function completeCallback(env: Env): Promise<{ ticket: string; calls: string[] }> {
  const calls = stubMetaExchange();
  const res = await worker.fetch(
    new Request(`${RELAY}/meta/callback?code=authcode&state=${INSTANCE_ID}:row:blob`),
    env,
  );
  expect(res.status).toBe(302);
  const loc = new URL(res.headers.get("location")!);
  const ticket = loc.searchParams.get("ticket")!;
  expect(ticket).toMatch(/^[0-9a-f-]{36}$/);
  return { ticket, calls };
}

afterEach(() => vi.unstubAllGlobals());

describe("healthz + routing", () => {
  it("answers ok and 404s unknown paths", async () => {
    const env = makeEnv();
    expect(await (await worker.fetch(new Request(`${RELAY}/healthz`), env)).text()).toBe("ok");
    const res = await worker.fetch(new Request(`${RELAY}/nope`), env);
    expect(res.status).toBe(404);
  });
});

describe("GET /authorize", () => {
  it("302s to the Instagram dialog with vendor creds injected", async () => {
    const env = makeEnv();
    await register(env);
    const res = await worker.fetch(
      new Request(`${RELAY}/authorize?state=${INSTANCE_ID}:row:blob`),
      env,
    );
    expect(res.status).toBe(302);
    const loc = new URL(res.headers.get("location")!);
    expect(loc.origin + loc.pathname).toBe("https://www.instagram.com/oauth/authorize");
    expect(loc.searchParams.get("client_id")).toBe(APP_ID);
    expect(loc.searchParams.get("redirect_uri")).toBe(`${RELAY}/meta/callback`);
    expect(loc.searchParams.get("state")).toBe(`${INSTANCE_ID}:row:blob`);
    expect(loc.searchParams.get("response_type")).toBe("code");
  });

  it("rejects unknown instances and malformed/legacy registry entries", async () => {
    const env = makeEnv();
    const cases = [
      null, // no entry
      INSTANCE_URL, // legacy bare string (pre-ADR-0034)
      JSON.stringify({ url: INSTANCE_URL }), // missing secret
      JSON.stringify({ url: "http://marketing.acme.com", secret: SHARED_SECRET }), // non-https
      "not json",
    ];
    for (const value of cases) {
      env.REGISTRY.store.clear();
      if (value !== null) await env.REGISTRY.put(INSTANCE_ID, value);
      const res = await worker.fetch(
        new Request(`${RELAY}/authorize?state=${INSTANCE_ID}:r:b`),
        env,
      );
      expect(res.status, `entry=${value}`).toBe(400);
    }
  });

  it("tolerates http only for loopback dev hosts", async () => {
    const env = makeEnv();
    await register(env, INSTANCE_ID, "http://localhost:8788");
    const res = await worker.fetch(
      new Request(`${RELAY}/authorize?state=${INSTANCE_ID}:r:b`),
      env,
    );
    expect(res.status).toBe(302);
  });
});

describe("GET /meta/callback", () => {
  it("fans Meta errors back to the registered instance", async () => {
    const env = makeEnv();
    await register(env);
    const res = await worker.fetch(
      new Request(
        `${RELAY}/meta/callback?error=access_denied&state=${INSTANCE_ID}:row:blob`,
      ),
      env,
    );
    expect(res.status).toBe(302);
    const loc = new URL(res.headers.get("location")!);
    expect(loc.origin).toBe(INSTANCE_URL);
    expect(loc.pathname).toBe("/api/social/oauth/relay-finish");
    expect(loc.searchParams.get("error")).toBe("access_denied");
    expect(loc.searchParams.get("state")).toBe(`${INSTANCE_ID}:row:blob`);
  });

  it("reports missing code without touching Meta", async () => {
    const env = makeEnv();
    await register(env);
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    const res = await worker.fetch(
      new Request(`${RELAY}/meta/callback?state=${INSTANCE_ID}:row:blob`),
      env,
    );
    const loc = new URL(res.headers.get("location")!);
    expect(loc.searchParams.get("error")).toBe("meta_oauth_missing_params");
    expect(spy).not.toHaveBeenCalled();
  });

  it("exchanges the code and issues a ticket + user-map entry", async () => {
    const env = makeEnv();
    await register(env);
    const { ticket, calls } = await completeCallback(env);
    expect(calls[0]).toBe("https://api.instagram.com/oauth/access_token");

    const raw = env.TICKETS.store.get(ticket)!;
    const payload = JSON.parse(raw);
    expect(payload.access_token).toBe("long-tok");
    expect(payload.instance_id).toBe(INSTANCE_ID);
    expect(payload.ig_user_id).toBe(IG_USER);
    // ig_user_id -> instance map for platform-event routing.
    expect(env.TICKETS.store.get(`u:${IG_USER}`)).toBe(INSTANCE_ID);
  });
});

describe("GET /ticket/{id} — shared-secret redeem (ADR 0034)", () => {
  it("redeems with the right sig, then deletes", async () => {
    const env = makeEnv();
    await register(env);
    const { ticket } = await completeCallback(env);

    const sig = await hmacHex(SHARED_SECRET, `ticket:${ticket}`);
    const res = await worker.fetch(
      new Request(`${RELAY}/ticket/${ticket}?sig=${sig}`),
      env,
    );
    expect(res.status).toBe(200);
    expect((await res.json()).access_token).toBe("long-tok");
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(env.TICKETS.store.has(ticket)).toBe(false);

    // Second redeem: gone.
    const again = await worker.fetch(
      new Request(`${RELAY}/ticket/${ticket}?sig=${sig}`),
      env,
    );
    expect(again.status).toBe(404);
  });

  it("403s a bad or missing sig without burning the ticket", async () => {
    const env = makeEnv();
    await register(env);
    const { ticket } = await completeCallback(env);

    for (const suffix of ["", "?sig=deadbeef", `?sig=${await hmacHex("wrong", `ticket:${ticket}`)}`]) {
      const res = await worker.fetch(new Request(`${RELAY}/ticket/${ticket}${suffix}`), env);
      expect(res.status, suffix).toBe(403);
      expect(env.TICKETS.store.has(ticket)).toBe(true);
    }

    // The ticket still redeems afterwards — probes can't burn it.
    const sig = await hmacHex(SHARED_SECRET, `ticket:${ticket}`);
    const res = await worker.fetch(
      new Request(`${RELAY}/ticket/${ticket}?sig=${sig}`),
      env,
    );
    expect(res.status).toBe(200);
  });

  it("404s unknown tickets", async () => {
    const env = makeEnv();
    const id = crypto.randomUUID();
    const sig = await hmacHex(SHARED_SECRET, `ticket:${id}`);
    const res = await worker.fetch(
      new Request(`${RELAY}/ticket/${id}?sig=${sig}`),
      env,
    );
    expect(res.status).toBe(404);
  });
});

describe("Meta platform callbacks", () => {
  it("rejects unsigned/garbage deauthorize posts", async () => {
    const env = makeEnv();
    for (const raw of [
      "not-a-request",
      "",
      await signedRequest({ algorithm: "HMAC-SHA256", user_id: IG_USER }, "wrong-secret"),
    ]) {
      const res = await worker.fetch(metaForm(raw), env);
      expect(res.status).toBe(400);
    }
  });

  it("forwards a verified deauthorize re-signed with the install secret", async () => {
    const env = makeEnv();
    await register(env);
    await env.TICKETS.put(`u:${IG_USER}`, INSTANCE_ID);

    const seen: { url: string; body: string }[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({ url: String(input), body: String(init?.body) });
      return new Response("{}", { status: 200 });
    });

    const res = await worker.fetch(
      metaForm(await signedRequest({ algorithm: "HMAC-SHA256", user_id: IG_USER })),
      env,
    );
    expect(res.status).toBe(200);
    expect(seen).toHaveLength(1);
    expect(seen[0].url).toBe(`${INSTANCE_URL}/api/social/meta/relay`);
    const fwd = JSON.parse(seen[0].body);
    expect(fwd.kind).toBe("deauthorize");
    expect(fwd.ig_user_id).toBe(IG_USER);
    expect(fwd.sig).toBe(await hmacHex(SHARED_SECRET, `deauthorize:${IG_USER}`));
    // User map entry is cleared on deauthorize.
    expect(env.TICKETS.store.has(`u:${IG_USER}`)).toBe(false);
  });

  it("proxies the instance's data-deletion answer to Meta", async () => {
    const env = makeEnv();
    await register(env);
    await env.TICKETS.put(`u:${IG_USER}`, INSTANCE_ID);
    vi.stubGlobal(
      "fetch",
      async () =>
        Response.json({
          url: `${INSTANCE_URL}/api/social/meta/data-deletion/abc`,
          confirmation_code: "abc",
        }),
    );
    const res = await worker.fetch(
      new Request(`${RELAY}/meta/data-deletion`, {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          signed_request: await signedRequest({ algorithm: "HMAC-SHA256", user_id: IG_USER }),
        }),
      }),
      env,
    );
    expect(res.status).toBe(200);
    expect((await res.json()).confirmation_code).toBe("abc");
  });

  it("503s when a mapped install is unreachable so Meta retries", async () => {
    const env = makeEnv();
    await register(env);
    await env.TICKETS.put(`u:${IG_USER}`, INSTANCE_ID);
    vi.stubGlobal("fetch", async () => {
      throw new Error("instance down");
    });
    const res = await worker.fetch(
      new Request(`${RELAY}/meta/data-deletion`, {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          signed_request: await signedRequest({ algorithm: "HMAC-SHA256", user_id: IG_USER }),
        }),
      }),
      env,
    );
    expect(res.status).toBe(503);
  });

  it("answers statically when no routing record exists", async () => {
    const env = makeEnv();
    const res = await worker.fetch(
      new Request(`${RELAY}/meta/data-deletion`, {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          signed_request: await signedRequest({ algorithm: "HMAC-SHA256", user_id: IG_USER }),
        }),
      }),
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.url).toContain("/meta/data-deletion-status?code=");
    expect(body.confirmation_code).toBeTruthy();
  });
});
