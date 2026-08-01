from internal.session.checkpointer import checkpoint_conninfo


def test_strips_asyncpg_prefix() -> None:
    assert (
        checkpoint_conninfo("postgresql+asyncpg://user:pass@host:5432/db")
        == "postgresql://user:pass@host:5432/db"
    )


def test_strips_postgres_asyncpg_prefix() -> None:
    assert (
        checkpoint_conninfo("postgres+asyncpg://user:pass@host/db")
        == "postgresql://user:pass@host/db"
    )


def test_strips_psycopg_prefix() -> None:
    assert (
        checkpoint_conninfo("postgresql+psycopg://user:pass@host/db")
        == "postgresql://user:pass@host/db"
    )


def test_passthrough_plain_url() -> None:
    url = "postgresql://user:pass@host:5432/db"
    assert checkpoint_conninfo(url) == url
