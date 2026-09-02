# Real Publish (Instagram) — Plan

Status: **backend + SPA shipped (2026-09-02)**; live Instagram acceptance is still
manual — see [ADR 0022](./adr/0022-real-publish-instagram.md) + STATUS entry. This
document is the working design; the ADR is the durable record.

Scope: upgrade `POST /api/sessions/{id}/confirm` from the stub adapter to a real
Instagram publish via Meta Graph API — org-scoped credentials in PostgreSQL, a
feature-flagged adapter, a receipt status machine, and the frontend receipt panel.
Zero LLM anywhere on the path ([ADR 0003](./adr/0003-confirm-without-llm.md)).

---

## 1. Current-state review

| Piece | File | Notes |
|-------|------|-------|
| Confirm handler | `cmd/api/routes/sessions.py` `confirm_session` | Validates `approval_token`, user/session-scoped idempotency, copy-only `400 image_required`; dispatches `internal/tools/publish.py`; writes `tool_receipts` (`stubbed` / `published` / `failed`); `session.status="confirmed"` only on success; SSE `confirm.completed` carries `permalink` / `error_kind` |
| Receipt store | `internal/memory/models.py` `ToolReceipt` | `status String(40)` + `request` / `response` JSONB — **no migration needed**; permalink / post id / error go into `response` |
| Tool contracts | `schemas/tools.py` | `PublishSocialPostRequest` / `PublishSocialPostResponse` already locked; request already carries `image_url` |
| REST contracts | `schemas/session.py` | `ConfirmSessionRequest` / `ConfirmSessionResponse` |
| SSE catalog | `schemas/contracts.py` | `ConfirmCompletedData` mapped in `EVENT_PAYLOAD_MODELS` |
| TS mirrors | `web/src/features/session/generated/` | Generated from `schemas/` via `scripts/typescript_gen` — never hand-edit |
| FE consumers | `web/src/features/session/use-session.ts`, `components/preview-panel.tsx` | `confirmPost` + `confirm.completed` / snapshot hydrate; published / failed / stubbed receipts |
| Crypto precedent | `internal/llm/keys.py` | Fernet under `BYOK_ENCRYPTION_KEY`; `encrypt_key` / `decrypt_key` / `mask_key` reused as-is |
| CLI precedent | `cmd/worker/main.py` `set-platform-role` | Bootstrap-only admin command pattern |

### Still open

Live Instagram acceptance (public HTTPS image + `PUBLISH_ADAPTER=instagram`) stays manual — not CI.

Backend + SPA from the original review (credential store, adapter seam, status vocabulary, copy-only 400, receipt panel, settings tab) are shipped.

---

## 2. Credential storage — `social_accounts`

One Alembic hex revision (`alembic revision -m "social_accounts"`). Mirrors the
`byok_providers` shape ([ADR 0020](./adr/0020-org-byok-keys-models-routing.md)):

```python
class SocialAccount(Base):
    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "platform", name="uq_social_accounts_company_platform"),
        CheckConstraint("platform IN ('instagram')", name="ck_social_accounts_platform"),
    )

    id: Mapped[uuid.UUID]               # PK, uuid4
    company_id: Mapped[uuid.UUID]       # FK entities.id ON DELETE CASCADE, indexed
    platform: Mapped[str]               # String(32) — 'instagram'
    ig_user_id: Mapped[str]             # String(64) — IG professional account id
    access_token_encrypted: Mapped[str] # Text — Fernet under BYOK_ENCRYPTION_KEY
    token_last4: Mapped[str]            # String(4)
    expires_at: Mapped[datetime | None] # long-lived token expiry; handled manually
    last_verified_at: Mapped[datetime | None]
    last_error_kind: Mapped[str | None] # String(40)
    created_by: Mapped[uuid.UUID | None] # FK users.id ON DELETE SET NULL
    created_at / updated_at             # server_default now()
```

- **One account per company per platform** (unique constraint). Multi-account is a
  follow-up; the constraint relaxes cleanly later.
