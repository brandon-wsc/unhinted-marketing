"""Eager media GC on session delete (ADR 0024 §5) — best-effort, refcount-aware."""

from __future__ import annotations

import pytest

from internal.media import gc

KEY_A = "sessions/a/r1-aa11.png"
KEY_B = "sessions/a/r2-bb22.png"


@pytest.mark.asyncio
async def test_reclaim_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed object delete logs and never raises; later keys are still attempted."""
    attempted: list[str] = []

    async def no_refs(db, key: str) -> list[str]:
        return []

    async def boom(key: str) -> None:
        attempted.append(key)
        raise RuntimeError("store unreachable")

    monkeypatch.setattr(gc.repos, "list_matching_media_refs", no_refs)
    monkeypatch.setattr(gc, "delete_key", boom)

    await gc.reclaim_unreferenced_keys(None, [KEY_A, KEY_B])
    assert attempted == [KEY_A, KEY_B]


@pytest.mark.asyncio
async def test_reclaim_skips_still_referenced_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refcount: a key peeled from a remaining row (e.g. fork) is not deleted."""
    deleted: list[str] = []

    async def refs(db, key: str) -> list[str]:
        # KEY_A still referenced via a legacy baked URL; KEY_B is refcount-zero.
        return [f"https://old.example/api/media/{key}"] if key == KEY_A else []

    async def record(key: str) -> None:
        deleted.append(key)

    monkeypatch.setattr(gc.repos, "list_matching_media_refs", refs)
    monkeypatch.setattr(gc, "delete_key", record)

    await gc.reclaim_unreferenced_keys(None, [KEY_A, KEY_B])
    assert deleted == [KEY_B]
