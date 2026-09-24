"""Pure graders for on-demand live eval — no API key, no network."""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.eval.graders import (
    grade_case,
    grade_draft,
    grade_grounding,
    grade_intent,
    grade_query_generator,
)

CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"


def test_eval_cases_yaml_shape() -> None:
    files = list(CASES_DIR.glob("*.yaml"))
    assert files, "expected frozen eval cases"
    ids: set[str] = set()
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), path.name
        cid = data.get("id")
        assert cid and cid not in ids, path.name
        ids.add(cid)
        assert data.get("node") in {
            "query_generator",
            "route_intent",
            "executor_post",
            "voice_fixture",
            "grounding_check",
        }
        assert data.get("suites")
        assert data.get("state")
        assert data.get("expect")


def test_query_followup_rejects_cheap_path_and_glue() -> None:
    output = {
        "search_query": "Chiikawa Hong Kong",
        "research": {
            "search_queries": ["Chiikawa Hong Kong", "usagi 兔糧"],
            "query_source": "normalize",
        },
    }
    expect = {
        "query_source": "llm",
        "min_queries": 1,
        "max_queries": 3,
        "queries_forbid_cjk": True,
        "queries_forbid_mixed_script": True,
        "queries_forbid_substrings": ["Chiikawa Hong Kong", "usagi 兔糧"],
    }
    reasons = grade_query_generator(output, expect)
    assert any("query_source" in r for r in reasons)
    assert any("CJK" in r or "mixed-script" in r for r in reasons)
    assert any("Chiikawa Hong Kong" in r for r in reasons)


def test_query_atomic_english_passes() -> None:
    output = {
        "search_query": "Chiikawa Usagi",
        "research": {
            "search_queries": ["Chiikawa Usagi", "Usagi favorite food"],
            "query_source": "llm",
        },
    }
    expect = {
        "query_source": "llm",
        "min_queries": 1,
        "max_queries": 3,
        "queries_forbid_cjk": True,
        "queries_forbid_mixed_script": True,
        "queries_forbid_substrings": ["Chiikawa Hong Kong", "usagi 兔糧"],
    }
    assert grade_query_generator(output, expect) == []


_CHIIKAWA_EXPECT = {
    "query_source": "llm",
    "min_queries": 1,
    "max_queries": 3,
    "queries_forbid_mixed_script": True,
    "queries_forbid_substrings": ["Chiikawa Hong Kong", "usagi 兔糧"],
    "queries_require_any": [
        ["Chiikawa", "ちいかわ"],
        ["favorite food", "rabbit feed", "rabbit food", "好物", "餌", "エサ", "兔糧"],
    ],
}


def test_query_set_covers_sense_and_prior_intent() -> None:
    output = {
        "search_query": "Chiikawa Usagi",
        "research": {
            "search_queries": [
                "Chiikawa Usagi",
                "Chiikawa Usagi favorite food",
                "ちいかわ うさぎ",
            ],
            "query_source": "llm",
        },
    }
    assert grade_query_generator(output, _CHIIKAWA_EXPECT) == []


def test_query_set_entity_only_misses_food_intent() -> None:
    output = {
        "research": {
            "search_queries": ["Chiikawa Usagi", "ちいかわ うさぎ"],
            "query_source": "llm",
        }
    }
    reasons = grade_query_generator(output, _CHIIKAWA_EXPECT)
    assert any("miss" in r and "favorite food" in r for r in reasons)


def test_query_set_food_only_misses_chiikawa_sense() -> None:
    output = {
        "research": {
            "search_queries": ["usagi", "Usagi favorite food", "rabbit feed"],
            "query_source": "llm",
        }
    }
    reasons = grade_query_generator(output, _CHIIKAWA_EXPECT)
    assert any("miss" in r and "Chiikawa" in r for r in reasons)


def test_min_voice_floor() -> None:
    from tests.eval.voice_judge import apply_max_voice, apply_min_voice

    scores = {"overall": 0.4}
    assert apply_min_voice({}, scores) == []
    assert apply_min_voice({"min_voice": 0.55}, scores)[0].startswith("voice 0.40")
    assert apply_min_voice({"min_voice": 0.55}, {"overall": 0.7}) == []
    assert apply_min_voice({"min_voice": 0.55}, None) == ["voice score missing"]
    assert apply_max_voice({"max_voice": 0.7}, {"overall": 0.95})[0].startswith("voice 0.95")
    assert apply_max_voice({"max_voice": 0.7}, {"overall": 0.4}) == []


