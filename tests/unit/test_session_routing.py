"""Pure routing / heuristic helpers — no LLM, no DB."""

from internal.session.nodes import (
    MAX_REVIEW_RETRIES,
    _heuristic_intent,
    _should_research,
    _wants_image_change,
    bump_review_attempt,
    route_after_intent,
    route_after_product_matcher,
    route_after_reviewer,
)
from internal.session.state import MODE_AGENT, MODE_CHAT, MODE_PREVIEW


def test_heuristic_intent_start_keywords() -> None:
    state = {
        "mode": MODE_CHAT,
        "messages": [{"role": "user", "content": "幫我寫帖"}],
    }
    assert _heuristic_intent(state) == "start"


def test_heuristic_intent_preview_revise_default() -> None:
    state = {
        "mode": MODE_PREVIEW,
        "messages": [{"role": "user", "content": "改短啲"}],
    }
    assert _heuristic_intent(state) == "revise"


def test_heuristic_intent_preview_confirm_phrases() -> None:
    state = {
        "mode": MODE_PREVIEW,
        "messages": [{"role": "user", "content": "可以出喇"}],
    }
    assert _heuristic_intent(state) == "confirm_intent"


def test_heuristic_intent_agent_without_draft_starts() -> None:
    state = {
        "mode": MODE_AGENT,
        "draft": {},
        "messages": [{"role": "user", "content": "嗯"}],
    }
    assert _heuristic_intent(state) == "start"


def test_wants_image_change() -> None:
    assert _wants_image_change("換張圖") is True
    assert _wants_image_change("改 caption") is False


def test_route_after_intent() -> None:
    assert route_after_intent({"intent": "start"}) == "load_context"
    assert route_after_intent({"intent": "revise"}) == "edit_copy"
    assert route_after_intent({"intent": "confirm_intent"}) == "ack_confirm"
    assert route_after_intent({"intent": "chat"}) == "chat"
    assert route_after_intent({}) == "chat"


def test_route_after_intent_research_gate() -> None:
    state = {
        "intent": "chat",
        "research_rule_pass": True,
        "research": {"need_facts": True, "ambiguous": False, "ask_clarify": False},
    }
    assert route_after_intent(state) == "query_generator"
    # Ambiguity must NOT block research — search best-effort first.
    assert (
        route_after_intent({**state, "research": {"need_facts": True, "ambiguous": True}})
        == "query_generator"
    )


def test_route_after_product_matcher() -> None:
    assert route_after_product_matcher({}) == "brainstormer"
    assert route_after_product_matcher({"product_clarify": False}) == "brainstormer"
    assert route_after_product_matcher({"product_clarify": True}) == "chat"


def test_should_research() -> None:
    assert (
        _should_research(
            {
                "research_rule_pass": True,
                "research": {"need_facts": True, "ambiguous": True, "ask_clarify": True},
            }
        )
        is True
    )
    assert (
        _should_research({"research_rule_pass": False, "research": {"need_facts": True}})
        is False
    )
    assert (
        _should_research(
            {"research_rule_pass": True, "research": {"need_facts": False}}
        )
        is False
    )


def test_route_after_reviewer_paths() -> None:
    assert (
        route_after_reviewer({"reviewer_passed": True, "need_image": True})
        == "executor_image_plan"
    )
    assert (
        route_after_reviewer({"reviewer_passed": True, "need_image": False})
        == "persist_preview"
    )
    assert route_after_reviewer({"reviewer_passed": False, "review_attempts": 0}) == "edit_copy"
    assert (
        route_after_reviewer(
            {"reviewer_passed": False, "review_attempts": MAX_REVIEW_RETRIES}
        )
        == "review_exhausted"
    )


def test_bump_review_attempt() -> None:
    assert bump_review_attempt({"review_attempts": 1}) == {"review_attempts": 2}
