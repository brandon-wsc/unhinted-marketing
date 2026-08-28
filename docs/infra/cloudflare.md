# Cloudflare infrastructure — Unhinted Marketing

Production edge layer for **Option A** (self-hosted origin + Cloudflare DNS/TLS/Tunnel). Aligns with [ADR 0006](../adr/0006-api-path-prefix-and-spa-proxy.md) same-origin `/api` routing and [ADR 0010](../adr/0010-org-membership-invites-and-shared-assets.md) on-prem targets.

## Topology

```text
app.example.com (Cloudflare DNS, proxied)
  ├── /*           → Tunnel → origin nginx → web/dist (CDN cached)
  ├── /api/*       → Tunnel → origin nginx → uvicorn :8000 (bypass cache)
  └── media.example.com → R2 custom domain (CDN cached)

On-prem / VPS:
  - nginx (infra/nginx/unhinted.conf.example)
  - uvicorn cmd.api.main:app
  - cmd.scheduler + PostgreSQL + pgvector
  - cloudflared (infra/cloudflare/cloudflared/config.yml.example)
```

See also: [cache-rules.md](../../infra/cloudflare/cache-rules.md), [waf-rate-limit-rules.json](../../infra/cloudflare/waf-rate-limit-rules.json).

---

## P0 — DNS + TLS + Tunnel

### 1. DNS

1. Add domain to Cloudflare; point registrar NS to Cloudflare.
2. Create records (proxied orange cloud):
   - `app` → CNAME `<tunnel-id>.cfargotunnel.com` (after tunnel create)
   - `media` → R2 custom domain (see P1)

### 2. TLS

- **SSL/TLS mode:** Full (strict) when origin serves HTTPS or Tunnel terminates to HTTP on localhost.
- **Edge certificates:** Automatic.
- **Origin certificate (optional):** Cloudflare Origin CA if nginx listens on 443 locally.

### 3. Application env (production)

```env
APP_ENV=production
WEB_BASE_URL=https://app.example.com
CORS_ORIGINS=https://app.example.com
REFRESH_COOKIE_SECURE=true
REFRESH_COOKIE_SAMESITE=lax
```

### 4. Cloudflare Tunnel

```bash
# On origin host
cloudflared tunnel login
cloudflared tunnel create unhinted
cp infra/cloudflare/cloudflared/config.yml.example /etc/cloudflared/config.yml
# Edit: tunnel UUID, hostname, credentials path
cloudflared tunnel route dns unhinted app.example.com
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

### 5. Origin nginx

```bash
pnpm --dir web install && pnpm --dir web run build
sudo cp infra/nginx/unhinted.conf.example /etc/nginx/sites-available/unhinted.conf
# Edit: server_name, root path to web/dist
sudo ln -s /etc/nginx/sites-available/unhinted.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Run API: `uvicorn cmd.api.main:app --host 127.0.0.1 --port 8000`

---

## P1 — R2 media storage

Code already uses S3-compatible boto3 ([`internal/media/storage.py`](../../internal/media/storage.py)). Replace MinIO with R2:

1. Cloudflare Dashboard → R2 → Create bucket `unhinted-media`.
2. R2 → Manage R2 API tokens → create token with Object Read & Write.
3. R2 bucket → Settings → Public access **or** custom domain `media.example.com` (recommended).
4. Set production `.env`:

```env
S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
S3_ACCESS_KEY=<R2_ACCESS_KEY_ID>
S3_SECRET_KEY=<R2_SECRET_ACCESS_KEY>
S3_BUCKET=unhinted-media
S3_REGION=auto
S3_PUBLIC_BASE_URL=https://media.example.com
```

Local dev continues to use MinIO (`docker compose up -d minio minio-init`) with values from [`.env.example`](../../.env.example).

**Note:** Current app uses public-read URLs for preview `<img src>`. For private buckets, use the optional R2 signed-URL Worker (P3).

---

## P1 — WAF + rate limiting

Configure in **Security → WAF → Rate limiting rules** (or import patterns from [`waf-rate-limit-rules.json`](../../infra/cloudflare/waf-rate-limit-rules.json)):

| Path | Limit | Purpose |
|------|-------|---------|
| `POST /api/auth/register`, `login`, `refresh` | 10/min per IP | Brute-force / credential stuffing |
| `POST /api/sessions/*/messages` | 30/min per IP | LLM cost abuse |

**SSE bypass:** Cache Rules must bypass `/api/sessions/*/events` — see [cache-rules.md](../../infra/cloudflare/cache-rules.md).

App-layer limits (`AUTH_RATE_LIMIT_*`) remain as a second line of defense; edge limits work across multiple API processes.

---

## P2 — CDN cache rules

Origin nginx sets `Cache-Control` for static assets and `no-cache` for `index.html`. Mirror at edge via [cache-rules.md](../../infra/cloudflare/cache-rules.md).

Quick checklist:

- [ ] `/api/*` — Bypass cache
- [ ] `/api/sessions/*/events` — Bypass cache
- [ ] `/assets/*`, `*.js`, `*.css` — Cache 1 year, immutable
- [ ] `/index.html` — No cache / respect origin
- [ ] Rocket Loader **off** for `app.example.com`

Optional Cloudflare Pages `_headers` for static-only hosting: [`infra/cloudflare/pages/_headers`](../../infra/cloudflare/pages/_headers).

---

## P2 — Turnstile (bot protection)

Optional; disabled by default in dev.

### Backend

```env
TURNSTILE_ENABLED=true
TURNSTILE_SECRET_KEY=<from Cloudflare Turnstile dashboard>
```

When enabled, `POST /api/auth/register` and `POST /api/auth/login` require `turnstile_token` in JSON body (verified server-side via Cloudflare siteverify).

### Frontend

```env
# web/.env.production or build-time env
VITE_TURNSTILE_SITE_KEY=<site key>
```

Widget renders on login/register when site key is set. See [`web/src/components/turnstile-widget.tsx`](../../web/src/components/turnstile-widget.tsx).

### WAF (optional)

After both sides are live, enable the disabled rule in `waf-rate-limit-rules.json` to block auth POSTs without `cf-turnstile-response` at edge.

---

## P3 — R2 signed URLs (private media)

Optional Worker for auth-gated media instead of public bucket policy:

- Script: [`infra/cloudflare/workers/r2-signed-urls.js`](../../infra/cloudflare/workers/r2-signed-urls.js)
- Deploy: `wrangler deploy` with R2 bucket binding
- Route: `media.example.com/*` or path prefix on API

Requires JWT validation at edge or short-lived tokens issued by API — see Worker README in that file.

---

## What Cloudflare does **not** replace

| Component | Keep on origin |
|-----------|----------------|
| PostgreSQL + pgvector | Yes — ADR hard boundary |
| LangGraph / uvicorn API | Yes — not Workers |
| `cmd.scheduler` / workers | Yes — separate process |
| Multi-worker SSE fan-out | Needs Redis later; CF is edge-only |

---

## SSE compatibility

API sets `X-Accel-Buffering: no` on session events. Verify:

1. nginx `proxy_buffering off` for `/api/` (see nginx example)
2. Tunnel `keepAliveTimeout` ≥ 90s
3. Cloudflare cache bypass on `/api/sessions/*/events`
4. No Rocket Loader

---

## Related docs

- [GETTING_STARTED.md](../GETTING_STARTED.md) — local dev
- [STATUS.md](../STATUS.md) — environment variable reference
- [ROADMAP.md](../ROADMAP.md) — Phase 4 S3 / Redis items
