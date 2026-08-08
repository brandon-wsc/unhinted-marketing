"""Unit tests for ADR 0009 fast research rules (+ mocked semantic gate)."""

from internal.session import fast_rules
from internal.session.fast_rules import normalize_search_query, research_rule_pass


def test_research_rule_skips_greeting(monkeypatch) -> None:
    monkeypatch.setattr(fast_rules, "classify_semantic_route", lambda _t: None)
    assert research_rule_pass("你好") is False
    assert research_rule_pass("hello!") is False


def test_research_rule_skips_product_howto(monkeypatch) -> None:
    monkeypatch.setattr(fast_rules, "classify_semantic_route", lambda _t: None)
    assert research_rule_pass("點用呢個 app") is False


def test_research_rule_passes_trends_regex_fallback(monkeypatch) -> None:
    monkeypatch.setattr(fast_rules, "classify_semantic_route", lambda _t: None)
    assert research_rule_pass("香港最近熱話有咩") is True


def test_research_rule_fails_freeform_without_fact_cue(monkeypatch) -> None:
    monkeypatch.setattr(fast_rules, "classify_semantic_route", lambda _t: None)
    assert research_rule_pass("想傾下返工好攰") is False
    assert research_rule_pass("幫我做帖") is False
    assert research_rule_pass("usagi") is False


def test_research_rule_semantic_need_search(monkeypatch) -> None:
    monkeypatch.setattr(fast_rules, "classify_semantic_route", lambda _t: "need_search")
    assert research_rule_pass("隨便講句") is True


def test_research_rule_semantic_chitchat(monkeypatch) -> None:
    monkeypatch.setattr(fast_rules, "classify_semantic_route", lambda _t: "chitchat")
    assert research_rule_pass("香港最近熱話有咩") is False


def test_research_rule_semantic_act_no_search(monkeypatch) -> None:
    monkeypatch.setattr(fast_rules, "classify_semantic_route", lambda _t: "act_no_search")
    assert research_rule_pass("香港最近熱話有咩") is False


def test_normalize_search_query_adds_hk() -> None:
    q = normalize_search_query("加班文化")
    assert q is not None
    assert "Hong Kong" in q


def test_normalize_search_query_rejects_colloquial() -> None:
    assert normalize_search_query("usagi想食嘅兔糧") is None
    assert normalize_search_query("有冇熱話") is None


def test_normalize_search_query_rejects_long() -> None:
    assert normalize_search_query("想" * 100) is None


def test_normalize_search_query_rejects_post_request() -> None:
    assert normalize_search_query("幫我寫帖講熱話") is None


def test_query_gen_out_atomic_queries() -> None:
    from internal.session.io import QueryGenOut

    out = QueryGenOut(
        search_queries=["Usagi rabbit food", "Usagi rabbit food", "pet feed HK"],
        search_query="ignored when list set",
    )
    assert out.atomic_queries() == ["Usagi rabbit food", "pet feed HK"]

    single = QueryGenOut(search_query="Hong Kong trends")
    assert single.atomic_queries() == ["Hong Kong trends"]
