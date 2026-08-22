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


def test_normalize_search_query_rejects_mixed_script_entity() -> None:
    assert normalize_search_query("usagi 兔糧") is None
    assert normalize_search_query("usagi 兔糧 Hong Kong") is None


def test_fallback_search_queries_glosses_rabbit_food() -> None:
    from internal.session.fast_rules import fallback_search_queries

    qs = fallback_search_queries("usagi 兔糧", "usagi想食嘅兔糧")
    assert qs
    assert all("兔糧" not in q for q in qs)
    assert any("rabbit food" in q.lower() for q in qs)
    assert any("usagi" in q.lower() for q in qs)


def test_polish_search_queries_expands_mixed_script() -> None:
    from internal.session.fast_rules import polish_search_queries

    qs = polish_search_queries(["usagi 兔糧", "Usagi rabbit food Hong Kong"])
    assert qs
    assert all("兔糧" not in q for q in qs)
    assert any("rabbit food" in q.lower() for q in qs)
    # Dedupe-friendly: English atomic query kept
    assert any(q == "Usagi rabbit food Hong Kong" or "usagi rabbit food" in q.lower() for q in qs)


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


def test_omit_nulls_drops_null_keys_and_list_items() -> None:
    from internal.session.io import omit_nulls

    assert omit_nulls(
        {
            "search_query": None,
            "search_queries": ["Usagi food preferences", None, "Usagi rabbit diet"],
            "time_range": None,
            "research": {"entity_surface": None, "need_facts": True},
        }
    ) == {
        "search_queries": ["Usagi food preferences", "Usagi rabbit diet"],
        "research": {"need_facts": True},
    }


def test_query_gen_out_null_optional_fields() -> None:
    """LLM optional-null must not fail the payload (turn c8aab85b)."""
    import json

    from internal.session.io import QueryGenOut, omit_nulls

    raw = """
        {
          "search_queries": ["Usagi food preferences", "Usagi rabbit diet", null],
          "search_query": null,
          "topic": "general",
          "time_range": null,
          "extra_llm_key": true
        }
        """
    out = QueryGenOut.model_validate(omit_nulls(json.loads(raw)))
    assert out.search_query == ""
    assert out.topic == "general"
    assert out.time_range == "week"
    assert out.atomic_queries() == ["Usagi food preferences", "Usagi rabbit diet"]


def test_intent_route_nested_nulls() -> None:
    from internal.session.io import IntentRoute, omit_nulls

    parsed = IntentRoute.model_validate(
        omit_nulls(
            {
                "intent": "chat",
                "rationale": None,
                "research": {
                    "need_facts": True,
                    "entity_surface": None,
                    "product_surface": None,
                },
            }
        )
    )
    assert parsed.rationale == ""
    assert parsed.research.need_facts is True
    assert parsed.research.entity_surface == ""
    assert parsed.research.product_surface == ""
