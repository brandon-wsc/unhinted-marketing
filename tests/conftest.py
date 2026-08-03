"""Shared pytest helpers (no DB required)."""

import pytest

from internal.config import settings


@pytest.fixture(autouse=True)
def _disable_llm_record_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never write LLM/node-step records unless they explicitly opt in."""
    monkeypatch.setattr(settings, "llm_record_enabled", False)
    monkeypatch.setattr(settings, "node_trace_enabled", False)