- Raw tokens are never logged and never serialized — `token_last4` only, same posture
  as BYOK keys.
- Seeding is CLI-only, following `set-platform-role`:

```bash
python -m cmd.worker connect-social-account \
  --company <company-uuid> --platform instagram \
  --ig-user-id <id> --token <long-lived-token> [--expires-at 2026-10-30]
```

The command upserts on `(company_id, platform)` so token rotation is re-running the
same command. Encryption happens in the command via `internal/llm/keys.py`.

**Product UX (Penpot, 2026-09-02):** editor-only Company settings tab
`/settings?tab=instagram` — empty / connected / expired. Manual paste, not OAuth.
CLI remains the bootstrap fallback. See [knowledge/UI.md](./knowledge/UI.md).

**Explicitly not in this slice:** OAuth connect flow, token auto-refresh scheduler
(long-lived tokens last ~60 days), multi-platform abstraction, webhooks.

---

## 3. Adapter layer + feature flag

New module `internal/tools/publish.py`:

```python
async def publish_social_post(
    db: AsyncSession, req: PublishSocialPostRequest
) -> PublishSocialPostResponse: ...
```

- Dispatches on env `PUBLISH_ADAPTER=stub|instagram` (default `stub`) —
  CI / dev / unit tests never reach Meta.
- `stub` preserves today's exact behavior and `status="stubbed"` wording — existing
  UI and tests stay green untouched. **Locked in Q&A:** keep `stubbed`; do not unify
  to `published` + `platform="stub"`.
- The Instagram path loads the org's `social_accounts` row, decrypts via
  `decrypt_key`, and runs the Graph two-phase publish:
  1. `POST /{ig-user-id}/media` — container with `image_url` + `caption`
     (caption = canonical draft `caption` + hashtags + cta, composed deterministically).
  2. `POST /{ig-user-id}/media_publish` — returns the media id; permalink fetched or
     derived per Graph response.
- Error taxonomy maps to `error_kind`: `token_expired` | `permission` |
  `platform_error` (incl. 5xx / timeout). No inline auto-retry — the user-private
  `idempotency_key` already makes a retried Confirm safe.

## 4. Media public URL

- Publish image = draft's first `media_ids` entry; the handler resolves it to a public
  URL via `S3_PUBLIC_BASE_URL` and fills `PublishSocialPostRequest.image_url`.
- Local MinIO is unreachable by Meta — live verification needs a tunnel or real S3.
  Unit tests mock httpx; this constraint is documented, not coded around.
- Multi-image carousels deferred (IG supports `CAROUSEL` containers; separate slice).

---

## 5. Protocol (frontend ↔ backend)

All new fields are optional / defaulted — old clients ignore them (ADR 0002
forward-compatibility convention).

### REST — `POST /api/sessions/{id}/confirm`

`ConfirmSessionResponse` (`schemas/session.py`):

```python
class ConfirmSessionResponse(BaseModel):
    receipt_id: uuid.UUID
    status: str                    # "stubbed" | "published" | "failed"
    tool_name: str
    idempotency_key: str
    permalink: str | None = None   # published only
    error_kind: str | None = None  # failed only
```

Error responses (existing plain-string `detail` style):

| Case | HTTP | detail |
|------|------|--------|
| Wrong `approval_token` | 400 | `Invalid approval_token for session` (unchanged) |
| Foreign idempotency key | 409 | `Idempotency key already used` (unchanged) |
| Copy-only draft | 400 | `image_required` |
| Org has no IG account | 400 | `social_account_not_connected` |

**`session.status` semantics (locked in Q&A):** set to `"confirmed"` only on
`stubbed` / `published`. On `failed` the session stays untouched so the user can fix
(image, account) and retry with a fresh idempotency key.

### Tool contract — `schemas/tools.py`

`PublishSocialPostResponse` gains `permalink: str | None = None` and
`error_kind: str | None = None`; `platform` is `"stub"` from the stub adapter and
`"instagram"` from the real one. Request shape unchanged.

