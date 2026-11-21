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


def _write_payload(**extra) -> dict:
    base = {
        "user_request": "幫我改下",
        "company": {"name": "美心"},
        "voice_pack": {"roast_level": 1},
        "active_persona": "hk_gen_z",
        "brief": {"angles": ["a"]},
        "draft": {"caption": "舊 caption", "hashtags": ["#x"], "cta": "c"},
        "ranked_signals": [{"signal_id": "s9", "title": "t9"}],
        "signals_trusted": True,
        "source_signal_ids": ["s1"],
        "primary_product": None,
        "related_products": [],
        "chosen_angle": "a",
        "image_format": "single",
        "need_image": True,
        "hold_image_park": False,
        "reviewer_feedback": "",
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_run_draft_post_seam_and_ref_filter(monkeypatch) -> None:
    """DraftOut seam kept; refs filtered to the source_signal_ids allowlist."""
    from internal.session import execute_harness as EH
    from internal.session.io import DraftOut

    async def fake_exec(prompt: str) -> DraftOut:
        return DraftOut(
            caption="新 caption",
            hashtags=["#hk"],
            cta="留言",
            source_signal_ids=["s1", "bogus"],
        )

    monkeypatch.setattr(EH, "run_executor_post_agent", fake_exec)
    result = await DH.run_draft_post(_write_payload())
    update = result.state_update
    assert update["draft"]["caption"] == "新 caption"
    assert update["source_signal_ids"] == ["s1"]
    assert update["need_image"] is True
    assert update["grounding_ok"] is True
    assert update["chosen_angle"] is None
    assert json.loads(result.reply)["drafted"] is True


@pytest.mark.asyncio
async def test_run_draft_post_fallback_on_parse_miss(monkeypatch) -> None:
    """Parse miss → deterministic fallback draft referencing the top signal."""
    from internal.session import execute_harness as EH

    async def fake_exec(prompt: str):
        return None

    monkeypatch.setattr(EH, "run_executor_post_agent", fake_exec)
    result = await DH.run_draft_post(_write_payload())
    update = result.state_update
    assert "t9" in update["draft"]["caption"]
    assert update["source_signal_ids"] == ["s1"]


@pytest.mark.asyncio
async def test_run_draft_post_provider_error_falls_back(monkeypatch) -> None:
    """LlmProviderError ≡ parse miss — the tool degrades, not dies."""
    from internal.llm.router import LlmProviderError
    from internal.session import execute_harness as EH

    async def fake_exec(prompt: str):
        raise LlmProviderError("provider down")

    monkeypatch.setattr(EH, "run_executor_post_agent", fake_exec)
    result = await DH.run_draft_post(_write_payload())
    assert result.state_update["draft"]["caption"]


@pytest.mark.asyncio
async def test_run_revise_draft_keeps_pending_image(monkeypatch) -> None:
    """Caption-only edit still owes the image the draft demanded (ADR 0036)."""
    from internal.session import execute_harness as EH
    from internal.session.io import EditOut

    async def fake_edit(prompt: str) -> EditOut:
        return EditOut(
            caption="改咗",
            hashtags=["#hk"],
            cta="留言",
            need_image=False,
            source_signal_ids=["s9"],
        )

    monkeypatch.setattr(EH, "run_edit_copy_agent", fake_edit)
    result = await DH.run_revise_draft(
        _write_payload(user_request="改成短啲", need_image=True)
    )
    update = result.state_update
    assert update["draft"]["caption"] == "改咗"
    # Ranked pool ids are citable for revise even when not previously cited.
    assert update["source_signal_ids"] == ["s9"]
    assert update["need_image"] is True
    assert update["grounding_ok"] is True


@pytest.mark.asyncio
async def test_run_revise_draft_format_change_sets_image(monkeypatch) -> None:
    from internal.session import execute_harness as EH
    from internal.session.io import EditOut

    async def fake_edit(prompt: str) -> EditOut:
        return EditOut(caption="改咗", need_image=False, source_signal_ids=[])

    monkeypatch.setattr(EH, "run_edit_copy_agent", fake_edit)
    result = await DH.run_revise_draft(
        _write_payload(user_request="換做四格漫畫", need_image=False)
    )
    update = result.state_update
    assert update["image_format"] == "comic_4panel"
    assert update["need_image"] is True
    # Fallback refs keep the previously cited set.
    assert update["source_signal_ids"] == ["s1"]


@pytest.mark.asyncio
async def test_run_revise_draft_fallback_appends_note(monkeypatch) -> None:
    from internal.session import execute_harness as EH

    async def fake_edit(prompt: str):
        return None

    monkeypatch.setattr(EH, "run_edit_copy_agent", fake_edit)
    result = await DH.run_revise_draft(_write_payload(user_request="改 caption"))
    caption = result.state_update["draft"]["caption"]
    assert caption.startswith("舊 caption")
    assert "修訂" in caption
