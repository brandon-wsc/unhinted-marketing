"""Shared session access guards.

Ownership and the ADR 0041 member token cap used to live as private
helpers inside ``cmd/api/routes/sessions.py``. They are lifted here so
callers beyond the HTTP routes enforce the same rules. Errors are
domain exceptions carrying ``status_code``/``detail``; each caller maps
them to its own transport (HTTPException in routes, its own error
shape elsewhere).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory import repos
from internal.memory.models import Session
from schemas.company import UsageLimitExceededDetail


@dataclass
class SessionGuardError(Exception):
    """Session access refusal with enough data for any transport to answer."""

    status_code: int
    detail: object


class SessionNotFoundError(SessionGuardError):
    def __init__(self) -> None:
        super().__init__(404, "Session not found")


class SessionAccessDeniedError(SessionGuardError):
    def __init__(self) -> None:
        super().__init__(403, "Access denied")


class MemberTokenLimitExceeded(SessionGuardError):
    """ADR 0041: member monthly token cap reached — carries the 403 payload."""

    def __init__(self, detail: UsageLimitExceededDetail) -> None:
        super().__init__(403, detail.model_dump(mode="json"))
        self.limit = detail.limit
        self.used = detail.used


async def require_owned_session(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> Session:
    """Fetch the session and assert it belongs to ``user_id``."""
    session = await repos.get_session(db, session_id)
    if not session:
        raise SessionNotFoundError()
    if session.user_id != user_id:
        raise SessionAccessDeniedError()
    return session


async def enforce_member_token_limit(
    db: AsyncSession, session: Session, user_id: uuid.UUID
) -> None:
    """ADR 0041: cap org `member` token spend at the turn boundary.

    Owner/admin bypass the cap entirely. The cap counts the member's whole
    spend — platform key ('env') and org BYOK ('org') are both the org's
    bill. llm_call_records flush asynchronously after each call, so
    in-flight turns can overshoot slightly — an accepted guardrail lag, not
    a hard rate limiter.
    """
    membership = await repos.get_org_membership(db, user_id, session.company_id)
    if membership is None or membership.role != "member" or membership.monthly_token_limit is None:
        return
    period_start, period_end = repos.member_month_bounds()
    by_source = await repos.sum_member_tokens_by_source(
        db, user_id=user_id, company_id=session.company_id, since=period_start
    )
    used = sum(by_source.values())
    if used >= membership.monthly_token_limit:
        raise MemberTokenLimitExceeded(
            UsageLimitExceededDetail(
                limit=membership.monthly_token_limit,
                used=used,
                period_end=period_end,
            )
        )
