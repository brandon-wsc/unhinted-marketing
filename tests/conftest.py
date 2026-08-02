"""Shared pytest helpers (no DB required)."""

import pytest

from internal.config import settings


@pytest.fixture(autouse=True)
def _disable_llm_record_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never write LLM call records unless they explicitly opt in (ADR 0005)."""
    monkeypatch.setattr(settings, "llm_record_enabled", False)
