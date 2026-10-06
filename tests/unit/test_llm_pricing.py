"""USD estimates: LiteLLM cost map first, static gap-fill — never guessed."""

from __future__ import annotations

import pytest

import internal.llm.pricing as pricing
from internal.llm.pricing import normalize_model_id, price_for, summarize_usage, usd_for

_FAKE_COST_MAP = {
    "litellm-model": {
        "input_cost_per_token": 1e-6,
        "output_cost_per_token": 2e-6,
        "cache_read_input_token_cost": 5e-7,
        "litellm_provider": "openai",
        "mode": "chat",
    },
    "no-price-fields": {"litellm_provider": "openai", "mode": "chat"},
    "free-model": {
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openai",
        "mode": "chat",
    },
}


@pytest.fixture(autouse=True)
def fake_cost_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin LiteLLM's map so tests never depend on the remote fetch or repricing."""
    monkeypatch.setattr(pricing, "_litellm_model_cost", lambda: _FAKE_COST_MAP)


def test_litellm_map_prices_known_model() -> None:
    # 1000 in * $1/1M + 500 out * $2/1M = 0.001 + 0.001
    assert abs(usd_for("litellm-model", 1000, 500) - 0.002) < 1e-12


def test_litellm_cached_tokens_billed_at_cache_rate() -> None:
    # 800 full-price in + 200 cache-read in + 100 out
    usd = usd_for("litellm-model", 1000, 100, cached_tokens=200)
    assert usd is not None
    assert abs(usd - (800 * 1e-6 + 200 * 5e-7 + 100 * 2e-6)) < 1e-12


def test_litellm_cached_tokens_capped_at_prompt() -> None:
    usd = usd_for("litellm-model", 100, 0, cached_tokens=5000)
    assert usd is not None
    assert abs(usd - 100 * 5e-7) < 1e-12


def test_litellm_entry_without_price_fields_falls_back() -> None:
    assert usd_for("no-price-fields", 1000, 1000) is None


def test_litellm_zero_cost_entry_is_unknown_not_zero() -> None:
    assert usd_for("free-model", 1000, 1000) is None


def test_litellm_map_unavailable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pricing, "_litellm_model_cost", lambda: None)
    usd = usd_for("gpt-4o-mini", 1_000_000, 500_000)
    assert usd is not None
    assert abs(usd - (0.15 + 0.30)) < 1e-9


def test_known_model_priced() -> None:
    usd = usd_for("gpt-4o-mini", 1_000_000, 500_000)
    assert usd is not None
    assert abs(usd - (0.15 + 0.30)) < 1e-9


def test_provider_prefix_normalized() -> None:
    assert normalize_model_id("openai/gpt-4o-mini") == "gpt-4o-mini"
    assert normalize_model_id("gemini/gemini-2.5-flash") == "gemini-2.5-flash"
    assert price_for("openai/gpt-4o") == price_for("gpt-4o")


def test_unknown_model_is_null_not_guessed() -> None:
    assert usd_for("my-fine-tune-9000", 1000, 1000) is None
    assert usd_for(None, 1000, 1000) is None
    assert usd_for("gpt-4o", None, None) is None


def test_summarize_usage_rollup() -> None:
    class _Rec:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    records = [
        _Rec(
            latency_ms=100,
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            model="gpt-4o-mini",
        ),
        _Rec(
            latency_ms=200,
            prompt_tokens=2000,
            completion_tokens=1000,
            total_tokens=3000,
            model="unknown-model-x",
        ),
    ]
    out = summarize_usage(records)
    assert out["calls"] == 2
    assert out["latency_ms"] == 300
    assert out["prompt_tokens"] == 3000
    assert out["total_tokens"] == 4500
    assert out["usd"] is None
    assert out["unknown_models"] == ["unknown-model-x"]


def test_summarize_usage_all_priced() -> None:
    class _Rec:
        latency_ms = 10
        model = "gpt-4o-mini"

        def __init__(self, p: int, c: int) -> None:
            self.prompt_tokens = p
            self.completion_tokens = c
            self.total_tokens = p + c

    out = summarize_usage([_Rec(1_000_000, 0)])
    assert out["usd"] is not None
    assert abs(out["usd"] - 0.15) < 1e-9
    assert out["unknown_models"] == []


def test_summarize_usage_empty() -> None:
    out = summarize_usage([])
    assert out["calls"] == 0
    assert out["total_tokens"] is None
    assert out["usd"] is None
    assert out["status_counts"] == {}


def test_summarize_usage_status_counts() -> None:
    class _Rec:
        latency_ms = 5
        prompt_tokens = 1
        completion_tokens = 1
        total_tokens = 2
        model = "gpt-4o-mini"

        def __init__(self, status: str) -> None:
            self.status = status

    out = summarize_usage([_Rec("ok"), _Rec("ok"), _Rec("provider_error")])
    assert out["status_counts"] == {"ok": 2, "provider_error": 1}


def test_summarize_usage_missing_status_defaults_ok() -> None:
    class _Rec:
        latency_ms = 5
        model = "gpt-4o-mini"

    out = summarize_usage([_Rec()])
    assert out["status_counts"] == {"ok": 1}


def test_summarize_usage_ttft_and_cached() -> None:
    class _Rec:
        latency_ms = 5
        model = "gpt-4o-mini"
        status = "ok"

        def __init__(self, ttft, cached) -> None:
            self.ttft_ms = ttft
            self.cached_tokens = cached

    out = summarize_usage([_Rec(120, 30), _Rec(None, None), _Rec(80, 10)])
    assert out["ttft_ms"] == [120, 80]
    assert out["cached_tokens"] == 40

    out = summarize_usage([_Rec(None, None)])
    assert out["ttft_ms"] == []
    assert out["cached_tokens"] is None
