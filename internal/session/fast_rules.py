"""Deterministic research gate (ADR 0009) — no LLM."""

from __future__ import annotations

import re

# Pure greetings / product-howto — skip Tavily / query_generator.
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

# Likely wants market / current facts.
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


def research_rule_pass(text: str) -> bool:
    """True = allow research path (still need classifier need_facts).

    Fail-closed: only explicit fact cues pass. Skip list always blocks.
    Classifier still decides need_facts / ambiguity after a pass.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    if _SKIP_RESEARCH.search(raw):
        return False
    return bool(_NEEDS_FACTS.search(raw))


def normalize_search_query(text: str, *, max_len: int = 160) -> str | None:
    """Cheap rewrite when utterance is already search-like; None = need LLM."""
    raw = " ".join((text or "").split())
    if not raw:
        return None
    # Long / multi-clause / instruction-like → LLM query_generator.
    if len(raw) > 80 or raw.count("，") + raw.count(",") >= 2:
        return None
    if any(k in raw for k in ("幫我", "帮我", "寫帖", "写帖", "做帖", "草稿", "發佈", "发布")):
        return None
    q = raw
    lower = q.lower()
    if "hong kong" not in lower and "香港" not in q and not re.search(r"\bhk\b", lower):
        q = f"{q} Hong Kong"
    return q[:max_len].strip() or None
