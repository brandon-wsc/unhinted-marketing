import pytest


@pytest.mark.asyncio
async def test_health(client) -> None:
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
