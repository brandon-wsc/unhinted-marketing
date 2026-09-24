"""Rough per-model list prices for eval/cost reporting — never authoritative.

USD per 1M tokens ``(input, output)``. Only ids we have actually resolved in
this stack belong here; unknown models return ``None`` so reports show
``usd: null`` instead of an invented number. Update as providers re-price.
"""

from __future__ import annotations

from typing import Any

# (input, output) USD per 1M tokens — provider list prices.
PRICE_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
}

# Provider/router prefixes that wrap a catalog id (see internal/llm/resolve.py).
_PROVIDER_PREFIXES = (
    "openai/",
    "openrouter/",
    "gemini/",
    "imagen/",
    "vertex_ai/",
    "anthropic/",
    "models/",
    "publishers/google/models/",
)


def normalize_model_id(model: str | None) -> str:
    """Reduce a recorded model id to its catalog leaf for price lookup."""
    raw = (model or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    for prefix in _PROVIDER_PREFIXES:
        if lowered.startswith(prefix):
            raw = raw[len(prefix) :]
            lowered = raw.lower()
    return raw


def price_for(model: str | None) -> tuple[float, float] | None:
    """List ``(input, output)`` USD per 1M for a model id, or None if unknown."""
    leaf = normalize_model_id(model)
    if not leaf:
        return None
    if leaf in PRICE_PER_1M:
        return PRICE_PER_1M[leaf]
    # Slash slugs such as ``deepseek/deepseek-v4-flash`` — try the bare leaf too.
    tail = leaf.split("/")[-1]
    return PRICE_PER_1M.get(tail)


def usd_for(
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    """Rough USD for one call; None when the model or usage is unknown."""
    price = price_for(model)
    if price is None:
        return None
    prompt = prompt_tokens or 0
    completion = completion_tokens or 0
    if prompt == 0 and completion == 0:
        return None
    return (prompt * price[0] + completion * price[1]) / 1_000_000


def summarize_usage(records: list[Any]) -> dict[str, Any]:
    """Aggregate LlmCallRecordBuilder-shaped records into one usage dict.

    ``usd`` is None unless every record with usage resolved a price —
    ``unknown_models`` lists the unpriced ids seen so reports stay honest.
    """
    prompt = 0
    completion = 0
    total = 0
    latency = 0
    usd = 0.0
    has_usage = False
    unknown: list[str] = []
    models: list[str] = []
    for rec in records:
        latency += int(getattr(rec, "latency_ms", None) or 0)
        p = getattr(rec, "prompt_tokens", None)
        c = getattr(rec, "completion_tokens", None)
        t = getattr(rec, "total_tokens", None)
        prompt += int(p or 0)
        completion += int(c or 0)
        total += int(t or 0)
        model = getattr(rec, "model", None)
        if model and model not in models:
            models.append(model)
        price = usd_for(model, p, c)
        if (p or c) and price is None:
            label = model or "unknown"
            if label not in unknown:
                unknown.append(label)
        if price is not None:
            usd += price
            has_usage = True
        elif p or c:
            has_usage = True  # tokens known, price unknown
    priced_all = not unknown
    return {
        "calls": len(records),
        "latency_ms": latency,
        "prompt_tokens": prompt or None,
        "completion_tokens": completion or None,
        "total_tokens": total or None,
        "usd": round(usd, 6) if has_usage and priced_all else None,
        "models": models,
        "unknown_models": unknown,
    }
