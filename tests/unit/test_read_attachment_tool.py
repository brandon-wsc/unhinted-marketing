"""read_attachment chat tool (ADR 0047 §6/§14) — pinned contract, no DB.

The tool is a read-only Pydantic AI function tool: ``≤5`` slices
``{chunk_id, ref, text}`` + ``partial``, ``≤3`` calls per turn, owner scope
re-checked on every call — the ids the LLM emits are untrusted (§14). Every
refusal returns ``slices=[]`` + a non-empty ``error``; the tool never
raises and never returns full document text (§5).

Invented names this step must satisfy (documented in
tests/api/attachment_helpers.py as well):

- ``internal.session.harness.read_attachment`` —
  ``async (ctx: RunContext[ChatDeps], attachment_id: str,
  query: str | None = None, section: str | None = None)
  -> ReadAttachmentResponse``; registered on the chat agent.
- ``schemas.tools.ReadAttachmentSlice {chunk_id, ref, text}`` and
  ``schemas.tools.ReadAttachmentResponse {slices, partial, error}``.
- ``ChatDeps`` gains ``user_id: uuid.UUID | None`` and per-turn counter
  ``attachment_reads: int``; ``harness.MAX_ATTACHMENT_READS_PER_TURN = 3``
  (chosen cap inside the ADR's 2–3 range; the test matches the
  ``"budget"`` keyword, not the exact string).
- ``harness.read_document`` — module-level seam the tool calls through;
  tests patch it via ``patch_read_document_seam``.
- ``CHAT_TOOL_NAMES`` gains ``"read_attachment"``; disjoint from
  ``PUBLISH_TOOL_NAMES``.

Chosen behavior where the ADR leaves room: a call with neither ``query``
nor ``section`` is refused **before** the seam runs (the service would
refuse anyway — the tool saves the hop); invalid ``attachment_id`` strings
may hit the seam or be refused locally — either way the shape is a
refusal, never an exception.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.test import TestModel

from internal.session import harness as H
from internal.session.context import session_db
from tests.api.attachment_helpers import (
    MAX_ATTACHMENT_READS,
    READ_ATTACHMENT_TOOL,
    patch_read_document_seam,
)

COMPANY_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
ATTACHMENT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")

SLICES = [
    {
        "chunk_id": str(uuid.uuid4()),
        "ref": "p.1 · 優惠詳情",
        "text": "優惠期由即日起至三月三十一日。",
    },
    {"chunk_id": str(uuid.uuid4()), "ref": "p.2", "text": "會員購買指定飲品可享九折優惠。"},
]


@pytest.fixture(autouse=True)
def _clear_chat_model_override() -> None:
    H.set_chat_model_override(None)
    yield
    H.set_chat_model_override(None)


def _tool():
    """Get the tool fn — AttributeError names the missing seam (right red)."""
    return getattr(H, READ_ATTACHMENT_TOOL)


def _ctx(deps: H.ChatDeps) -> SimpleNamespace:
    """Fake RunContext — only ``ctx.deps`` may be touched by the tool."""
    return SimpleNamespace(deps=deps)


def _deps() -> H.ChatDeps:
    return H.ChatDeps(company_id=COMPANY_ID, user_id=USER_ID)


async def _call_tool(deps: H.ChatDeps, **kwargs):
    return await _tool()(_ctx(deps), **kwargs)


def _result_dump(result) -> dict:
    """Result may be a pydantic model or plain dict — both dump to a dict."""
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return dict(result)


# --- allowlist / registration -------------------------------------------------


def test_read_attachment_in_chat_tool_names() -> None:
    assert READ_ATTACHMENT_TOOL in H.CHAT_TOOL_NAMES
    assert READ_ATTACHMENT_TOOL not in H.PUBLISH_TOOL_NAMES
    assert H.CHAT_TOOL_NAMES.isdisjoint(H.PUBLISH_TOOL_NAMES)


def test_read_attachment_registered_on_chat_agent() -> None:
    agent = H.build_chat_agent(model=TestModel(call_tools=[], custom_output_text="x"))
    names = H.registered_function_tool_names(agent)
    assert READ_ATTACHMENT_TOOL in names
    assert names.isdisjoint(H.PUBLISH_TOOL_NAMES)


# --- happy path / seam pass-through --------------------------------------------


@pytest.mark.asyncio
async def test_read_attachment_passes_slices_and_scope_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        calls.append(
            {
                "db": db,
                "company_id": company_id,
                "user_id": user_id,
                "attachment_id": attachment_id,
                "query": query,
                "section": section,
            }
        )
        return {"slices": SLICES, "partial": True}

    patch_read_document_seam(monkeypatch, stub)
    db = AsyncMock()
    with session_db(db):
        result = await _call_tool(_deps(), attachment_id=str(ATTACHMENT_ID), query="優惠期")

    assert len(calls) == 1, "tool must hit the read_document seam once"
    call = calls[0]
    assert call["db"] is db
    assert call["company_id"] == COMPANY_ID
    assert call["user_id"] == USER_ID
    assert str(call["attachment_id"]) == str(ATTACHMENT_ID)
    assert call["query"] == "優惠期"

    dump = _result_dump(result)
    assert dump["partial"] is True
    assert len(dump["slices"]) == len(SLICES)
    for got, want in zip(dump["slices"], SLICES, strict=True):
        got = _result_dump(got)
        assert got["chunk_id"] == want["chunk_id"]
        assert got["ref"] == want["ref"]
        assert got["text"] == want["text"]


@pytest.mark.asyncio
async def test_read_attachment_section_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        calls.append({"query": query, "section": section})
        return {"slices": SLICES[:1], "partial": False}

    patch_read_document_seam(monkeypatch, stub)
    with session_db(AsyncMock()):
        result = await _call_tool(_deps(), attachment_id=str(ATTACHMENT_ID), section="優惠詳情")
    assert calls == [{"query": None, "section": "優惠詳情"}]
    assert _result_dump(result)["slices"]


# --- refusals (never raise) -----------------------------------------------------


@pytest.mark.asyncio
async def test_read_attachment_refuses_when_seam_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown / out-of-scope ids are indistinguishable (§14): the seam
    returns ``None`` and the tool surfaces an error, not an exception."""

    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        return None

    patch_read_document_seam(monkeypatch, stub)
    with session_db(AsyncMock()):
        result = await _call_tool(_deps(), attachment_id=str(uuid.uuid4()), query="優惠期")
    dump = _result_dump(result)
    assert dump["slices"] == []
    assert dump["error"]


