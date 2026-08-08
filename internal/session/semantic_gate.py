"""Semantic research gate via Aurelio semantic-router + FastEmbed (ADR 0009).

Preferred small multilingual model was ``intfloat/multilingual-e5-small``, but
FastEmbed's registry does not ship it (only ``multilingual-e5-large`` ~2GB).
Default: ``sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2``.

Override with ``SEMANTIC_ROUTER_MODEL`` (must be a FastEmbed-supported id).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Literal

from internal.config import settings

logger = logging.getLogger(__name__)

SemanticRouteName = Literal["chitchat", "act_no_search", "need_search"]

# FastEmbed-supported multilingual small (see TextEmbedding.list_supported_models).
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_CHITCHAT_UTTERANCES = [
    "hi",
    "hello",
    "hey",
    "你好",
    "哈囉",
    "早安",
    "午安",
    "晚安",
    "謝謝",
    "感謝",
    "拜拜",
    "bye bye",
    "thank you",
    "有人在嗎",
    "你好呀",
    "hihi",
    "點用",
    "怎么用",
    "怎麼用",
    "如何使用",
    "what can you do",
    "who are you",
    "你係邊個",
    "你是谁",
    "點用呢個app",
    "教我用",
    "點用 Unhinted",
]

_ACT_NO_SEARCH_UTTERANCES = [
    "幫我做帖",
    "幫我寫帖",
    "寫個草稿",
    "改短啲",
    "改 caption",
    "可以出",
    "發佈",
    "做一則 IG 文",
    "起草社交貼文",
    "revise the caption",
    "make it shorter",
    "publish",
    "confirm",
]

_NEED_SEARCH_UTTERANCES = [
    "幫我找 Threads 上的行銷案例",
    "最近 IG 上有什麼熱門話題",
    "幫我調研競品廣告文案",
    "政府買咗冒牌水，點抽水好",
    "想知道 2026 年最新的行銷趨勢",
    "分析一下戶外品牌的行銷策略",
    "香港最近熱話",
    "香港熱搜",
    "而家有咩新聞",
    "市場數據點樣",
    "最新趨勢",
    "熱門話題有咩",
    "查下競品",
    "調研一下",
    "有冇熱話可以做帖",
    "HK marketing trends",
    "latest news Hong Kong",
    "最近新聞",
    "而家市場點",
    "熱話有咩",
    "搜下熱搜",
]

_lock = threading.Lock()
_router: Any | None = None
_router_failed = False


def reset_semantic_router_for_tests() -> None:
    """Clear singleton (unit tests)."""
    global _router, _router_failed
    with _lock:
        _router = None
        _router_failed = False


def _build_router() -> Any:
    from semantic_router import Route
    from semantic_router.encoders import FastEmbedEncoder
    from semantic_router.routers import SemanticRouter

    model = (settings.semantic_router_model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    threshold = float(settings.semantic_router_score_threshold)
    encoder = FastEmbedEncoder(name=model, score_threshold=threshold)
    routes = [
        Route(name="chitchat", utterances=list(_CHITCHAT_UTTERANCES)),
        Route(name="act_no_search", utterances=list(_ACT_NO_SEARCH_UTTERANCES)),
        Route(name="need_search", utterances=list(_NEED_SEARCH_UTTERANCES)),
    ]
    return SemanticRouter(encoder=encoder, routes=routes, auto_sync="local")


def get_semantic_router() -> Any | None:
    """Lazy process-level SemanticRouter; None if disabled or init failed."""
    global _router, _router_failed
    if not settings.semantic_router_enabled:
        return None
    if _router_failed:
        return None
    if _router is not None:
        return _router
    with _lock:
        if _router is not None or _router_failed:
            return _router
        try:
            _router = _build_router()
            logger.info(
                "Semantic router ready model=%s threshold=%s",
                settings.semantic_router_model or DEFAULT_MODEL,
                settings.semantic_router_score_threshold,
            )
        except Exception:
            _router_failed = True
            logger.exception(
                "Semantic router init failed — falling back to regex research gate"
            )
            return None
        return _router


def classify_semantic_route(text: str) -> SemanticRouteName | None:
    """Return matched route name, or None if unclear / disabled / error."""
    raw = (text or "").strip()
    if not raw:
        return None
    router = get_semantic_router()
    if router is None:
        return None
    try:
        choice = router(raw)
    except Exception:
        logger.exception("Semantic router classify failed")
        return None
    name = getattr(choice, "name", None) if choice is not None else None
    if name in ("chitchat", "act_no_search", "need_search"):
        return name  # type: ignore[return-value]
    return None
