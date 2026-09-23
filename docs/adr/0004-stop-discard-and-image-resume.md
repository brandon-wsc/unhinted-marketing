# ADR 0004 — Stop discards turn; image resume is explicit

- **Status:** Accepted (§1 composer lock superseded by [ADR 0016](./0016-queue-send-while-turn-in-flight.md); image-park node and image-parked Send superseded by [ADR 0036](./0036-image-direction-new-script.md))
- **Date:** 2026-08-02
- **Supersedes:** — (closes STATUS H2: blind `ainvoke(None)` on any `POST /messages`)

## Context

While the graph runs, overlapping `POST /messages` and “resume image by typing” were unsafe: in-flight work ignored Stop, and any message while parked at `interrupt_before=["executor_image_plan"]` blindly resumed image generation (`ainvoke(None)`), so user text could not cancel or redirect.

## Decision

1. **Composer lock (product):** ~~While a turn is in-flight **or** the session is parked awaiting image OK, the chat composer (input + Send) is locked. The primary control becomes **Stop**.~~ **Superseded by [ADR 0016](./0016-queue-send-while-turn-in-flight.md):** in-flight typing/Send queues locally; Stop stays available beside Send. Parked image OK still must not blind-resume via `POST /messages`.
2. **Stop = discard this turn:** Do not keep partial graph progress. Restore `sessions.state` to the pre-turn snapshot, delete messages created by that turn, and `adelete_thread` on the LangGraph checkpointer. After unlock, the next Send is a **new** message. **Exception:** Stop mid `POST /resume-image` cancels the image run and **re-parks** at the image interrupt (`awaiting_image_ok` / Generate-image CTA returns); only Stop while already parked (no in-flight) discards the whole agent turn.
3. **Backend participates:** Per-session in-memory turn registry holds the running `asyncio.Task`. `POST /sessions/{id}/stop` cancels the task (in-flight) or discards parked state. Concurrent `POST /messages` while busy ~~or **image-parked**~~ returns **409**. **Image-parked Send is a new script ([ADR 0036](./0036-image-direction-new-script.md)), not 409.** Parked at `angle_gate` is a typed pick ([ADR 0028](./0028-angle-pick-before-draft.md)).
4. **Image resume is explicit:** Only `POST /sessions/{id}/resume-image` may `ainvoke(None)` when parked at ~~`executor_image_plan`~~ `executor_image_gen` ([ADR 0036](./0036-image-direction-new-script.md)). Normal `POST /messages` never blind-resumes the image interrupt.
5. **SSE:** Publish `turn.cancelled` after Stop. Payload includes `awaiting_image_ok` so clients know whether to unlock fully or keep the Generate-image CTA.
6. **LLM cancel path (implementation):** Session chat and JSON completions (`astream_text` / `complete_json`) use LiteLLM **streaming** and always **`aclose`** the upstream stream on exit — including `asyncio.CancelledError` from Stop — so mid-node cancel can abort provider generation best-effort. Image generation remains non-stream; rely on parked CTA to avoid kickoff.

## Consequences

- InterruptCard “Generate image” must call `resume-image`, not a canned chat message.
- Checkpointer writes are separate from the app DB session; discard must explicitly `adelete_thread` (rolling back the HTTP transaction alone is insufficient).
- Mid-node cancel: streaming + `aclose` improves odds of stopping further tokens; **already-generated tokens / image jobs may still bill**. No partial resume of discarded turns.
- Turn registry is **single-process** (same class of limit as the in-memory SSE bus); multi-worker stop requires a later shared store.
- Confirm / publish remains ADR 0003 (Stop never publishes).

## UI note — parked preview is not a ready post

Presentation only. Park / resume / Stop / Discard restore are unchanged here.

When the preview pane is open, the session is parked at image OK (`awaiting_image_ok`), and the current revision has no ready primary image, the pane is a **待出圖** board: pending caption, plan summary (format, prompt, panel beats), and the status line 「格式已經鎖死。可以棄置，或者出圖。想轉格式要先寫過一篇稿。」 Apply / 確認出街 stay in the footer and are disabled. The pane does not use the Instagram frame or the grey 「圖片位置」 placeholder. While Execute (`POST /resume-image`, client `sending` while still parked) is in flight, the same pane shows a spinner and 「出緊圖…」 and still does not look ready. Discard | 出圖 stay on the chat card.

A revision that already has a renderable primary image keeps today's accepted preview (real image, Apply / 確認出街 usable), including after Discard restores that revision and leaves the pane open.

ADR 0036 is not on `main` yet (it lands with the image-direction work, PR #87). On `main` the first image park still happens before a preview row exists, so this board shows once a pending revision with no image is on screen. Full Discard-restores-last-accepted behavior depends on #87; this note will need a reconcile where both change preview chrome.
