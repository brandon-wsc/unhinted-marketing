# ADR 0003 — Confirm / publish without LLM

- **Status:** Accepted
- **Date:** 2026-07-29
- **Supersedes:** —

## Context

LLM output is useful for draft iteration but unsafe as the publish gate (hallucinated “posted”, ambiguous chat intent, no idempotency). Platform APIs need deterministic validation and receipts.

## Decision

1. **Confirm is a traditional HTTP handler** — `POST /sessions/{id}/confirm` validates `approval_token`, calls the platform adapter (stub today), writes `tool_receipts`. **Zero LLM.**
2. LangGraph may surface `confirm_intent` / `ack_confirm` for UX (e.g. pending confirm), but **must not** call publish adapters.
3. Each preview revision mints an `approval_token`; Confirm requires the token for the revision being published.
4. Tool contract for publish: `PublishSocialPostRequest` / response in `schemas/tools.py` (adapter input), distinct from chat.

## Consequences

- Chat never publishes; product copy and FE must keep Confirm as the only publish control.
- Graph / prompt changes cannot “helpfully” add a publish tool inside the LLM zone without a superseding ADR.
- Idempotency keys live on Confirm, not on chat turns.
