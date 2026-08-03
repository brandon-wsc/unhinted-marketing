import uuid

import pytest


@pytest.mark.asyncio
async def test_signals_top_requires_auth(client) -> None:
    res = await client.get("/api/signals/top")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_recommended_questions_requires_auth(client) -> None:
    res = await client.get(f"/api/companies/{uuid.uuid4()}/recommended-questions")
    assert res.status_code == 401
