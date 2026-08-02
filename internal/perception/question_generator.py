"""Generate landing-page recommended questions from company profile + HK signals."""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.llm.router import ModelTier, complete_json
from internal.memory.knowledge_seed import ensure_default_personas
from internal.memory.models import Entity
from internal.memory.repos import (
    get_latest_questions,
    list_personas,
    list_top_signals,
    save_recommended_questions,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Hong Kong marketing strategist.
Given a company profile and recent HK market signals, produce recommended chat questions
for a marketing assistant landing page.

Return JSON only:
{
  "questions": [
    {
      "id": "q1",
      "text": "question in Traditional Chinese (zh-HK)",
      "rationale": "brief English rationale",
      "source_signal_ids": ["signal_id from input"],
      "persona_slug": "optional persona slug from input"
    }
  ]
}

Rules:
- Produce exactly 5 to 7 questions.
- Each question must reference at least one source_signal_id from the input signals.
- Questions should be actionable for social/content marketing.
- Prefer Traditional Chinese (zh-HK) for question text.
"""


def _profile_summary(company: Entity) -> str:
    profile = company.profile or {}
    lines = [f"Company: {company.name}", f"Slug: {company.slug}"]
    if profile:
        lines.append(f"Profile JSON: {json.dumps(profile, ensure_ascii=False)}")
    else:
        lines.append("Profile: (empty — infer from company name)")
    return "\n".join(lines)


def _signals_summary(signals: list) -> str:
    if not signals:
        return "No recent signals available."
    rows = []
    for s in signals:
        rows.append(
            {
                "signal_id": s.signal_id,
                "source": s.source,
                "title": s.title,
                "excerpt": s.excerpt,
                "metrics": s.metrics,
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


async def _personas_summary(db: AsyncSession) -> str:
    await ensure_default_personas(db)
    personas = await list_personas(db)
    rows = [
        {"slug": p.slug, "label": (p.profile or {}).get("label", p.name)} for p in personas
    ]
    return json.dumps(rows, ensure_ascii=False)


async def generate_questions_for_company(
    db: AsyncSession,
    company: Entity,
    *,
    force: bool = False,
) -> dict:
    if not force:
        cached = await get_latest_questions(db, company.id)
        if cached and cached.expires_at > datetime.now(UTC):
            return {
                "company_id": str(company.id),
                "cached": True,
                "generated_at": cached.generated_at.isoformat(),
                "expires_at": cached.expires_at.isoformat(),
                "questions": cached.questions,
                "source_signal_ids": cached.source_signal_ids,
            }

    signals = await list_top_signals(db, limit=15, region="HK")
    if not signals:
        raise RuntimeError("No HK signals in database — run hot-search worker first")

    user_prompt = "\n\n".join(
        [
            _profile_summary(company),
            "Personas:",
            await _personas_summary(db),
            "Recent HK signals:",
            _signals_summary(signals),
        ]
    )

    try:
        raw = await complete_json(
            tier=ModelTier.CHEAP,
            system=SYSTEM_PROMPT,
            user=user_prompt,
        )
        payload = json.loads(raw)
        questions = payload.get("questions") or []
    except Exception:
        logger.exception("LLM question generation failed; using fallback")
        questions = _fallback_questions(signals)

    valid_signal_ids = {s.signal_id for s in signals}
    normalized: list[dict] = []
    used_signals: set[str] = set()
    for i, q in enumerate(questions[:7]):
        text = (q.get("text") or "").strip()
        if not text:
            continue
        refs = [sid for sid in (q.get("source_signal_ids") or []) if sid in valid_signal_ids]
        if not refs and signals:
            refs = [signals[i % len(signals)].signal_id]
        used_signals.update(refs)
        normalized.append(
            {
                "id": q.get("id") or f"q{i + 1}",
                "text": text,
                "rationale": q.get("rationale"),
                "source_signal_ids": refs,
                "persona_slug": q.get("persona_slug"),
            }
        )

    if len(normalized) < 5:
        normalized.extend(_fallback_questions(signals)[len(normalized) : 5])

    row = await save_recommended_questions(
        db,
        company_id=company.id,
        questions=normalized,
        source_signal_ids=sorted(used_signals),
        ttl_hours=settings.question_cache_ttl_hours,
    )
    await db.commit()
    return {
        "company_id": str(company.id),
        "cached": False,
        "generated_at": row.generated_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "questions": normalized,
        "source_signal_ids": row.source_signal_ids,
    }


def _fallback_questions(signals: list) -> list[dict]:
    templates = [
        "我哋可以點樣利用「{title}」呢個熱話做社交媒體內容？",
        "針對香港市場，「{title}」有咩內容角度值得試？",
        "可唔可以幫我寫一個關於「{title}」嘅 post 草稿？",
        "「{title}」同我哋品牌有咩關聯？應唔應該跟？",
        "有咩 hashtag 同發文時間建議，配合「{title}」？",
    ]
    out: list[dict] = []
    for i, tmpl in enumerate(templates):
        sig = signals[i % len(signals)]
        out.append(
            {
                "id": f"fallback-q{i + 1}",
                "text": tmpl.format(title=sig.title[:60]),
                "rationale": "Template fallback when LLM unavailable",
                "source_signal_ids": [sig.signal_id],
                "persona_slug": "hk-young-professional" if i % 2 == 0 else "hk-parent-shopper",
            }
        )
    return out


async def generate_questions_all_companies(db: AsyncSession, *, force: bool = False) -> list[dict]:
    from internal.memory.repos import list_companies

    results = []
    for company in await list_companies(db):
        try:
            result = await generate_questions_for_company(db, company, force=force)
            results.append(result)
        except Exception:
            logger.exception("Question generation failed for company %s", company.id)
    return results
