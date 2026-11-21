"""Draft-pipeline tool bodies for the main agent — ADR 0062.

``run_propose_angles`` folds the legacy ``load_context → trend_searcher →
product_matcher → brainstormer`` chain into one tool call: deterministic
context assembly, a TrendRank inner call, the SQL catalog match, then the
BriefOut sub-agent (``create_agent`` + ``ToolStrategy``, ADR 0061). The
``state_update`` mirrors what those vertices wrote so downstream guarantees
(angle_gate park, executor_post grounding allowlist) see identical state.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel

from internal.llm.router import LlmProviderError, ModelTier
from internal.memory.knowledge_seed import ensure_default_personas
from internal.memory.product_retrieve import (
    ProductHit,
    hit_to_payload,
    pick_primary,
    search_products_for_member,
)
from internal.memory.repos import (
    get_company,
    get_signals_by_ids,
    list_personas,
    list_top_signals,
)
from internal.session import harness as H
from internal.session import ingest as ingest_mod
from internal.session import prompts
from internal.session.context import get_db
from internal.session.image_format import IMAGE_FORMAT_OPTIONS, lock_brief_to_format
from internal.session.io import BriefOut, TrendRank, offered_angles
from internal.session.state import MODE_AGENT
from internal.session.tiers import NODE_MODEL_TIERS
from internal.session.voice import (
    audience_catalog_from_entities,
    pick_active_persona,
    voice_pack,
)

logger = logging.getLogger(__name__)

_trend_override: BaseChatModel | None = None
_brainstorm_override: BaseChatModel | None = None


def set_trend_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model for the trend-rank call."""
    global _trend_override
    _trend_override = model


