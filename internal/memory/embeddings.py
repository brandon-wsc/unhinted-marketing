"""Local text embeddings via FastEmbed (COLLECT K4 / semantic-gate model family)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from internal.config import settings

logger = logging.getLogger(__name__)

# paraphrase-multilingual-MiniLM-L12-v2 output size — keep migration in sync.
EMBEDDING_DIM = 384

# FastEmbed downloads weights via huggingface_hub.snapshot_download → tqdm
# thread_map, whose ensure_lock is not safe for concurrent callers: two
# in-flight downloads can both observe ``_lock`` unset and the second context
# exit crashes on ``del tqdm_class._lock`` (AttributeError). Serialize every
# FastEmbed model build process-wide — internal/session/semantic_gate.py's
# FastEmbedEncoder construction holds this too.
fastembed_init_lock = threading.Lock()

_lock = threading.Lock()
_model: Any | None = None
_model_failed = False
_load_started = False
# Set once a warmup attempt finishes (success OR failure) so interactive
# readers can wait out a cold load instead of silently losing vector search.
_load_done = threading.Event()


def reset_product_embedder_for_tests() -> None:
    """Clear singleton (unit tests)."""
    global _model, _model_failed, _load_started
    with _lock:
        _model = None
        _model_failed = False
        _load_started = False
    _load_done.clear()


def embedding_model_name() -> str:
    """Public accessor for the active model id (stamped on document chunks, ADR 0047)."""
    return _model_name()


def _model_name() -> str:
    return (settings.product_embedding_model or "").strip() or (
        settings.semantic_router_model
        or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )


def _init_model_safe() -> None:
    global _model, _model_failed
    try:
        try:
            from fastembed import TextEmbedding

            name = _model_name()
            with fastembed_init_lock:
                loaded = TextEmbedding(model_name=name)
        except Exception:
            with _lock:
                _model_failed = True
            logger.exception("Product embedder init failed — vector tier disabled")
            return
        with _lock:
            _model = loaded
        logger.info("Product embedder ready model=%s dim=%s", _model_name(), EMBEDDING_DIM)
    finally:
        _load_done.set()


def start_product_embedder_warmup() -> None:
    """Load FastEmbed in a daemon thread. Never blocks the caller."""
    global _load_started
    if not settings.product_embeddings_enabled:
        return
    with _lock:
        if _model is not None or _model_failed or _load_started:
            return
        _load_started = True
    threading.Thread(
        target=_init_model_safe,
        name="product-embedder-init",
        daemon=True,
    ).start()


def _get_model() -> Any | None:
    if not settings.product_embeddings_enabled:
        return None
    if _model is not None:
        return _model
    if _model_failed:
        return None
    start_product_embedder_warmup()
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
    """Single query embedding for retrieve.

    Unlike ``embed_texts`` — worker-side, where a cold model parks vectors as
    NULL for the reschedule loop — a query embed backs interactive reads
    (``read_attachment``). Returning None mid-warmup yields empty slices and
    the LLM reports the document unreadable, so this waits out an in-flight
    load with a bound instead of giving up instantly.
    """
    _get_model()
    if _load_started and _model is None and not _model_failed:
        _load_done.wait(timeout=30)
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
