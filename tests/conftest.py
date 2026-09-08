"""Shared pytest helpers (no DB required)."""

from pathlib import Path

import pytest

from internal.config import settings


@pytest.fixture(autouse=True)
def _disable_llm_record_persistence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Tests never write LLM/node-step records unless they explicitly opt in."""
    monkeypatch.setattr(settings, "llm_record_enabled", False)
    monkeypatch.setattr(settings, "node_trace_enabled", False)
    # Avoid FastEmbed model download in unit/CI; opt in per-test if needed.
    monkeypatch.setattr(settings, "semantic_router_enabled", False)
    monkeypatch.setattr(settings, "product_embeddings_enabled", False)
    # ADR 0022: never inherit PUBLISH_ADAPTER=instagram from a local .env.
    monkeypatch.setattr(settings, "publish_adapter", "stub")
    # ADR 0024: on-prem local store into a tmp dir (never the repo data/media).
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    monkeypatch.setattr(settings, "media_root", str(tmp_path / "media"))