def test_query_too_many() -> None:
    output = {
        "research": {
            "search_queries": ["a", "b", "c", "d"],
            "query_source": "llm",
        }
    }
    reasons = grade_query_generator(output, {"query_source": "llm", "max_queries": 3})
    assert any("want <=3" in r for r in reasons)


def test_intent_confirm_and_parse() -> None:
    assert (
        grade_intent(
            {"intent": "confirm_intent", "_eval_parse_ok": True},
            {"intent": "confirm_intent", "parse_ok": True},
        )
        == []
    )
    reasons = grade_intent(
        {"intent": "confirm_intent", "_eval_parse_ok": False},
        {"intent": "confirm_intent", "parse_ok": True},
    )
    assert any("parse missed" in r for r in reasons)


def test_intent_chat_must_not_start() -> None:
    reasons = grade_intent(
        {"intent": "start", "_eval_parse_ok": True},
        {"intent": "chat", "intent_not": "start", "parse_ok": True},
    )
    assert any("want 'chat'" in r for r in reasons)
    assert any("must not be 'start'" in r for r in reasons)


def test_draft_simplified_and_slang() -> None:
    reasons = grade_draft(
        {"parsed": {"caption": "这绝绝子真的给力"}},
        {"caption_nonempty": True, "forbid_simplified": True, "forbid_mainland_slang": True},
    )
    assert any("simplified" in r for r in reasons)
    assert any("mainland slang" in r for r in reasons)


def test_draft_hk_caption_passes() -> None:
    assert (
        grade_draft(
            {"parsed": {"caption": "星期五 OT 完飲罐嘢先走。"}},
            {
                "caption_nonempty": True,
                "forbid_simplified": True,
                "forbid_mainland_slang": True,
            },
        )
        == []
    )


def test_draft_none_fails() -> None:
    reasons = grade_draft({"parsed": None}, {"caption_nonempty": True})
    assert reasons == ["executor_post returned no DraftOut"]


def test_grade_case_dispatches() -> None:
    case = {
        "node": "query_generator",
        "expect": {"query_source": "llm", "min_queries": 1},
    }
    output = {
        "research": {"search_queries": ["Hong Kong overtime"], "query_source": "llm"},
        "search_query": "Hong Kong overtime",
    }
    assert grade_case(case, output) == []
    grounding = {"node": "grounding_check", "expect": {"grounding_ok": True}}
    assert grade_case(grounding, {"grounding_ok": True}) == []
    assert grade_case({"node": "nope"}, {})[0].startswith("unknown node")


def test_draft_forbid_substrings_and_regex() -> None:
    output = {
        "parsed": {
            "caption": "97% 香港人都話好",
            "cta": "了解更多",
            "hashtags": ["#HongKong"],
        }
    }
    reasons = grade_draft(
        output,
        {
            "caption_nonempty": True,
            "forbid_substrings": ["全港第一"],
            "forbid_regex": [r"\d+(\.\d+)?\s*%"],
        },
    )
    assert not any("全港第一" in r for r in reasons)
    assert any("forbidden pattern" in r and "97%" in r for r in reasons)
    reasons2 = grade_draft(output, {"forbid_substrings": ["97%"]})
    assert any("forbidden substring" in r for r in reasons2)


def test_grounding_ok_and_kept_ids() -> None:
    output = {
        "grounding_ok": False,
        "source_signal_ids": ["cassette:ot"],
        "reviewer_feedback": "Missing or invalid source_signal_ids: ['cassette:nope']",
    }
    expect = {
        "grounding_ok": False,
        "feedback_contains": ["Missing or invalid"],
        "kept_signal_ids": ["cassette:ot"],
    }
    assert grade_grounding(output, expect) == []


def test_grounding_flags_wrong_ok_and_feedback() -> None:
    output = {"grounding_ok": True, "source_signal_ids": ["a"], "reviewer_feedback": ""}
    reasons = grade_grounding(
        output, {"grounding_ok": False, "feedback_contains": ["Missing"]}
    )
    assert any("grounding_ok" in r for r in reasons)
    assert any("feedback misses" in r for r in reasons)


def test_grounding_kept_ids_mismatch() -> None:
    output = {"grounding_ok": False, "source_signal_ids": ["a"], "reviewer_feedback": "x"}
    reasons = grade_grounding(output, {"kept_signal_ids": ["a", "b"]})
    assert any("kept ids" in r for r in reasons)


def test_grounding_product_claim_feedback() -> None:
    output = {
        "grounding_ok": False,
        "source_signal_ids": ["a"],
        "reviewer_feedback": "Caption has numbers not in primary product row: ['97']",
    }
    assert (
        grade_grounding(
            output,
            {"grounding_ok": False, "feedback_contains": ["not in primary product row"]},
        )
        == []
    )
