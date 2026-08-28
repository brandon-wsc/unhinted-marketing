# Cloudflare cache rules (dashboard reference)

Apply in **Caching → Cache Rules** (or legacy Page Rules). Hostname: `app.example.com`.

| Order | Name | Match | Cache action | Edge TTL |
|-------|------|-------|--------------|----------|
| 1 | Bypass API | URI Path starts with `/api/` | Bypass cache | — |
| 2 | Bypass SSE | URI Path matches `^/api/sessions/.*/events$` | Bypass cache | — |
| 3 | Immutable assets | URI Path matches `.*\.(js|css|woff2?|ttf|eot|svg|ico)$` OR starts with `/assets/` | Eligible for cache | 1 year |
| 4 | SPA shell | URI Path equals `/index.html` | Eligible for cache | Respect origin (`no-cache`) |
| 5 | Default SPA | Hostname equals `app.example.com` | Eligible for cache | Respect origin |

## R2 media (`media.example.com`)

| Order | Name | Match | Cache action | Edge TTL |
|-------|------|-------|--------------|----------|
| 1 | Public preview images | Hostname equals `media.example.com` | Eligible for cache | 1 day (adjust per privacy policy) |

Origin nginx (`infra/nginx/unhinted.conf.example`) sets matching `Cache-Control` headers so Cloudflare respects them under **Cache Level: Standard**.

## Settings to avoid breaking SSE

- Do **not** enable Rocket Loader on `app.example.com`.
- **WebSockets** are not used; SSE uses long-lived HTTP — ensure proxy read timeout ≥ 3600s (nginx + Tunnel `originRequest` in `cloudflared/config.yml.example`).
