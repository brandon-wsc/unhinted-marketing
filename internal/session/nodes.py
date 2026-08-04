"""Session LangGraph nodes — DB + LiteLLM with heuristic fallbacks."""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from pydantic import BaseModel

from internal.llm.recorder import mark_last_call
from internal.llm.router import (
    LlmProviderError,
    ModelTier,
    astream_text,
    complete_json,
    complete_text,
    generate_image,
    has_llm_credentials,
    resolve_image_model,
    resolve_model,
)
from internal.media.storage import media_object_key, persist_generated_image
from internal.memory.knowledge_seed import ensure_default_personas
from internal.memory.repos import get_company, get_signals_by_ids, list_personas, list_top_signals
from internal.session.voice import voice_context
from internal.session.image_format import (
    compose_generation_prompt,
    image_format_from_text,
    normalize_image_format,
)
from internal.session import prompts
from internal.session.context import get_db
from internal.session.events import session_event_bus
from internal.session.io import (
    BriefOut,
    DraftOut,
    EditOut,
    ImagePlanOut,
    IntentRoute,
    ReviewOut,
    TrendRank,
)
from internal.session.state import MODE_AGENT, MODE_CHAT, MODE_PREVIEW, SessionState
from internal.session.tiers import NODE_MODEL_TIERS
from internal.session.trace import record_node_step

logger = logging.getLogger(__name__)

MAX_REVIEW_RETRIES = 2
T = TypeVar("T", bound=BaseModel)


def _last_user_text(state: SessionState) -> str:
    messages = state.get("messages") or []
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content") or "")
    return ""


def _append_assistant(state: SessionState, content: str) -> list[dict[str, Any]]:
    messages = list(state.get("messages") or [])
    messages.append({"role": "assistant", "content": content})
    return messages


def _signals_payload(signals: list) -> list[dict[str, Any]]:
    return [
        {
            "signal_id": s.signal_id,
            "source": s.source,
            "title": s.title,
            "excerpt": s.excerpt,
            "metrics": s.metrics or {},
        }
        for s in signals
    ]


def _heuristic_intent(state: SessionState) -> str:
    mode = state.get("mode", MODE_CHAT)
    lower = _last_user_text(state).lower()
    if mode == MODE_PREVIEW and any(
        k in lower for k in ("可以出", "confirm", "publish", "發佈", "发布")
    ):
        return "confirm_intent"
    if mode == MODE_PREVIEW:
        return "revise"
    if any(
        k in lower
        for k in ("開始", "开始", "start", "做帖", "post", "推薦", "推荐", "草稿", "寫帖", "写帖")
    ):
        return "start"
    if mode == MODE_AGENT and not (state.get("draft") or {}).get("caption"):
        return "start"
    return "chat"


def _wants_image_change(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in ("圖", "图片", "圖片", "image", "photo", "visual", "封面"))


async def _parse_llm_json(tier: ModelTier, system: str, user: str, model: type[T]) -> T | None:
    if not has_llm_credentials():
        return None
    try:
        raw = await complete_json(tier=tier, system=system, user=user)
        parsed = model.model_validate_json(raw)
    except LlmProviderError:
        # Provider/transport/auth/model failures must surface to the UI — do not
        # silently fall back while credentials are configured. The record already
        # carries status=provider_error; no heuristic takes over, so no fallback mark.
        raise
    except Exception:
        # ADR 0005: validation failed and heuristics take over — the fine-tuning signal.
        mark_last_call(parse_ok=False, fallback_used=True)
        logger.exception("LLM JSON node failed (%s)", model.__name__)
        return None
    mark_last_call(parse_ok=True)
    return parsed


def _llm_failure_reply(exc: LlmProviderError, *, chinese: bool) -> str:
    if chinese:
        return (
            f"AI 服務暫時唔可用（{exc.kind}"
            + (f" · {exc.model}" if exc.model else "")
            + f"）：{exc.message}"
        )
    return (
        f"AI service unavailable ({exc.kind}"
        + (f" · {exc.model}" if exc.model else "")
        + f"): {exc.message}"
    )


def _thread_uuid(state: SessionState) -> uuid.UUID | None:
    thread_id = state.get("thread_id")
    if not thread_id:
        return None
    try:
        return uuid.UUID(str(thread_id))
    except ValueError:
        return None


