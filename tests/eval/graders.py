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
    blob = " ".join(queries).lower()
    for group in expect.get("queries_require_any") or []:
        needles = group if isinstance(group, list) else [group]
        if not any(str(n).lower() in blob for n in needles):
            reasons.append(f"queries miss {needles!r}: {queries!r}")
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


def _draft_blob(parsed: dict[str, Any]) -> str:
    parts = [str(parsed.get("caption") or ""), str(parsed.get("cta") or "")]
    parts.extend(str(tag) for tag in (parsed.get("hashtags") or []))
    return "\n".join(parts)


def grade_draft(output: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    parsed = output.get("parsed")
    if parsed is None:
        reasons.append("executor_post returned no DraftOut")
        return reasons
    caption = str(parsed.get("caption") or "")
    if expect.get("caption_nonempty") and not caption.strip():
        reasons.append("empty caption")
    blob = _draft_blob(parsed)
    if expect.get("forbid_simplified"):
        hits = sorted({ch for ch in blob if ch in SIMPLIFIED_CHARS})
        if hits:
            reasons.append(f"simplified chars {''.join(hits)}")
    if expect.get("forbid_mainland_slang"):
        lower = blob.lower()
        for token in MAINLAND_SLANG:
            if token.lower() in lower or token in blob:
                reasons.append(f"mainland slang {token!r}")
    lower_blob = blob.lower()
    for needle in expect.get("forbid_substrings") or []:
        if str(needle).lower() in lower_blob:
            reasons.append(f"forbidden substring {needle!r} in draft")
    for pattern in expect.get("forbid_regex") or []:
        match = re.search(str(pattern), blob)
        if match:
            reasons.append(f"forbidden pattern {pattern!r} matched {match.group(0)!r}")
    return reasons


def grade_grounding(output: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    """Deterministic grounding_check outcome — citations, claims, feedback."""
    reasons: list[str] = []
    want_ok = expect.get("grounding_ok")
    if want_ok is not None and output.get("grounding_ok") != want_ok:
        reasons.append(f"grounding_ok={output.get('grounding_ok')!r} want {want_ok!r}")
    feedback = str(output.get("reviewer_feedback") or "")
    for needle in expect.get("feedback_contains") or []:
        if str(needle) not in feedback:
            reasons.append(f"feedback misses {needle!r}: {feedback!r}")
    kept_want = expect.get("kept_signal_ids")
    if kept_want is not None:
        kept = sorted(str(s) for s in (output.get("source_signal_ids") or []))
        if kept != sorted(str(s) for s in kept_want):
            reasons.append(f"kept ids {kept} want {sorted(kept_want)}")
    return reasons


def grade_retrieve(output: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    """Deterministic product-retrieve outcome — hit sets, primary, clarify.

    ``output`` shape: {"hits": [{sku, score, match_kind}], "primary_sku",
    "primary_kind", "clarify"}. Assert set properties, never exact scores —
    HNSW/model drift can move scores without breaking behavior.
    """
    reasons: list[str] = []
    hits = output.get("hits") or []
    skus = [str(h.get("sku") or "") for h in hits]

    for group in expect.get("hit_any") or []:
        needles = group if isinstance(group, list) else [group]
        if not any(str(n) in skus for n in needles):
            reasons.append(f"hits miss any-of {needles!r}: {skus!r}")
    for sku in expect.get("hit_all") or []:
        if str(sku) not in skus:
            reasons.append(f"hits miss {sku!r}: {skus!r}")
    for sku in expect.get("hit_none") or []:
        if str(sku) in skus:
            reasons.append(f"hit_none violated by {sku!r}")
    if expect.get("primary_none") and output.get("primary_sku") is not None:
        reasons.append(f"expected no primary, got {output.get('primary_sku')!r}")
    want_primary = expect.get("primary_is")
    if want_primary is not None and output.get("primary_sku") != want_primary:
        reasons.append(
            f"primary={output.get('primary_sku')!r} want {want_primary!r}"
        )
    want_kind = expect.get("primary_kind")
    if want_kind and output.get("primary_kind") != want_kind:
        reasons.append(
            f"primary_kind={output.get('primary_kind')!r} want {want_kind!r}"
        )
    want_clarify = expect.get("clarify")
    if want_clarify is not None and bool(output.get("clarify")) != bool(want_clarify):
        reasons.append(f"clarify={output.get('clarify')!r} want {want_clarify!r}")
    min_hits = expect.get("min_hits")
    if min_hits is not None and len(hits) < int(min_hits):
        reasons.append(f"got {len(hits)} hits, want >={min_hits}")
    max_hits = expect.get("max_hits")
    if max_hits is not None and len(hits) > int(max_hits):
        reasons.append(f"got {len(hits)} hits, want <={max_hits}")
    if expect.get("vector_hit"):
        kinds = {str(h.get("match_kind")) for h in hits}
        if "vector" not in kinds:
            reasons.append(f"no vector-tier hit in {kinds!r}")
    for pair in expect.get("rank_before") or []:
        a, b = str(pair[0]), str(pair[1])
        ia = skus.index(a) if a in skus else -1
        ib = skus.index(b) if b in skus else -1
        if ia < 0 or ib < 0:
            missing = a if ia < 0 else b
            reasons.append(f"rank_before {pair!r}: {missing!r} not in {skus!r}")
        elif ia >= ib:
            reasons.append(f"rank_before violated: {a}@{ia} not before {b}@{ib}")
    return reasons


def grade_case(case: dict[str, Any], output: dict[str, Any]) -> list[str]:
    expect = case.get("expect") or {}
    node = case.get("node")
    if node == "query_generator":
        return grade_query_generator(output, expect)
    if node == "route_intent":
        return grade_intent(output, expect)
    if node in ("executor_post", "voice_fixture"):
        return grade_draft(output, expect)
    if node == "grounding_check":
        return grade_grounding(output, expect)
    return [f"unknown node {node!r}"]
