# ADR 0016 — Queue send while a turn is in flight

- **Status:** Accepted
- **Date:** 2026-08-19
- **Supersedes:** [ADR 0004](./0004-stop-discard-and-image-resume.md) §1 (composer lock while in-flight)

## Context

ADR 0004 locked the chat composer while a graph turn ran, replacing Send with Stop. That prevented overlapping `POST /messages` (409 busy) but left the UI idle: users could not draft the next instruction until the current LLM turn finished.

Cursor / Codex let the user type and Send without interrupting the running agent; extra Sends wait in a local queue.

## Decision

1. **Composer stays open while a turn is in flight.** Textarea and Send remain usable. Send does **not** call `POST /messages` and does **not** Stop. It enqueues the text (FIFO, max 3) in the SPA.
2. **Stop is beside Send**, not a replacement. Stop still discards only the **running** turn (ADR 0004 §2–6). Stop does **not** clear the queue. After Stop unlocks (and the session is not parked at image OK), the client drains the queue.
3. **Queue lives on the frontend only.** No pending-messages table. Lost on refresh / session switch. Another tab that `POST`s while busy still gets **409**. Queue chrome sits **on the composer card** (Codex desktop: list above the textarea), not as transcript bubbles. Rows can be deleted or popped back into the input to edit (re-insert at the same index).
4. **Drain when idle:** `!sending && !stopping && !awaiting_image_ok`. If the current turn parks at Generate-image, hold the queue and show that the user must pick a format / Stop first — do not auto-`stopTurn` a parked draft.
5. **Parked + explicit Send** (composer, not drain) keeps today’s path: `stopTurn` then a new message. Image resume remains `POST /resume-image` only (ADR 0004 §4).

## Consequences

- Backend busy/parked 409 is unchanged (safety net, multi-tab).
- Optimistic queued items (`local-q-*`) are client-only until drain runs a normal send.
- `composerLocked` is only Stop-in-flight (`stopping`), not `sending`.
