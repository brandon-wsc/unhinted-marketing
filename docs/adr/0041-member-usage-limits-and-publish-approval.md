# ADR 0041 — Member platform-key usage limits and publish approval

## Status

Accepted

## Context

An org owner today can invite `admin` / `member` users ([ADR 0010](0010-org-membership-invites-and-shared-assets.md)), but there is no per-member governance: every member burns the shared platform LLM key without a cap, and every member can Confirm a publish directly ([ADR 0003](0003-confirm-without-llm.md)). For a real multi-user SME product, owners need two controls: a per-member spend cap on platform-key usage (junior staff shouldn't drain the platform quota), and an optional sign-off step before a member's post goes out (intern drafts need a manager's eyes first).

ADR 0020 deferred platform-key quotas; this ADR un-defers the member-scoped slice only. Org-wide quotas and BYOK quota accounting stay deferred.

## Decision

### 1. Per-member platform-key monthly token limit

- New nullable column `organization_members.monthly_token_limit` (integer). `NULL` = unlimited, so existing members and fresh installs are unaffected. Settable by `owner` / `admin` via the member-management `PATCH`.
- The cap counts **platform-key spend only**: sum `llm_call_records.total_tokens` for `user_id` + `company_id` where `key_source = 'env'` ([ADR 0020](0020-org-byok-keys-models-routing.md)). Org BYOK calls (`key_source = 'org'`) do not count — BYOK spend is the org's own bill. Image-generation calls count when the provider reports usage (gpt-image and Gemini image do; flat-priced image APIs that return no `usage` contribute `NULL` and are unmetered by design — a provider limitation, not a second billing model).
- Period is the current UTC calendar month: `[first-of-month 00:00Z, first-of-next-month 00:00Z)`. The usage meter returns `period_start` / `period_end` so the UI can show the window.
- Enforcement lives at every turn/generation boundary — `POST /api/sessions/{id}/messages`, the `initial_message` path on session create, `POST .../choose-angle`, `POST .../resume-image`, and `POST .../media/{image_id}/regen` — **before** the turn or image generation runs. If the caller's org role in the session's company is `member` and a limit is set and `used >= limit`, the route returns `403` with a structured detail (`usage_limit_exceeded`, `limit`, `used`, `period_end`) defined in `schemas/`.
- It is deliberately **not** enforced inside the LLM router or graph nodes: `llm_call_records` flush asynchronously after the call ([ADR 0020](0020-org-byok-keys-models-routing.md)), so in-flight calls can overshoot the cap slightly. That lag is accepted; it is a budget guardrail, not a hard rate limiter.
- `owner` / `admin` roles are never capped by this column; the limit is only evaluated for `member`.
- Newly accepted member invites seed `monthly_token_limit` from `MEMBER_DEFAULT_MONTHLY_TOKEN_LIMIT` (unset = `NULL`). The default applies to `member` invites only, not `admin` or the bootstrap `owner`.
- The usage meter is `GET /api/companies/{id}/usage` (self) and the member list carries per-member `monthly_token_limit` + current-month `used_tokens`.

### 2. Member publish approval (opt-in org policy)

- Org policy `member_publish_requires_approval` stored on `entities.profile` JSONB — same place voice settings live — read via `GET`/`PATCH /api/companies/{id}/governance`. Default **off** when the key is absent; existing installs publish directly as today.
- When the policy is on and the confirming user's org role is `member`, `POST /sessions/{id}/confirm` does **not** call the publish adapter. It parks the request as a `tool_receipts` row with `status = 'pending_approval'`, `tool_name = 'publish_social_post'`, the member's `user_id`, and the member's original `idempotency_key`. The receipt `request` carries the execution payload: `approval_token`, `platform`, `revision`, plus a render/execution snapshot (`copy`, `media_ids`, `image_url`).
- Reusing `tool_receipts` (vs a new table) keeps the existing idempotency-key machinery intact: a repeat Confirm with the same key hits the existing-receipt replay path and returns the parked row — no double-queue, no schema for a second request journal. Alternative considered: a dedicated `publish_approvals` table pointing at drafts. Rejected because it duplicates the receipt lifecycle (created → resolved) and the idempotency dedupe that Confirm already guarantees.
- Parking **supersedes** older `pending_approval` receipts for the same session (`status → 'superseded'`): only the latest parked revision sits in the queue, so an approver can't publish a stale revision the member already replaced.
- The parked `approval_token` is the draft's existing token; approval **executes that token** — it does not mint a fresh one and does not bypass token validation ([ADR 0003](0003-confirm-without-llm.md)). Draft rows are append-only ([ADR 0008](0008-preview-images-append-only.md)), so the parked revision stays resolvable.
- Approvals are traditional HTTP, same plane as the product-proposal queue ([ADR 0011](0011-knowledge-commit-without-llm.md)) — owner/admin of the org only (`organization_members.role`; `platform_level` is not consulted):
  - `GET /api/companies/{id}/publish-approvals` — the queue. Sessions are user-scoped, so approvers cannot open the member's session; the list payload carries everything needed to render the card: requester identity, platform, revision, draft `copy`, resolved `media` / `image_url`, `idempotency_key`, `created_at`.
  - `POST .../{receipt_id}/approve` — runs the **same** publish execution path as Confirm (same `publish_social_post` adapter call, same request build, same receipt write). The original `tool_receipts` row is updated in place to the adapter outcome (`published` / `stubbed` / `failed`); `user_id` and `idempotency_key` never change. The row is taken `FOR UPDATE`, so two approvers can't double-execute; a repeat approve on a terminal receipt returns the existing row idempotently.
  - `POST .../{receipt_id}/reject` — sets `status = 'rejected'` with reviewer + timestamp in `response`, publishes `confirm.completed` so the member's open session sees it, and leaves the member free to edit and Confirm again (which parks a fresh request).
- Success statuses stay `{published, stubbed}` ([ADR 0022](0022-real-publish-instagram.md)); `pending_approval` / `rejected` / `superseded` are queue lifecycle states the UI renders as parked/rejected, never as published.

## Consequences

- Owners get a spend cap and a publish gate for junior accounts without changing anything for orgs that don't opt in.
- A member over their cap can still read sessions and review drafts — only turn dispatch is gated.
- The queue is org-scoped and cross-org access 403s; approvers never open member sessions.
- Publish still executes only via HTTP — never from graph nodes or chat phrases.
- Slight overshoot of the token cap is possible because recorder writes lag in-flight calls; documented and accepted.