def _agent_progress_payload(node: str) -> dict[str, Any]:
    tier = NODE_MODEL_TIERS.get(node)
    if node == "executor_image_gen":
        return {
            "node": node,
            "model_tier": None,
            "model": resolve_image_model(),
        }
    return {
        "node": node,
        "model_tier": tier.value if tier else None,
        "model": resolve_model(tier) if tier else None,
    }


async def publish_agent_progress(state: SessionState, node: str) -> None:
    """Fan out agent.progress the moment a node starts (not post-turn)."""
    payload = _agent_progress_payload(node)
    session_id = _thread_uuid(state)
    if not session_id:
        return
    session_event_bus.record_turn_progress(session_id, "agent.progress", payload)
    try:
        await session_event_bus.publish(session_id, "agent.progress", payload)
    except Exception:
        logger.exception("failed to publish agent.progress (%s)", node)


NodeFn = Callable[[SessionState], Awaitable[dict[str, Any]]]


def agent_progress(node: str) -> Callable[[NodeFn], NodeFn]:
    """Decorate a graph node to announce itself over SSE before it runs."""

    def decorator(fn: NodeFn) -> NodeFn:
        @wraps(fn)
        async def wrapped(state: SessionState) -> dict[str, Any]:
            await publish_agent_progress(state, node)
            out = await fn(state)
            record_node_step(node, dict(state), out)
            return out

        return wrapped

    return decorator


@agent_progress("route_intent")
async def route_intent(state: SessionState) -> dict[str, Any]:
    payload = {
        "mode": state.get("mode", MODE_CHAT),
        "has_draft": bool((state.get("draft") or {}).get("caption")),
        "last_user_message": _last_user_text(state),
    }
    parsed = await _parse_llm_json(
        NODE_MODEL_TIERS["route_intent"] or ModelTier.CHEAP,
        prompts.ROUTE_INTENT,
        json.dumps(payload, ensure_ascii=False),
        IntentRoute,
    )
    intent = parsed.intent if parsed else _heuristic_intent(state)
    mode = state.get("mode", MODE_CHAT)
    if intent == "revise" and mode != MODE_PREVIEW:
        intent = "start" if _heuristic_intent(state) == "start" else "chat"
    if intent == "confirm_intent" and mode != MODE_PREVIEW:
        intent = "chat"
    return {"intent": intent}


@agent_progress("load_context")
async def load_context(state: SessionState) -> dict[str, Any]:
    db = get_db()
    company_id = state.get("company_id")
    company_payload: dict[str, Any] = {
        "company_id": company_id,
        "voice": voice_context(None),
    }
    if company_id:
        company = await get_company(db, uuid.UUID(company_id))
        if company:
            profile = company.profile or {}
            company_payload = {
                "company_id": str(company.id),
                "name": company.name,
                "slug": company.slug,
                "profile": profile,
                "voice": voice_context(profile),
            }
    await ensure_default_personas(db)
    personas = await list_personas(db)
    persona_rows = [
        {"slug": p.slug, "name": p.name, "profile": p.profile or {}} for p in personas
    ]
    return {
        "mode": MODE_AGENT,
        "company_context": {**company_payload, "personas": persona_rows},
    }


@agent_progress("trend_searcher")
async def trend_searcher(state: SessionState) -> dict[str, Any]:
    db = get_db()
    signals = await list_top_signals(db, limit=20, region="HK")
    ctx = dict(state.get("company_context") or {})
    if not signals:
        ctx["ranked_signals"] = []
        return {"source_signal_ids": [], "company_context": ctx}

    payload = {
        "company": ctx,
        "user_request": _last_user_text(state),
        "signals": _signals_payload(signals),
    }
    parsed = await _parse_llm_json(
        NODE_MODEL_TIERS["trend_searcher"] or ModelTier.CHEAP,
        prompts.TREND_SEARCH,
        json.dumps(payload, ensure_ascii=False),
        TrendRank,
    )
    valid = {s.signal_id for s in signals}
    if parsed and parsed.ranked_signal_ids:
        ranked_ids = [sid for sid in parsed.ranked_signal_ids if sid in valid][:8]
    else:
        ranked_ids = [s.signal_id for s in signals[:5]]

    order = {sid: i for i, sid in enumerate(ranked_ids)}
    ranked = sorted(
        [s for s in signals if s.signal_id in order],
        key=lambda s: order[s.signal_id],
    )
    ctx["ranked_signals"] = _signals_payload(ranked)
    if parsed and parsed.notes:
        ctx["trend_notes"] = parsed.notes
    return {"source_signal_ids": ranked_ids, "company_context": ctx}


