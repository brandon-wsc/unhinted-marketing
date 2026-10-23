"""Tool-level refusals (ADR 0051 §7).

A ToolRefusal is raised inside a handler but becomes a normal tool result —
``isError: true`` with a machine ``reason`` — never an HTTP error. Guard
refusals map to the same shape via ``GUARD_REASONS``.
"""

from __future__ import annotations

from dataclasses import dataclass

from internal.session.guards import (
    MemberTokenLimitExceeded,
    SessionAccessDeniedError,
    SessionGuardError,
    SessionNotFoundError,
)

GUARD_REASONS: dict[type, str] = {
    SessionNotFoundError: "not_found",
    SessionAccessDeniedError: "access_denied",
    MemberTokenLimitExceeded: "usage_limit_exceeded",
}


@dataclass
class ToolRefusal(Exception):
    reason: str
    message: str

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(f"{reason}: {message}")


def refusal_reason(exc: BaseException) -> str:
    if isinstance(exc, ToolRefusal):
        return exc.reason
    if isinstance(exc, SessionGuardError):
        return GUARD_REASONS.get(type(exc), "access_denied")
    return "error"
