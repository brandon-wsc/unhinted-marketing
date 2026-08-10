from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from internal.config import settings

# pool_pre_ping: drop dead connections before checkout (idle Postgres kill /
# Docker restart). pool_recycle: force refresh before long-lived sockets go stale.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
)


def attach_pgvector(eng: AsyncEngine) -> None:
    """Register pgvector codecs on each asyncpg connection (COLLECT K4)."""

    @event.listens_for(eng.sync_engine, "connect")
    def _register_pgvector(dbapi_connection, _connection_record) -> None:
        try:
            from pgvector.asyncpg import register_vector

            dbapi_connection.run_async(register_vector)
        except Exception:
            # Extension may be missing on fresh DBs before migrate; retrieve falls back.
            return


attach_pgvector(engine)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
