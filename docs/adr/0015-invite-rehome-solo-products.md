# ADR 0015 — Solo-org invite accept rehomes products to Mine

- **Status:** Accepted
- **Date:** 2026-08-15
- **Amends:** [ADR 0013](./0013-invite-accept-replaces-bootstrap-org.md) (fate of the replaced solo org)

## Context

ADR 0013 deletes the sole-owner single-member org on invite accept so the one-org invariant holds. Cascade then dropped **org voice** (`entities.profile`) and **all products** (`company_id` FK). That is correct for a throwaway register-bootstrap org, and wrong for a one-person company the invitee had already used.

Sessions and drafts stay `user_id`-scoped (ADR 0010 §5) and already survive. The painful loss is COLLECT: catalog rows and brand voice.

## Decision

Replace path (sole owner of a **single-member** org) is unchanged for membership: drop that membership, join the invited org, delete the orphaned `entities` row.

On that path, **before** deleting the old company:

1. **Products** — every `products` row for the old `company_id` (org-scope and Mine) is **rehomed** to the invited company as **`owner_scope = user`**, `user_id` = acceptor. They appear under Products → Mine. Org-scope unique SKUs in the destination are unaffected (org still covers user on retrieve). If the solo org had both org and Mine rows for the same SKU, keep one user row (org catalog wins) so `uq_products_user_sku` holds.
2. **Voice** — **not** copied. Destination keeps the invited company's voice. Old `entities.profile` dies with the row.
3. **Sessions / drafts / preview media** — unchanged (still keyed by `user_id`).
4. **Pending Mine→org proposals** on the old company — cascade-delete with the entity (nothing to propose into a deleted org).

**409** for any non-replaceable membership is unchanged (multi-member org, or non-owner role).

**UI:** logged-in invite accept (replace-eligible) shows a warning before **Join company**: products → Mine in the new company; voice is not transferred; chats/drafts stay. Copy must not imply one-click join without that notice.

## Consequences

- `clear_bootstrap_solo_org` takes the destination company id and rehomes products in the same transaction as delete.
- Tests: rehome org + Mine SKUs onto dest Mine; duplicate SKU collapse; voice not present on dest from the invitee; 409 path untouched.
- Does not add an org `status` column. Does not migrate voice. Does not create an org-catalog copy on the destination (invitee joins as admin/member, not owner — they must Propose to share).
