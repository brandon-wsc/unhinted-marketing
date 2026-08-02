# ADR 0004 — Stop discards turn; image resume is explicit

- **Status:** Accepted
- **Date:** 2026-08-02
- **Supersedes:** — (closes STATUS H2: blind `ainvoke(None)` on any `POST /messages`)

## Context

While the graph runs, overlapping `POST /messages` and “resume image by typing” were unsafe: in-flight work ignored Stop, and any message while parked at `interrupt_before=["executor_image_plan"]` blindly resumed image generation (`ainvoke(None)`), so user text could not cancel or redirect.

## Decision

1. **Composer lock (product):** While a turn is in-flight **or** the session is parked awaiting image OK, the chat composer (input + Send) is locked. The primary control becomes **Stop**.
2. **Stop = discard this turn:** Do not keep partial graph progress. Restore `sessions.state` to the pre-turn snapshot, delete messages created by that turn, and `adelete_thread` on the LangGraph checkpointer. After unlock, the next Send is a **new** message.
3. **Backend participates:** Per-session in-memory turn registry holds the running `asyncio.Task`. `POST /sessions/{id}/stop` cancels the task (in-flight) or discards parked state. Concurrent `POST /messages` while busy or parked returns **409**.
4. **Image resume is explicit:** Only `POST /sessions/{id}/resume-image` may `ainvoke(None)` when parked. Normal `POST /messages` never blind-resumes.
5. **SSE:** Publish `turn.cancelled` after a successful discard so other tabs can unlock.

## Consequences

- InterruptCard “Generate image” must call `resume-image`, not a canned chat message.
- Checkpointer writes are separate from the app DB session; discard must explicitly `adelete_thread` (rolling back the HTTP transaction alone is insufficient).
- Mid-node cancel is best-effort (possible orphan LLM cost / MinIO objects); no partial resume.
- Turn registry is **single-process** (same class of limit as the in-memory SSE bus); multi-worker stop requires a later shared store.
- Confirm / publish remains ADR 0003 (Stop never publishes).
