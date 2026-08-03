"""Happy-path signals + recommended-questions (beyond auth-only checks)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from internal.memory import repos
from tests.api.helpers import auth_header, register_user


@pytest.mark.asyncio
async def test_signals_top_empty(client) -> None:
    data = await register_user(client)
    res = await client.get("/api/signals/top", headers=auth_header(data["access_token"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["region"] == "HK"
    assert body["count"] == 0
    assert body["signals"] == []


@pytest.mark.asyncio
async def test_signals_top_with_rows(client, db_session) -> None:
    data = await register_user(client)
    await repos.upsert_signal(
        db_session,
        signal_id=f"sig-{uuid.uuid4().hex[:8]}",
        source="google_trends",
        title="HK typhoon",
        url="https://example.com/typhoon",
        excerpt="weather",
        metrics={"rank": 1, "keyword": "typhoon"},
        region="HK",
    )
    await db_session.commit()

    res = await client.get("/api/signals/top", headers=auth_header(data["access_token"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] >= 1
    assert body["signals"][0]["title"] == "HK typhoon"


@pytest.mark.asyncio
async def test_recommended_questions_not_ready(client) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    res = await client.get(
        f"/api/companies/{company_id}/recommended-questions",
        headers=auth_header(data["access_token"]),
    )
    assert res.status_code == 404
    assert "question-generator" in res.json()["detail"]


@pytest.mark.asyncio
async def test_recommended_questions_happy_path(client, db_session) -> None:
    data = await register_user(client)
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    await repos.save_recommended_questions(
        db_session,
        company_id=company_id,
        questions=[
            {
                "id": "q1",
                "text": "點樣用呢個 trend 做 content？",
                "rationale": "hot",
                "source_signal_ids": ["s1"],
                "persona_slug": "brand_manager",
            }
        ],
        source_signal_ids=["s1"],
        ttl_hours=12,
    )
    await db_session.commit()

    res = await client.get(
        f"/api/companies/{company_id}/recommended-questions",
        headers=auth_header(data["access_token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["company_id"] == str(company_id)
    assert body["is_stale"] is False
    assert body["questions"][0]["id"] == "q1"
    assert body["source_signal_ids"] == ["s1"]


@pytest.mark.asyncio
async def test_recommended_questions_stale(client, db_session) -> None:
    data = await register_user(client)
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    row = await repos.save_recommended_questions(
        db_session,
        company_id=company_id,
        questions=[{"id": "q1", "text": "Old?"}],
        source_signal_ids=[],
        ttl_hours=1,
    )
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    res = await client.get(
        f"/api/companies/{company_id}/recommended-questions",
        headers=auth_header(data["access_token"]),
    )
    assert res.status_code == 200
    assert res.json()["is_stale"] is True
