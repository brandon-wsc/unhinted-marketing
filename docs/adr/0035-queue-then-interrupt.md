# ADR 0035 — Empty Enter interrupts a queued in-flight turn

- **Status:** Accepted
- **Date:** 2026-09-22
- **Supersedes:** — (extends [ADR 0016](./0016-queue-send-while-turn-in-flight.md) §1–2; does not change park Send)

## Context

ADR 0016 lets the user enqueue the next instruction while a turn is in flight. Stop stays a separate control: it discards the running turn and then drains the queue. There was no keyboard path to do that Stop-then-drain on purpose. An empty Enter did nothing, so the only way to run the queue now was the Stop button.

The intended gesture matches a queue-first interrupt: the first Enter (with text) still queues; Enter again on an empty composer interrupts. But interrupting means *redirect*, not *erase* — Cursor (`Stop & send`), Codex (Esc → `turn_aborted`), and Devin all keep the running turn's messages and append the next instruction as a new message. Discarding would make the gesture look like it rewrote the message being worked on, and drops context the model should still see. The Stop button's discard ([ADR 0004](./0004-stop-discard-and-image-resume.md)) stays — it is the deliberate "bin this take" escape hatch.

## Decision

1. **Text Enter while in flight still queues** (ADR 0016 §1). It does not Stop and does not `POST /messages`.
2. **Empty Enter interrupts only when the queue is non-empty and a turn is in flight.** Composer trim is empty, the user is not editing a queued row, and the session is not parked at image OK or the angle pick. That Enter calls `POST /stop` with `mode: "interrupt"`, then the existing drain sends the queue head.
3. **Empty Enter with an empty queue is a no-op.** It must not Stop.
4. **Parked gates are unchanged.** Image-park Send still enqueues and must not Stop ([ADR 0031](./0031-queue-send-while-image-parked.md)). Angle-park Send stays a typed pick ([ADR 0028](./0028-angle-pick-before-draft.md)). Empty Enter at either park does not interrupt.
5. **`POST /api/sessions/{id}/stop` accepts `{"mode": "discard" | "interrupt"}`** — default `discard`, so the Stop button and existing clients are unchanged. `mode: "interrupt"` **keeps the turn**: the task is cancelled, but the turn's messages stay in the transcript, assistant output that completed graph nodes produced is persisted, and the turn's user message is marked `metadata.interrupted = true`. `session.state` is not restored — it is only written at end-of-turn, so it already holds pre-turn values. The graph thread is still deleted: the next turn rebuilds context from the DB transcript, so the model sees the interrupted exchange.
6. **Interrupt applies to in-flight `message` turns only.** Parked sessions, `resume_image`, and `choose_angle` turns keep their existing discard / re-park semantics regardless of `mode` (ADR 0004 / 0028 / 0031).
7. **`turn.cancelled` gains `kept: true`** on interrupt cancels. Clients must not prune the turn's messages for that event; `kept` absent/false keeps the discard prune.
8. **Mid-node streamed tokens are not persisted.** What survives is what completed nodes appended to `values["messages"]` — the same boundary Codex draws.
9. **No new backend route.** Interrupt is Stop (interrupt mode) plus drain. Shift+Enter stays newline; IME composition still does not submit.

## Consequences

- Transcript after interrupt: user message (+ any completed-node assistant replies) → queued message → new turn. Nothing is rewritten or hidden.
- Discard remains the deliberate escape hatch: one click on Stop still wipes a wrong-direction take.
- Backend still enforces one turn per session — interrupt cancels first, then the queued message starts a fresh turn with full transcript context.
- Stop button behavior is unchanged, including drain after unlock when the session is not re-parked.
- The hint is copy only (`chat.queue.interrupt`); no second button.
- Queue remains SPA-only and is still lost on refresh (ADR 0016 §3).