@pytest.mark.asyncio
async def test_read_attachment_refuses_without_query_or_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chosen pin: ``query?|section?`` — a bare id is refused before the
    seam (the service refuses too; the tool saves the hop)."""
    calls: list[dict] = []

    async def stub(db, **kwargs):
        calls.append(kwargs)
        return {"slices": SLICES, "partial": False}

    patch_read_document_seam(monkeypatch, stub)
    with session_db(AsyncMock()):
        result = await _call_tool(_deps(), attachment_id=str(ATTACHMENT_ID))
    dump = _result_dump(result)
    assert dump["slices"] == []
    assert dump["error"]
    assert calls == [], "param-less call must not reach the seam"


@pytest.mark.asyncio
async def test_read_attachment_refuses_invalid_attachment_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        return None

    patch_read_document_seam(monkeypatch, stub)
    with session_db(AsyncMock()):
        result = await _call_tool(_deps(), attachment_id="not-a-uuid", query="優惠期")
    dump = _result_dump(result)
    assert dump["slices"] == []
    assert dump["error"]


@pytest.mark.asyncio
async def test_read_attachment_refuses_without_db_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``session_db`` contextvar → refusal, never a RuntimeError leak."""
    calls: list[dict] = []

    async def stub(db, **kwargs):
        calls.append(kwargs)
        return {"slices": SLICES, "partial": False}

    patch_read_document_seam(monkeypatch, stub)
    result = await _call_tool(_deps(), attachment_id=str(ATTACHMENT_ID), query="優惠期")
    dump = _result_dump(result)
    assert dump["slices"] == []
    assert dump["error"]
    assert calls == []


# --- per-turn budget (§6: ≤2–3 calls/turn) --------------------------------------


@pytest.mark.asyncio
async def test_read_attachment_fourth_call_hits_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        return {"slices": SLICES, "partial": False}

    patch_read_document_seam(monkeypatch, stub)
    deps = _deps()
    with session_db(AsyncMock()):
        results = [
            await _call_tool(deps, attachment_id=str(ATTACHMENT_ID), query="優惠期")
            for _ in range(MAX_ATTACHMENT_READS + 1)
        ]
    dumps = [_result_dump(r) for r in results]
    for i, dump in enumerate(dumps[:MAX_ATTACHMENT_READS]):
        assert not dump["error"], f"call {i + 1} must be within budget: {dump}"
    over = dumps[MAX_ATTACHMENT_READS]
    assert over["slices"] == []
    assert over["error"] and "budget" in str(over["error"]).lower()


@pytest.mark.asyncio
async def test_read_attachment_budget_is_per_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counter lives on ``ChatDeps`` (per-turn) — a fresh deps instance
    gets a fresh budget."""

    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        return {"slices": SLICES, "partial": False}

    patch_read_document_seam(monkeypatch, stub)
    with session_db(AsyncMock()):
        first = _deps()
        for _ in range(MAX_ATTACHMENT_READS):
            await _call_tool(first, attachment_id=str(ATTACHMENT_ID), query="q")
        fresh = _deps()
        result = await _call_tool(fresh, attachment_id=str(ATTACHMENT_ID), query="q")
    assert not _result_dump(result)["error"]


# --- full-text invariant (§5) ----------------------------------------------------


@pytest.mark.asyncio
async def test_read_attachment_result_shape_never_leaks_full_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The result model carries ONLY slices/partial/error — no doc_profile,
    no full-content field, and slice keys stay {chunk_id, ref, text} even
    when the seam hands back extra keys."""
    fat_slices = [
        {
            "chunk_id": str(uuid.uuid4()),
            "ref": "p.1",
            "text": "slice text",
            "full_text": "x" * 20_000,
            "doc_profile": {"title": "should not leak"},
        }
    ]

    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        return {"slices": fat_slices, "partial": False}

    patch_read_document_seam(monkeypatch, stub)
    with session_db(AsyncMock()):
        result = await _call_tool(_deps(), attachment_id=str(ATTACHMENT_ID), query="優惠期")
    dump = _result_dump(result)
    assert set(dump) == {"slices", "partial", "error"}, (
        f"result exposes unexpected fields: {sorted(dump)}"
    )
    for s in dump["slices"]:
        assert set(_result_dump(s)) <= {"chunk_id", "ref", "text"}
