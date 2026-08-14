# Enterprise Knowledge

> **Status:** K0–K6 shipped (settings + slim packs + matcher + embeddings + exemplars + Approvals)  
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
| Locked retrieve/tenant decisions (optional formal ADR) | Future [ADR 0012](../adr/) if needed — behavior shipped K3–K4 |
| K6 promote / Approvals (commit without LLM) | [ADR 0011](../adr/0011-knowledge-commit-without-llm.md) |
| Org membership + invites | [ADR 0010](../adr/0010-org-membership-invites-and-shared-assets.md) |
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
| **K6** | Promote Mine → org + owner/admin approve | ✅ COLLECT + ADR 0011 + UI |

ADR **0010** (accepted): org membership, invites, shared-asset scope — [0010](../adr/0010-org-membership-invites-and-shared-assets.md).  
ADR **0011** (accepted): knowledge commit without LLM — [0011](../adr/0011-knowledge-commit-without-llm.md) (mirrors [ADR 0003](../adr/0003-confirm-without-llm.md)).  
ADR **0012** (optional): formal product retrieve + `company_id` filter (behavior already shipped in K3–K4).  

Chat scratch (User × New) still does not persist to org KB. Org import still bypasses the queue.

---

## References

- [VOICE.md](../VOICE.md)
- [ROADMAP.md](../ROADMAP.md)
- [ADR 0009](../adr/0009-research-gate-and-tavily-ingest.md)