### SSE — `confirm.completed` (`schemas/contracts.py` `ConfirmCompletedData`)

```python
class ConfirmCompletedData(BaseModel):
    receipt_id: str
    status: str = "stubbed"        # stubbed | published | failed
    tool_name: str = "publish_social_post"
    idempotency_key: str = ""
    permalink: str | None = None
    error_kind: str | None = None
```

Session snapshot hydrate assembles `confirmReceipt` from the latest `tool_receipts`
row (`status` + `response.permalink` / `response.error_kind`) — same source as REST.

### TS mirrors (generated, never hand-edited)

1. Edit the Pydantic sources above.
2. `python -m scripts.export_contracts` → OpenAPI + `docs/contracts/publish-social-post-response.schema.json`.
3. `cd scripts/typescript_gen && npm run generate` → `generated/publish-social-post-response.ts` + `api.ts`.
4. Consumers: `use-session.ts` (`confirmPost`, `confirm.completed` handler, snapshot
   restore) and `preview-panel.tsx` receipt block, matching Penpot frames
   (`Session · split|paged · published` / `failed`; Library `Receipt / *`):
   - `published` → success panel + 「喺 Instagram 睇」 permalink
   - `failed` → error panel + 「再確認」 (session stays unconfirmed) + retry hint
   - `stubbed` → unchanged success panel, 「回執：stubbed」
   - copy-only → Confirm disabled, hint 「Instagram 出帖要有圖」 (`ConfirmGate / image-required`)

---

## 6. Security posture

- Confirm stays HTTP-only, zero LLM ([ADR 0003](./adr/0003-confirm-without-llm.md));
  publish is never registered as an in-loop tool.
- Per-revision `approval_token` gate unchanged; user/session-scoped idempotency
  unchanged (IDOR protection from hardening I1).
- Tokens at rest are Fernet-encrypted; production already refuses to boot without
  `BYOK_ENCRYPTION_KEY`.
- New env: `PUBLISH_ADAPTER` (default `stub`), `META_GRAPH_API_VERSION` (pinned).

---

## 7. Testing

- **Unit (mock httpx):** two-phase success, token expired, permission denied,
  platform 5xx / timeout, non-http image → `platform_error`, no-account
  `PublishPreconditionError` (`tests/unit/test_publish.py`). Copy-only 400, no-account
  400, idempotent replay, and failed confirm leaving `session.status` untouched are
  API tests (`tests/api/test_confirm.py`).
- **API integration (tests/api):** stub adapter stays green; social-account CRUD never
  leaks the raw token (`tests/api/test_company_social.py`).
- **Contracts:** `export_contracts` output committed; schema tests in
  `tests/unit/test_schemas_session.py` / `test_schemas_contracts.py` / `test_schemas_social.py`.
- **Live acceptance (manual, not CI):** curl flow question → draft → image → confirm
  → real IG post + permalink in receipt. Requires tunnel/real S3 for media.

---

## 8. PR slicing

1. `docs(adr)` — ADR 0022 + STATUS (**done**: `docs/real-publish-adr`)
2. `feat(db)` — `social_accounts` migration + model + repos + `connect-social-account` CLI (**done**)
3. `feat(publish)` — `internal/tools/publish.py` seam + stub move + `PUBLISH_ADAPTER` flag (**done**)
4. `feat(publish)` — Instagram adapter + handler wiring + status machine + copy-only 400 (**done**)
5. `feat(web)` — receipt panel: permalink / failure reason / retry hint; settings Instagram tab (**this slice**)
6. `test(publish)` — mock adapter coverage + contracts regen (**done**); live acceptance still manual

## 9. Deferred (explicit non-goals)

- OAuth connect flow; token auto-refresh
- Facebook / Threads platforms; multi-account per platform; platform switcher
- Multi-image carousels
- Per-day publish rate limits (ROADMAP Safety — separate slice)
- Container-status polling worker for mid-flow failures