# Batch streamed pieces so a long reply cannot overflow the per-subscriber
# SSE queue (events are put_nowait; full queues drop events).
_DELTA_FLUSH_CHARS = 24


async def _publish_deltas(
    session_id: uuid.UUID, pending: list[str], *, force: bool = False
) -> None:
    text = "".join(pending)
    if not text or (not force and len(text) < _DELTA_FLUSH_CHARS):
        return
    pending.clear()
    try:
        await session_event_bus.publish(session_id, "message.delta", {"content": text})
    except Exception:
        logger.exception("failed to publish message.delta")


async def _chat_stream(state: SessionState, user: str) -> str | None:
    """Stream the chat reply, publishing message.delta events live per turn."""
    history = (state.get("messages") or [])[-8:]
    payload = json.dumps({"history": history, "latest": user}, ensure_ascii=False)
    tier = NODE_MODEL_TIERS["chat"] or ModelTier.CHEAP
    session_id = _thread_uuid(state)

    parts: list[str] = []
    pending: list[str] = []
    async for piece in astream_text(tier=tier, system=prompts.CHAT, user=payload):
        parts.append(piece)
        pending.append(piece)
        if session_id:
            await _publish_deltas(session_id, pending)
    if session_id:
        await _publish_deltas(session_id, pending, force=True)
    return "".join(parts).strip() or None


async def chat(state: SessionState) -> dict[str, Any]:
    user = _last_user_text(state)
    reply: str | None = None
    chinese = any("\u4e00" <= c <= "\u9fff" for c in user)
    llm_error: str | None = None
    if has_llm_credentials():
        try:
            reply = await _chat_stream(state, user)
        except LlmProviderError as exc:
            logger.warning("chat LLM stream failed: %s", exc.message)
            llm_error = exc.message
            reply = _llm_failure_reply(exc, chinese=chinese)
        except Exception:
            logger.exception("chat LLM stream failed — retrying without stream")
            try:
                history = (state.get("messages") or [])[-8:]
                reply = await complete_text(
                    tier=NODE_MODEL_TIERS["chat"] or ModelTier.CHEAP,
                    system=prompts.CHAT,
                    user=json.dumps({"history": history, "latest": user}, ensure_ascii=False),
                )
            except LlmProviderError as exc:
                logger.warning("chat LLM failed: %s", exc.message)
                llm_error = exc.message
                reply = _llm_failure_reply(exc, chinese=chinese)
            except Exception:
                logger.exception("chat LLM failed")
    if not reply:
        reply = (
            "我可以幫你睇香港熱話同草擬社交貼文。想開始嘅話，揀一條推薦問題，"
            "或者直接講你想做咩內容。"
            if chinese
            else (
                "I can help with HK trends and draft social posts. "
                "Pick a recommended question or tell me what you want to create."
            )
        )
    out: dict[str, Any] = {"messages": _append_assistant(state, reply), "mode": MODE_CHAT}
    if llm_error:
        out["error"] = llm_error
    record_node_step("chat", dict(state), out)
    return out


@agent_progress("brainstormer")
async def brainstormer(state: SessionState) -> dict[str, Any]:
    ctx = state.get("company_context") or {}
    payload = {
        "company": ctx,
        "user_request": _last_user_text(state),
        "signals": ctx.get("ranked_signals") or [],
        "source_signal_ids": state.get("source_signal_ids") or [],
    }
    parsed = await _parse_llm_json(
        NODE_MODEL_TIERS["brainstormer"] or ModelTier.MEDIUM,
        prompts.BRAINSTORM,
        json.dumps(payload, ensure_ascii=False),
        BriefOut,
    )
    if parsed:
        brief = parsed.model_dump()
    else:
        titles = [s.get("title") for s in (ctx.get("ranked_signals") or [])[:3] if s.get("title")]
        topic = titles[0] if titles else "香港熱話"
        personas = ctx.get("personas") or []
        brief = {
            "can_do": [f"圍繞「{topic}」寫一則社交貼文", "加入品牌語氣同 CTA"],
            "cannot_do": ["未按 Confirm 前唔可以真正發佈", "唔好捏造未有 signal 支撐嘅數據"],
            "angles": [f"用「{topic}」連結品牌價值", "短片/靜態圖配合熱搜節奏"],
            "persona": personas[0].get("slug") if personas else None,
            "summary": f"基於近期 HK signals，建議做一則同「{topic}」相關嘅 grounded post。",
        }
    return {"mode": MODE_AGENT, "brief": brief}


