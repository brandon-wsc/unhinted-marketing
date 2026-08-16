# ADR 0013 — Invite accept replaces bootstrap solo org

- **Status:** Accepted
- **Date:** 2026-08-13
- **Amends:** [ADR 0010](./0010-org-membership-invites-and-shared-assets.md) §4 (one user ↔ one org)
- **Amended by:** [ADR 0015](./0015-invite-rehome-solo-products.md) (products rehome to Mine; voice discarded)

## Context

Register auto-creates a company `entities` row plus a sole-owner membership (ADR 0010 §1). Under ADR 0010 §4, invite accept returns **409 for any existing membership**. Combined, this creates a dead end for the most common invite path: a teammate opens the invite link, **registers with the invited email** (as the UI instructs), and is now the sole owner of a throwaway single-member org — accept then 409s forever, with no self-service way out.

The one-org invariant (ADR 0010 §4) is still correct for MVP; only the bootstrap-org collision needs relief.

## Decision

`POST /api/invites/{token}/accept` gains a **narrow exception** to the 409 rule:

- If the accepting user's **only** membership is **sole owner** of an org with **exactly one member** (themselves) — the register-bootstrap org — accept **replaces** that membership: the user joins the invited org with the invite's role.
- The orphaned bootstrap org's `entities` row is **deleted** in the same transaction. **Product rows are rehomed first** (all become Mine on the invited org); **voice is not copied** — [ADR 0015](./0015-invite-rehome-solo-products.md). A bootstrap org with no members is unreachable garbage otherwise.
- **Any other existing membership** (multi-member org, or non-owner role) → **409 unchanged**. There is still no org switcher and no self-service way to leave a real team.

All other invite rules from ADR 0010 §2 are untouched: token single-use, 7-day expiry, email match (403), revoked/expired/used (400).

## Consequences

- Backend amend in `cmd/api/routes/invites.py` + repos on `feat/web-org-team-settings`, before the invite page ships; API tests cover replace, 409 (multi-member org), and orphan-org deletion.
- Register flow itself is unchanged — the exception lives entirely on the accept path.
- Data-loss edge for **voice only** is accepted on replace; products move to Mine ([ADR 0015](./0015-invite-rehome-solo-products.md)). Invite-accept UI warns before Join.
- UI spec: locked decision #5 in [knowledge/UI.md](../knowledge/UI.md) now points here as the contract authority.
- Later ADRs (multi-org, ownership transfer) must account for this replace path; it does not generalize into multi-org support.
