"""Fake HK signals for session node unit tests (no DB)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def fake_signal(
    signal_id: str,
    *,
    title: str = "香港熱話",
    source: str = "google_trends",
    excerpt: str | None = "excerpt",
    metrics: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        signal_id=signal_id,
        source=source,
        title=title,
        excerpt=excerpt,
        metrics=metrics or {"rank": 1},
        url=None,
        region="HK",
    )