@agent_progress("executor_post")
async def executor_post(state: SessionState) -> dict[str, Any]:
    ctx = state.get("company_context") or {}
    signal_ids = list(state.get("source_signal_ids") or [])
    payload = {
        "company": ctx,
        "brief": state.get("brief") or {},
        "signals": ctx.get("ranked_signals") or [],
        "allowed_signal_ids": signal_ids,
        "user_request": _last_user_text(state),
    }
    parsed = await _parse_llm_json(
        NODE_MODEL_TIERS["executor_post"] or ModelTier.MEDIUM,
        prompts.EXECUTOR_POST,
        json.dumps(payload, ensure_ascii=False),
        DraftOut,
    )
    allowed = set(signal_ids)
    if parsed:
        refs = [sid for sid in parsed.source_signal_ids if sid in allowed] or signal_ids[:3]
        draft = {
            "caption": parsed.caption,
            "hashtags": parsed.hashtags or ["#HongKong", "#Marketing"],
            "cta": parsed.cta or "了解更多",
        }
    else:
        ranked = ctx.get("ranked_signals") or []
        title = ranked[0].get("title") if ranked else "香港熱話"
        company_name = ctx.get("name") or "我哋"
        draft = {
            "caption": (
                f"最近成日聽到「{title}」？"
                f"「{company_name}」都睇住——嚟緊有啲貼地內容，留言話我哋知你最想知邊方面。"
            ),
            "hashtags": ["#HongKong", "#熱話"],
            "cta": "留言話我哋知",
        }
        refs = signal_ids[:3]

    return {
        "draft": draft,
        "source_signal_ids": refs,
        "need_image": True,
        "grounding_ok": True,
    }


@agent_progress("grounding_check")
async def grounding_check(state: SessionState) -> dict[str, Any]:
    db = get_db()
    ids = list(state.get("source_signal_ids") or [])
    if not ids:
        # Allow empty only if there are truly no signals in the system.
        signals = await list_top_signals(db, limit=1, region="HK")
        if not signals:
            return {
                "grounding_ok": True,
                "reviewer_feedback": "No HK signals in DB — draft is template-only",
            }
        return {
            "grounding_ok": False,
            "reviewer_feedback": "Draft has no source_signal_ids but signals exist in DB",
            "source_signal_ids": [],
        }

    found = await get_signals_by_ids(db, ids)
    found_ids = {s.signal_id for s in found}
    missing = [sid for sid in ids if sid not in found_ids]
    kept = [sid for sid in ids if sid in found_ids]
    if missing:
        return {
            "source_signal_ids": kept,
            "grounding_ok": False,
            "reviewer_feedback": f"Missing or invalid source_signal_ids: {missing}",
        }
    return {"source_signal_ids": kept, "grounding_ok": True, "reviewer_feedback": ""}


@agent_progress("reviewer")
async def reviewer(state: SessionState) -> dict[str, Any]:
    attempts = int(state.get("review_attempts") or 0)
    if state.get("grounding_ok") is False:
        return {
            "reviewer_passed": False,
            "reviewer_feedback": state.get("reviewer_feedback")
            or "Grounding check failed — fix citations",
            "review_attempts": attempts,
        }

    payload = {
        "draft": state.get("draft") or {},
        "brief": state.get("brief") or {},
        "company": state.get("company_context") or {},
        "source_signal_ids": state.get("source_signal_ids") or [],
        "grounding_ok": state.get("grounding_ok", True),
        "mode": state.get("mode"),
    }
    parsed = await _parse_llm_json(
        NODE_MODEL_TIERS["reviewer"] or ModelTier.STRONG,
        prompts.REVIEWER,
        json.dumps(payload, ensure_ascii=False),
        ReviewOut,
    )
    if parsed:
        return {
            "reviewer_passed": parsed.passed,
            "reviewer_feedback": parsed.feedback if not parsed.passed else "",
            "review_attempts": attempts,
        }

    # Fallback: pass when grounded and caption present
    draft = state.get("draft") or {}
    ok = bool(draft.get("caption")) and state.get("grounding_ok", True) is not False
    return {
        "reviewer_passed": ok,
        "reviewer_feedback": "" if ok else "Caption missing or grounding failed",
        "review_attempts": attempts,
    }


