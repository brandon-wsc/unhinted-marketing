"""Product embedder unit tests — FastEmbed construction mocked (no download)."""

from __future__ import annotations

from internal.config import settings
from internal.memory import embeddings


def test_product_embedder_init_holds_fastembed_init_lock(monkeypatch) -> None:
    """Regression: concurrent snapshot_download callers race inside tqdm
    thread_map's ensure_lock (``del tqdm_class._lock`` AttributeError), so
    every FastEmbed build must hold the shared ``fastembed_init_lock``."""
    embeddings.reset_product_embedder_for_tests()
    monkeypatch.setattr(settings, "product_embeddings_enabled", True)
    import fastembed

    class FakeEmbedding:
        def __init__(self, model_name: str) -> None:
            # Must already be held by _init_model_safe — an uncontended
            # acquire here would mean the lock was not taken.
            assert not embeddings.fastembed_init_lock.acquire(blocking=False)

    monkeypatch.setattr(fastembed, "TextEmbedding", FakeEmbedding)
    embeddings.start_product_embedder_warmup()
    assert embeddings._load_done.wait(timeout=5)
    assert embeddings._model is not None
    assert not embeddings._model_failed
    embeddings.reset_product_embedder_for_tests()
