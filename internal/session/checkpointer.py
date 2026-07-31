"""LangGraph PostgreSQL checkpointer (tables owned by checkpointer.setup)."""

from __future__ import annotations

import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from internal.config import settings

logger = logging.getLogger(__name__)


def checkpoint_conninfo(database_url: str | None = None) -> str:
    """Convert SQLAlchemy async URL → psycopg conninfo."""
    url = database_url or settings.database_url
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


async def open_postgres_checkpointer() -> tuple[AsyncConnectionPool, AsyncPostgresSaver]:
    """Open a connection pool and AsyncPostgresSaver; run setup() for checkpoint tables.

    Idle Postgres (or Docker) may close sockets the pool still thinks are live —
    without ``check`` / keepalives, the next ``aget_state`` / ``ainvoke`` fails
    with ``server closed the connection unexpectedly``.
    """
    conninfo = checkpoint_conninfo()
    pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=10,
        # Recycle before common idle timeouts; validate every checkout.
        max_idle=300,
        max_lifetime=1800,
        check=AsyncConnectionPool.check_connection,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            # libpq TCP keepalives — detect silent server-side closes early.
            "keepalives": 1,
            "keepalives_idle": 60,
            "keepalives_interval": 15,
            "keepalives_count": 4,
        },
        open=False,
    )
    await pool.open()
    saver = AsyncPostgresSaver(conn=pool)
    await saver.setup()
    logger.info("LangGraph Postgres checkpointer ready")
    return pool, saver


async def close_postgres_checkpointer(pool: AsyncConnectionPool | None) -> None:
    if pool is not None:
        await pool.close()