@agent_progress("edit_copy")
async def edit_copy(state: SessionState) -> dict[str, Any]:
    user = _last_user_text(state)
    feedback = state.get("reviewer_feedback") or ""
    signal_ids = list(state.get("source_signal_ids") or [])
    payload = {
        "draft": state.get("draft") or {},
        "user_feedback": user,
        "reviewer_feedback": feedback,
        "signals": (state.get("company_context") or {}).get("ranked_signals") or [],
        "allowed_signal_ids": signal_ids,
    }
    parsed = await _parse_llm_json(
        NODE_MODEL_TIERS["edit_copy"] or ModelTier.MEDIUM,
        prompts.EDIT_COPY,
        json.dumps(payload, ensure_ascii=False),
        EditOut,
    )
    allowed = set(signal_ids)
    if parsed:
        refs = [sid for sid in parsed.source_signal_ids if sid in allowed] or signal_ids
        out: dict[str, Any] = {
            "draft": {
                "caption": parsed.caption,
                "hashtags": parsed.hashtags,
                "cta": parsed.cta,
            },
            "source_signal_ids": refs,
            "need_image": parsed.need_image or _wants_image_change(user),
            "grounding_ok": True,
        }
        fmt = image_format_from_text(user)
        if fmt:
            out["image_format"] = fmt
            out["need_image"] = True
        return out

    draft = dict(state.get("draft") or {})
    note = feedback or user
    caption = draft.get("caption") or "（修訂草稿）"
    if note:
        caption = f"{caption}\n\n（修訂：{note[:200]}）"
    draft["caption"] = caption
    out: dict[str, Any] = {
        "draft": draft,
        "need_image": _wants_image_change(user),
        "grounding_ok": True,
    }
    fmt = image_format_from_text(user)
    if fmt:
        out["image_format"] = fmt
        out["need_image"] = True
    return out


@agent_progress("executor_image_plan")
async def executor_image_plan(state: SessionState) -> dict[str, Any]:
    fmt = normalize_image_format(state.get("image_format"))
    payload = {
        "draft": state.get("draft") or {},
        "brief": state.get("brief") or {},
        "company": state.get("company_context") or {},
        "image_format": fmt,
    }
    parsed = await _parse_llm_json(
        NODE_MODEL_TIERS["executor_image_plan"] or ModelTier.MEDIUM,
        prompts.IMAGE_PLAN,
        json.dumps(payload, ensure_ascii=False),
        ImagePlanOut,
    )
    if parsed:
        plan = parsed.model_dump()
        plan["format"] = normalize_image_format(plan.get("format") or fmt)
        if plan["format"] != "comic_4panel":
            plan["panels"] = []
        return {"image_plan": plan, "image_format": plan["format"]}

    company = (state.get("company_context") or {}).get("name") or "brand"
    caption = ((state.get("draft") or {}).get("caption") or "")[:120]
    if fmt == "comic_4panel":
        plan = {
            "format": "comic_4panel",
            "prompt": (
                f"4-panel comic strip for {company}, Hong Kong everyday scenes "
                f"inspired by: {caption or 'market trends'}, clear gutters, "
                "no logos, no unreadable text"
            ),
            "composition": "2x2 comic grid, equal panels, reading L→R then top→bottom",
            "style": "clean line comic, contemporary HK urban",
            "avoid": ["logos", "watermarks", "real celebrity faces", "dense readable text"],
            "panels": [
                {"index": 1, "beat": "hook scene — instant everyday recognition; no product"},
                {"index": 2, "beat": "escalate human friction / absurdity"},
                {"index": 3, "beat": "peak pain — still no hard sell"},
                {"index": 4, "beat": "product as soft remedy; attitude, not feature list"},
            ],
        }
    else:
        plan = {
            "format": "single",
            "prompt": (
                f"Clean modern social media image for {company}, Hong Kong urban mood, "
                f"inspired by: {caption or 'market trends'}, no logos, no unreadable text"
            ),
            "composition": "subject centered, negative space for optional caption overlay",
            "style": "bright, contemporary, editorial",
            "avoid": ["logos", "watermarks", "real celebrity faces"],
            "panels": [],
        }
    return {"image_plan": plan, "image_format": fmt}


