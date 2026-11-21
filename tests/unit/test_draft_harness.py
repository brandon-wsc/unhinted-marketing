"""ADR 0062 draft_harness — propose_angles tool body, mocked LLM + repos."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from internal.session import draft_harness as DH
from internal.session.context import session_db
from internal.session.state import MODE_AGENT
from tests.unit.lc_fakes import _ScriptedChat, out_call


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    DH.set_trend_model_override(None)
    DH.set_brainstorm_model_override(None)
    yield
    DH.set_trend_model_override(None)
    DH.set_brainstorm_model_override(None)


def _scripted(*msgs: AIMessage | str) -> _ScriptedChat:
    return _ScriptedChat(
        messages=iter([AIMessage(content=m) if isinstance(m, str) else m for m in msgs])
    )


def _payload(**extra) -> dict:
    base = {
        "user_request": "幫我做帖",
        "company_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "22222222-2222-2222-2222-222222222222",
        "research": {},
        "research_signals": [
            {"signal_id": "s1", "title": "t1", "source": "tavily"},
            {"signal_id": "s2", "title": "t2", "source": "tavily"},
        ],
        "source_signal_ids": ["s1", "s2"],
        "signals_trusted": True,
        "handoff_signal_ids": [],
        "prior_brief": {},
        "angle_feedback": None,
        "image_format": "single",
    }
    base.update(extra)
    return base


def _mock_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        DH,
        "get_company",
        AsyncMock(
            return_value=SimpleNamespace(
                id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                name="Test Co",
                slug="test-co",
                profile={},
            )
        ),
    )
    monkeypatch.setattr(DH, "ensure_default_personas", AsyncMock())
    monkeypatch.setattr(DH, "list_personas", AsyncMock(return_value=[]))
    monkeypatch.setattr(DH, "search_products_for_member", AsyncMock(return_value=[]))


@pytest.mark.asyncio
async def test_run_propose_angles_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_repos(monkeypatch)
    DH.set_trend_model_override(
        _scripted(out_call("TrendRank", {"ranked_signal_ids": ["s2", "s1"], "notes": "n"}))
    )
    DH.set_brainstorm_model_override(
        _scripted(
            out_call(
                "BriefOut",
                {
                    "angles": ["a1", "a2"],
                    "recommended_angle_index": 1,
                    "persona": "hk_gen_z",
                    "summary": "sum",
                },
            )
        )
    )
    with session_db(AsyncMock()):
        result = await DH.run_propose_angles(_payload())
    assert result.ready is True
    update = result.state_update
    assert update["mode"] == MODE_AGENT
    assert update["company_context"]["name"] == "Test Co"
    assert update["source_signal_ids"] == ["s2", "s1"]
    assert update["ranked_signals"][0]["signal_id"] == "s2"
    assert update["trend_notes"] == "n"
    assert update["brief"]["angles"] == ["a1", "a2"]
    assert update["brief"]["recommended_angle_index"] == 1
    assert update["angle_feedback"] is None
    reply = json.loads(result.reply)
    assert reply["angles"] == ["a1", "a2"]
    assert reply["recommended_angle_index"] == 1


@pytest.mark.asyncio
async def test_run_propose_angles_clarify_skips_brainstorm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambiguous product → clarify reply, no brief written, no brainstorm call."""
    _mock_repos(monkeypatch)
    hit = SimpleNamespace(
        product=SimpleNamespace(id=uuid.uuid4(), owner_scope="user")
    )
    monkeypatch.setattr(
        DH, "search_products_for_member", AsyncMock(return_value=[hit, hit])
    )
    monkeypatch.setattr(DH, "pick_primary", lambda _hits: (None, True))
    monkeypatch.setattr(
        DH, "hit_to_payload", lambda h: {"product_id": str(h.product.id)}
    )
    typed_calls: list[str] = []

    async def _counting(tier_key: str, *_a: object, **_kw: object) -> None:
        typed_calls.append(tier_key)
        return None

    monkeypatch.setattr(DH, "_run_typed", _counting)
    with session_db(AsyncMock()):
        result = await DH.run_propose_angles(_payload())
    assert result.ready is False
    assert "brainstormer" not in typed_calls
    assert "brief" not in result.state_update
    assert result.state_update["product_clarify"] is True
    reply = json.loads(result.reply)
    assert reply["clarify"] is True
    assert reply["candidates"]


@pytest.mark.asyncio
async def test_run_propose_angles_brainstorm_miss_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parse miss → deterministic fallback brief (matches legacy brainstormer)."""
    _mock_repos(monkeypatch)
    DH.set_trend_model_override(_scripted("sorry no structured output"))
    DH.set_brainstorm_model_override(_scripted("no output call either"))
    with session_db(AsyncMock()):
        result = await DH.run_propose_angles(_payload())
    assert result.ready is True
    brief = result.state_update["brief"]
    assert brief["angles"], "fallback brief always offers angles"
    # TrendRank parse miss → default first-8 ranked ids, no trend_notes.
    assert result.state_update["source_signal_ids"] == ["s1", "s2"]
    assert "trend_notes" not in result.state_update


@pytest.mark.asyncio
async def test_run_propose_angles_no_session_db() -> None:
    result = await DH.run_propose_angles(_payload())
    assert json.loads(result.reply) == {"error": "no_session_db"}
    assert result.state_update == {}
    assert result.ready is False
