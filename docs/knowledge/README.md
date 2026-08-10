# Enterprise Knowledge

> **Status:** K0–K5 shipped (settings + slim packs + matcher + embeddings + exemplars) · K6 held (org system)  
> **Boundary:** PostgreSQL only — no parallel KB, no chat free-browse ([AGENTS.md](../../AGENTS.md))

Hub for **what** marketing knowledge Unhinted needs, **how** session nodes consume it, and (later) **how** users collect/import it.

---

## Docs in this folder

| Doc | Purpose | Audience |
|-----|---------|----------|
| [MODEL.md](./MODEL.md) | Knowledge planes: signals, voice, audience, pain, optional product catalog | Product / backend design |
| [SESSION.md](./SESSION.md) | SessionState contract, graph placement, node payloads, grounding | Graph / node implementers |
| [COLLECT.md](./COLLECT.md) | Human-provided knowledge: org/user libraries, cover rules, import, retrieve | Ops / backend |
| [UI.md](./UI.md) | Company settings IA: Voice / Products (Org\|Mine) / Approvals — what UI collects | Product / frontend |

**Not in this folder**

| Topic | Authority |
|-------|-----------|
| HK social craft (trend hooks, zh-HK) | [VOICE.md](../VOICE.md) |
| Locked retrieve/tenant decisions (when shipped) | Future [ADR 0010](../adr/) |
| Shipped vs held checklist | [STATUS.md](../STATUS.md) |
| Architecture overview | [ROADMAP § Knowledge](../ROADMAP.md#knowledge-postgresql) |
| Market research ingest | [ADR 0009](../adr/0009-research-gate-and-tavily-ingest.md) |

---

## Core idea

1. **Pain points first** — hooks come from human emotion (signal + user turn), not from SKU schema.  
2. **Voice & audience** — small, compress once per turn (`voice_pack`, `audience_catalog` → `active_persona`).  
3. **Product catalog optional** — if user imported CSV/Excel, resolve **primary** product (or ask); **related** products via retrieve are optional extras.  
4. **No required product fields** — store raw import row + searchable text; grounding checks claims against retrieved rows, not form validation.  
5. **COLLECT = human-provided** — not open web ([ADR 0009](../adr/0009-research-gate-and-tavily-ingest.md)). **Org covers user** on SKU clash; **user covers org only after admin approve** ([COLLECT §2](./COLLECT.md#2-ownership-org--user-new--old)).

---

## Phased delivery

| Phase | Scope | Doc |
|-------|-------|-----|
| **K0** | This folder + links | README / MODEL / SESSION / COLLECT / UI |
| **K1** | `voice_pack`, `audience_catalog`, slim LLM payloads + Voice settings UI | ✅ SESSION + UI |
| **K2** | `ranked_signals` top-level (out of fat `company_context`) | ✅ SESSION |
| **K3** | Optional catalog + `product_matcher` + Products Org tab | ✅ MODEL + SESSION + COLLECT + UI |
| **K3b** | User product lib + org-wins retrieve + Products Mine tab | ✅ COLLECT + UI |
| **K4** | pgvector hybrid retrieve + cross-tenant tests | ✅ COLLECT |
| **K5** | Exemplar captions (Voice settings + Confirm promote) | ✅ COLLECT + UI |
| **K6** | **Held** — promote to org + **admin approve** (user covers org only after approve) | COLLECT + ADR |

ADR **0010** (future): lock product retrieve + `company_id` filter formally (behavior already shipped in K3–K4).  
ADR **0011** (future, after K6 UX): knowledge commit without LLM — mirror [ADR 0003](../adr/0003-confirm-without-llm.md).

### Held: promote to org (K6)

**Not in K0–K5.** **User × New** (chat scratch) is instant for drafting; **Org × Old** changes require import or K6 **promote + owner/admin approve**. Org **directly covers** user on SKU clash at retrieve time.

**Prerequisite order:** K3–K4 retrieve works → K5 manual import/UI → **design K6 approve UX** → ADR 0011 + code.

---

## References

- [VOICE.md](../VOICE.md)
- [ROADMAP.md](../ROADMAP.md)
- [ADR 0009](../adr/0009-research-gate-and-tavily-ingest.md)
