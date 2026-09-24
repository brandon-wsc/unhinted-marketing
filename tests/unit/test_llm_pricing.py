"""Static price table lookup — never invent a price for unknown models."""

from __future__ import annotations

from internal.llm.pricing import normalize_model_id, price_for, summarize_usage, usd_for


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
