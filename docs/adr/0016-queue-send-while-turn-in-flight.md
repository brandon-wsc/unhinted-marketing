# ADR 0016 — Queue send while a turn is in flight

- **Status:** Accepted (§6 superseded by [ADR 0031](./0031-queue-send-while-image-parked.md), then by [ADR 0036](./0036-image-direction-new-script.md); image-park drain hold in §5 superseded by ADR 0036; empty-Enter interrupt: [ADR 0035](./0035-queue-then-interrupt.md))
- **Date:** 2026-08-19
- **Supersedes:** [ADR 0004](./0004-stop-discard-and-image-resume.md) §1 (composer lock while in-flight)

## Context

ADR 0004 locked the chat composer while a graph turn ran, replacing Send with Stop. That prevented overlapping `POST /messages` (409 busy) but left the UI idle: users could not draft the next instruction until the current LLM turn finished.

Cursor / Codex let the user type and Send without interrupting the running agent; extra Sends wait in a local queue.

## Decision

1. **Composer stays open while a turn is in flight.** Textarea and Send remain usable. Send does **not** call `POST /messages` and does **not** Stop. It enqueues the text (FIFO, max 3) in the SPA. **Empty Enter** while that queue is non-empty is Stop, then drain ([ADR 0035](./0035-queue-then-interrupt.md)); empty Enter with an empty queue does nothing.
2. **Stop is beside Send**, not a replacement. Stop still discards only the **running** turn (ADR 0004 §2–6). Stop does **not** clear the queue. After Stop unlocks (and the session is not parked at image OK or the angle pick), the client drains the queue.
3. **Queue lives on the frontend only.** No pending-messages table. Lost on **refresh**. **Session switch** save/restores that session’s queue **and** composer textarea (SPA memory, including mid-edit of a queued row). Another tab that `POST`s while busy still gets **409**. Queue chrome sits **on the composer card** (Codex desktop: list above the textarea), not as transcript bubbles. Rows can be deleted or popped back into the input to edit (re-insert at the same index).
4. **Leave ≠ Stop.** Switching session (or New chat) does **not** cancel the left session’s server turn. Client apply is bound to session id: in-flight REST/SSE from A must not paint B. `sending` / Stop / agent trail belong only to the session on screen. Returning to A while its POST is still open restores `sending`.
5. **Drain when idle:** `!sending && !stopping && !awaiting_angle_pick` **for the current session**. ~~Also hold while `awaiting_image_ok`.~~ **Image-park hold superseded by [ADR 0036](./0036-image-direction-new-script.md):** a queued line drains as a direction-change turn (new script + plan), not after Execute. The angle pick still holds the queue — do not auto-`stopTurn` a parked angle card. ([ADR 0028](./0028-angle-pick-before-draft.md) §7.)
6. **Parked + explicit Send** (composer, not drain) ~~keeps today’s path: `stopTurn` then a new message.~~ **Superseded by [ADR 0036](./0036-image-direction-new-script.md)** (which superseded [ADR 0031](./0031-queue-send-while-image-parked.md)): image park + Send is a new script + plan and re-parks (no `stopTurn`, no blind image resume). Angle park + Send is still a typed pick ([ADR 0028](./0028-angle-pick-before-draft.md) §3). Image resume remains `POST /resume-image` only ([ADR 0004](./0004-stop-discard-and-image-resume.md) §4).

## Consequences

- Backend busy/parked 409 is unchanged (safety net, multi-tab / other device). Same-tab leave-and-return uses the in-flight map + REST hydrate; `GET /messages` still has no `busy` flag.
- Optimistic queued items (`local-q-*`) and the textarea draft are client-only until drain runs a normal send.
- `composerLocked` is only Stop-in-flight (`stopping`), not `sending`.