def set_brainstorm_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model for the brainstorm call."""
    global _brainstorm_override
    _brainstorm_override = model


@dataclass
class ProposeAnglesResult:
    reply: str  # JSON string the tool returns to the main agent
    state_update: dict[str, Any] = field(default_factory=dict)
    ready: bool = False  # brief written — handoff("start") may proceed


def _propose_error(code: str) -> ProposeAnglesResult:
    return ProposeAnglesResult(reply=json.dumps({"error": code}))


async def _run_typed(
    tier_key: str,
    system: str,
    user_prompt: str,
    out_type: Any,
    override: BaseChatModel | None,
) -> Any | None:
    """Typed inner call; provider outage degrades to a parse miss (None)."""
    if override is not None:
        chat, label = override, H.model_label(override)
    else:
        chat, label = H.live_lc_model(NODE_MODEL_TIERS[tier_key] or ModelTier.CHEAP)
    try:
        return await H.run_typed_lc_agent(
            chat=chat,
            label=label,
            tier=NODE_MODEL_TIERS[tier_key],
            system=system,
            user_prompt=user_prompt,
            tools=[],
            out_type=out_type,
            is_valid=lambda _parsed: True,
            log_tag=tier_key,
        )
    except LlmProviderError:
        return None


async def _load_context(
    db: Any, payload: dict[str, Any], update: dict[str, Any]
) -> dict[str, Any]:
    """Port of ``load_context`` — company, voice pack, audience catalog."""
    company_id = payload.get("company_id")
    slim: dict[str, Any] = {"company_id": company_id} if company_id else {}
    pack = voice_pack(None)
    if company_id:
        company = await get_company(db, uuid.UUID(str(company_id)))
        if company:
            slim = {
                "company_id": str(company.id),
                "name": company.name,
                "slug": company.slug,
            }
            pack = voice_pack(company.profile)
    await ensure_default_personas(db)
    update["company_context"] = slim
    update["voice_pack"] = pack
    update["audience_catalog"] = audience_catalog_from_entities(await list_personas(db))
    return slim


async def _rank_trends(
    db: Any, payload: dict[str, Any], company: dict[str, Any], update: dict[str, Any]
) -> None:
    """Port of ``trend_searcher`` — prefer research_signals, else PG(+handoff)."""
    user = str(payload.get("user_request") or "")
    signals_trusted = payload.get("signals_trusted")
    prior = list(payload.get("research_signals") or [])
    if prior:
        signals_payload = prior[:20]
        ranked_ids = [s["signal_id"] for s in signals_payload if s.get("signal_id")][:8]
        parsed: TrendRank | None = await _run_typed(
            "trend_searcher",
            prompts.TREND_SEARCH,
            json.dumps(
                {
                    "company": company,
                    "user_request": user,
                    "signals": signals_payload,
                    "signals_trusted": signals_trusted,
                },
                ensure_ascii=False,
            ),
            TrendRank,
            _trend_override,
        )
        valid = {s["signal_id"] for s in signals_payload if s.get("signal_id")}
        if parsed and parsed.ranked_signal_ids:
            ranked_ids = [sid for sid in parsed.ranked_signal_ids if sid in valid][:8]
        order = {sid: i for i, sid in enumerate(ranked_ids)}
        update["source_signal_ids"] = ranked_ids
        update["ranked_signals"] = sorted(
            [s for s in signals_payload if s.get("signal_id") in order],
            key=lambda s: order[str(s["signal_id"])],
        )
        if parsed and parsed.notes:
            update["trend_notes"] = parsed.notes
        return

    signals = await list_top_signals(db, limit=20, region="HK")
    handoff_ids = [
        str(sid) for sid in (payload.get("handoff_signal_ids") or []) if sid
    ]
    if handoff_ids:
        handoff = await get_signals_by_ids(db, handoff_ids)
        if handoff:
            signals = handoff + [s for s in signals if s.signal_id not in set(handoff_ids)]
    if not signals:
        update["source_signal_ids"] = []
        update["ranked_signals"] = []
        update["trend_notes"] = ""
        return

    parsed = await _run_typed(
        "trend_searcher",
        prompts.TREND_SEARCH,
        json.dumps(
            {
                "company": company,
                "user_request": user,
                "signals": ingest_mod.signal_row_dicts(signals),
                "signals_trusted": signals_trusted,
            },
            ensure_ascii=False,
        ),
        TrendRank,
        _trend_override,
    )
    if parsed and parsed.ranked_signal_ids:
        valid = {s.signal_id for s in signals}
        ranked_ids = [sid for sid in parsed.ranked_signal_ids if sid in valid][:8]
    else:
        ranked_ids = [s.signal_id for s in signals[:5]]
    order = {sid: i for i, sid in enumerate(ranked_ids)}
    update["source_signal_ids"] = ranked_ids
    update["ranked_signals"] = ingest_mod.signal_row_dicts(
        sorted([s for s in signals if s.signal_id in order], key=lambda s: order[s.signal_id])
    )
    if parsed and parsed.notes:
        update["trend_notes"] = parsed.notes


def _product_queries(research: dict[str, Any], user: str) -> list[str]:
    queries: list[str] = []
    for raw in (
        str(research.get("product_surface") or "").strip(),
        str(research.get("entity_surface") or "").strip(),
        user.strip()[:200],
    ):
        if raw and raw not in queries:
            queries.append(raw)
    return queries


def _should_match_product(research: dict[str, Any]) -> bool:
    """Port of ``_should_match_product`` — inside the tool, intent is always start."""
    if research.get("need_product"):
        return True
    if str(research.get("sell_intent") or "none") in ("explicit", "implicit"):
        return True
    return bool(str(research.get("product_surface") or "").strip())


def _related_payloads(
    user_hits: list[ProductHit],
    signal_hits: list[ProductHit],
    *,
    exclude: set[uuid.UUID],
) -> list[dict[str, Any]]:
    """Org-scope related products (ADR 0040): user-pool first, dedupe, cap 2."""
    out: list[dict[str, Any]] = []
    seen = set(exclude)
    for hit in (*user_hits, *signal_hits):
        if hit.product.owner_scope != "org" or hit.product.id in seen:
            continue
        seen.add(hit.product.id)
        out.append(hit_to_payload(hit))
        if len(out) >= 2:
            break
    return out


async def _match_products(
    db: Any, payload: dict[str, Any], update: dict[str, Any]
) -> dict[str, Any]:
    """Port of ``product_matcher`` — SQL catalog match, no LLM."""
    empty = {
        "primary_product": None,
        "related_products": [],
        "product_clarify": False,
        "product_context_ids": [],
        "product_candidates": [],
    }
    ranked = update.get("ranked_signals") or []
    signal_queries = [str(s["title"]).strip()[:200] for s in ranked[:2] if s.get("title")]
    research = dict(payload.get("research") or {})
    if not _should_match_product(research) and not signal_queries:
        return empty
    company_id, user_id = payload.get("company_id"), payload.get("user_id")
    if not company_id or not user_id:
        return empty

    cid, uid = uuid.UUID(str(company_id)), uuid.UUID(str(user_id))
    queries = _product_queries(research, str(payload.get("user_request") or ""))
    hits = (
        await search_products_for_member(db, company_id=cid, user_id=uid, queries=queries, limit=5)
        if queries
        else []
    )
    signal_hits = (
        await search_products_for_member(
            db, company_id=cid, user_id=uid, queries=signal_queries, limit=4
        )
        if signal_queries
        else []
    )
    if not hits:
        return {**empty, "related_products": _related_payloads([], signal_hits, exclude=set())}

    primary, clarify = pick_primary(hits)
    candidates = [hit_to_payload(h) for h in hits[:3]]
    if clarify or primary is None:
        return {
            "primary_product": None,
            "related_products": [],
            "product_clarify": True,
            "product_context_ids": [],
            "product_candidates": candidates,
        }
    primary_payload = hit_to_payload(primary)
    return {
        "primary_product": primary_payload,
        "related_products": _related_payloads(
            hits[1:], signal_hits, exclude={primary.product.id}
        ),
        "product_clarify": False,
        "product_context_ids": [primary_payload["product_id"]],
        "product_candidates": [],
    }


def _fallback_brief(catalog: list[dict[str, Any]], signals: list[dict[str, Any]]) -> dict[str, Any]:
    titles = [s.get("title") for s in signals[:3] if s.get("title")]
    topic = titles[0] if titles else "香港熱話"
    return {
        "can_do": [f"圍繞「{topic}」寫一則社交貼文", "加入品牌語氣同 CTA"],
        "cannot_do": ["未按 Confirm 前唔可以真正發佈", "唔好捏造未有 signal 支撐嘅數據"],
        "angles": [f"用「{topic}」連結品牌價值", "短片/靜態圖配合熱搜節奏"],
        "recommended_angle_index": 0,
        "persona": catalog[0].get("slug") if catalog else None,
        "summary": f"基於近期 HK signals，建議做一則同「{topic}」相關嘅 grounded post。",
    }


async def run_propose_angles(payload: dict[str, Any]) -> ProposeAnglesResult:
    """Context → trend rank → product match → BriefOut, as one tool call."""
    try:
        db = get_db()
    except RuntimeError:
        return _propose_error("no_session_db")

    update: dict[str, Any] = {"mode": MODE_AGENT}
    company = await _load_context(db, payload, update)
    await _rank_trends(db, payload, company, update)

    update.update(await _match_products(db, payload, update))
    if update["product_clarify"]:
        reply = json.dumps(
            {"clarify": True, "candidates": update["product_candidates"][:3]},
            ensure_ascii=False,
        )
        return ProposeAnglesResult(reply=reply, state_update=update)

    signals = list(update.get("ranked_signals") or [])[:8]
    brief_payload = {
        "company": company,
        "voice_pack": update["voice_pack"],
        "audience_catalog": update["audience_catalog"],
        "user_request": str(payload.get("user_request") or ""),
        "signals": signals,
        "signals_trusted": payload.get("signals_trusted"),
        "source_signal_ids": update.get("source_signal_ids") or [],
        "primary_product": update.get("primary_product"),
        "related_products": (update.get("related_products") or [])[:2],
        "prior_brief": payload.get("prior_brief") or {},
        "angle_feedback": payload.get("angle_feedback"),
        "agent_notes": payload.get("agent_notes"),
        "image_format": payload.get("image_format"),
    }
    parsed: BriefOut | None = await _run_typed(
        "brainstormer",
        prompts.BRAINSTORM,
        json.dumps(brief_payload, ensure_ascii=False),
        BriefOut,
        _brainstorm_override,
    )
    if parsed:
        brief = parsed.model_dump()
        idx = brief.get("recommended_angle_index")
        if (
            not isinstance(idx, int)
            or isinstance(idx, bool)
            or not (0 <= idx < len(offered_angles(brief)))
        ):
            brief["recommended_angle_index"] = None
    else:
        brief = _fallback_brief(update["audience_catalog"], signals)

    sticky = str(payload.get("chosen_image_format") or "").strip()
    current = str(payload.get("current_image_format") or "").strip()
    if sticky in IMAGE_FORMAT_OPTIONS or current in IMAGE_FORMAT_OPTIONS:
        brief = lock_brief_to_format(brief, str(payload.get("image_format") or ""))

    update["brief"] = brief
    update["active_persona"] = pick_active_persona(
        update["audience_catalog"], brief.get("persona")
    )
    update["angle_feedback"] = None
    reply = json.dumps(
        {
            "angles": offered_angles(brief),
            "recommended_angle_index": brief.get("recommended_angle_index"),
            "persona": brief.get("persona"),
            "summary": brief.get("summary"),
        },
        ensure_ascii=False,
    )
    return ProposeAnglesResult(reply=reply, state_update=update, ready=True)
