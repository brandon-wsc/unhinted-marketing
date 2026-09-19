# ADR 0028 — Angle pick parks before drafting

- **Status:** Superseded by [ADR 0029](./0029-angle-persona-bundled-gate.md) (persona on the same card); park `>= 2` superseded by [ADR 0030](./0030-image-format-in-bundled-gate.md) §7 (`>= 1`)
- **Date:** 2026-09-15
- **Supersedes:** — (adds a second `interrupt_before` park; does not change [ADR 0004](./0004-stop-discard-and-image-resume.md) Stop semantics)

## Context

`intent=start` ran `load_context → trend_searcher → product_matcher → brainstormer → executor_post` with no user input on direction. `brainstormer` already emits `brief.angles` (plural) but they were display-only (`brief.updated`); `executor_post` consumed the whole brief, so the agent picked signal, product, persona, and angle itself. ROADMAP's `chat → recommend → preview` loop had no recommend step inside the session.

## Decision

1. **Park after brainstorm:** New `angle_gate` node added to `interrupt_before`. `route_after_brainstormer` routes to it when `len(brief.angles) >= 2` — **including when `chosen_angle` is already set**. The gate, not this router, validates the pick (match vs feedback). Single-angle briefs go straight to `executor_post`. The park emits `draft.awaiting_angle_pick` (angles payload) and `session.state.awaiting_angle_pick` for hydrate — same contract as `awaiting_image_ok`.
2. **Pick is explicit:** `POST /sessions/{id}/choose-angle` with `{angle_index}` or `{angle}` text → `aupdate_state(chosen_angle)` → `ainvoke(None)`. A **typed message while parked at the angle gate is also a pick** (the only park where `POST /messages` resumes); parked at the image interrupt still returns 409 per ADR 0004.
3. **Non-matching text = feedback, not a pick:** `angle_gate` resolves the pick against offered angles (exact / 1-based index / 一二三四 / substring). No match → `chosen_angle=None`, `angle_feedback=text` → route back to `brainstormer` → fresh angles → parks again. This is the「都唔啱」loop; escape hatch is Stop.
4. **Match = lock:** matched pick → `executor_post` with `chosen_angle` in its payload; the node clears it in output so a later `start` re-offers.
5. **Stop / cancel reuse ADR 0004:** parked discard deletes the graph thread + restores pre-turn `session.state`; Stop mid `POST /choose-angle` re-parks at `angle_gate` (turn registry `kind="choose_angle"` + parked snapshot, mirroring `resume_image`). A provider error mid choose-angle re-parks the same way, so Retry resumes the failed pick instead of opening a new chat turn.
6. **No LLM in the gate:** `angle_gate` is a plain routing node — no `agent.progress`, no LLM call. `route_intent` is not consulted on resume turns.
7. **Queue holds while parked (ADR 0016 §5 applies to both gates):** queued sends were composed before the options existed — they must not drain into the gate, where the text would be read as a pick or `angle_feedback`. The queue drains once the session is unparked (pick accepted → turn proceeds, or Stop discards the park).

## Consequences

- Every `start` with ≥2 brainstormed angles now waits for the user — the missing "recommend" step exists as a real checkpoint, not a chat hint. — **Park count superseded by [ADR 0030](./0030-image-format-in-bundled-gate.md) §7** (`>= 1`).
- `interrupt_before` has two entries; any code asking "is it parked" must check **which** node is next (`snapshot.next`), not just non-empty.
- The pick card is the canonical affordance; free text is a convenience path. Both end at `chosen_angle` or `angle_feedback` — no third state.
- Re-offer loop is bounded by user action only; each cycle costs one brainstormer call.
- Confirm / publish remains ADR 0003; this ADR only adds a pre-draft decision point.
- Resume `aupdate_state({chosen_angle})` is attributed to `brainstormer` (last completed node) and re-fires that node's edges. The brainstormer router must still schedule `angle_gate`; short-circuiting to `executor_post` when `chosen_angle` is non-empty skips `resolve_angle_pick` and drafts Other/feedback text as a locked angle. `as_node="angle_gate"` alone is not a substitute — that treats the gate as already run.
