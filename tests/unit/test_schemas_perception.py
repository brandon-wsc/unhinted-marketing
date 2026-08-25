import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from schemas.perception import (
    RecommendedQuestionItem,
    RecommendedQuestionsGenerating,
    RecommendedQuestionsResponse,
    SignalMetrics,
    SignalResponse,
    TopSignalsResponse,
)


def test_signal_metrics_defaults() -> None:
    metrics = SignalMetrics()
    assert metrics.rank is None
    assert metrics.keyword is None


def test_signal_response_roundtrip() -> None:
    now = datetime.now(UTC)
    sig = SignalResponse(
        signal_id="hk-1",
        source="google_trends",
        title="Hong Kong weather",
        url="https://example.com",
        excerpt="hot",
        region="HK",
        metrics={"rank": 1},
        ingested_at=now,
    )
    assert sig.signal_id == "hk-1"
    assert sig.metrics["rank"] == 1


def test_top_signals_response() -> None:
    body = TopSignalsResponse(region="HK", count=0, signals=[])
    assert body.count == 0
    assert body.signals == []


def test_recommended_question_item_defaults() -> None:
    item = RecommendedQuestionItem(id="q1", text="點樣推廣？")
    assert item.rationale is None
    assert item.source_signal_ids == []
    assert item.persona_slug is None


def test_recommended_questions_response() -> None:
    now = datetime.now(UTC)
    company_id = uuid.uuid4()
    body = RecommendedQuestionsResponse(
        company_id=company_id,
        questions=[RecommendedQuestionItem(id="q1", text="Hello?")],
        source_signal_ids=["s1"],
        generated_at=now,
        expires_at=now,
    )
    assert body.is_stale is False
    assert body.run_status == "idle"
    assert body.company_id == company_id


def test_recommended_question_requires_text() -> None:
    with pytest.raises(ValidationError):
        RecommendedQuestionItem(id="q1")


def test_recommended_questions_generating() -> None:
    company_id = uuid.uuid4()
    run_id = uuid.uuid4()
    body = RecommendedQuestionsGenerating(
        company_id=company_id, run_id=run_id, status="running"
    )
    assert body.retry_after_seconds == 3
    failed = RecommendedQuestionsGenerating(company_id=company_id, status="failed")
    assert failed.run_id is None
