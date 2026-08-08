"""Semantic gate unit tests — no live FastEmbed download."""

from __future__ import annotations

from types import SimpleNamespace

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
