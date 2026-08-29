"""Deterministic graders for live agent eval — no LLM-as-judge."""

from __future__ import annotations

import re
from typing import Any

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# Latin token next to CJK (e.g. ``usagi 兔糧`` / ``Usagi兔糧``) — not atomic English.
MIXED_SCRIPT_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*\s*[\u4e00-\u9fff]|[\u4e00-\u9fff]\s*[A-Za-z]"
)

# Common simplified-only chars that should not appear in zh-HK social copy.
SIMPLIFIED_CHARS = frozenset("这们个来对吗里后时会说过还没为发经现点国汉")

MAINLAND_SLANG = (
    "绝绝子",
    "yyds",
    "YYDS",
    "躺平",
    "内卷",
    "给力",
    "奥利给",
    "破防",
    "栓Q",
    "宝子们",
    "家人们",
    "整活",
)


def _queries_of(output: dict[str, Any]) -> list[str]:
    research = output.get("research") or {}
    raw = research.get("search_queries") or []
    if isinstance(raw, list) and raw:
        return [str(q) for q in raw if str(q).strip()]
    q = output.get("search_query")
    return [str(q)] if q else []


def grade_query_generator(output: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    queries = _queries_of(output)
    source = (output.get("research") or {}).get("query_source")
    want_source = expect.get("query_source")
    if want_source and source != want_source:
        reasons.append(f"query_source={source!r} want {want_source!r}")
    min_q = expect.get("min_queries", 1)
    max_q = expect.get("max_queries", 3)
    if len(queries) < min_q:
        reasons.append(f"got {len(queries)} queries, want >={min_q}")
    if len(queries) > max_q:
        reasons.append(f"got {len(queries)} queries, want <={max_q}")
    if expect.get("queries_forbid_cjk"):
        for q in queries:
            if CJK_RE.search(q):
                reasons.append(f"CJK in query {q!r}")
    if expect.get("queries_forbid_mixed_script"):
        for q in queries:
            if MIXED_SCRIPT_RE.search(q):
                reasons.append(f"mixed-script glue in query {q!r}")
    for needle in expect.get("queries_forbid_substrings") or []:
        low = needle.lower()
        for q in queries:
            if low in q.lower():
                reasons.append(f"forbidden substring {needle!r} in {q!r}")
    return reasons


def grade_intent(output: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if expect.get("parse_ok") and not output.get("_eval_parse_ok"):
        reasons.append("route_intent LLM parse missed (heuristic fallback)")
    intent = output.get("intent")
    want = expect.get("intent")
    if want and intent != want:
        reasons.append(f"intent={intent!r} want {want!r}")
    banned = expect.get("intent_not")
    if banned and intent == banned:
        reasons.append(f"intent must not be {banned!r}")
    return reasons


def grade_draft(output: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    parsed = output.get("parsed")
    if parsed is None:
        reasons.append("executor_post returned no DraftOut")
        return reasons
    caption = str(parsed.get("caption") or "")
    if expect.get("caption_nonempty") and not caption.strip():
        reasons.append("empty caption")
    blob = caption
    if expect.get("forbid_simplified"):
        hits = sorted({ch for ch in blob if ch in SIMPLIFIED_CHARS})
        if hits:
            reasons.append(f"simplified chars {''.join(hits)}")
    if expect.get("forbid_mainland_slang"):
        lower = blob.lower()
        for token in MAINLAND_SLANG:
            if token.lower() in lower or token in blob:
                reasons.append(f"mainland slang {token!r}")
    return reasons


def grade_case(case: dict[str, Any], output: dict[str, Any]) -> list[str]:
    expect = case.get("expect") or {}
    node = case.get("node")
    if node == "query_generator":
        return grade_query_generator(output, expect)
    if node == "route_intent":
        return grade_intent(output, expect)
    if node == "executor_post":
        return grade_draft(output, expect)
    return [f"unknown node {node!r}"]