@agent_progress("executor_image_gen")
async def executor_image_gen(state: SessionState) -> dict[str, Any]:
    """Render via LLM_IMAGE_MODEL (LiteLLM). Wrong/chat-only models must error.

    - No credentials (CI / offline): placeholder URL for UI mock.
    - ``LLM_IMAGE_MODEL=placeholder``: explicit mock even with credentials.
    - Credentials + unset image model: ``LlmProviderError`` (do not silently succeed).
    - Credentials + real model: ``aimage_generation``; provider failures surface as
      ``LlmProviderError`` → ``llm.failed`` in the session turn.
    """
    revision = int(state.get("revision") or 0) + 1
    thread = state.get("thread_id") or "session"
    placeholder = f"placeholder://local/{thread}/r{revision}.png"

    image_model = resolve_image_model()
    if not has_llm_credentials():
        return {"image_url": placeholder}
    if image_model and image_model.lower() == "placeholder":
        return {"image_url": placeholder}
    if not image_model:
        raise LlmProviderError(
            "No image model configured (set LLM_IMAGE_MODEL, e.g. dall-e-3). "
            "Chat-only models (DeepSeek, gpt-4o-mini, …) cannot generate images.",
            kind="unsupported",
        )

    plan = state.get("image_plan") or {}
    prompt = compose_generation_prompt(plan)
    if not prompt:
        company = (state.get("company_context") or {}).get("name") or "brand"
        prompt = f"Clean modern social media image for {company}, Hong Kong urban mood"

    # Size is provider-specific; LiteLLM drop_params handles unsupported keys.
    raw_ref = await generate_image(prompt=prompt)
    key = media_object_key(session_id=str(thread), revision=revision)
    url = await persist_generated_image(raw_ref, key=key)
    return {"image_url": url}


async def ack_confirm(state: SessionState) -> dict[str, Any]:
    user = _last_user_text(state)
    reply: str | None = None
    if has_llm_credentials():
        try:
            reply = await complete_text(
                tier=NODE_MODEL_TIERS["ack_confirm"] or ModelTier.CHEAP,
                system=prompts.ACK_CONFIRM,
                user=user or "可以出",
                temperature=0.3,
            )
        except Exception:
            logger.exception("ack_confirm LLM failed")
    if not reply:
        chinese = any("\u4e00" <= c <= "\u9fff" for c in user) or not user
        reply = (
            "收到！內容已經準備好。請喺介面撳 Confirm 掣先會真正發佈——聊天入面講「可以出」唔等於發佈。"
            if chinese
            else (
                "Got it — your draft is ready. Tap Confirm in the UI to publish. "
                "Saying so in chat does not publish."
            )
        )
    out = {
        "messages": _append_assistant(state, reply),
        "pending_confirm": True,
    }
    record_node_step("ack_confirm", dict(state), out)
    return out


async def persist_preview(state: SessionState) -> dict[str, Any]:
    revision = int(state.get("revision") or 0) + 1
    token = secrets.token_urlsafe(24)
    out = {
        "mode": MODE_PREVIEW,
        "revision": revision,
        "approval_token": token,
        "need_image": False,
        "pending_confirm": False,
    }
    record_node_step("persist_preview", dict(state), out)
    return out


def route_after_intent(state: SessionState) -> str:
    intent = state.get("intent") or "chat"
    if intent == "start":
        return "load_context"
    if intent == "revise":
        return "edit_copy"
    if intent == "confirm_intent":
        return "ack_confirm"
    return "chat"


def route_after_reviewer(state: SessionState) -> str:
    if not state.get("reviewer_passed", False):
        attempts = int(state.get("review_attempts") or 0) + 1
        if attempts > MAX_REVIEW_RETRIES:
            return "review_exhausted"
        return "edit_copy"
    if state.get("need_image", False):
        return "executor_image_plan"
    return "persist_preview"


def bump_review_attempt(state: SessionState) -> dict[str, Any]:
    return {"review_attempts": int(state.get("review_attempts") or 0) + 1}


def review_exhausted(state: SessionState) -> dict[str, Any]:
    feedback = state.get("reviewer_feedback") or "Reviewer rejected the draft"
    messages = _append_assistant(
        state,
        f"草稿未能通過審核（已重試 {MAX_REVIEW_RETRIES} 次）：{feedback}",
    )
    out = {
        "messages": messages,
        "error": f"Reviewer failed after {MAX_REVIEW_RETRIES} retries",
        "review_attempts": int(state.get("review_attempts") or 0) + 1,
    }
    record_node_step("review_exhausted", dict(state), out)
    return out
