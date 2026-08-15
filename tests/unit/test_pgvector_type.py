"""Unit tests for asyncpg-safe pgvector bind processor."""

from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg

from internal.memory.embeddings import EMBEDDING_DIM
from internal.memory.pgvector_type import Vector


def test_asyncpg_bind_processor_keeps_list() -> None:
    dialect = PGDialect_asyncpg()
    process = Vector(EMBEDDING_DIM).bind_processor(dialect)
    vec = [0.01] * EMBEDDING_DIM
    bound = process(vec)
    assert isinstance(bound, list)
    assert bound[0] == 0.01
    assert process(None) is None
