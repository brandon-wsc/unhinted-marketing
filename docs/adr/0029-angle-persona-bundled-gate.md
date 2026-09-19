# ADR 0029 — Bundled angle + persona gate

- **Status:** Accepted
- **Date:** 2026-09-19
- **Supersedes:** [ADR 0028](./0028-angle-pick-before-draft.md) (park still fires after brainstorm; the card now answers two fields in one submit)

## Context

[ADR 0028](./0028-angle-pick-before-draft.md) parked after `brainstormer` so the user picks a direction before `executor_post` drafts. That closed the missing "recommend" step for **angles**. Persona stayed unattended: `brainstormer` still writes `brief.persona` and `pick_active_persona` locks `active_persona` before the park. Users who care about voice / persona only discover the choice after the draft exists.

ROADMAP's `chat → recommend → preview` loop still wants a single recommend checkpoint, not a second park. Sequential "answer angle, then answer persona" would add a park, a resume kind, and another Stop/re-park surface. Chat-layer soft clarify (`ask_clarify` / `product_clarify`) already covers ad-hoc questions in prose; it is not a structured pick.

## Decision

1. **Bundled card, single park.** The `angle_gate` park (`draft.awaiting_angle_pick` + `session.state.awaiting_angle_pick`) stays the one recommend interrupt. Payload gains persona options: `personas` (org audience catalog) + `recommended_persona` (agent's `brief.persona`, pre-selected). One submit answers both. No second `interrupt_before` entry.

2. **`POST /sessions/{id}/choose-angle` extended.** Body is `{angle_index | angle, persona?}`. Omitting `persona` accepts the agent recommendation. No new endpoint.

3. **Typed message = angle only.** Free text while parked still resolves against offered angles (exact / 1-based index / 一二三四 / substring). Persona is changeable only via the explicit card field, so angle copy and persona names cannot collide in substring match.

4. **Park condition unchanged.** `route_after_brainstormer` still parks when `len(brief.angles) >= 2` (including when `chosen_angle` is already set). Persona rides along when the gate parks. Single-angle briefs keep the fast path to `executor_post` with the agent persona. — **Superseded by [ADR 0030](./0030-image-format-in-bundled-gate.md) §7:** the gate now parks at ≥1 angle; there is no single-angle fast path.

5. **Feedback loop preserved.** Non-matching text → `chosen_angle=None`, `angle_feedback=text` → `brainstormer` regenerates angles → parks again. A submitted persona pick is orthogonal to angles and survives re-brainstorm cycles (the card re-offers with that persona pre-selected). Escape hatch is Stop.

6. **Match = lock both.** Matched angle + resolved persona → `executor_post` with `chosen_angle` and `active_persona`. The node clears both in output so a later `start` re-offers.

7. **Unchanged boundaries.** No LLM in the gate; `route_intent` is not consulted on resume turns. Stop / cancel / re-park reuse [ADR 0004](./0004-stop-discard-and-image-resume.md) (`kind="choose_angle"`). Queue holds while parked per [ADR 0016](./0016-queue-send-while-turn-in-flight.md) §5. Confirm / publish remains [ADR 0003](./0003-confirm-without-llm.md). Resume `aupdate_state` is still attributed to `brainstormer`; the brainstormer router must still schedule `angle_gate` (same attribution trap as 0028).

8. **Out of scope — no dynamic structured questions.** LLM-initiated follow-ups stay chat-layer soft clarify (at most one short question after answering). A generic clarify park (LLM decides to interrupt with a structured card) needs its own ADR with usage evidence.

## Consequences

- Every `start` with ≥2 brainstormed angles now surfaces persona as a first-class choice on the same card as the angle pick.
- FE renders one bundled card (angle options + persona select) instead of angle-only buttons; typed-reply convenience path is unchanged for angles.
- `draft.awaiting_angle_pick` grows fields; clients that ignore unknown keys keep working until they render persona.
- Re-offer loop cost is unchanged (one brainstormer call per「都唔啱」cycle). Persona stickiness across cycles is the only new state to hydrate.
- Product / signal remain agent-chosen; they are not on this card. Soft `product_clarify` in chat is unchanged.
