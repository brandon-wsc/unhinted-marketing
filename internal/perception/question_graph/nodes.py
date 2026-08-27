"""Question worker graph nodes (ADR 0018).

Node names are the pipeline contract. Tests mock ``complete_json`` / repos at
this module's namespace, same style as session node tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any

from internal.llm.recorder import mark_last_call
from internal.llm.router import (
    LlmProviderError,
    ModelTier,
    complete_json,
    has_llm_credentials,
)
from internal.memory.repos import (
    get_company,
    list_companies,
    list_products,
    list_top_signals,
    update_company_profile,
    upsert_signal,
)
from internal.perception.hot_search import ingest_hot_search
from internal.perception.question_graph import prompts
from internal.perception.question_graph.context import get_db
from internal.perception.question_graph.state import QuestionGraphState
from internal.perception.rss_news import ingest_rss_news
from internal.perception.tavily import has_tavily_credentials, search_tavily

logger = logging.getLogger(__name__)

THIN_CORPUS = 5
CORPUS_LIMIT = 30
SCREEN_PRESELECT = 20
SHORTLIST_MAX = 10
SHORTLIST_MIN = 3
RESEARCH_MAX = 8
DEEP_MAX = 8
PRODUCTS_PER_CANDIDATE = 2
# Timing fuel only — Tavily persists (ADR 0009) but must not dominate next-run recency.
TIMING_SOURCES = ("google_trends_hk", "google_news_hk", "yahoo_news_hk")

_TOPIC_STOP = frozenset(
    {
        "hk",
        "hong",
        "kong",
        "hongkong",
        "the",
        "and",
        "for",
        "news",
        "live",
        "show",
        "sale",
        "new",
        "香港",
        "熱話",
        "熱搜",
        "新聞",
        "最新",
        "推出",
        "新品",
        "展覽",
        "聯乘",
        "合作",
        "周末",
        "週末",
        "人潮",
        "訊號",
        "天氣",
        "專訪",
        "消息",
    }
)
_CELEB_MARKERS = ("緋聞", "戀情", "撻著", "離婚", "分手", "出軌", "約會")

FALLBACK_TEMPLATES = [
    "「{title}」呢單，點出 post 先有畫面、又唔好似新聞稿？",
    "幫我用「{title}」寫個 post，輕鬆啲，唔好板起塊面。",
    "「{title}」抽返個人性出嚟，我哋可以點入戲？",
    "「{title}」呢個熱話，點講先似朋友講、唔似公關？",
    "「{title}」可以點橋去我哋產品，一句有畫面？",
]


def _signal_to_dict(s: Any) -> dict[str, Any]:
    return {
        "signal_id": s.signal_id,
        "source": s.source,
        "title": s.title,
        "url": s.url,
        "excerpt": s.excerpt,
        "metrics": s.metrics or {},
    }


def _norm_text(value: str) -> str:
    return re.sub(r"[\s　，。、「」！？!?,.\-—]+", "", (value or "")).lower()


def topic_key(title: str) -> str:
    """Collapse IP/trend variants (Chiikawa 展覽 / Chiikawa 聯乘 → chiikawa)."""
    raw = title or ""
    latin = [t for t in re.findall(r"[a-z0-9]{3,}", raw.lower()) if t not in _TOPIC_STOP]
    cjk = [
        t
        for t in re.findall(r"[\u4e00-\u9fff]{2,}", raw)
        if t not in _TOPIC_STOP
    ]
    if latin:
        return latin[0]
    if cjk:
        return cjk[0]
    return _norm_text(raw)[:16] or "topic"


def _cluster_cap(items: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = topic_key(item.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out


def _looks_like_ip_or_celeb(title: str) -> bool:
    key = topic_key(title)
    if re.fullmatch(r"[a-z][a-z0-9]{3,}", key):
        return True
    return any(marker in (title or "") for marker in _CELEB_MARKERS)


def _flags(state: QuestionGraphState, *add: str) -> list[str]:
    return [*(state.get("quality_flags") or []), *add]


def _fingerprint_keywords(state: QuestionGraphState) -> list[str]:
    """Company fingerprint: name tokens + profile + inferred keys + products + audience."""
    kws: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if len(text) >= 2 and text not in kws:
            kws.append(text)

    for tok in re.split(r"[\s,，/・|｜\-—()（）]+", state.get("company_name") or ""):
        add(tok)
    profile = state.get("profile") or {}
    for key in ("category", "industry", "inferred_category"):
        add(profile.get(key))
    for key in ("keywords", "inferred_keywords"):
        extra = profile.get(key)
        if isinstance(extra, list):
            for item in extra[:10]:
                add(item)
    for name in (state.get("product_names") or [])[:20]:
        add(name)
    for row in (state.get("audience") or [])[:10]:
        add(row.get("label"))
    return kws


def _keyword_score(title: str, keywords: list[str]) -> int:
    low = (title or "").lower()
    return sum(1 for kw in keywords if kw.lower() in low)


def _fingerprint_summary(state: QuestionGraphState, keywords: list[str]) -> str:
    return "\n".join(
        [
            f"Company: {state.get('company_name') or ''} ({state.get('company_slug') or ''})",
            f"Fingerprint keywords: {json.dumps(keywords, ensure_ascii=False)}",
            f"Products: {json.dumps((state.get('product_names') or [])[:10], ensure_ascii=False)}",
            f"Audience: {json.dumps((state.get('audience') or [])[:6], ensure_ascii=False)}",
        ]
    )


def _candidates_brief(candidates: list[dict[str, Any]], *, with_research: bool = False) -> str:
    rows = []
    for c in candidates:
        row: dict[str, Any] = {
            "signal_id": c["signal_id"],
            "title": c["title"],
            "excerpt": (c.get("excerpt") or "")[:200],
        }
        if with_research and c.get("research"):
            row["research"] = [r[:200] for r in c["research"][:2]]
        for key in ("scene", "emotion", "constraints", "products"):
            val = c.get(key)
            if val:
                row[key] = val
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False, indent=2)


async def ensure_signals(state: QuestionGraphState) -> dict[str, Any]:
    """Load the HK timing corpus; if too thin, run ingest inline (never fail on clock order)."""
    db = get_db()
    sources = list(TIMING_SOURCES)
    signals = await list_top_signals(db, limit=CORPUS_LIMIT, region="HK", sources=sources)
    flags: list[str] = []
    if len(signals) < THIN_CORPUS:
        try:
            await ingest_hot_search(db)
        except Exception:
            logger.exception("ensure_signals: hot-search ingest failed")
            flags.append("hot_search_ingest_failed")
        try:
            await ingest_rss_news(db)
        except Exception:
            logger.exception("ensure_signals: RSS ingest failed")
            flags.append("rss_ingest_failed")
        signals = await list_top_signals(db, limit=CORPUS_LIMIT, region="HK", sources=sources)
    return {
        "signals": [_signal_to_dict(s) for s in signals],
        "quality_flags": _flags(state, *flags),
    }


async def _infer_category_once(state: QuestionGraphState) -> dict[str, Any]:
    """Cold-start ladder step 2: one cheap infer, cached on profile.inferred_*.

    Never overwrites human-written fields — only the inferred_ keys.
    """
    db = get_db()
    profile = dict(state.get("profile") or {})
    if profile.get("inferred_category"):
        return profile
    user = "\n".join(
        [
            f"Company name: {state.get('company_name') or ''}",
            f"Slug: {state.get('company_slug') or ''}",
            f"Profile hints: {json.dumps(profile, ensure_ascii=False)[:800]}",
        ]
    )
    try:
        raw = await complete_json(
            tier=ModelTier.CHEAP, system=prompts.INFER_CATEGORY_SYSTEM, user=user
        )
        payload = json.loads(raw)
        mark_last_call(parse_ok=True)
    except LlmProviderError:
        mark_last_call(fallback_used=True)
        return profile
    except Exception:
        mark_last_call(parse_ok=False, fallback_used=True)
        return profile

    category = str(payload.get("category") or "").strip()
    keywords = [str(k).strip() for k in payload.get("keywords") or [] if str(k).strip()][:10]
    if not category:
        return profile

    profile["inferred_category"] = category
    if keywords:
        profile["inferred_keywords"] = keywords
    try:
        company = await get_company(db, uuid.UUID(state["company_id"]))
        if company is not None:
            await update_company_profile(
                db,
                company,
                patch={
                    "inferred_category": category,
                    **({"inferred_keywords": keywords} if keywords else {}),
                },
            )
            await db.commit()
    except Exception:
        logger.exception("Failed to cache inferred category for company %s", state.get("company_id"))
    return profile


async def cheap_screen(state: QuestionGraphState) -> dict[str, Any]:
    """Score the corpus against the company fingerprint; drop 全港都搜但品牌無橋."""
    signals = state.get("signals") or []
    keywords = _fingerprint_keywords(state)
    flags: list[str] = []
    profile = dict(state.get("profile") or {})

    if not keywords and has_llm_credentials():
        profile = await _infer_category_once(state)
        keywords = _fingerprint_keywords({**state, "profile": profile})

    if not keywords:
        # Cold-start ladder step 3: diversity fallback never fails the run.
        return {
            "shortlisted": _cluster_cap(signals, limit=SHORTLIST_MAX),
            "profile": profile,
            "quality_flags": _flags(state, "cold_start_diversity"),
        }

    scored = sorted(
        signals,
        key=lambda s: _keyword_score(s["title"], keywords),
        reverse=True,
    )
    preselected = _cluster_cap(scored, limit=SCREEN_PRESELECT)

    llm_kept: list[dict[str, Any]] | None = None
    if has_llm_credentials():
        user = "\n\n".join(
            [
                _fingerprint_summary(state, keywords),
                "Candidates:",
                _candidates_brief(preselected),
                f"Keep at most {SHORTLIST_MAX} signal_ids. Duplicate IP/entity titles count as one keep.",
            ]
        )
        try:
            raw = await complete_json(
                tier=ModelTier.CHEAP, system=prompts.CHEAP_SCREEN_SYSTEM, user=user
            )
            keep = json.loads(raw).get("keep") or []
            mark_last_call(parse_ok=True)
            valid = {s["signal_id"] for s in preselected}
            keep_set = {sid for sid in keep if sid in valid}
            llm_kept = [s for s in preselected if s["signal_id"] in keep_set]
        except LlmProviderError:
            mark_last_call(fallback_used=True)
            flags.append("screen_llm_failed")
        except Exception:
            mark_last_call(parse_ok=False, fallback_used=True)
            flags.append("screen_llm_failed")
    else:
        flags.append("screen_heuristic_only")

    rejected_keys: set[str] = set()
    if llm_kept:
        shortlisted = _cluster_cap(llm_kept)
        rejected_keys = {topic_key(s["title"]) for s in preselected} - {
            topic_key(s["title"]) for s in shortlisted
        }
    else:
        if llm_kept is not None:
            flags.append("screen_llm_empty")
        shortlisted = _cluster_cap(
            [s for s in preselected if _keyword_score(s["title"], keywords) > 0]
        )

    kept_keys = {topic_key(s["title"]) for s in shortlisted}
    if len(shortlisted) < SHORTLIST_MIN:
        added = 0
        for s in scored:
            key = topic_key(s["title"])
            if key in kept_keys or key in rejected_keys:
                continue
            if _keyword_score(s["title"], keywords) <= 0:
                continue
            shortlisted.append(s)
            kept_keys.add(key)
            added += 1
            if len(shortlisted) >= SHORTLIST_MIN:
                break
        if added:
            flags.append("screen_topup")
        if len(shortlisted) < SHORTLIST_MIN:
            flags.append("screen_thin")

    # Empty keep / zero keyword overlap must not wipe the landing (ADR 0018:
    # prefer cards). Do not restore LLM-rejected IP clusters or no-bridge celeb.
    if not shortlisted and signals:
        flags.append("screen_empty_fallback")
        for s in _cluster_cap(scored, limit=SHORTLIST_MAX):
            key = topic_key(s["title"])
            if key in rejected_keys:
                continue
            if _looks_like_ip_or_celeb(s["title"]) and _keyword_score(s["title"], keywords) <= 0:
                continue
            shortlisted.append(s)
            if len(shortlisted) >= SHORTLIST_MIN:
                break

    return {
        "shortlisted": shortlisted[:SHORTLIST_MAX],
        "profile": profile,
        "quality_flags": _flags(state, *flags),
    }


async def shallow_research(state: QuestionGraphState) -> dict[str, Any]:
    """One Tavily hop per shortlisted candidate; persist every hit (ADR 0009)."""
    db = get_db()
    candidates = (state.get("shortlisted") or [])[:RESEARCH_MAX]

    if not has_tavily_credentials():
        return {
            "researched": candidates,
            "quality_flags": _flags(state, "research_unavailable"),
        }

    researched: list[dict[str, Any]] = []
    any_snippet = False

    async def fetch(cand: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        try:
            items = await asyncio.wait_for(
                search_tavily(cand["title"], max_results=3), timeout=20
            )
        except Exception:
            logger.exception("shallow_research tavily failed for %s", cand.get("signal_id"))
            items = []
        return cand, items

    pairs = await asyncio.gather(*[fetch(c) for c in candidates])
    for cand, items in pairs:
        snippets: list[str] = []
        for item in items:
            await upsert_signal(
                db,
                signal_id=item["signal_id"],
                source=item["source"],
                title=item["title"],
                url=item.get("url"),
                excerpt=item.get("excerpt"),
                metrics=item.get("metrics") or {},
            )
            excerpt = (item.get("excerpt") or "").strip()
            if excerpt:
                snippets.append(excerpt[:300])
        any_snippet = any_snippet or bool(snippets)
        researched.append({**cand, "research": snippets})
    await db.commit()

    flags = [] if any_snippet else ["research_empty"]
    return {"researched": researched, "quality_flags": _flags(state, *flags)}


async def filter_candidates(state: QuestionGraphState) -> dict[str, Any]:
    """Deterministic named-org block first; LLM keeps followable + bridgeable."""
    db = get_db()
    candidates = state.get("researched") or []
    flags: list[str] = []

    own_name = (state.get("company_name") or "").strip().lower()
    companies = await list_companies(db)
    org_names = {
        (c.name or "").strip()
        for c in companies
        if (c.name or "").strip() and (c.name or "").strip().lower() != own_name
    }

    def blocked(title: str) -> bool:
        low = (title or "").lower()
        return any(len(name) >= 2 and name.lower() in low for name in org_names)

    survivors = [c for c in candidates if not blocked(c["title"])]
    dropped_orgs = len(candidates) - len(survivors)
    if dropped_orgs:
        flags.append("org_mentions_blocked")

    keywords = _fingerprint_keywords(state)
    bridged = []
    dropped_ip = 0
    for c in survivors:
        if _looks_like_ip_or_celeb(c["title"]) and _keyword_score(c["title"], keywords) <= 0:
            dropped_ip += 1
            continue
        bridged.append(c)
    survivors = bridged
    if dropped_ip:
        flags.append("no_bridge_ip_blocked")

    if survivors and has_llm_credentials():
        user = "\n\n".join(
            [
                _fingerprint_summary(state, _fingerprint_keywords(state)),
                "Candidates:",
                _candidates_brief(survivors, with_research=True),
            ]
        )
        try:
            raw = await complete_json(
                tier=ModelTier.CHEAP, system=prompts.FILTER_SYSTEM, user=user
            )
            keep = json.loads(raw).get("keep") or []
            mark_last_call(parse_ok=True)
        except LlmProviderError:
            mark_last_call(fallback_used=True)
            keep = []
            flags.append("filter_llm_failed")
        except Exception:
            mark_last_call(parse_ok=False, fallback_used=True)
            keep = []
            flags.append("filter_llm_failed")
        if keep:
            keep_ids = {row.get("signal_id") for row in keep if isinstance(row, dict)}
            reasons = {
                row.get("signal_id"): str(row.get("reason") or "")
                for row in keep
                if isinstance(row, dict)
            }
            survivors = [
                {**c, "filter_reason": reasons.get(c["signal_id"], "")}
                for c in survivors
                if c["signal_id"] in keep_ids
            ]

    return {"filtered": survivors, "quality_flags": _flags(state, *flags)}


async def deep_research(state: QuestionGraphState) -> dict[str, Any]:
    """Scene / emotion / constraints per survivor (VOICE: 抽人性唔抽機構)."""
    survivors = (state.get("filtered") or [])[:DEEP_MAX]
    if not survivors or not has_llm_credentials():
        flags = [] if not survivors else ["deep_research_skipped"]
        return {"deep": survivors, "quality_flags": _flags(state, *flags)}

    user = "\n\n".join(
        [
            f"Company: {state.get('company_name') or ''}",
            "Candidates:",
            _candidates_brief(survivors, with_research=True),
        ]
    )
    try:
        raw = await complete_json(
            tier=ModelTier.MEDIUM, system=prompts.DEEP_RESEARCH_SYSTEM, user=user
        )
        items = json.loads(raw).get("items") or []
        mark_last_call(parse_ok=True)
    except LlmProviderError:
        mark_last_call(fallback_used=True)
        return {"deep": survivors, "quality_flags": _flags(state, "deep_research_failed")}
    except Exception:
        mark_last_call(parse_ok=False, fallback_used=True)
        return {"deep": survivors, "quality_flags": _flags(state, "deep_research_failed")}

    notes = {
        row.get("signal_id"): row
        for row in items
        if isinstance(row, dict) and row.get("signal_id")
    }
    deep = []
    for cand in survivors:
        note = notes.get(cand["signal_id"]) or {}
        deep.append(
            {
                **cand,
                "scene": str(note.get("scene") or ""),
                "emotion": str(note.get("emotion") or ""),
                "constraints": str(note.get("constraints") or ""),
            }
        )
    return {"deep": deep, "quality_flags": _flags(state)}


async def product_match(state: QuestionGraphState) -> dict[str, Any]:
    """Attach org catalog products per candidate. Read-only (ADR 0011)."""
    db = get_db()
    candidates = state.get("deep") or []
    products = await list_products(
        db, company_id=uuid.UUID(state["company_id"]), owner_scope="org"
    )

    def hits_for(cand: dict[str, Any]) -> list[str]:
        text = " ".join(
            [cand.get("title") or "", cand.get("excerpt") or "", *(cand.get("research") or [])]
        ).lower()
        out: list[str] = []
        for p in products:
            tokens = [t for t in re.split(r"[\s,，/・|｜\-—()（）]+", p.name or "") if len(t) >= 2]
            if any(t.lower() in text for t in tokens):
                out.append(p.name)
            if len(out) >= PRODUCTS_PER_CANDIDATE:
                break
        return out

    return {"deep": [{**c, "products": hits_for(c)} for c in candidates]}


def _pad_questions(
    candidates: list[dict[str, Any]],
    recent: set[str],
    existing: int,
    *,
    used_topics: set[str],
    recent_signal_ids: set[str],
    recent_topics: set[str],
) -> list[dict[str, Any]]:
    """Template pad from real screened candidates only — never fake signal refs."""
    out: list[dict[str, Any]] = []
    if not candidates:
        return out
    i = 0
    while len(out) < 5 - existing and i < len(candidates) * len(FALLBACK_TEMPLATES):
        cand = candidates[i % len(candidates)]
        text = FALLBACK_TEMPLATES[i % len(FALLBACK_TEMPLATES)].format(title=cand["title"][:60])
        i += 1
        key = topic_key(cand["title"])
        sid = cand["signal_id"]
        if _norm_text(text) in recent:
            continue
        if key in used_topics or key in recent_topics:
            continue
        if sid in recent_signal_ids:
            continue
        used_topics.add(key)
        out.append(
            {
                "id": f"fallback-q{existing + len(out) + 1}",
                "text": text,
                "rationale": None,
                "source_signal_ids": [sid],
                "persona_slug": None,
            }
        )
    return out


def _candidate_by_id(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {c["signal_id"]: c for c in candidates}


def _question_topics(refs: list[str], by_id: dict[str, dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for sid in refs:
        cand = by_id.get(sid)
        if cand:
            keys.add(topic_key(cand.get("title") or ""))
    return keys


async def compose_questions(state: QuestionGraphState) -> dict[str, Any]:
    """5–7 zh-HK questions with voice; real signal refs; dedupe vs recent serves."""
    candidates = state.get("deep") or state.get("filtered") or []
    recent = {_norm_text(t) for t in (state.get("recent_texts") or [])}
    flags: list[str] = []

    raw_questions: list[dict[str, Any]] = []
    if candidates and has_llm_credentials():
        voice = state.get("voice") or {}
        system = prompts.COMPOSE_SYSTEM.format(voice_block=prompts.voice_block(voice))
        user = "\n\n".join(
            [
                _fingerprint_summary(state, _fingerprint_keywords(state)),
                "Candidates (with scene/emotion/products):",
                _candidates_brief(candidates, with_research=True),
                "Recently served questions (do not repeat or lightly rephrase):",
                json.dumps((state.get("recent_texts") or [])[:20], ensure_ascii=False),
            ]
        )
        try:
            raw = await complete_json(tier=ModelTier.CHEAP, system=system, user=user)
            raw_questions = json.loads(raw).get("questions") or []
            mark_last_call(parse_ok=True)
        except LlmProviderError:
            mark_last_call(fallback_used=True)
            flags.append("compose_llm_failed")
        except Exception:
            mark_last_call(parse_ok=False, fallback_used=True)
            flags.append("compose_llm_failed")

    valid_ids = {c["signal_id"] for c in candidates}
    by_id = _candidate_by_id(candidates)
    recent_signal_ids = {str(sid) for sid in (state.get("recent_signal_ids") or []) if sid}
    recent_topics = {topic_key(t) for t in (state.get("recent_texts") or [])}
    used_topics: set[str] = set()
    normalized: list[dict[str, Any]] = []
    used_signals: set[str] = set()
    for i, q in enumerate(raw_questions[:7]):
        if not isinstance(q, dict):
            continue
        text = str(q.get("text") or "").strip()
        if not text:
            continue
        refs = [sid for sid in (q.get("source_signal_ids") or []) if sid in valid_ids]
        if not refs:
            continue  # ADR 0018: no round-robin fake refs
        if _norm_text(text) in recent:
            continue
        if any(sid in recent_signal_ids for sid in refs):
            continue
        topics = _question_topics(refs, by_id)
        if topics & used_topics or topics & recent_topics:
            continue
        used_signals.update(refs)
        used_topics.update(topics)
        normalized.append(
            {
                "id": str(q.get("id") or f"q{i + 1}"),
                "text": text,
                "rationale": (str(q["rationale"]).strip() or None)
                if q.get("rationale")
                else None,
                "source_signal_ids": refs,
                "persona_slug": q.get("persona_slug"),
            }
        )

    if len(normalized) < 5:
        pad = _pad_questions(
            candidates,
            recent,
            len(normalized),
            used_topics=used_topics,
            recent_signal_ids=recent_signal_ids,
            recent_topics=recent_topics,
        )
        for p in pad:
            used_signals.update(p["source_signal_ids"])
        normalized.extend(pad)
        if pad:
            flags.append("template_only" if not raw_questions else "template_pad")

    return {
        "questions": normalized[:7],
        "used_signal_ids": sorted(used_signals),
        "quality_flags": _flags(state, *flags),
    }


# Node-name → function (graph module locks the pipeline order).
PIPELINE = [
    ("ensure_signals", ensure_signals),
    ("cheap_screen", cheap_screen),
    ("shallow_research", shallow_research),
    ("filter", filter_candidates),
    ("deep_research", deep_research),
    ("product_match", product_match),
    ("compose_questions", compose_questions),
]
