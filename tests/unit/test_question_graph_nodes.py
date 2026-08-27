"""Question worker graph nodes — mocked LLM / repos, no live API."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from internal.perception.question_graph import nodes as Q
from internal.perception.question_graph.graph import build_question_graph
from internal.perception.question_graph.prompts import COMPOSE_SYSTEM


def _sig(sid: str, title: str, *, excerpt: str = "") -> dict:
    return {
        "signal_id": sid,
        "source": "google_trends_hk",
        "title": title,
        "url": None,
        "excerpt": excerpt,
        "metrics": {},
    }


def _state(**extra):
    state = {
        "run_id": "11111111-1111-1111-1111-111111111111",
        "company_id": "22222222-2222-2222-2222-222222222222",
        "company_name": "豆豆咖啡",
        "company_slug": "doudou-coffee",
        "profile": {"category": "咖啡"},
        "voice": {"craft": "hk_social_editor", "roast_level": 1, "locale": "zh-HK"},
        "audience": [{"slug": "office", "label": "上班族", "hook": "下午茶"}],
        "product_names": ["燕麥拿鐵"],
        "recent_texts": [],
        "quality_flags": [],
        "signals": [
            _sig("s-coffee", "香港咖啡節"),
            _sig("s-celeb", "某明星緋聞"),
            _sig("s-typhoon", "颱風訊號"),
        ],
    }
    state.update(extra)
    return state


@pytest.fixture
def no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Q, "has_llm_credentials", lambda: False)
    monkeypatch.setattr(Q, "has_tavily_credentials", lambda: False)


@pytest.mark.asyncio
async def test_cheap_screen_fingerprint_heuristic(no_llm: None) -> None:
    out = await Q.cheap_screen(_state())
    ids = {s["signal_id"] for s in out["shortlisted"]}
    assert "s-coffee" in ids
    assert "s-celeb" not in ids
    assert "screen_heuristic_only" in out["quality_flags"]
    assert "screen_thin" in out["quality_flags"]


@pytest.mark.asyncio
async def test_cheap_screen_cold_start_diversity(no_llm: None) -> None:
    out = await Q.cheap_screen(
        _state(company_name="", profile={}, product_names=[], audience=[], signals=[_sig("s1", "熱話A")])
    )
    assert out["shortlisted"][0]["signal_id"] == "s1"
    assert "cold_start_diversity" in out["quality_flags"]


@pytest.mark.asyncio
async def test_filter_blocks_named_org(monkeypatch: pytest.MonkeyPatch, no_llm: None) -> None:
    other = SimpleNamespace(name="對手茶飲")
    monkeypatch.setattr(Q, "get_db", lambda: AsyncMock())
    monkeypatch.setattr(Q, "list_companies", AsyncMock(return_value=[other]))
    out = await Q.filter_candidates(
        _state(
            researched=[
                _sig("s-rival", "對手茶飲推出新品"),
                _sig("s-ok", "咖啡節周末人潮"),
            ]
        )
    )
    ids = {s["signal_id"] for s in out["filtered"]}
    assert "s-rival" not in ids
    assert "s-ok" in ids
    assert "org_mentions_blocked" in out["quality_flags"]


@pytest.mark.asyncio
async def test_compose_skips_fake_signal_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Q, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return json.dumps(
            {
                "questions": [
                    {
                        "id": "q-fake",
                        "text": "跟呢個假 signal？",
                        "source_signal_ids": ["not-a-real-id"],
                    },
                    {
                        "id": "q-ok",
                        "text": "香港咖啡節可以點出？",
                        "source_signal_ids": ["s-coffee"],
                        "rationale": "場景夠近",
                    },
                ]
            }
        )

    monkeypatch.setattr(Q, "complete_json", fake_complete_json)
    out = await Q.compose_questions(_state(deep=[_sig("s-coffee", "香港咖啡節")]))
    ids = {q["id"] for q in out["questions"]}
    assert "q-fake" not in ids
    assert "q-ok" in ids
    assert out["used_signal_ids"] == ["s-coffee"]


@pytest.mark.asyncio
async def test_compose_dedupes_recent_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Q, "has_llm_credentials", lambda: True)
    recent = "香港咖啡節可以點出？"

    async def fake_complete_json(**_kwargs):
        return json.dumps(
            {
                "questions": [
                    {"id": "q1", "text": recent, "source_signal_ids": ["s-coffee"]},
                    {
                        "id": "q2",
                        "text": "燕麥拿鐵點樣夾呢個熱話？",
                        "source_signal_ids": ["s-coffee"],
                    },
                ]
            }
        )

    monkeypatch.setattr(Q, "complete_json", fake_complete_json)
    out = await Q.compose_questions(
        _state(deep=[_sig("s-coffee", "香港咖啡節")], recent_texts=[recent])
    )
    texts = {q["text"] for q in out["questions"]}
    assert recent not in texts
    assert any("燕麥拿鐵" in t for t in texts)


@pytest.mark.asyncio
async def test_compose_template_pad_uses_real_ids(no_llm: None) -> None:
    cand = [_sig("s-coffee", "香港咖啡節"), _sig("s-typhoon", "颱風訊號")]
    out = await Q.compose_questions(_state(deep=cand))
    assert 1 <= len(out["questions"]) <= 2
    valid = {"s-coffee", "s-typhoon"}
    for q in out["questions"]:
        assert q["source_signal_ids"]
        assert set(q["source_signal_ids"]) <= valid
    assert "template_only" in out["quality_flags"]
    by_title = {c["signal_id"]: c["title"] for c in cand}
    q_keys = [Q.topic_key(by_title[q["source_signal_ids"][0]]) for q in out["questions"]]
    assert len(q_keys) == len(set(q_keys))


def test_question_graph_compiles() -> None:
    graph = build_question_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_execute_guarded_rolls_back_before_marking_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal.perception.question_graph import runner as R

    fake_db = SimpleNamespace(rolled_back=False)
    finished: dict = {}

    async def fake_rollback() -> None:
        fake_db.rolled_back = True

    async def fake_get(_cls, run_id):
        assert fake_db.rolled_back
        return SimpleNamespace(id=run_id, status="running")

    async def fake_commit() -> None:
        pass

    fake_db.rollback = fake_rollback
    fake_db.get = fake_get
    fake_db.commit = fake_commit

    class _SessionCM:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, *_exc):
            return False

    class _SemCM:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    async def boom(*_a, **_k):
        raise RuntimeError("ingest boom")

    async def fake_finish(_db, _run, **kwargs):
        finished.update(kwargs)

    monkeypatch.setattr(R, "SessionLocal", lambda: _SessionCM())
    monkeypatch.setattr(R, "_get_semaphore", lambda: _SemCM())
    monkeypatch.setattr(R, "_execute", boom)
    monkeypatch.setattr(R, "finish_question_run", fake_finish)
    await R._execute_guarded(run_id=uuid.uuid4(), company_id=uuid.uuid4())
    assert fake_db.rolled_back
    assert finished["status"] == "failed"
    assert "ingest boom" in finished["error"]


def test_refresh_abandons_run_without_live_worker() -> None:
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from internal.perception.question_graph import runner as R

    run_id = uuid.uuid4()
    zombie = SimpleNamespace(
        id=run_id, started_at=datetime.now(UTC) - timedelta(minutes=2)
    )
    R._live_run_ids.discard(run_id)
    assert R._should_abandon(zombie, R.TRIGGER_REFRESH)
    R._live_run_ids.add(run_id)
    try:
        assert not R._should_abandon(zombie, R.TRIGGER_REFRESH)
    finally:
        R._live_run_ids.discard(run_id)


def test_compose_prompt_bans_mainland_traffic_jargon() -> None:
    assert "流量" in COMPOSE_SYSTEM
    assert "衝流量" in COMPOSE_SYSTEM
    assert "包裝成 IG Carousel" in COMPOSE_SYSTEM
    assert "like / follow" in COMPOSE_SYSTEM


def test_compose_prompt_keeps_voice_light_on_serious_topics() -> None:
    assert "Topic vs voice" in COMPOSE_SYSTEM
    assert "時事節目" in COMPOSE_SYSTEM
    assert "政策評論" in COMPOSE_SYSTEM
    assert "你覺得呢個制度公唔公平" in COMPOSE_SYSTEM
    assert "輕鬆小編" in COMPOSE_SYSTEM
    assert "政府通告" in COMPOSE_SYSTEM


def test_fallback_templates_are_unhinted_voice() -> None:
    joined = " ".join(Q.FALLBACK_TEMPLATES)
    assert "針對香港市場" not in joined
    assert "利用" not in joined
    assert "有畫面" in joined
    assert "板起塊面" in joined


@pytest.mark.asyncio
async def test_compose_passes_scene_emotion_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Q, "has_llm_credentials", lambda: True)
    seen: dict = {}

    async def fake_complete_json(**kwargs):
        seen.update(kwargs)
        return json.dumps(
            {
                "questions": [
                    {
                        "id": "q-ok",
                        "text": "香港咖啡節排隊等到心急，點出 post 先有畫面？",
                        "source_signal_ids": ["s-coffee"],
                    }
                ]
            }
        )

    monkeypatch.setattr(Q, "complete_json", fake_complete_json)
    cand = _sig("s-coffee", "香港咖啡節")
    cand["scene"] = "排隊買手沖"
    cand["emotion"] = "等到心急"
    cand["products"] = ["燕麥拿鐵"]
    await Q.compose_questions(_state(deep=[cand]))
    assert "排隊買手沖" in seen["user"]
    assert "等到心急" in seen["user"]
    assert "燕麥拿鐵" in seen["user"]


def test_topic_key_collapses_ip_variants() -> None:
    assert Q.topic_key("Chiikawa 展覽") == Q.topic_key("Chiikawa 聯乘")
    assert Q.topic_key("Chiikawa 展覽") == "chiikawa"


@pytest.mark.asyncio
async def test_ensure_signals_uses_timing_sources_only(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []
    rows = [
        SimpleNamespace(
            signal_id=f"s{i}",
            source="google_trends_hk",
            title=f"t{i}",
            url=None,
            excerpt="",
            metrics={},
        )
        for i in range(8)
    ]

    async def fake_list(_db, **kwargs):
        seen.append(kwargs)
        return rows

    monkeypatch.setattr(Q, "get_db", lambda: AsyncMock())
    monkeypatch.setattr(Q, "list_top_signals", fake_list)
    out = await Q.ensure_signals(_state())
    assert seen[0]["sources"] == list(Q.TIMING_SOURCES)
    assert "tavily" not in seen[0]["sources"]
    assert len(out["signals"]) == 8


@pytest.mark.asyncio
async def test_cheap_screen_caps_chiikawa_cluster(no_llm: None) -> None:
    signals = [_sig(f"ck{i}", f"Chiikawa 展覽{i}") for i in range(5)]
    signals.append(_sig("s-coffee", "香港咖啡節"))
    out = await Q.cheap_screen(_state(signals=signals))
    chiikawa = [s for s in out["shortlisted"] if Q.topic_key(s["title"]) == "chiikawa"]
    assert len(chiikawa) <= 1
    assert any(s["signal_id"] == "s-coffee" for s in out["shortlisted"])
    assert "s-coffee" in {s["signal_id"] for s in out["shortlisted"]}


@pytest.mark.asyncio
async def test_cheap_screen_llm_keep_all_still_caps_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals = [_sig(f"ck{i}", f"Chiikawa 展覽{i}") for i in range(5)]
    signals.append(_sig("s-coffee", "香港咖啡節"))
    monkeypatch.setattr(Q, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return json.dumps({"keep": [s["signal_id"] for s in signals]})

    monkeypatch.setattr(Q, "complete_json", fake_complete_json)
    out = await Q.cheap_screen(_state(signals=signals))
    chiikawa = [s for s in out["shortlisted"] if Q.topic_key(s["title"]) == "chiikawa"]
    assert len(chiikawa) == 1
    assert any(s["signal_id"] == "s-coffee" for s in out["shortlisted"])


@pytest.mark.asyncio
async def test_cheap_screen_does_not_restore_dropped_chiikawa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals = [_sig(f"ck{i}", f"Chiikawa 展覽{i}") for i in range(5)]
    signals.append(_sig("s-coffee", "香港咖啡節"))
    monkeypatch.setattr(Q, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return json.dumps({"keep": ["s-coffee"]})

    monkeypatch.setattr(Q, "complete_json", fake_complete_json)
    out = await Q.cheap_screen(_state(signals=signals))
    ids = {s["signal_id"] for s in out["shortlisted"]}
    assert "s-coffee" in ids
    assert not any(Q.topic_key(s["title"]) == "chiikawa" for s in out["shortlisted"])


@pytest.mark.asyncio
async def test_cheap_screen_llm_empty_keep_does_not_wipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Q, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return json.dumps({"keep": []})

    monkeypatch.setattr(Q, "complete_json", fake_complete_json)
    out = await Q.cheap_screen(
        _state(
            signals=[
                _sig("s-a", "破邊洲預約"),
                _sig("s-b", "颱風訊號"),
                _sig("s-c", "加息"),
            ]
        )
    )
    ids = {s["signal_id"] for s in out["shortlisted"]}
    assert {"s-a", "s-b", "s-c"} <= ids
    assert "screen_llm_empty" in out["quality_flags"]
    assert "screen_empty_fallback" in out["quality_flags"]


@pytest.mark.asyncio
async def test_filter_drops_no_bridge_ip(monkeypatch: pytest.MonkeyPatch, no_llm: None) -> None:
    monkeypatch.setattr(Q, "get_db", lambda: AsyncMock())
    monkeypatch.setattr(Q, "list_companies", AsyncMock(return_value=[]))
    out = await Q.filter_candidates(
        _state(
            researched=[
                _sig("s-ck", "Chiikawa 展覽"),
                _sig("s-coffee", "香港咖啡節"),
            ]
        )
    )
    ids = {s["signal_id"] for s in out["filtered"]}
    assert "s-ck" not in ids
    assert "s-coffee" in ids
    assert "no_bridge_ip_blocked" in out["quality_flags"]


@pytest.mark.asyncio
async def test_compose_caps_chiikawa_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Q, "has_llm_credentials", lambda: True)
    cands = [_sig(f"ck{i}", f"Chiikawa 展覽{i}") for i in range(5)]
    cands.append(_sig("s-coffee", "香港咖啡節"))

    async def fake_complete_json(**_kwargs):
        return json.dumps(
            {
                "questions": [
                    {
                        "id": f"q{i}",
                        "text": f"Chiikawa 展覽{i} 點出好？",
                        "source_signal_ids": [f"ck{i}"],
                    }
                    for i in range(5)
                ]
            }
        )

    monkeypatch.setattr(Q, "complete_json", fake_complete_json)
    out = await Q.compose_questions(_state(deep=cands))
    ck = [q for q in out["questions"] if "chiikawa" in q["text"].lower()]
    assert len(ck) <= 1


@pytest.mark.asyncio
async def test_compose_skips_recent_signal_combo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Q, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return json.dumps(
            {
                "questions": [
                    {
                        "id": "q1",
                        "text": "再問一次咖啡節？",
                        "source_signal_ids": ["s-coffee"],
                    },
                    {
                        "id": "q2",
                        "text": "颱風日點出限時飲品？",
                        "source_signal_ids": ["s-typhoon"],
                    },
                ]
            }
        )

    monkeypatch.setattr(Q, "complete_json", fake_complete_json)
    out = await Q.compose_questions(
        _state(
            deep=[_sig("s-coffee", "香港咖啡節"), _sig("s-typhoon", "颱風訊號")],
            recent_signal_ids=["s-coffee"],
        )
    )
    ids = {q["id"] for q in out["questions"]}
    assert "q1" not in ids
    assert "q2" in ids
