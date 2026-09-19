# ADR 0030 — Image format rides the bundled angle gate

- **Status:** Accepted
- **Date:** 2026-09-19
- **Supersedes:** [ADR 0029](./0029-angle-persona-bundled-gate.md) §4 park condition only (gate now parks at ≥1 angle; no single-angle fast path). Otherwise extends ADR 0029; does not change [ADR 0004](./0004-stop-discard-and-image-resume.md) image-park semantics.

## Context

The single-vs-comic pick (`image_format`: `single` | `comic_4panel`) is made at the **image park** (`awaiting_image_ok`, ADR 0004) — after `executor_post` has already drafted the caption and the reviewer loop has run. A 4-panel comic is a different creative: it needs a story arc (panels 1-3 situational pain with no product, panel 4 soft remedy — see `compose_generation_prompt` in `internal/session/image_format.py`). Picking the format after the draft means the comic's panel beats are reverse-engineered from a caption that was conceived for a single image, and the caption itself never gets the chance to complement a comic narrative.

[ADR 0029](./0029-angle-persona-bundled-gate.md) already established the bundled recommend card: one park after `brainstormer`, one submit answering angle + persona before drafting. Format is the same class of decision — it shapes the draft, so it belongs on that card, not at the image park.

## Decision

1. **Format rides the bundled card.** The `angle_gate` park payload (`draft.awaiting_angle_pick` + `session.state.awaiting_angle_pick`) gains `image_format_options` (`["single", "comic_4panel"]`) and `recommended_image_format` (sticky prior pick, else the current state value, default `single`). One `POST /sessions/{id}/choose-angle` submit answers angle + persona + format. Still no second `interrupt_before` entry.

2. **`POST /choose-angle` body extended.** `{angle_index | angle, persona?, image_format?}`. Omitting `image_format` keeps the current state value (default `single`). No new endpoint.

3. **Typed message = angle only.** Free text while parked still resolves against offered angles only (ADR 0028 §3). Format is changeable via the card field or via free-text format cues in a normal (non-parked) chat turn, where `edit_copy`'s `image_format_from_text` detection already applies — never via the parked typed reply, so angle copy and format words cannot collide in substring match.

4. **Sticky across the feedback loop.** A submitted format pick survives「都唔啱」re-brainstorm cycles (stored as `chosen_image_format`, mirroring `chosen_persona` in ADR 0029 §5); the re-offered card pre-selects it. Matched pick = lock: `angle_gate` resolves `chosen_image_format` → `image_format` and clears it, so a later `start` re-offers.

5. **`executor_post` drafts with the format known.** Its LLM payload gains `image_format`; the prompt directs comic drafts to complement a 4-panel arc (caption does not restate panel beats; product only soft-landed) and single-image drafts to keep current behaviour. `executor_image_plan` is unchanged — it already consumes `state.image_format`.

6. **Late switch retained, image-only.** The image-park toggle (`POST /resume-image` with `image_format`, ADR 0004) stays as an escape hatch, but it re-generates the image only — it does **not** re-run the draft. The UI labels it as such. `GET /sessions/{id}/messages` returns `recommended_image_format` at **both** parks (sticky `chosen_image_format`, else `state.image_format`, else `single`) so a reload at the image park does not default the toggle to `single` and silently late-switch a comic draft.

7. **No single-angle fast path.** `route_after_brainstormer` parks whenever `len(brief.angles) >= 1` — a lone angle still needs user confirm, and the format question always gets asked (supersedes [ADR 0029](./0029-angle-persona-bundled-gate.md) §4's `>= 2` condition). Only a 0-angle brief goes straight to `executor_post` (nothing to confirm). Because the gate always runs when there is anything to confirm, a sticky `chosen_image_format` can never be stranded by a 1-angle re-brief — it is resolved on the next matched pick.

8. **Unchanged boundaries.** No LLM in the gate; `route_intent` is not consulted on resume turns. Stop / cancel / re-park reuse [ADR 0004](./0004-stop-discard-and-image-resume.md) (`kind="choose_angle"`). Queue holds while parked per [ADR 0016](./0016-queue-send-while-turn-in-flight.md) §5. Confirm / publish remains [ADR 0003](./0003-confirm-without-llm.md). Resume `aupdate_state` is still attributed to `brainstormer`; the brainstormer router must still schedule `angle_gate` (same attribution trap as 0028/0029).

## Consequences

- Every `start` with ≥1 brainstormed angle now surfaces format as a first-class choice on the same card as angle + persona; the draft is written for the chosen format. A 0-angle brief still drafts immediately.
- FE renders one bundled card (angle options + persona select + format segmented control) instead of angle + persona only; typed-reply convenience path is unchanged and angle-only.
- `draft.awaiting_angle_pick` grows fields again; clients that ignore unknown keys keep working until they render format.
- A wrong early pick is recoverable two ways: re-`start`, or the late image-park toggle (image-only re-gen, caption untouched). Reload hydrates the toggle from `GET /messages` `recommended_image_format` at the image park — not from in-memory `lastImageFormatPick` alone.
- Re-offer loop cost is unchanged (one brainstormer call per cycle). `chosen_image_format` stickiness is the only new gate state to hydrate.
