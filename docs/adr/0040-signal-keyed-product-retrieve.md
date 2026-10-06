# ADR 0040 — Signal-keyed product retrieve (newsjacking path)

- **Status:** Accepted
- **Date:** 2026-10-06
- **Supersedes:** — (extends [COLLECT](../knowledge/COLLECT.md) §5; does not change primary/clarify rules)

## Context

`product_matcher` only ever queries the catalog with **user-message-derived** text (`product_surface` + `entity_surface` + raw message). For the newsjacking use case — a ranked market signal exists first and the job is "which product can ride it" (IKEA-小編 flow) — the user never names a product, so `need_product`/`sell_intent`/`product_surface` stay empty, `_should_match_product` returns false, and the catalog is never consulted. `brainstormer`/`executor_post` then have no retrieved product to hook the hook back onto.

The retrieve-eval harness (`scripts/eval_retrieve.py`, committed alongside) shows the vector tier already matches theme queries with **zero lexical overlap**: 「政府採購冒牌飲用水」surfaces 蒸餾水/濾水壺 at cosine 0.48–0.55, and unrelated queries return nothing under the 0.42 floor. Retrieval quality is not the blocker — **wiring** is.

## Decision

1. **Second query source in `product_matcher`.** When `ranked_signals` is non-empty, the node additionally queries `search_products_for_member` with signal-derived queries: titles of the top-2 ranked signals. Still at most one extra DB call per turn — no ReAct loop, consistent with the locked "one search hop per user turn" rule.
2. **Signal hits are a separate pool.** The user-derived retrieve keeps producing `primary_product` / `product_candidates` / `product_clarify` exactly as before. Signal-keyed hits can only enter `related_products` (org-scope rows, dedupe vs already-hit ids, cap 2) — they can never become primary and never appear in a clarify prompt. The guarantee is **structural** (separate call, separate list), not threshold-dependent: it survives future document enrichment raising vector scores past `PRIMARY_MIN_SCORE`.
3. **Gate widened.** `product_matcher` runs when `_should_match_product` OR `ranked_signals` is non-empty. With no user product intent and no signal hits the node still returns the empty payload; a signal-keyed miss never parks the turn.
4. **No new LLM call, node, or threshold.** Signal retrieve reuses the same hybrid path (lexical + Tier C + RRF + tenant filter). `grounding_check` stays authoritative on `primary_product` only — related suggestions are creative fodder, not grounding sources for price/spec claims.
5. **`related_products` ordering:** leftover org hits from the user pool first, then signal-pool hits — user intent outranks opportunistic suggestions.

## Consequences

- 「政府買咗冒牌水，點抽水好」→ signal ranks → matcher suggests 蒸餾水/濾水壺 in `related_products` → brainstormer can angle 「食水安全 → 我哋支水有檢測報告」 without the user naming a SKU.
- Theme-hit scores today sit 0.48–0.60, under the 0.55 primary floor — quarantining them to `related_products` matches that reality; widening `search_document` with scenario/benefit text later raises margin without touching this contract.
- Signal retrieve adds ~10–20 ms (one embed + scoped SQL) on act-path turns only; chitchat/revise paths unchanged.
- Eval coverage: `tests/eval/retrieve_cases/newsjacking.yaml` locks "theme hit ⇒ related, never primary" — any future promotion of signal hits must revisit those expects deliberately.
- Deferred: per-product scenario/angle text (`angle_text`) to widen vector margin; multi-chunk documents for long offer snippets.
