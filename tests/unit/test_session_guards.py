"""Session access guards (internal/session/guards.py) — no Postgres.

``company_id`` is the ADR 0051 §6 grant binding: an MCP token is scoped to
one company, so a session the same user owns in another company is refused.
REST callers omit it and keep the user-only check.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from internal.memory import repos
from internal.session.guards import (
    SessionAccessDeniedError,
    SessionNotFoundError,
    require_owned_session,
)

USER = uuid.uuid4()
COMPANY_A = uuid.uuid4()
COMPANY_B = uuid.uuid4()


def _patch_session(monkeypatch: pytest.MonkeyPatch, session) -> None:
    async def fake_get_session(db, session_id):
        return session

    monkeypatch.setattr(repos, "get_session", fake_get_session)


def _session(*, user_id=USER, company_id=COMPANY_A):
    return SimpleNamespace(id=uuid.uuid4(), user_id=user_id, company_id=company_id)


async def test_missing_session_is_not_found(monkeypatch):
    _patch_session(monkeypatch, None)
    with pytest.raises(SessionNotFoundError):
        await require_owned_session(None, uuid.uuid4(), USER)


async def test_other_users_session_is_denied(monkeypatch):
    _patch_session(monkeypatch, _session(user_id=uuid.uuid4()))
    with pytest.raises(SessionAccessDeniedError):
        await require_owned_session(None, uuid.uuid4(), USER)


async def test_user_only_check_ignores_company(monkeypatch):
    session = _session(company_id=COMPANY_B)
    _patch_session(monkeypatch, session)
    assert await require_owned_session(None, session.id, USER) is session


async def test_company_binding_accepts_same_company(monkeypatch):
    session = _session(company_id=COMPANY_A)
    _patch_session(monkeypatch, session)
    assert await require_owned_session(None, session.id, USER, company_id=COMPANY_A) is session


async def test_company_binding_denies_own_session_in_other_company(monkeypatch):
    _patch_session(monkeypatch, _session(company_id=COMPANY_B))
    with pytest.raises(SessionAccessDeniedError):
        await require_owned_session(None, uuid.uuid4(), USER, company_id=COMPANY_A)
