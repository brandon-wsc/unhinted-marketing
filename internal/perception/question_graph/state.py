"""State for the recommended-questions worker graph (ADR 0018).

Company-scoped, plain-data only — no checkpointer in v1, but keep the state
serializable so step I/O records stay inspectable.
"""

from __future__ import annotations

from typing import Any, TypedDict


class QuestionGraphState(TypedDict, total=False):
    run_id: str
    company_id: str
    trigger: str  # get_miss | refresh | scheduler

    # Preloaded by the runner before invoke
    company_name: str
    company_slug: str
    profile: dict[str, Any]
    voice: dict[str, Any]  # voice_pack output
    audience: list[dict[str, str]]  # audience_catalog rows
    product_names: list[str]  # org catalog product names (fingerprint + prompts)
    recent_texts: list[str]  # question texts served in the dedupe window
    recent_signal_ids: list[str]  # source_signal_ids served in the dedupe window

    # Pipeline data
    signals: list[dict[str, Any]]  # raw corpus (ensure_signals)
    shortlisted: list[dict[str, Any]]  # cheap_screen survivors
    researched: list[dict[str, Any]]  # shallow_research adds "research" snippets
    filtered: list[dict[str, Any]]  # filter survivors
    deep: list[dict[str, Any]]  # deep_research adds scene/emotion/constraints
    questions: list[dict[str, Any]]  # compose_questions output
    used_signal_ids: list[str]  # real refs bound by compose_questions

    quality_flags: list[str]
