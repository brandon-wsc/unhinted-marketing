"""Semantic gate unit tests — no live FastEmbed download."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from internal.memory.embeddings import fastembed_init_lock
from internal.session import semantic_gate as sg


def test_classify_semantic_route_empty() -> None:
    sg.reset_semantic_router_for_tests()
    assert sg.classify_semantic_route("") is None


def test_classify_semantic_route_disabled(monkeypatch) -> None:
    sg.reset_semantic_router_for_tests()
    monkeypatch.setattr(sg.settings, "semantic_router_enabled", False)
    assert sg.classify_semantic_route("香港熱話") is None


def test_classify_semantic_route_uses_router(monkeypatch) -> None:
    sg.reset_semantic_router_for_tests()

    class FakeRouter:
        def __call__(self, text: str):
            return SimpleNamespace(name="need_search", similarity_score=0.9)

    monkeypatch.setattr(sg, "get_semantic_router", lambda: FakeRouter())
    assert sg.classify_semantic_route("熱話") == "need_search"


def test_classify_semantic_route_unknown_name(monkeypatch) -> None:
    sg.reset_semantic_router_for_tests()

    class FakeRouter:
        def __call__(self, text: str):
            return SimpleNamespace(name=None, similarity_score=0.1)

    monkeypatch.setattr(sg, "get_semantic_router", lambda: FakeRouter())
    assert sg.classify_semantic_route("???") is None


def test_classify_does_not_block_on_cold_init(monkeypatch) -> None:
    sg.reset_semantic_router_for_tests()
    monkeypatch.setattr(sg.settings, "semantic_router_enabled", True)
    released = threading.Event()

    def blocked_build():
        released.wait(timeout=5)

        class Ready:
            def __call__(self, text: str):
                return SimpleNamespace(name="need_search")

        return Ready()

    monkeypatch.setattr(sg, "_build_router", blocked_build)
    t0 = time.monotonic()
    assert sg.classify_semantic_route("香港熱話") is None
    assert time.monotonic() - t0 < 0.5
    released.set()
    for _ in range(50):
        if sg.classify_semantic_route("香港熱話") == "need_search":
            return
        time.sleep(0.02)
    raise AssertionError("semantic router never became ready after warmup")


def test_router_init_holds_fastembed_init_lock(monkeypatch) -> None:
    """Regression: concurrent snapshot_download callers race inside tqdm
    thread_map's ensure_lock (``del tqdm_class._lock`` AttributeError), so
    the FastEmbedEncoder build must hold the shared ``fastembed_init_lock``."""
    sg.reset_semantic_router_for_tests()
    monkeypatch.setattr(sg.settings, "semantic_router_enabled", True)

    def build():
        # Must already be held by _init_router_safe — an uncontended acquire
        # here would mean the lock was not taken.
        assert not fastembed_init_lock.acquire(blocking=False)
        return SimpleNamespace(name="router")

    monkeypatch.setattr(sg, "_build_router", build)
    sg.start_semantic_router_warmup()
    for _ in range(50):
        if sg._router is not None or sg._router_failed:
            break
        time.sleep(0.02)
    assert sg._router is not None
    assert not sg._router_failed
    sg.reset_semantic_router_for_tests()
