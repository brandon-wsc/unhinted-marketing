# ADR 0042 — Per-invite monthly token limit

## Status

Accepted

## Context

[ADR 0041](0041-member-usage-limits-and-publish-approval.md) added a per-member spend cap (`organization_members.monthly_token_limit`), but it can only be set **after** the invitee accepts — via the member-management `PATCH`, or globally via `MEMBER_DEFAULT_MONTHLY_TOKEN_LIMIT` for `member` invites. Between accept and the owner remembering to patch, a fresh member runs at the env default or unlimited, and a per-person cap can't be decided at invite time where the owner is already choosing the role.

## Decision

- New nullable column `org_invites.monthly_token_limit` (integer). `NULL` = "no preset" — the invite behaves exactly as today.
- `POST /api/companies/{id}/invites` accepts an optional `monthly_token_limit` (`≥ 1`). `OrgInviteItem` returns it so the pending-invite list can show the preset cap.
- On accept (`POST /api/invites/{token}/accept`), an explicit invite limit wins: `monthly_token_limit = invite.monthly_token_limit ?? (role == 'member' ? MEMBER_DEFAULT_MONTHLY_TOKEN_LIMIT : NULL)`.
- The explicit preset is stored regardless of invited role — it is recorded intent, and survives a later admin→member demotion. Enforcement is unchanged: the cap is only ever evaluated for org role `member` (ADR 0041 §1). An `admin` membership with a stored limit is uncapped until demoted.
- UI: the invite form gains an optional token-limit field (empty = no preset); the pending-invite table shows the preset.

## Consequences

- Owners can cap a junior account's spend in the same step where they pick its role; no unlimited window between accept and the first member PATCH.
- `MEMBER_DEFAULT_MONTHLY_TOKEN_LIMIT` stays as the fallback for `member` invites without an explicit preset — existing behavior is untouched when the field is omitted.
- Revoking and re-inviting with a different limit is the correction path; there is no separate "patch pending invite" endpoint.
