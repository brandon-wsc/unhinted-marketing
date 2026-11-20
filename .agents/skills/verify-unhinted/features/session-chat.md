# Session chat

## Sub-features

- `POST /api/sessions/{id}/messages` `{content}` — runs a LangGraph turn; parks at the angle gate (`awaiting_angle_pick`, `brief.angles`) per ADR 0028
- `POST /api/sessions/{id}/choose-angle` `{angle_index}` — resumes the parked turn into drafting
- `GET /api/sessions/{id}/messages` — assistant reply + brief state persisted
- `GET /api/sessions/{id}/events` — SSE stream of the turn (live deltas; REST stays source of truth per ADR 0002)

## How to get to it (user POV)

The main chat box: type a marketing prompt, pick an angle card, watch the draft stream in.

## Driving it with curl

Not scripted — the session graph calls a real LLM. To drive it, export `OPENAI_API_KEY` (and any `LLM_*` overrides) **before** `verify.sh launch`; the keys pass through into `api.env`. Then, with `TOKEN`/`$sid` from a `session-workspace` drive:

```bash
curl -sS -X POST http://127.0.0.1:8871/api/sessions/$sid/messages \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content":"幫我寫個 IG post 推廣夏日凍檸茶"}'
```

Proof is the parked-turn state (`awaiting_angle_pick: true` + `brief.angles` non-empty in the messages response), then a `choose-angle` resume producing assistant draft messages — not merely a 200 on send.

## Gotchas

- Without an LLM key the message call fails server-side; there is no keyless stub for chat — only image gen has `LLM_IMAGE_MODEL=placeholder` mock mode.
- `initial_message` on `POST /api/sessions` also runs a turn — same key requirement.
- Stop/interrupt semantics (ADR 0004/0016/0035/0036) and image-park flows are separate journeys; a parked angle pick resumes via `choose-angle` or another typed message, never a blind retry.
- SSE (`/events`) is an enhancement layer — proof still comes from REST responses, not the stream alone.
