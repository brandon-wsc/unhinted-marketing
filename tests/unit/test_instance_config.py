"""Instance settings seeding + Meta BYO creds (ADR 0026 / ADR 0032) — mocked repos."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from internal import config
from internal.instance.config import (
    _seed_meta_from_env,
    _snapshot_from_row,
    ensure_instance_settings_seeded,
    reset_snapshot_cache,
    snapshot_from_env,
)
from internal.llm.keys import decrypt_key
from internal.memory.models import InstanceSettings


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config.settings, "byok_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr(config.settings, "meta_app_id", "env-app-id")
    monkeypatch.setattr(config.settings, "meta_app_secret", "env-secret")
    monkeypatch.setattr(config.settings, "oauth_relay_url", None)
    monkeypatch.setattr(config.settings, "meta_oauth_instance_id", None)
    reset_snapshot_cache()


def _mock_repos(
    monkeypatch: pytest.MonkeyPatch, row: InstanceSettings | None
) -> tuple[AsyncMock, dict]:
    """Patch repos get/upsert against a single in-memory row holder."""
    from internal.instance import config as mod

    holder: dict[str, InstanceSettings | None] = {"row": row}

    async def fake_get(_db):
        return holder["row"]

    async def fake_upsert(_db, **fields):
        existing = holder["row"]
        if existing is None:
            existing = InstanceSettings(id=1)
            holder["row"] = existing
        for key, value in fields.items():
            setattr(existing, key, value)
        return existing

    upsert = AsyncMock(side_effect=fake_upsert)
    monkeypatch.setattr(mod.repos, "get_instance_settings", fake_get)
    monkeypatch.setattr(mod.repos, "upsert_instance_settings", upsert)
    return upsert, holder


async def test_seed_meta_from_env_backfills_null_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade path: env-configured installs keep working when the row exists
    but never had Meta creds (meta_app_id IS NULL)."""
    _configure(monkeypatch)
    row = InstanceSettings(id=1)
    _mock_repos(monkeypatch, row)
    db = AsyncMock()

    seeded = await _seed_meta_from_env(db, snapshot_from_env())

    assert seeded is True
    assert row.meta_app_id == "env-app-id"
    assert row.meta_app_secret_last4 == "cret"
    assert decrypt_key(row.meta_app_secret_encrypted) == "env-secret"
    db.commit.assert_awaited()


async def test_seed_meta_from_env_skips_portal_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portal clear stores "" — env must not resurrect creds on reboot."""
    _configure(monkeypatch)
    row = InstanceSettings(id=1, meta_app_id="")
    upsert, _ = _mock_repos(monkeypatch, row)
    db = AsyncMock()

    seeded = await _seed_meta_from_env(db, snapshot_from_env())

    # Only the generated relay instance_id is written — env creds stay out.
    assert seeded is True
    assert row.meta_app_id == ""
    fields = upsert.await_args.kwargs
    assert "meta_app_id" not in fields
    assert "meta_app_secret_encrypted" not in fields
    assert fields["meta_oauth_instance_id"]


async def test_seed_meta_from_env_skips_when_already_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    row = InstanceSettings(id=1, meta_app_id="portal-app")
    upsert, _ = _mock_repos(monkeypatch, row)
    db = AsyncMock()

    seeded = await _seed_meta_from_env(db, snapshot_from_env())

    # Creds are left alone; only the missing relay instance_id is generated.
    assert seeded is True
    fields = upsert.await_args.kwargs
    assert list(fields) == ["meta_oauth_instance_id"]
    assert fields["meta_oauth_instance_id"]


async def test_ensure_seeded_creates_row_with_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    _, holder = _mock_repos(monkeypatch, None)
    db = AsyncMock()

    await ensure_instance_settings_seeded(db)

    row = holder["row"]
    assert row is not None
    assert row.meta_app_id == "env-app-id"
    assert decrypt_key(row.meta_app_secret_encrypted) == "env-secret"
    from internal.instance import config as mod

    snap = mod.get_snapshot()
    assert snap.meta_app_id == "env-app-id"
    assert snap.meta_app_secret == "env-secret"
    assert snap.meta_oauth_mode == "byo"


async def test_ensure_seeded_existing_row_backfills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    row = InstanceSettings(id=1)
    _mock_repos(monkeypatch, row)
    db = AsyncMock()

    await ensure_instance_settings_seeded(db)

    assert row.meta_app_id == "env-app-id"
    from internal.instance import config as mod

    assert mod.get_snapshot().meta_app_secret == "env-secret"


async def test_snapshot_from_row_handles_undecryptable_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    row = InstanceSettings(
        id=1, meta_app_id="app", meta_app_secret_encrypted="not-fernet"
    )
    snap = _snapshot_from_row(row)
    assert snap.meta_app_id == "app"
    assert snap.meta_app_secret == ""
    assert snap.meta_oauth_mode == "byo"


async def test_snapshot_from_row_meta_oauth_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    assert _snapshot_from_row(InstanceSettings(id=1, meta_oauth_mode="relay")).meta_oauth_mode == "relay"
    # Unknown values fall back to byo rather than leaking through.
    assert _snapshot_from_row(InstanceSettings(id=1, meta_oauth_mode="bogus")).meta_oauth_mode == "byo"
