# ADR 0006 — API path prefix vs SPA same-origin proxy

- **Status:** Accepted; **migration executed 2026-08-04**
- **Date:** 2026-08-03
- **Supersedes:** —
- **Related:** [ADR 0005](./0005-platform-levels-and-llm-records.md) (admin API + web admin page)

## Context

Dev serves the React SPA at `localhost:5173` and proxies selected path prefixes to FastAPI at `localhost:8000` (`web/vite.config.ts`):

```text
/auth, /health, /sessions, /companies, /signals, /admin  →  API
```

Browser navigations and `fetch` share that origin. Vite's string proxy keys are **prefix matches** (`path.startsWith(key)`): a key `"/admin"` also captures `/admin-panel`, `/administrator`, etc.

When the SPA gained a page at `/admin` (ADR 0005), a full page refresh requested `GET /admin` as HTML navigation. Vite proxied it to FastAPI; FastAPI has no such route → `{"detail":"Not Found"}`. Client-side React Router never ran. Renaming the page to `/admin-panel` does **not** fix this by itself — that path still starts with `/admin`.

### Was this a bug from day one?

| Layer | Assessment |
|-------|------------|
| **User-visible failure** | No — until a SPA route shared a prefix with a proxied API segment. `/`, `/login`, `/register` never collided with `/auth`, `/sessions`, … |
| **Latent design footgun** | **Yes** — from the moment same-origin vite proxy listed top-level resource names (`/sessions`, `/auth`, …). Any future SPA path under those prefixes (or sharing their string prefix) would break refresh the same way. Example: a page at `/authenticate` would be swallowed by `"/auth"`. |
| **Root cause class** | SPA and HTTP API share one URL namespace with no reserved API root. Dev proxy (and a future prod reverse-proxy) must special-case every collision. |

This is not a React Router bug and not a FastAPI bug. It is a **namespace collision** between document URLs and API URLs on one origin.

## Decision

### 1. Long-term: mount the HTTP API under a single reserved prefix `/api`

All public JSON/SSE routes move under `/api/…`, e.g.:

| Before | After |
|--------|-------|
| `/auth/*` | `/api/auth/*` |
| `/sessions/*` | `/api/sessions/*` |
| `/companies/*` | `/api/companies/*` |
| `/signals/*` | `/api/signals/*` |
| `/admin/*` | `/api/admin/*` |
| `/health` | `/api/health` |

Vite (and production ingress) then needs **one** proxy rule:

```text
/api  →  API upstream
```

The SPA owns every other path (`/`, `/login`, `/admin`, `/admin-panel`, …) without per-resource proxy lists or Accept-header bypass hacks.

### 2. Until migration: do not place SPA document routes under proxied prefixes

Interim options (any one is enough; prefer clarity over cleverness):

1. **SPA path outside every proxy prefix** — e.g. `/console` (does not start with `/admin`, `/auth`, `/sessions`, …).
2. **Tight proxy match** — regex `^/admin(?:/|$)` so `/admin-panel` is not captured (fragile; easy to get wrong again).
3. **HTML bypass** — proxy only non-`Accept: text/html` requests (dev-only smell; must be mirrored in prod).

Do **not** treat renaming alone (`/admin` → `/admin-panel`) as sufficient without (1) or (2).

### 3. Migration is a deliberate follow-up, not part of ADR 0005

Moving to `/api` touches FastAPI routers, OpenAPI export, web `fetch` paths, vite proxy, API tests, and any external clients. Ship as its own change with contract re-export. Backward-compatible dual-mount (`/` + `/api`) is optional for one release if needed; this repo has no public API consumers yet, so a hard cut is acceptable.

## Consequences

- **Better:** One proxy rule; SPA free to use any path; prod nginx/Caddy config matches mental model; eliminates the “refresh → Not Found JSON” class of bugs.
- **Cost:** Mechanical path rewrite across backend + `web/` + docs/contracts; brief churn for anyone with hardcoded URLs.
- **OpenAPI / contracts:** Paths in `docs/openapi.json` become `/api/…`; regenerate via `python -m scripts.export_contracts`.
- **SSE:** Event URLs (`/api/sessions/{id}/events`) move with the rest; clients already go through the same origin proxy — update fetch paths only.
- **Status until done:** Current multi-key vite proxy + careful SPA naming remains the interim rule; document any new SPA route against the proxy prefix list before merge.

## Rejected alternatives (as the durable fix)

- **Keep growing the vite proxy key list + bypass heuristics** — works in demos, fails the next colliding name, diverges from prod.
- **HashRouter** — avoids server path issues but worsens URLs/bookmarks; does not teach the API/SPA split for production.
- **Separate API origin in dev** (`localhost:8000` from the browser) — CORS + cookie/`SameSite` complexity; production will often same-origin again anyway.

## Update (2026-08-04) — migration executed

Hard cut (no dual-mount):

- FastAPI: all routers + `/api/health` mounted under `/api` (`cmd/api/main.py`); refresh cookie `Path=/api/auth`
- Web: `API_BASE = "/api"`; vite proxy is a single `"/api"` → `:8000` rule
- SPA document route `/admin` kept; refresh now serves the React app (API is `/api/admin/*`)
- Contracts re-exported; API tests updated

## Update (2026-08-13) — SPA route `/system` (API unchanged)

- UserMenu label **System**; SPA document route `/system` replaces `/admin` for platform ops UI ([STATUS](./STATUS.md) decision 2026-08-13).
- **HTTP API remains** `/api/admin/*` — platform-level namespace per ADR 0005, not tenant `organization_members.role`.
- Legacy SPA `/admin` redirects to `/system` (query preserved). No `/api/system` alias in this slice.
