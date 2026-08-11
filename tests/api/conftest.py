"""API integration fixtures. Requires TEST_DATABASE_URL (never uses DATABASE_URL)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cmd.api.main import create_app
from internal.memory.database import get_db
from internal.session.graph import set_session_graph

REPO_ROOT = Path(__file__).resolve().parents[2]

TRUNCATE_TABLES = (
    "tool_receipts",
    "preview_drafts",
    "preview_images",
    "session_messages",
    "session_node_steps",
    "sessions",
    "llm_call_records",
    "recommended_questions",
    "edges",
    "raw_news_events",
    "products",
    "org_invites",
    "refresh_tokens",
    "organization_members",
    "entities",
    "users",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: API tests that need TEST_DATABASE_URL",
    )


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set — skipping API integration tests")
    return url


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    """Run alembic against the test DB (subprocess so settings load fresh)."""
    env = {**os.environ, "DATABASE_URL": test_database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    return test_database_url


@pytest_asyncio.fixture
async def engine(migrated_database: str):
    # Function-scoped: session-scoped async engines break across pytest-asyncio loops.
    from internal.memory.database import attach_pgvector

    eng = create_async_engine(migrated_database, echo=False, pool_pre_ping=True)
    attach_pgvector(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_db(engine, migrated_database: str):
    """Truncate app tables before each API test."""
    from internal.auth.rate_limit import reset_auth_rate_limiter

    reset_auth_rate_limiter()
    async with engine.begin() as conn:
        tables = ", ".join(TRUNCATE_TABLES)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    set_session_graph(None)
    yield
    set_session_graph(None)


@asynccontextmanager
async def _noop_lifespan(app):
    """Skip Postgres checkpointer; graph lazy-inits with MemorySaver if needed."""
    set_session_graph(None)
    try:
        yield
    finally:
        set_session_graph(None)


@pytest_asyncio.fixture
async def app(session_factory):
    application = create_app(lifespan_fn=_noop_lifespan)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = _override_get_db
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
        await session.rollback()
