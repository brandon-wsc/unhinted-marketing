"""Lock ROUTE_INTENT / QUERY_GENERATOR / CHAT snippets that encode research policy."""

from internal.session.prompts import (
    BRAINSTORM,
    CHAT,
    EXECUTOR_POST,
    QUERY_GENERATOR,
    REVIEWER,
    ROUTE_INTENT,
    TREND_SEARCH,
)


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


def test_downstream_prompts_respect_signals_trusted() -> None:
    assert "signals_trusted" in TREND_SEARCH
    assert "signals_trusted" in BRAINSTORM
    assert "signals_trusted" in EXECUTOR_POST
    assert "signals_trusted" in REVIEWER


def test_brainstorm_honors_locked_image_format() -> None:
    """UAT S3: tone feedback must not rewrite a sticky comic into 單圖."""
    assert "image_format" in BRAINSTORM
    assert "comic_4panel" in BRAINSTORM
    assert "angle_feedback" in BRAINSTORM
    assert "4 格漫畫" in BRAINSTORM


def test_executor_post_image_format_beats_brief_vehicle() -> None:
    assert "image_format" in EXECUTOR_POST
    assert "authoritative" in EXECUTOR_POST


def test_craft_bans_mainland_traffic_jargon() -> None:
    assert "流量" in EXECUTOR_POST
    assert "衝流量" in EXECUTOR_POST
    assert "種草" in EXECUTOR_POST
    assert "流量" in REVIEWER
    assert "like" in EXECUTOR_POST
