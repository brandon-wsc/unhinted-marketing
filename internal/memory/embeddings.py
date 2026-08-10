"""Local text embeddings via FastEmbed (COLLECT K4 / semantic-gate model family)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from internal.config import settings

logger = logging.getLogger(__name__)

# paraphrase-multilingual-MiniLM-L12-v2 output size — keep migration in sync.
EMBEDDING_DIM = 384

_lock = threading.Lock()
_model: Any | None = None
_model_failed = False


def reset_product_embedder_for_tests() -> None:
    """Clear singleton (unit tests)."""
    global _model, _model_failed
    with _lock:
        _model = None
        _model_failed = False


def _model_name() -> str:
    return (settings.product_embedding_model or "").strip() or (
        settings.semantic_router_model
        or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )


def _get_model() -> Any | None:
    global _model, _model_failed
    if not settings.product_embeddings_enabled:
        return None
    if _model_failed:
        return None
    if _model is not None:
        return _model
    with _lock:
        if _model is not None or _model_failed:
            return _model
        try:
            from fastembed import TextEmbedding

            name = _model_name()
            _model = TextEmbedding(model_name=name)
            logger.info("Product embedder ready model=%s dim=%s", name, EMBEDDING_DIM)
        except Exception:
            _model_failed = True
            logger.exception("Product embedder init failed — vector tier disabled")
            return None
        return _model


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """Embed documents; returns one vector (or None) per input. Never raises."""
    if not texts:
        return []
    cleaned = [(t or "").strip() for t in texts]
    if not any(cleaned):
        return [None] * len(texts)
    model = _get_model()
    if model is None:
        return [None] * len(texts)
    try:
        # Preserve alignment: embed only non-empty; fill None for empty.
        indexed = [(i, t) for i, t in enumerate(cleaned) if t]
        if not indexed:
            return [None] * len(texts)
        vectors = list(model.embed([t for _, t in indexed]))
        out: list[list[float] | None] = [None] * len(texts)
        for (i, _), raw in zip(indexed, vectors, strict=True):
            vec = [float(x) for x in raw]
            if len(vec) != EMBEDDING_DIM:
                logger.warning(
                    "Unexpected embedding dim=%s expected=%s — dropping",
                    len(vec),
                    EMBEDDING_DIM,
                )
                continue
            out[i] = vec
        return out
    except Exception:
        logger.exception("Product embed_texts failed")
        return [None] * len(texts)


def embed_query(text: str) -> list[float] | None:
    """Single query embedding for retrieve."""
    vecs = embed_texts([text])
    return vecs[0] if vecs else None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))
