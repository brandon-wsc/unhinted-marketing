# Collect — human-provided knowledge (org + user)

> **Status:** K3–K5 shipped (products import/retrieve + embeddings + exemplars) · K6 held · Offer snippets deferred  
> **Parent:** [README.md](./README.md) · **Runtime:** [SESSION.md](./SESSION.md)

**Scope:** **Human-provided** knowledge (import, paste, settings) that **open web cannot replace** — stored at **organization** and/or **user** scope ([§2](#2-ownership-org--user-new--old)). Not the same as “owned by one login only.”

**Out of scope (document elsewhere):**

| Source | Authority |
|--------|-----------|
| HK hot search, Tavily, public trends | [ADR 0009](../adr/0009-research-gate-and-tavily-ingest.md), background workers |
| Pain / pain points per turn | [SESSION.md](./SESSION.md) — extracted from signal + user message, not a user KB table |
| Platform zh-HK craft | [VOICE.md](../VOICE.md) |

---

## 1. User-owned vs open web

| | User-owned (**COLLECT**) | Open web (**not COLLECT**) |
|--|--------------------------|----------------------------|
| Examples | SKU/price list, internal promo copy, brand forbidden words, approved post captions | Google Trends HK, news excerpts, public “hot topics” |
| Who writes it | User import, paste, company settings, Confirm → promote | Workers + session research ingest |
| Tenant | **Must** scope every row & retrieve by `company_id` | Mostly shared HK corpus; query-filtered |
| Grounding ids | `product_context_ids`, snippet ids | `source_signal_ids` |

If the company has **not** imported or pasted user-owned data, retrieve **skips** — the session still runs on pain + signals + voice ([MODEL.md](./MODEL.md)).

---

## 2. Ownership (org × user, new × old)

Two dimensions:

| Dimension | Values | Meaning |
|-----------|--------|---------|
| **Scope** | **Org** | `company_id` — shared company catalog |
| | **User** | `company_id` + `user_id` — personal library (same tenant) |
| **Maturity** | **New** | This turn / pending — scratch, just pasted, proposal queue |
| | **Old** | Committed rows in PG — stable retrieve targets |

### 2×2 matrix

| | **Org** | **User** |
|--|---------|----------|
| **New** | Pending proposal / admin import job (not yet committed, or awaiting approve) | Session scratch, new personal row (instant use) |
| **Old** | Company catalog — **source of truth** | Personal catalog — SKUs **not** in org, or pre-promote drafts |

### Cover rules (locked)

**Retrieve (what `product_matcher` uses for this user):**

```text
1. User × New   — session scratch (this turn only; instant draft)
2. Org × Old    — company catalog wins over User × Old
3. User × Old   — only when org has no matching SKU
```

- **Org directly covers User:** same `(company_id, sku)` → **org row wins**; ignore user committed row for retrieve and grounding.
- **User × New** does not permanently cover org — it is turn-local until promoted.
- **Org × New** is **not** in retrieve until committed to Org × Old.

**Commit (replace by SKU — no merge-conflict UI):**

| Action | Result |
|--------|--------|
| Import / API → org | Upsert **Org × Old** (`ON CONFLICT REPLACE`) |
| Member saves personal row | Upsert **User × Old** (cannot override org retrieve for same SKU) |
| Member **promote** → org | **Org × New** (proposal) → owner/admin **approve** → **Org × Old** replaces org row by SKU |
| User covers org | **Only after approve** — user cannot silently overwrite org catalog |

Approve gate: `organization_members.role` ∈ `{owner, admin}` ([ROADMAP § User System](../ROADMAP.md#user-system--authentication)). Members propose; admins commit org changes.

**No bidirectional sync.** Org → user is not a copy — retrieve union + org-wins rule. User → org is promote + approve only.

Planned row shape: `owner_scope: org | user`, `user_id` nullable, unique `(company_id, sku)` on **org** rows; `(company_id, user_id, sku)` on **user** rows.

---

## 3. What users can collect (inventory)

| Kind | Entry | Required for MVP | Notes |
|------|-------|------------------|-------|
| **Product catalog (org)** | CSV / Excel import (owner/admin) | K3 | Org × Old; retrieve for all members |
| **Product catalog (user)** | Personal import / save | K3b | User × Old; org covers on SKU clash |
| **Voice overlay** | Org settings + optional user overlay | K1 | Org default; user may overlay / reset ([MODEL](./MODEL.md)) |
| **Exemplar captions** | Manual promote from Confirm / settings UI | K5 | Not chat→KB auto-write; see K6 held |
| **Offer snippets** | Paste in **import UI** or dedicated upload | K5 optional | Session paste → KB is **K6 held** |
| **Per-company personas** | CRUD | Later | MVP uses global seed (`knowledge_seed.py`); override = user-owned |

**Not user-owned KB:** global persona seeds, platform defaults, market signals.

---

## 4. Product import (K3)

### Formats

- **CSV** (UTF-8, with or without BOM)
- **Excel** (`.xlsx`) — `openpyxl`

### Column policy

- **No required column names** — flexible headers.
- **Hard limit: 50 columns** — more than that → reject whole file (400) with a clear message; do not silently truncate. Column picker / mapping comes later.
- Each row → one catalog row:
  - **`profile` JSONB** — original column → value map (preserves user shape).
  - **`search_document`** — concatenation for SQL + embedding, e.g.  
    `{name} | {sku} | {aliases} | {description} | …` from mapped or all non-empty cells.
- Optional **column mapping** step (MVP: fixed template doc; later: UI or LLM-suggested map + user confirm).

### Identity & dedupe

- Scope: **`company_id`** on every row; **`owner_scope`**: `org` (import API, owner/admin) or `user` (personal).
- Uniqueness: **`(company_id, sku)`** for org rows; **`(company_id, user_id, sku)`** for user rows.
- **Upsert** on re-import; **`status`**: `active` | `archived`; retrieve only `active`.

### API (shipped)

- `POST /api/companies/{company_id}/products/import` — org catalog; owner/admin (`scope=org` default).
- `POST /api/companies/{company_id}/products/import?scope=user` — user personal library; any member.
- Also: `GET …/products`, `POST …/products` (manual add), `POST …/products/{id}/archive`.
- Response (import): `{ imported, updated, skipped, errors[] }`.

### Errors

- Bad rows: **skip + report** (partial success); do not fail entire batch silently.
- Empty file → 400 with clear message.

### Storage (shipped)

Dedicated **`products`** table (not `entities` type `product`). Columns:

| Column | Purpose |
|--------|---------|
| `id` | UUID |
| `company_id` | Tenant key |
| `owner_scope` | `org` \| `user` |
| `user_id` | NULL (org) or owner (user) |
| `search_document` | Text for lexical / embed |
| `profile` | Raw import row JSONB |
| `sku` / `name` | Denormalized for exact match |
| `embedding` | `vector(384)`, K4 |
| `status` | `active` \| `archived` |

**No required fields inside `profile`** — grounding compares caption text to **retrieved row content**, not form validation.

---

## 5. Retrieve (org + user libraries)

Used by `product_matcher` ([SESSION.md](./SESSION.md)). Merges **Org × Old** and **User × Old** with [§2 cover rules](#cover-rules-locked): **org wins on SKU clash**; **User × New** (session scratch) wins for the current turn only.

### Flow

1. LLM extract (cheap): `product_surface`, `search_queries[]`, `sell_intent` (`explicit` | `implicit` | `none`).
2. If session scratch matches → use **User × New** for this turn (`primary_product.source = session_scratch`).
3. **Tier A — SQL exact:** `sku` / external id, `company_id = :cid`, org rows + `(user_id = :uid OR owner_scope = org)`.
4. **Tier B — SQL fuzzy:** `ILIKE`, `pg_trgm` on `search_document`; **prefer org hit over user hit** when both match.
5. **Tier C — vector (K4):** embed queries; same tenant + scope filter; org rank boost on tie.
6. **RRF** merge → candidate list; dedupe by SKU with **org row retained**.
7. **Primary:** top-1 if score ≥ threshold **and** margin vs top-2; else **`product_clarify`**.
8. **Related:** neighbors from **org** catalog only, top-2 — empty OK.

MVP (K3): Tier A + B; org+user union with org-wins dedupe. **K4:** Tier C FastEmbed vectors + RRF-style merge (`max(lex, vec, scaled RRF)`); always `company_id` in SQL before score.

### Repo contract (shipped)

```python
async def search_products_for_member(
    db, *, company_id: UUID, user_id: UUID, queries: list[str], limit: int = 5
) -> list[ProductHit]: ...
```

Implemented in `internal/memory/product_retrieve.py`. **Never** search without `company_id`. User scope requires `user_id`. No cross-company rows.

---

## 6. Tenant isolation

User-owned data **must not leak across companies**.

| Layer | Rule |
|-------|------|
| **SQL** | `company_id` always; user rows also filter `user_id` |
| **API** | Import/list/delete via `require_company_access` |
| **Session** | `company_id` from `sessions.company_id` → graph state; not from LLM |
| **Repo** | Functions require `company_id` as first arg; no optional global mode |
| **Tests** | Seed company A + B; retrieve as A → zero B ids (K4 gate) |
| **RLS** | Optional hardening later (`app.company_id` setting) |

**Anti-patterns:** global vector top-K then filter; trusting prompt for tenant; shared slug namespace across orgs.

Locked decisions → [ADR 0010](../adr/0010-org-membership-invites-and-shared-assets.md) (org/invites); product retrieve tenant filter behavior shipped in K3–K4 (optional formal ADR 0012 later).

---

## 7. RAG tuning (K4)

Applies **only** to product `search_document` corpus (not market signals).

| Topic | Default |
|-------|---------|
| Embedding model | Same family as semantic gate — FastEmbed multilingual MiniLM (`PRODUCT_EMBEDDING_MODEL` or `SEMANTIC_ROUTER_MODEL`) |
| Dim | **384** (`products.embedding vector(384)` — Alembic `12d5c92e3f74`) |
| Chunking | **One product row = one chunk** |
| Query text | Joined `product_surface` / matcher queries — not full chat dump |
| Thresholds | Lexical primary floor 0.55 + margin 0.12; vector cosine min **0.42** |
| Re-embed | Inline on import upsert / manual create (`embed_texts`) |
| Disable | `PRODUCT_EMBEDDINGS_ENABLED=false` → lexical-only |

Eval set: ~20 user utterances × ~10 SKUs per company; live FastEmbed regression optional (CI mocks / disables embedder).

---

## 8. Other user-owned channels (K5 — outline)

**UI surfaces (locked):** [UI.md](./UI.md) — UserMenu → Company settings (Voice / Products tabs Org|Mine / Approvals).

### Voice settings

- Persist on `entities.profile` for `entity_type=company`.
- Fields: `roast_level`, `forbidden_phrases`, `tone_notes`, `locale` — see [MODEL.md § Brand voice](./MODEL.md#brand-voice-voice_pack).
- Shell form: [UI.md § Voice](./UI.md#voice-k1).

### Exemplar captions

- Source: Voice settings (manual ≤3) **or** Confirm → **Save caption as voice example** (`POST /api/companies/{id}/voice/exemplars`).
- Cap: ≤3 captions × ≤150 chars into `entities.profile.exemplar_captions` → `voice_pack`.
- Not chat auto-write; owner/admin only.

### Offer snippets (optional, K5)

- User upload / admin paste → `offer_snippets`: `snippet_id`, `company_id`, `raw_excerpt`, `source`.
- Same tenant rules as products; retrieve when no SKU match but internal promo text exists.
- **Chat paste → persist to org KB:** held to **K6** (promote + admin approve — §9).
- No dedicated MVP page until needed — Products / Voice first.

---

## 9. Held — promote to org (K6)

> **Status:** Product + UX **not designed**. No graph node or API until K6 is specced.

**Intent:** Member adds **User × New / User × Old** content in chat or personal lib, then **promotes** to org. **User covers org only after owner/admin approve** → upsert **Org × Old** (replace by SKU, diff before approve). Same philosophy as Confirm ≠ LLM ([ADR 0003](../adr/0003-confirm-without-llm.md)).

**Why held (after K5):**

| Need first | Reason |
|------------|--------|
| K3–K4 working retrieve | Know what a committed row looks like |
| K5 manual import / settings | Baseline path without agent writes |
| Approve UX design | Proposal card? diff? batch? TTL? — undecided |
| ADR 0011 | Lock propose vs commit boundary |

**Until K6:**

- **User × New** → session scratch only — instant draft, not org catalog.
- **Org × Old** → import API / admin settings only (no chat promote).
- Agent **must not** upsert org rows from chat without approve HTTP.

**K6 sketch (when ready — not implemented):**

1. Member submits promote → **Org × New** (proposal + diff vs org row if SKU exists).
2. `POST …/proposals/{id}/approve` — owner/admin, zero LLM, idempotent **replace** org row by SKU.
3. `POST …/reject` — keep user personal row; org unchanged.

Do not implement until approve flow is agreed and ADR 0011 is accepted.

---

## 10. Open questions

**Decided (K3–K5):** dedicated `products` table (not `entities` type `product`); upsert **replace by SKU**; embedding **inline** on import/create; exemplars on `entities.profile.exemplar_captions` + Confirm promote.

Still open:

1. CSV column mapping UI (vs flexible headers only)?
2. Offer snippets: separate table vs `kind` on products?
3. **K6:** Proposal UI, diff for product patch, reject / “session only”, proposal TTL?

---

## 11. Phase checklist

| Phase | COLLECT deliverable |
|-------|---------------------|
| **K3** | §4 org import + storage; §5 retrieve (org only MVP OK) | ✅ |
| **K3b** | User personal lib + org-wins dedupe in §5 | ✅ |
| **K4** | §7 vector tier + cross-tenant tests | ✅ |
| **K5** | Import UI ([UI.md](./UI.md)); §8 manual exemplar + offer upload | ✅ exemplars (offer snippets optional / deferred) |
| **K6** | **Held** — §9 promote + Approvals UI → org replace |

---

## References

- [MODEL.md § Product catalog](./MODEL.md#product-catalog-optional)
- [SESSION.md](./SESSION.md)
- [ADR 0009](../adr/0009-research-gate-and-tavily-ingest.md) — open web ingest (not COLLECT)
