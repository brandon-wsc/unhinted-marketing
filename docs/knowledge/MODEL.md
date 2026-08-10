# Knowledge model

> **Parent:** [README.md](./README.md) · **Runtime usage:** [SESSION.md](./SESSION.md) · **Ingest (TBD):** [COLLECT.md](./COLLECT.md)

What knowledge exists, how big it is, and whether it is **compressed** (always in session) or **retrieved** (on demand).

Hard boundary: **PostgreSQL only** — signals, entities, edges, future product rows. External web facts enter via ingest ([ADR 0009](../adr/0009-research-gate-and-tavily-ingest.md)), not live browse from chat.

Platform craft (Hook → Bridge → CTA; see [VOICE.md](../VOICE.md) §0) lives in [VOICE.md](../VOICE.md) + `internal/session/prompts.py` — **not** duplicated per company.

---

## Planes (five kinds)

| Plane | Purpose | Size | Strategy | Grounding |
|-------|---------|------|----------|-----------|
| **Pain points** | Human emotion for hook & bridge | Turn-local | Extract each turn from signal + user text | Creative — no cite; no institution punchlines |
| **Market signals** | HK hot search / web facts | Large, time-bound | Rank + top-K; PG ∪ Tavily ingest | `source_signal_ids` |
| **Brand voice** | Tone, forbidden words, exemplars | Small (~200–400 tok) | Compress once → `voice_pack` | Reviewer + VOICE.md |
| **Audiences** | Who we write for | Catalog compressed; one active | `audience_catalog` → `active_persona` | Brief + executor |
| **Product catalog** | What to sell (optional) | Unbounded if imported | Retrieve on demand; **never** full catalog in prompt | Primary row ids; see SESSION |

**Priority for Unhinted copy:** pain + signals (timing) → voice → optional product bridge. A post can be grounded and on-brand **without** any catalog row.

---

## Pain points

Collected **per turn**, not maintained as a user-edited KB table.

| Source | Examples |
|--------|----------|
| User message | 「OT 坐到散」→ tired, back pain, WFH |
| Ranked signal | 「夏天好熱」→ heat, AC contrast (human feeling, not institution as punchline) |
| Brief | `pain_points[]`, `visual_hook`, `bridge_hypothesis` |

See [VOICE.md §0](../VOICE.md) — signals are timing fuel; the joke target is eternal human pain.

---

## Brand voice (`voice_pack`)

**Compress once** in `load_context`. Few knobs — users may tune these.

| Field | Required | Source |
|-------|----------|--------|
| `craft` | yes | constant `hk_social_editor` |
| `roast_level` | yes | `entities.profile.roast_level` 0–3, default 1 |
| `roast_level_label` | yes | derived |
| `locale` | yes | profile or `zh-HK` |
| `forbidden_phrases` | recommended | profile + platform defaults, ≤15 |
| `tone_notes` | optional | profile |
| `exemplar_captions` | recommended | approved posts / manual seed, ≤3 × ≤150 chars |

Do **not** put full brand PDFs in `voice_pack`.

---

## Audiences (`audience_catalog` → `active_persona`)

**Catalog entry** (session, compressed):

```json
{
  "slug": "hk-young-professional",
  "label": "HK Young Professional (25–34)",
  "hook": "authentic, mobile-first, skeptical of hard sells"
}
```

**Active persona** (after brainstormer picks `brief.persona`): expanded `content_preferences`, `marketing_angles`.

**MVP:** global seeded personas (`entities.entity_type=persona`, `internal/memory/knowledge_seed.py`).  
**Later:** per-company overrides.

---

## Product catalog (optional)

If the user **has not** imported products, the graph skips catalog retrieve and may still draft using pain + brand soft sell.

If they **have** imported user-owned catalog (CSV/Excel — [COLLECT.md](./COLLECT.md)):

### Storage (planned)

- Rows scoped by **`company_id`** (not global slug alone — see open questions in README phase K3).
- **`search_document`** — one text blob for SQL + embedding (name, sku, aliases, description, raw columns).
- **`profile` JSONB** — original import row; **no required schema**; best-effort extract only.

### Runtime roles

| Role | Rule |
|------|------|
| **Primary** (sell target) | Must resolve to one row **or** ask user to clarify |
| **Related** (optional extras) | Optional retrieve neighbors; **empty is OK** |

**Cover ([COLLECT §2](./COLLECT.md#2-ownership-org--user-new--old)):** org catalog **wins over** user personal row on same SKU; user may only change org after **admin approve** (promote). Session scratch is turn-local only.

Do **not** require users to fill `benefits[]`, `claim_rules[]`, `price_hkd` etc. Grounding = caption claims must match **retrieved row text**, not missing form fields.

### When catalog path runs

| Condition | Behavior |
|-----------|----------|
| No catalog for company | Skip product retrieve |
| Catalog + user **explicit** sell intent | Extract product name → search → primary or clarify |
| Catalog + trend-only request | Optional related suggest; do not force SKU |

Extract + search flow detail: [SESSION.md](./SESSION.md). User import + retrieve + tenant: [COLLECT.md](./COLLECT.md) (open web → ADR 0009, not COLLECT).

---

## Market signals (shipped)

| Field | Store |
|-------|-------|
| `signal_id`, `source`, `title`, `excerpt`, `metrics` | `raw_news_events` |
| Promoted topics | `entities` type `topic` + `edges` |
| Session merge | PG ∪ Tavily upsert → `research_signals`, `ranked_signals` |

---

## What is *not* knowledge

| Item | Treatment |
|------|-----------|
| Chat history | `session_messages` — window only |
| Draft / preview | Output artifacts |
| Platform craft | VOICE.md + prompts |
| Live web | Upsert to PG before cite |
| Publish | Confirm HTTP only ([ADR 0003](../adr/0003-confirm-without-llm.md)) |

---

## PostgreSQL stores

| Store | Status | Contents |
|-------|--------|----------|
| `raw_news_events` | ✅ | Market signals |
| `entities` (`company`) | ✅ | Org; `profile` JSONB |
| `entities` (`persona`) | ✅ | Default audiences |
| `entities` (`topic`) | ✅ | Promoted topics |
| `entities` (`product`) | ⬜ | Optional per-company catalog |
| `edges` | ✅ | Graph links |
| pgvector | ✅ products.embedding (K4) | Signals similarity still later |

No second vector DB. No repo markdown bundle for tenant KB.

---

## Open questions (before K3)

1. Product row: dedicated table vs `entities` + `(company_id, sku)` unique?
2. Exemplar source: profile JSON vs promote from `preview_drafts`?
3. Persona scope: global seed vs per-company for MVP?
4. Preview persist: `product_context_ids` column vs inside `copy` JSON?
