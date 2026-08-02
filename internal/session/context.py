"""Request-scoped DB session for LangGraph nodes (not checkpointed)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession

_db_var: ContextVar[AsyncSession | None] = ContextVar("session_db", default=None)


def get_db() -> AsyncSession:
    db = _db_var.get()
    if db is None:
        raise RuntimeError("Session DB context not set — call set_db() before graph.ainvoke")
    return db


@contextmanager
def session_db(db: AsyncSession) -> Iterator[AsyncSession]:
    token = _db_var.set(db)
    try:
        yield db
    finally:
        _db_var.reset(token)
