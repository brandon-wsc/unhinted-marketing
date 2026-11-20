# Session workspace

## Sub-features

- `POST /api/sessions` `{company_id}` — creates an empty session (`201`), no `initial_message` → no LLM turn
- `GET /api/sessions` — the new session appears in the list
- `PATCH /api/sessions/{id}` — rename + pin (`title`, `pinned`)
- `GET /api/sessions/{id}/messages` — `{session, messages[], brief, awaiting_*}` shape
- `DELETE /api/sessions/{id}` — `204`, gone from the next list

## How to get to it (user POV)

The signed-in workspace sidebar: new chat, rename/pin in history, open the transcript, delete. All reachable without the LLM — the graph only runs when a message is sent.

## Driving it with curl/verify.sh

```bash
.agents/skills/verify-unhinted/scripts/verify.sh drive first-run-setup   # once per run
.agents/skills/verify-unhinted/scripts/verify.sh drive session-workspace
```

Reads `state/auth.json` (token refreshed first — access tokens live ~15 min). Evidence: `evidence/<run-id>/session-workspace/01..06-*.json`; proof is the session round-trip — create `201` → present in list → patch applies → delete `204` → absent.

## Gotchas

- `POST /api/sessions` with `initial_message` triggers `run_session_turn` → needs the LLM; keep it out of this keyless drive (that's `session-chat`).
- `state/auth.json` is per-run; after `cleanup` it is gone — re-drive `first-run-setup` on the next launch.
- Other users' sessions must 403 (`_require_owned_session`); cross-user isolation is a different journey and would need a second account via the invite flow — not scripted.
