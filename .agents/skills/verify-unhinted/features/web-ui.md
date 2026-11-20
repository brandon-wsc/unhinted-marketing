# Web UI

## Sub-features

- `/login` SPA — sign in against the API
- `/setup` wizard — drives `GET/POST /api/setup` (same path as `first-run-setup`)
- Workspace — chat panel + session history + preview pane (`web/src/pages`, `features/session`)

## How to get to it (user POV)

`https://unhinted.localhost:5173` (vite dev, self-signed certs under `web/certs`) is what a user opens; nginx proxies `/api` in shipped deployments.

## Driving it with playwright/browser

`cd web && pnpm run dev` starts vite on `:5173`. Caveat: `web/vite.config` hardcodes the `/api` proxy to `http://localhost:8000` — it will hit whatever is on :8000, **not** the verify instance on :8871. To aim the SPA at a verify run, either launch the verify API on port 8000 (`VERIFY_API_PORT=8000 verify.sh launch`, requires :8000 free) or drive the API directly over HTTP like the other features. Playwright MCP or `curl` against the SPA both count as driving; capture a screenshot of the post-login workspace, not just a 200 on `/`.

## Gotchas

- Serving the SPA's document while its `/api` calls land on a *different* (e.g. dev :8000) backend is a false proof — check the network tab hits the verify port.
- `WEB_BASE_URL`/`CORS_ORIGINS` in `api.env` point at the API itself; browser flows that mint links (invites, OAuth) will hand back `127.0.0.1:8871` URLs — expected in a verify run.
- TLS: vite serves self-signed `unhinted.localhost` certs (`scripts/dev-certs.sh` regenerates); plain `localhost:5173` also works.
- The static gates (`pnpm run lint`, `pnpm run build`, `pnpm test` under `web/`) are CI checks — they do not prove the running UI.
