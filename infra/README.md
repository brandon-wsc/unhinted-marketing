# Infrastructure configs

Reference implementations for production deployment. Not executed by CI.

| Path | Purpose |
|------|---------|
| [cloudflare/cloudflared/config.yml.example](cloudflare/cloudflared/config.yml.example) | Cloudflare Tunnel → origin nginx |
| [nginx/unhinted.conf.example](nginx/unhinted.conf.example) | Same-origin SPA + `/api` proxy (ADR 0006) |
| [cloudflare/waf-rate-limit-rules.json](cloudflare/waf-rate-limit-rules.json) | WAF / rate limit rule templates |
| [cloudflare/cache-rules.md](cloudflare/cache-rules.md) | CDN cache rule checklist |
| [cloudflare/pages/_headers](cloudflare/pages/_headers) | Optional Cloudflare Pages cache headers |
| [cloudflare/workers/](cloudflare/workers/) | R2 signed-URL Worker (private media) |

Operator guide: [docs/infra/cloudflare.md](../docs/infra/cloudflare.md).
