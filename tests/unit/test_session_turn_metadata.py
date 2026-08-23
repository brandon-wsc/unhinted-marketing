from __future__ import annotations

from internal.session.service import user_turn_metadata


def test_user_turn_metadata_empty_without_progress() -> None:
    assert user_turn_metadata({}, [], 12_000) is None
    assert user_turn_metadata({"keep": 1}, [], None) is None


def test_user_turn_metadata_stores_actions_and_duration() -> None:
    events = [
        {"type": "agent.progress", "data": {"node": "reviewer", "model_tier": "strong"}},
        {"type": "brief.updated", "data": {"summary": "x"}},
        {"type": "agent.progress", "data": {"node": "chat", "model": "m"}},
    ]
    meta = user_turn_metadata({"keep": True}, events, 41_250)
    assert meta == {
        "keep": True,
        "agent_actions": [
            {"node": "reviewer", "model_tier": "strong"},
            {"node": "chat", "model": "m"},
        ],
        "duration_ms": 41250,
    }


def test_user_turn_metadata_omits_negative_duration() -> None:
    events = [{"type": "agent.progress", "data": {"node": "chat"}}]
    meta = user_turn_metadata({}, events, -3)
    assert meta == {"agent_actions": [{"node": "chat"}]}
    assert "duration_ms" not in meta
