# Confirm & publish

## Sub-features

- `POST /api/sessions/{id}/confirm` `{approval_token}` — the only publish path (ADR 0003); stub adapter returns a deterministic result, never Meta
- Invalid/missing `approval_token` → `400`; replay → idempotent
- Preview persist is a precondition — confirm on a session with no draft fails (e.g. `400 image_required` classes per `tests/api/test_confirm.py`)

## How to get to it (user POV)

The Confirm button on the Instagram-layout preview — a deliberate click, never a chat phrase.

## Driving it with curl

Not scripted end-to-end: reaching confirm needs a session that holds a draft + preview, which today means a real LLM turn (see `session-chat`). With keys passed through at launch, drive `session-chat` to a draft, read the `approval_token` from the preview payload, then:

```bash
curl -sS -X POST http://127.0.0.1:8871/api/sessions/$sid/confirm \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"approval_token\":\"$TOKEN_FROM_PREVIEW\"}"
```

`PUBLISH_ADAPTER=stub` is forced in `api.env` — the publish boundary is isolated by design, so a stubbed success is honest proof of the confirm path (validation, token, idempotency), not of Meta delivery. Check evidence for `session.status` flipping to confirmed and a second POST returning the idempotent response.

## Gotchas

- Chat text like「可以出」must never publish — a journey that "confirms" via `POST /messages` and sees a publish effect has found a hard-boundary bug (ADR 0003).
- Negative paths are cheap and keyless-ish where a draft exists: bad token → `400`; replay → idempotent. Cover them when you drive this.
- The Instagram adapter (`PUBLISH_ADAPTER=instagram`) + OAuth connect flow is out of scope — `tests/api/test_social_oauth.py` covers it with mocked Graph; live Meta stays unverified here.
