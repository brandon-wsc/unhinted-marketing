"""Lock ROUTE_INTENT / QUERY_GENERATOR / CHAT snippets that encode research policy."""

from internal.session.prompts import CHAT, QUERY_GENERATOR, ROUTE_INTENT


def test_route_intent_need_facts_is_topic_gate_not_knowledge_check() -> None:
    assert "TOPIC gate" in ROUTE_INTENT
    assert "NEVER set need_facts false" in ROUTE_INTENT
    assert "usagi想食嘅兔糧" in ROUTE_INTENT
    assert "evergreen creative brainstorming" not in ROUTE_INTENT
    assert "answering well needs current/market/web facts" not in ROUTE_INTENT
    assert "research_rule_pass true" in ROUTE_INTENT


def test_query_generator_splits_entity_from_product() -> None:
    assert '["usagi", "Usagi favorite food", "rabbit feed"]' in QUERY_GENERATOR
    assert "One conjunct per query" in QUERY_GENERATOR
    assert 'NOT ["Usagi rabbit food"]' in QUERY_GENERATOR


def test_query_generator_follow_up_rewrites_from_prior_question() -> None:
    assert "prior「usagi想食嘅兔糧」+ now「Chiikawa」" in QUERY_GENERATOR
    assert 'NOT ["Chiikawa Hong Kong"]' in QUERY_GENERATOR
    assert "recent_thread" in QUERY_GENERATOR


def test_route_intent_follow_up_stays_chat() -> None:
    assert "keep intent=chat" in ROUTE_INTENT
    assert "Chiikawa Usagi 兔糧" in ROUTE_INTENT


def test_chat_does_not_fuse_across_search_queries() -> None:
    assert "metrics.query" in CHAT
    assert "Do not merge hits" in CHAT
    assert "signals_trusted" in CHAT
