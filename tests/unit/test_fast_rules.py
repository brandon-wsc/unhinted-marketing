"""Unit tests for ADR 0009 fast research rules."""

from internal.session.fast_rules import normalize_search_query, research_rule_pass


def test_research_rule_skips_greeting() -> None:
    assert research_rule_pass("你好") is False
    assert research_rule_pass("hello!") is False


def test_research_rule_skips_product_howto() -> None:
    assert research_rule_pass("點用呢個 app") is False


def test_research_rule_passes_trends() -> None:
    assert research_rule_pass("香港最近熱話有咩") is True


def test_research_rule_fails_freeform_without_fact_cue() -> None:
    assert research_rule_pass("想傾下返工好攰") is False
    assert research_rule_pass("幫我做帖") is False
    assert research_rule_pass("usagi") is False


def test_normalize_search_query_adds_hk() -> None:
    q = normalize_search_query("加班文化")
    assert q is not None
    assert "Hong Kong" in q


def test_normalize_search_query_rejects_long() -> None:
    assert normalize_search_query("想" * 100) is None


def test_normalize_search_query_rejects_post_request() -> None:
    assert normalize_search_query("幫我寫帖講熱話") is None
