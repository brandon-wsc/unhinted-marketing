"""Deterministic + semantic research gate (ADR 0009)."""

from __future__ import annotations

import re

from internal.session.semantic_gate import classify_semantic_route

# Pure greetings / product-howto — skip Tavily / query_generator (regex fallback).
_SKIP_RESEARCH = re.compile(
    r"("
    r"^你好[啊阿嗎嘛]?[!！.。]*$"
    r"|^hello[!!.]*$"
    r"|^hi[!!.]*$"
    r"|^hey[!!.]*$"
    r"|點用|怎么用|怎麼用|如何使用|what can you do|how do (i|you) use"
    r"|你係邊個|你是谁|who are you"
    r")",
    re.IGNORECASE,
)

# Likely wants market / current facts (regex fallback when semantic unavailable).
_NEEDS_FACTS = re.compile(
    r"("
    r"熱話|热话|趨勢|趋势|trend|熱搜|热搜"
    r"|而家|依家|最近|今日|今次|latest|news|新聞|新闻"
    r"|興唔興|够不够|夠唔夠|數據|数据|排名|rank"
    r"|香港|hong kong|\bhk\b"
    r"|市場|市场|market"
    r")",
    re.IGNORECASE,
)


def _regex_research_pass(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _SKIP_RESEARCH.search(raw):
        return False
    return bool(_NEEDS_FACTS.search(raw))


def research_pass_for_route(route: str | None, text: str) -> bool:
    """Map semantic route → research_rule_pass; regex if route is None."""
    if route == "need_search":
        return True
    if route in ("chitchat", "act_no_search"):
        return False
    return _regex_research_pass(text)


def research_rule_pass(text: str) -> bool:
    """True = allow research path (still need classifier need_facts).

    Prefer semantic-router (FastEmbed). Only ``need_search`` passes.
    ``chitchat`` / ``act_no_search`` / unclear → false.
    If semantic is disabled or fails to init, fall back to fail-closed regex.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    return research_pass_for_route(classify_semantic_route(raw), raw)


def normalize_search_query(text: str, *, max_len: int = 160) -> str | None:
    """Cheap rewrite only when text is already keyword-like; None = need LLM.

    Spoken Cantonese / full clauses must NOT become Tavily queries (e.g.
    ``usagi想食嘅兔糧`` → None so query_generator can emit atomic keywords).
    """
    raw = " ".join((text or "").split())
    if not raw:
        return None
    if len(raw) > 80 or raw.count("，") + raw.count(",") >= 2:
        return None
    if any(
        k in raw
        for k in (
            "幫我",
            "帮我",
            "寫帖",
            "写帖",
            "做帖",
            "草稿",
            "發佈",
            "发布",
            # Spoken / clause markers — not atomic search terms
            "想食",
            "嘅",
            "係咪",
            "有冇",
            "點樣",
            "怎么",
            "怎麼",
            "什麼",
            "什么",
            "一下",
            "幫",
            "帮",
        )
    ):
        return None
    # Require mostly keyword shape: short token count
    if len(raw.split()) > 8:
        return None
    q = raw
    lower = q.lower()
    if "hong kong" not in lower and "香港" not in q and not re.search(r"\bhk\b", lower):
        q = f"{q} Hong Kong"
    return q[:max_len].strip() or None
