import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithAuth } from "@/context/auth-context";
import { apiRefresh, type TokenResponse } from "@/lib/api";

const TOKENS: TokenResponse = {
  access_token: "tok-fresh",
  token_type: "bearer",
  expires_in: 900,
  user: {
    id: "u1",
    email: "a@b.co",
    display_name: "A",
    is_active: true,
    platform_level: 9,
    created_at: "2026-01-01T00:00:00Z",
    organizations: [],
  },
};

function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("apiRefresh", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shares one in-flight refresh across concurrent callers", async () => {
    let refreshCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        refreshCalls += 1;
        await new Promise((r) => setTimeout(r, 10));
        return jsonRes(TOKENS);
      }),
    );

    const [a, b] = await Promise.all([apiRefresh(), apiRefresh()]);

    expect(refreshCalls).toBe(1);
    expect(a.access_token).toBe("tok-fresh");
    expect(b.access_token).toBe("tok-fresh");
  });

  it("issues a new request after the previous one settles", async () => {
    let refreshCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        refreshCalls += 1;
        return jsonRes(TOKENS);
      }),
    );

    await apiRefresh();
    await apiRefresh();

    expect(refreshCalls).toBe(2);
  });

  it("clears the in-flight slot on failure so the next call retries", async () => {
    let refreshCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        refreshCalls += 1;
        return refreshCalls === 1
          ? jsonRes({ detail: "Invalid refresh token" }, 401)
          : jsonRes(TOKENS);
      }),
    );

    await expect(Promise.all([apiRefresh(), apiRefresh()])).rejects.toThrow(
      "Invalid refresh token",
    );
    expect(refreshCalls).toBe(1);

    const again = await apiRefresh();
    expect(again.access_token).toBe("tok-fresh");
    expect(refreshCalls).toBe(2);
  });
});

describe("fetchWithAuth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("runs a single refresh for parallel 401s, then retries all callers", async () => {
    let refreshCalls = 0;
    const bearerSeen: Array<string | null> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        refreshCalls += 1;
        await new Promise((r) => setTimeout(r, 10));
        return jsonRes(TOKENS);
      }
      const auth = new Headers(init?.headers).get("Authorization");
      bearerSeen.push(auth);
      if (auth === `Bearer ${TOKENS.access_token}`) return jsonRes({ ok: true });
      return jsonRes({ detail: "Invalid or expired token" }, 401);
    });
    vi.stubGlobal("fetch", fetchMock);

    const [a, b] = await Promise.all([
      fetchWithAuth("tok-stale", "/api/a"),
      fetchWithAuth("tok-stale", "/api/b"),
    ]);

    expect(refreshCalls).toBe(1);
    expect(a.status).toBe(200);
    expect(b.status).toBe(200);
    expect(bearerSeen.filter((h) => h === "Bearer tok-stale")).toHaveLength(2);
    expect(bearerSeen.filter((h) => h === `Bearer ${TOKENS.access_token}`)).toHaveLength(2);
  });

  it("returns the original 401 when refresh fails", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        return jsonRes({ detail: "Invalid refresh token" }, 401);
      }
      return jsonRes({ detail: "Invalid or expired token" }, 401);
    });
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchWithAuth("tok-stale", "/api/a");
    expect(res.status).toBe(401);
  });
});
