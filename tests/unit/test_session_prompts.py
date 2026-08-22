"""Lock prompt contracts that are easy to regress in ROUTE_INTENT."""

from internal.session.prompts import ROUTE_INTENT


def test_route_intent_need_facts_is_topic_gate_not_knowledge_check() -> None:
    assert "TOPIC gate" in ROUTE_INTENT
    assert "NEVER set need_facts false" in ROUTE_INTENT
    assert "usagi想食嘅兔糧" in ROUTE_INTENT
    assert "evergreen creative brainstorming" not in ROUTE_INTENT
    assert "answering well needs current/market/web facts" not in ROUTE_INTENT
    assert "research_rule_pass true" in ROUTE_INTENT
