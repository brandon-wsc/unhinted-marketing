# Session usage

> **Parent:** [README.md](./README.md) · **What knowledge is:** [MODEL.md](./MODEL.md)

How LangGraph **loads**, **slices**, and **grounds** knowledge per turn. K1–K5 session packs + `product_matcher` shipped; see [Current code](#current-code-shipped-baseline).

---

## Graph placement (target)

```
load_context          → voice_pack, audience_catalog, slim company_context
trend_searcher        → ranked_signals, source_signal_ids
product_matcher       → primary_product, related_products[], product_clarify?
brainstormer          → brief (incl. pain_points), active_persona
angle_gate            → PARK for user pick when brief.angles ≥ 2 (ADR 0028)
executor_post         → draft (chosen_angle direction), refine product_context_ids
grounding_check       → source_signal_ids + product claims vs retrieved rows
reviewer              → voice + grounding + craft
```

Revise path (`edit_copy`): reuse turn state; re-run `product_matcher` only when user changes product (future `need_product` gate).

If `product_clarify` is true after matcher → short-circuit to **chat** (ask which SKU) — do not enter executor with a guessed primary.

### Angle pick gate ([ADR 0029](../adr/0029-angle-persona-bundled-gate.md))

- `brief.angles` ≥ 2 → graph parks at `interrupt_before=["angle_gate"]` (the gate validates any pending `chosen_angle`; a non-empty value is not a skip). `draft.awaiting_angle_pick` carries the offered angles, `personas` (audience catalog), and `recommended_persona`; `session.state.awaiting_angle_pick` hydrates the bundled card.
- Pick: `POST /sessions/{id}/choose-angle` (`angle_index` or `angle` text, optional `persona`), or a typed `POST /messages` while angle-parked (angle only — persona is the card field; image park still 409s).
- `angle_gate` resolves angle picks (exact / 1-based index / CJK numeral / substring). Match → `chosen_angle` + resolved `active_persona` → `executor_post` (pick fields cleared on output). Non-match → `angle_feedback` → `brainstormer` regenerates angles and parks again; a submitted `chosen_persona` survives the loop.
- Stop while parked discards the turn (ADR 0004); Stop mid `choose-angle` re-parks at `angle_gate`.

---

## SessionState fields (shipped)

| Field | Producer | Consumers |
|-------|----------|-----------|
| `voice_pack` | `load_context` | chat†, brainstormer, executor_post, edit_copy, reviewer |
| `audience_catalog` | `load_context` | trend_searcher†, brainstormer |
| `ranked_signals` | `trend_searcher` | brainstormer, executor_post, edit_copy |
| `trend_notes` | `trend_searcher` | optional via slim company LLM slice |
| `primary_product` | `product_matcher` | brainstormer, executor_post, reviewer, grounding_check |
| `related_products` | `product_matcher` | brainstormer (optional) |
| `product_clarify` | `product_matcher` | route → chat |
| `product_context_ids` | matcher → executor/edit | grounding_check, reviewer, preview persist |
| `product_candidates` | `product_matcher` | chat (clarify) |
| `active_persona` | `brainstormer` / `angle_gate` | executor_post, reviewer, image_plan† |
| `source_signal_ids` | research_ingest, trend_searcher, executor, edit | grounding_check, reviewer |
| `chosen_angle` | choose-angle resume / typed pick | `angle_gate` (match check), `executor_post` (payload) |
| `chosen_persona` | choose-angle card field | `angle_gate` (locks `active_persona`); sticky on re-brief |
| `angle_feedback` | `angle_gate` on non-matching text | `brainstormer` (regenerate angles) |

† minimal slice only.

### Slim `company_context`

Identity only — do not pass full `profile` or `personas[]` to LLM payloads:

```json
{
  "company_id": "uuid",
  "name": "Acme HK",
  "slug": "acme-hk"
}
```

`trend_notes` (from `trend_searcher`) and `ranked_signals` are **top-level** SessionState fields (K2), not nested under `company_context`.
### `research` (ADR 0009 — shipped today)

Side channel on `route_intent` output (`ResearchFlags` in `internal/session/io.py`). Controls **open-web / market** ingest — not product catalog (K3).

**Shipped fields:**

| Field | Meaning |
|-------|---------|
| `need_facts` | Turn needs current market / web facts → may run `query_generator` + Tavily∪PG |
| `ambiguous` | Entity has multiple senses; does not block search |
| `ask_clarify` | User must pick a sense before **drafting** (not a substitute for search) |
| `entity_surface` | Short noun phrase hint for `query_generator`. Sense-pick follow-up should combine prior topic + chosen sense (e.g. `Chiikawa Usagi 兔糧`), not the IP name alone |
| `rationale` | Debug / trace |

Same `research` dict, written later (not on `ResearchFlags`):

| Field | Meaning |
|-------|---------|
| `search_queries` | 1–3 atomic queries, **one conjunct each** (entity vs intent vs product class — do not glue `Usagi rabbit food`) |
| `query_source` | `llm` \| `normalize` \| `fallback` — set by `query_generator` |
| `signals_trusted` | Consumer bit (set by `research_ingest`): `false` if fallback queries or no Tavily items this turn |

Follow-up turns: `route_intent` / `query_generator` see `recent_thread`. A short sense pick after a fact question stays `chat`, skips the cheap `normalize` path (so `Chiikawa` does not become `Chiikawa Hong Kong`), and rewrites queries from the prior question. The **set** must still cover that prior intent (e.g. 兔糧 / favorite food) plus the new sense; a JP entity query such as `ちいかわ うさぎ` may be one slot, not a substitute for the food/feed queries. **One search hop per user turn** — no loop-until-enough.

Example (market-only turn — no catalog):

```json
{
  "need_facts": true,
  "ambiguous": false,
  "ask_clarify": false,
  "entity_surface": "HK heat wave",
  "rationale": "..."
}
```

### `research` — product catalog (shipped with K3 matcher)

Same `research` object / `ResearchFlags` — catalog path is independent of market facts:

| Field | Meaning |
|-------|---------|
| `need_product` | Turn needs user-owned catalog retrieve → `product_matcher` |
| `sell_intent` | `explicit` \| `implicit` \| `none` |
| `product_surface` | Short noun phrase for catalog search (when `need_product`) |

Example (sell explicit — catalog path, market optional):

```json
{
  "need_facts": false,
  "need_product": true,
  "sell_intent": "explicit",
  "product_surface": "SKU-2048"
}
```

`need_facts` and `need_product` are **independent** — both may be true in one turn.

### `brief` extension (planned)

```json
{
  "pain_points": ["…"],
  "visual_hook": "…",
  "bridge_hypothesis": "…",
  "persona": "hk-young-professional",
  "primary_product_id": "uuid-or-null",
  "can_do": [],
  "cannot_do": [],
  "angles": [],
  "summary": "..."
}
```

String values are zh-HK user-facing copy in production; ellipses here are placeholders only.

### `primary_product` (when catalog hit)

```json
{
  "product_id": "uuid",
  "name": "...",
  "search_document": "excerpt used in prompt",
  "match_score": 0.87,
  "source": "session_scratch | org_catalog | user_catalog"
}
```

`related_products`: same shape, 0–2 items; may be empty.

---

## Node payload budget

| Node | Include | Exclude |
|------|---------|---------|
| `route_intent` | `company_name` | voice, products, signals |
| `query_generator` | `company_name`, `need_product` | full context |
| `chat` | `voice.roast_level`, `research_signals[:8]`, optional `primary_product` if resolved | full voice_pack, catalog |
| `trend_searcher` | `company_name`, `audience_catalog`, `signals[:20]` | products |
| `product_matcher` | *(no LLM)* `company_id` + queries | — |
| `brainstormer` | `voice_pack`, `audience_catalog`, `signals[:8]`, `primary_product?`, `related_products[:2]`, pains from extract | raw profile JSONB |
| `executor_post` | `voice_pack`, `active_persona`, `primary_product`, `signals[:8]`, brief | full catalog |
| `reviewer` | `voice_pack`, draft, `primary_product?`, ids | catalog, history |
| `edit_copy` | `voice_pack`, `primary_product?`, allowed signal/product ids | company blob |
| `executor_image_plan` | `company_name`, `product_name?`, roast mood | full voice_pack |

Implementation target: `node_payload(node, state)` in `internal/session/knowledge_payload.py`.

---

## Grounding rules

| Claim type | Rule | Validator |
|------------|------|-----------|
| Market / trend facts | `source_signal_ids` ⊆ PG signals | `grounding_check` |
| Price / SKU / spec in caption | Must match **primary** retrieved row text if present; if no catalog row, **no invented numbers** | `grounding_check` + `reviewer` |
| Pain / scene | Creative; no cite | `reviewer` (craft only) |
| Tone | `voice_pack` + VOICE.md | `reviewer` |
| Publish | — | Confirm HTTP ([ADR 0003](../adr/0003-confirm-without-llm.md)) |

Draft schema (planned): `product_context_ids` on `DraftOut` / `EditOut`; persist on `preview_drafts` with `source_signal_ids`.

**Chat-only product facts (no import):** **User × New** (session scratch) for this turn; **do not** write to **Org × Old** until [COLLECT §9 K6](./COLLECT.md#9-promote-to-org-k6) owner/admin approve.

---

## Current code (shipped baseline)

Today `load_context` emits top-level `voice_pack` + `audience_catalog` and identity-only `company_context` (K1). `trend_searcher` writes top-level `ranked_signals` + `trend_notes` (K2). `product_matcher` (no LLM) resolves `primary_product` with org-wins cover + hybrid lexical/vector retrieve (K4); ambiguous matches route to `chat` via `product_clarify`.

---

## References

- [MODEL.md](./MODEL.md)
- [COLLECT.md](./COLLECT.md) — user-owned import & retrieve; chat scratch still not org KB (K6 is Mine catalog only)
- [ADR 0009](../adr/0009-research-gate-and-tavily-ingest.md)
