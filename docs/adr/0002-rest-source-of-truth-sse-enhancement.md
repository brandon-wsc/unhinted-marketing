# ADR 0002 — REST is source of truth; SSE is enhancement

- **Status:** Accepted
- **Date:** 2026-07-31
- **Supersedes:** —

## Context

Session turns stream assistant tokens and agent progress over SSE while `POST /sessions/{id}/messages` also returns the full transcript and turn events. Dual writers without a hierarchy cause UI drift after refresh or missed events.

## Decision

1. **REST is the client source of truth** for session transcript, mode, draft revision / token, and turn outcomes. `POST /messages` (and draft/confirm endpoints) return authoritative state.
2. **SSE is an enhancement layer** for live `message.delta`, `agent.progress`, and related events. Clients merge into the same state with **dedupe**.
3. After reconnect or missed SSE, clients rehydrate from REST / snapshot — they must not treat the stream as durable storage.
4. Event names and payload shapes are catalogued in `schemas/contracts.py` (`SessionEventType` + payload models).

## Consequences

- New live UX must still be reconstructible from REST (or snapshot) after refresh.
- Adding SSE fields without updating the contract catalog creates a parallel truth — avoid.
- Multi-worker SSE fan-out (e.g. Redis) remains a scaling concern; it does not change this SSOT rule.
