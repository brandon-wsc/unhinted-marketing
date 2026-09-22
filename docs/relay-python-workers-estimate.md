# Estimate — rewrite the OAuth relay to Python Workers

**Status:** estimate only. No rewrite, no Meta dashboard change, no production deploy.
**Date:** 2026-09-22
**Audience:** go / no-go for Brandon
**Sources checked:** `relay/` (handler, vitest, wrangler, README), ADR 0032 §3, ADR 0033 §3, ADR 0034, `docs/STATUS.md`, `.github/workflows/ci.yml`, `internal/config.py` (`HOSTED_OAUTH_RELAY_URL`), `internal/auth/meta_oauth.py` (ticket + event HMAC the install already verifies). Python Workers: [GA blog, 2026-09-21](https://blog.cloudflare.com/python-workers-ga/), [Python Workers docs](https://developers.cloudflare.com/workers/languages/python/) (page still dated 2026-09-17), [packages](https://developers.cloudflare.com/workers/languages/python/packages/), [how they work](https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/).

## Recommendation

**Stay on TypeScript.** Revisit only if single-language ops becomes a real goal, and only after a half-day `pywrangler` spike.

Python Workers went GA on 2026-09-21. This relay is already a ~520-line, security-sensitive edge program whose protocol is frozen by ADR 0032 / 0034 and whose URL is an exact Meta redirect. A port is a contained ~5 person-day project, and it does not change product behavior.

## Effort

One engineer who already knows this relay. Days are 8-hour person-days.

| Slice | Low | Likely | High |
|---|---:|---:|---:|
| Toolchain spike: `pywrangler dev`, KV `put` with 60s TTL, `formData`, `fetch`, 302 | 2h | 4h | 8h |
| Port handler (routes, registry, exchange, HMAC, signed_request) | 6h | 12h | 20h |
| Port the vitest contract to pytest with fakes | 4h | 8h | 12h |
| CI + deploy toolchain (uv job, retire npm) | 2h | 4h | 8h |
| Docs (README, `AGENTS.md`, short ADR/STATUS note) | 2h | 3h | 4h |
| UAT + in-place cutover + rollback drill | 4h | 8h | 16h |
| **Total** | **20h (2.5d)** | **39h (5d)** | **68h (8.5d)** |

**Low 2.5d / likely 5d / high 8.5d.**

The high band is FFI friction (KV options, form bodies, redirect `Response`) plus a supervised production cutover that needs a second attempt. It is not a hidden second system: the FastAPI app, web UI, and KV namespace IDs stay put.

## 1. Scope inventory

The worker is transit-only. Tokens are not logged. Tickets live in KV for 60 seconds. The install redeems them with HMAC (ADR 0034). Nothing else in the repo should change if the HTTP contract stays byte-compatible.

### Endpoints (`relay/src/index.ts`)

| Route | Behavior |
|---|---|
| `GET /healthz` | `ok` |
| `GET /authorize?state={instance_id}:…` | REGISTRY allowlist, then 302 to `https://www.instagram.com/oauth/authorize` with vendor `client_id`, scopes, and fixed `redirect_uri` `{origin}/meta/callback` |
| `GET /meta/callback` | Meta redirect. Exchange code → long-lived token → `/me`. 302 to `{REGISTRY.url}/api/social/oauth/relay-finish?ticket&state` or `?error=` |
| `POST /meta/deauthorize` | Verify Meta `signed_request`, forward to the install, delete `u:{ig_user_id}` |
| `POST /meta/data-deletion` | Same verify + forward. Proxy the install's `{url, confirmation_code}`. **503** when a user-map row exists and the forward fails. Static JSON only when no row exists |
| `GET /meta/data-deletion-status?code=` | Static “relay stores no user data” |
| `GET /ticket/{uuid}?sig=` | HMAC-SHA256(secret, `ticket:{id}`) hex, constant-time compare. 403 does **not** delete. Success deletes and returns JSON `cache-control: no-store` |

Unknown paths: 404. Error codes the API allows through on relay-finish are listed in `cmd/api/routes/social.py` (`access_denied`, `meta_oauth_missing_params`, `meta_oauth_exchange_failed`, `meta_oauth_not_professional`, `meta_oauth_missing_publish`, `meta_oauth_graph_error:\d+`).

### Bindings and secrets (`relay/wrangler.toml`)

| Name | Kind | Notes |
|---|---|---|
| `REGISTRY` | KV `fcb5053c60f1416ea93d08d02ae93f20` | `instance_id` → `{"url","secret"}`. https required; `http` only for `localhost` / `127.0.0.1` / `[::1]`. Bare strings fail closed |
| `TICKETS` | KV `03b6f9135c274b7e9baad129ea49e227` | Ticket JSON, `expirationTtl: 60`. User map `u:{ig_user_id}` → instance id, TTL 90 days |
| `META_APP_ID` | var | `1381157764130031` in toml |
| `META_GRAPH_API_VERSION` | var | `v22.0` (code strips a leading `v`) |
| `META_APP_SECRET` | Worker secret | `wrangler secret put`. Not in git |

Worker name: `unhinted-oauth-relay`. Live base URL, hardcoded in `internal/config.py`: `https://unhinted-oauth-relay.unhinted.workers.dev`. Custom domain route in toml is commented out. No cron, Durable Objects, R2, or queues.

### Meta and install calls

- Browser 302: `https://www.instagram.com/oauth/authorize`
- `POST https://api.instagram.com/oauth/access_token` (form)
- `GET https://graph.instagram.com/access_token` (`ig_exchange_token`; **client secret is a query param**)
- `GET https://graph.instagram.com/v{version}/me`
- `POST {install}/api/social/meta/relay` with `{kind, ig_user_id, sig}`

`exchangeCode` mirrors `internal/auth/meta_oauth.py` (`_parse_short_lived`, professional account types, publish scope). The install checks `relay_ticket_signature` / `relay_event_signature` with `hmac` + SHA-256 hex. A Python worker can use that same stdlib construction. Do not import `internal.auth.meta_oauth` into the worker: Pyodide vs the app runtime, and the module pulls the API.

`expires_at` today is `Date.toISOString()` (`…Z`). The API parses it with `datetime.fromisoformat`. Keep a `Z` or offset form that 3.12 accepts.

### Tests

`relay/test/index.test.ts` (~400 lines, vitest). KV is an in-memory `Map`. `fetch` is stubbed. No workerd, no Meta network. Coverage that must be re-ported:

- healthz / 404
- authorize injects vendor creds and the fixed redirect URI
- authorize rejects missing, legacy bare-string, secret-less, non-https, and invalid JSON registry rows
- http loopback allowed
- callback fans `error=access_denied` and missing `code` (no Meta fetch)
- happy-path ticket + `u:{ig}` map
- redeem once, then 404; bad/missing sig is 403 and does not burn the ticket
- signed_request reject / deauthorize forward + map delete
- data-deletion proxy, 503 when the install throws, static answer when unmapped

### CI and deploy

- CI job `relay` in `.github/workflows/ci.yml`: Node 22, `npm ci`, `tsc --noEmit`, `vitest run`. No deploy step.
- `release.yml` does not mention the relay.
- Deploy and registry edits are manual (`relay/README.md`): `wrangler deploy`, `wrangler kv key put`, `wrangler secret put`.
- `AGENTS.md` quick command: `cd relay && npm ci && npm run types && npm test`.
- Toolchain today: `wrangler` ^4.33 (lock resolves 4.135), vitest 5, TypeScript 5.8, `@cloudflare/workers-types`. `compatibility_date = "2026-09-20"`.

### Docs that a real port would touch

- `relay/README.md` (setup, register, endpoints)
- `AGENTS.md` relay command
- `.github/workflows/ci.yml` relay job
- A short note on ADR 0032 §3 / STATUS: implementation language and the ops CLI. The ADR locks “Cloudflare Worker” plus the protocol, not TypeScript, so a superseding ADR is unnecessary if URLs, HMAC, REGISTRY JSON, and TTLs stay
- Comment in `cmd/api/routes/social.py` that points at `relay/src/index.ts`

Unchanged on a faithful port: FastAPI routes, web UI, migrations, KV ids, `HOSTED_OAUTH_RELAY_URL`, Meta dashboard entries.

## 2. Python Workers fit

GA as of **2026-09-21**. The Worker runs Pyodide (CPython-on-Wasm) inside the isolate. Entrypoint:

```python
from workers import WorkerEntrypoint, Response

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return Response("ok")
```

### Toolchain

- **pywrangler** (`workers-py`) wraps **wrangler**. It vendors packages from `pyproject.toml` and still needs **uv and Node**.
- Local: `uv run pywrangler dev`. Deploy: `uv run pywrangler deploy`.
- `uv run pywrangler kv …` / `secret put` are the same Wrangler commands. Existing KV ids and `META_APP_SECRET` stay on the worker if the script **name** stays `unhinted-oauth-relay`.
- Docs dated 2026-09-17 still say: add compatibility flag `python_workers`. The GA post does not say the flag was removed. Treat it as required until a deploy proves otherwise.
- Packages example uses `requires-python = ">=3.13"`. This repo’s API CI is 3.12. The relay should be its own uv project, not the API venv.
- Pyodide version is selected from `compatibility_date`.

### HTTP clients

Docs (packages page) list **async** clients only: **`aiohttp`** and **`httpx2`**, plus JavaScript **`fetch`** through FFI (`request.json()` already returns a Python dict; `urlparse(request.url)` is the documented URL parse).

The GA blog says upstream work lets **`requests` / `httpx`** route through `fetch` and that sockets now exist. That claim is newer than the packages page (2026-09-18). For this relay, call **`fetch`** (the same three Meta calls as today). Do not take a dependency on `httpx` or `aiohttp` until a spike shows them on this compatibility date. The long-lived token request puts the app secret in the query string; `fetch` already does that in the TypeScript worker.

### KV and secrets

FFI docs show `await self.env.FOO.put("bar", "baz")` and `await self.env.FOO.get("bar")`. The GA post says binding values are converted to Python dicts without `to_js`. Ticket TTL is the Workers KV **minimum of 60 seconds**, which this relay already uses (`TICKET_TTL_SECONDS = 60`). The spike has to confirm the Python call accepts `expirationTtl` (JS options object). Secrets and `[vars]` arrive on `self.env` the same way.

KV `get`+`delete` is still not atomic. ADR 0032 already accepts that race. A language change does not fix it; a Durable Object would, and that is out of scope.

### Cold start / snapshot

`pywrangler deploy` runs top-level imports, snapshots Wasm linear memory, and restores that snapshot per isolate. The published “~10s → ~1s” figure is for a worker that imports FastAPI, httpx, and Pydantic. This relay can stay on the stdlib (`hmac`, `hashlib`, `json`, `urllib.parse`, `uuid`) plus `fetch`. No import-time KV or network. A sub-second restore is in family with the three Meta round-trips the callback already waits on. Measure it once on a **preview** worker name before touching production. It is unlikely to decide the port.

### Blockers

No hard blocker for this workload (HTTP fetch, KV, secrets, HMAC, form POST, 302).

Open questions, all spike-sized:

1. Is `python_workers` still mandatory the week after GA?
2. Does `put(key, value, {"expirationTtl": 60})` work without `to_js`?
3. `await request.formData()` for Meta’s `signed_request` body, and `Response` with status 302 + `Location`.
4. `workers` is injected by the runtime. Plain pytest cannot import a live `WorkerEntrypoint`. Keep protocol functions importable on CPython and leave a thin `Default.fetch` shim for `pywrangler`.

## 3. Migration steps

Protocol stays. The install, the browser, and Meta should not be able to tell the runtimes apart.

1. **Spike (throwaway).** `pywrangler init` on a scratch worker name (not `unhinted-oauth-relay`). Prove healthz, KV put/get with `expirationTtl: 60`, form POST, outbound `fetch`, and a 302. Stop if TTL or form parsing needs a JS shim larger than a few lines.
2. **Parity port.** New modules under `relay/` for registry parse, HMAC, signed_request, exchange, and routing. Shim `Default.fetch`. Keep worker name, KV ids, var names, and secret name. Preserve error code strings and ticket JSON keys (`instance_id`, `ig_user_id`, `access_token`, `expires_at`, `missing_scopes`).
3. **Tests.** Pytest the same cases as `relay/test/index.test.ts`, with a Map-backed KV and a fake `fetch`. CI runs that on CPython. Do not require workerd in CI.
4. **Preview smoke.** `pywrangler dev` or a second worker name against a loopback REGISTRY row (http localhost is already allowed). This does not complete a real Meta code exchange: that callback origin is not on the vendor app.
5. **Cutover.** In-place `pywrangler deploy` to **the same worker name**, so `https://unhinted-oauth-relay.unhinted.workers.dev/meta/callback` does not change. One supervised relay-mode Connect. Rollback is the previous Workers version (`wrangler rollback`), which restores the TypeScript script, KV, and secret together.
6. **Retire TypeScript** after that Connect succeeds: delete `package.json`, lockfile, `tsconfig`, vitest; point `AGENTS.md` and the CI job at uv/pytest; note the CLI in the ADR/STATUS line.

Dual-run (two hostnames at once) needs a second exact Valid OAuth Redirect URI on the vendor Meta app, then a later removal. Skip it unless the in-place rollback window is unacceptable.

## 4. Risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| Meta Strict Mode | `{relay}/meta/callback`, `/meta/deauthorize`, and `/meta/data-deletion` are exact dashboard strings. A new worker name changes `*.workers.dev` and breaks connect until the dashboard is edited | Keep `name = "unhinted-oauth-relay"`. No second production hostname |
| Ticket TTL | KV rejects TTL under 60s. A Python `put` that drops `expirationTtl` leaves long-lived tokens in KV | Spike the option. Assert TTL in a local miniflare put if the binding exposes it; otherwise watch the key from `wrangler kv` during UAT |
| Ticket HMAC | Install uses `hmac.new(secret, f"ticket:{id}", sha256).hexdigest()`. A bad encoding (str vs bytes, hex case, comparing before the registry lookup) 403s every redeem or, worse, accepts a wrong sig | Port the vitest vectors. 403 must not delete |
| signed_request | Meta’s `<b64url sig>.<b64url json>` must match the current padding and `HMAC-SHA256` check. Deauthorize and data-deletion depend on it | Same test vectors as today (wrong secret, garbage, happy path) |
| REGISTRY JSON | Fail-closed `{url, secret}`, https, loopback exception. A looser parser re-opens the open redirect ADR 0032 forbids | Port the five negative authorize cases unchanged |
| `expires_at` shape | API uses `datetime.fromisoformat` | Emit an ISO string 3.12 parses (`Z` is fine on 3.11+) |
| Live cutover | The production script swap is the first real Meta round-trip. A bad deploy breaks relay-mode Connect until rollback. Already-connected tokens keep working (ADR 0032) | Deploy in a quiet window, previous version ready, one Connect, then rollback drill on a scratch worker beforehand |
| CI | Relay job is Node + npm + tsc + vitest. pywrangler still wants Node, but unit tests should not | Replace the job with uv + pytest. Keep Node off the critical path |
| Local CLI | Operators use `npx wrangler`. pywrangler shells out to wrangler and pins its own copy via `workers-runtime-sdk` | Document one command for deploy. KV `key put` can stay `wrangler` or move with it; do not fork the toml |
| Docs lag | Intro page still describes the beta flag four days before this estimate; packages page still names `httpx2` while the GA blog says `httpx` works | Believe a spike on this account, not the blog alone |
| Secret in the long-lived URL | Existing behavior: `client_secret` is a query param to `graph.instagram.com`. Language change does not make that worse, and logging it would | Keep the “do not log params” rule. Graph `console.warn` today logs only `code`, `subcode`, `type`, `fbtrace` |

## 5. What we would not do

- Share the API’s `exchange_code` by importing `internal/`.
- Add FastAPI inside the worker. Seven routes do not need an ASGI stack, and that stack is what makes cold start interesting.
- Change REGISTRY, ticket TTL, HMAC messages, or the hosted URL.
- Fix the KV get/delete race with a Durable Object in the same change.
