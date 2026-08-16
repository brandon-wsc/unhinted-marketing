# ADR 0011 — Knowledge commit without LLM (K6 Approvals)

- **Status:** Accepted
- **Date:** 2026-08-14
- **Supersedes:** — (unblocked by [ADR 0010](./0010-org-membership-invites-and-shared-assets.md))
- **Mirrors:** [ADR 0003](./0003-confirm-without-llm.md) — Confirm/publish is HTTP, not chat

## Context

COLLECT cover rules already say **user cannot silently overwrite org catalog** — Mine SKUs are ignored at retrieve when org has the same SKU, and chat scratch stays turn-local. Org import / settings write is owner/admin only. That left no path for a teammate to put a personal product into the company list.

K6 is that path: **propose** (any member, own Mine row) → **Approvals** (owner/admin) → **commit Org × Old**. Same philosophy as Confirm: the LLM must not write the org catalog.

## Decision

1. **Propose / approve / reject / cancel are traditional HTTP** — zero LLM. Graph nodes must not upsert org products.
2. **MVP source = User × Old products only** (Mine catalog). Chat scratch (User × New), offer snippets, and Voice exemplars are out of this ADR. Exemplars stay K5 owner/admin direct promote.
3. **Snapshot at propose** — `product_proposals` stores `sku`, `name`, `profile` copied from the Mine row. Later Mine edits do not change a pending proposal.
4. **One pending proposal per `(company_id, sku)`** — second propose → **409**. Rejected / approved / **cancelled** rows do not block a new propose.
5. **Approve = replace-by-SKU** — owner/admin `POST …/proposals/{id}/approve` upserts **Org × Old** from the snapshot (same `upsert_product_row` as import) and re-embeds. Idempotent: already approved → 200, no second write.
6. **Reject** — org unchanged; Mine row stays. `POST …/reject`.
7. **Cancel** — proposer withdraws a **pending** request (`POST …/cancel`). Org unchanged; Mine row stays. Idempotent if already cancelled. Not pending → 409. Only `proposed_by` (not another member; owner/admin use reject).
8. **Who** — any org member proposes **their own** active Mine row. List / approve / reject require `require_company_settings_editor` (owner/admin). Cancel requires `require_company_access` + proposer.
9. **UI** — `/settings?tab=approvals` in the Company settings sidebar for owner/admin only. Mine tab shows **Add to company** or **Cancel request** (icon + tooltip). Diff is proposed vs current org row (or empty = new SKU). No TTL / batch for MVP.

### HTTP

| Method | Route | Who |
|--------|-------|-----|
| POST | `/api/companies/{id}/products/{product_id}/propose` | row owner (Mine) |
| GET | `/api/companies/{id}/proposals` | owner/admin |
| POST | `/api/companies/{id}/proposals/{id}/approve` | owner/admin |
| POST | `/api/companies/{id}/proposals/{id}/reject` | owner/admin |
| POST | `/api/companies/{id}/proposals/{id}/cancel` | proposer |

## Consequences

- Org import still bypasses the queue (owner/admin writing Org × Old directly).
- Retrieve cover rules unchanged until approve lands the org row.
- Chat still must not persist products to org KB.
- Deferred: proposal TTL, batch approve, chat-scratch promote, offer-snippet queue.
