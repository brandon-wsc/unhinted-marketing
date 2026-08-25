"""Run-scoped DB session for question-graph nodes (not checkpointed)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession

_db_var: ContextVar[AsyncSession | None] = ContextVar("question_graph_db", default=None)


def get_db() -> AsyncSession:
    db = _db_var.get()
    if db is None:
        raise RuntimeError("Question-graph DB context not set — set by the runner before invoke")
    return db


@contextmanager
def question_db(db: AsyncSession) -> Iterator[AsyncSession]:
    token = _db_var.set(db)
    try:
        yield db
    finally:
        _db_var.reset(token)
