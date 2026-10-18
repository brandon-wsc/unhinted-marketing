"""Chat-node attachment wiring (ADR 0047 §5/§6/§14) — no DB.

Pins the two ``_chat_stream`` changes the read_attachment step needs:

- the JSON payload gains ``"attachments": [{id, filename, title,
  kind_guess, status, partial}]`` hydrated from ``state["attachments"]``
  (digests only — a planted full-text sentinel must never reach the
  prompt), and
- ``deps=ChatDeps(company_id=…, user_id=…)`` pulls ``user_id`` from
  ``state["user_id"]`` so the tool can re-check owner scope (§14).

The chat node runs the REAL harness — ``has_llm_credentials`` is patched
where ``nodes`` imports it and a ``FunctionModel`` (with a
``stream_function`` for ``run_stream``) probes the prompt / issues real
``read_attachment`` tool calls through ``set_chat_model_override``.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from internal.session import harness as H
from internal.session import nodes as N
from internal.session.context import session_db
from internal.session.state import MODE_CHAT
from tests.api.attachment_helpers import (
    FULL_TEXT_SENTINEL,
    MAX_ATTACHMENT_READS,
    make_digest_probe_model,
    make_read_attachment_driver,
    patch_read_document_seam,
)

COMPANY_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
ATTACHMENT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")

ATTACHMENT_FILENAME = "offers.md"
ATTACHMENT_TITLE = "產品目錄"
OFFER_REPLY = (
    "見到你上傳咗 offers.md（產品目錄）。我可以幫你："
    "①用呢份嘢出 post ②存入我嘅庫 ③講吓重點。想點？"
)
FINAL_TEXT = "睇完份嘢，重點係優惠期到三月底。"


@pytest.fixture(autouse=True)
def _clear_chat_model_override() -> None:
    H.set_chat_model_override(None)
    yield
    H.set_chat_model_override(None)


@pytest.fixture(autouse=True)
def _llm_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chat gates on the symbol ``nodes`` imported — patch it there."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)


def _attachment_digest() -> dict:
    """State digest shape per ``service._attachment_digest``: id/filename/
    status + lifted doc_profile subset. ``full_text`` is a planted leak
    canary — a correct ``_chat_stream`` whitelists digest fields only."""
    return {
        "id": str(ATTACHMENT_ID),
        "filename": ATTACHMENT_FILENAME,
        "status": "ready_lexical",
        "owner_scope": "session",
        "title": ATTACHMENT_TITLE,
        "kind_guess": "document",
        "partial": True,
        "doc_profile": {"title": ATTACHMENT_TITLE, "pages": 2},
        "full_text": FULL_TEXT_SENTINEL,
    }


def _chat_state(**extra) -> dict:
    state = {
        "mode": MODE_CHAT,
        "messages": [{"role": "user", "content": "用呢份嘢"}],
        "company_id": str(COMPANY_ID),
        "user_id": str(USER_ID),
        "thread_id": str(uuid.uuid4()),
        "attachments": [_attachment_digest()],
        "draft": {},
        "source_signal_ids": [],
    }
    state.update(extra)
    return state


# --- digest payload (§5) --------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_payload_carries_attachment_digests() -> None:
    """The FunctionModel emits the crafted offering ONLY when the prompt
    carries the digest (attachments key + filename + title) and no
    full-text sentinel — red until ``_chat_stream`` wires it."""
    seen: dict = {}
    H.set_chat_model_override(
        make_digest_probe_model(
            filename=ATTACHMENT_FILENAME,
            title=ATTACHMENT_TITLE,
            reply=OFFER_REPLY,
            seen=seen,
        )
    )
    out = await N.chat(_chat_state())
    reply = out["messages"][-1]["content"]
    assert seen.get("saw_full_text") is not True, (
        "prompt leaked a non-digest field (full text) — §5 violation"
    )
    assert reply == OFFER_REPLY, (
        f"digest never reached the chat prompt: {reply!r} "
        f"(model saw {seen})"
    )


# --- deps / scope wiring (§14) ---------------------------------------------------


@pytest.mark.asyncio
async def test_read_attachment_tool_gets_company_and_user_from_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FunctionModel-issued ``read_attachment`` call must reach the seam
    with ``company_id`` + ``user_id`` hydrated from session state."""
    seam_calls: list[dict] = []

    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        seam_calls.append(
            {
                "company_id": company_id,
                "user_id": user_id,
                "attachment_id": attachment_id,
                "query": query,
                "section": section,
            }
        )
        return {
            "slices": [
                {"chunk_id": str(uuid.uuid4()), "ref": "p.1", "text": "優惠期由即日起。"}
            ],
            "partial": False,
        }

    patch_read_document_seam(monkeypatch, stub)
    returns_seen: list[str] = []
    H.set_chat_model_override(
        make_read_attachment_driver(
            calls=[{"attachment_id": str(ATTACHMENT_ID), "query": "優惠期"}],
            returns_seen=returns_seen,
            final_text=FINAL_TEXT,
        )
    )
    with session_db(AsyncMock()):
        out = await N.chat(_chat_state())

    assert seam_calls, (
        "read_document seam never called — tool/deps wiring missing "
        f"(reply was {out['messages'][-1]['content']!r})"
    )
    assert str(seam_calls[0]["company_id"]) == str(COMPANY_ID)
    assert str(seam_calls[0]["user_id"]) == str(USER_ID)
    assert str(seam_calls[0]["attachment_id"]) == str(ATTACHMENT_ID)
    assert out["messages"][-1]["content"] == FINAL_TEXT


@pytest.mark.asyncio
async def test_read_attachment_untrusted_id_returns_error_not_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§14: the LLM emits an id not attached to this session — the seam
    refuses (``None``) and the tool return carries an error, never raises."""

    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        return None

    patch_read_document_seam(monkeypatch, stub)
    returns_seen: list[str] = []
    H.set_chat_model_override(
        make_read_attachment_driver(
            calls=[{"attachment_id": str(uuid.uuid4()), "query": "優惠期"}],
            returns_seen=returns_seen,
            final_text=FINAL_TEXT,
        )
    )
    with session_db(AsyncMock()):
        out = await N.chat(_chat_state())

    assert returns_seen, "tool call never returned — run died inside the agent"
    blob = returns_seen[0]
    assert (
        '"slices": []' in blob or "slices': []" in blob or "slices=[]" in blob
    ), f"refused read must carry empty slices: {blob!r}"
    assert '"error"' in blob or "'error'" in blob or "error=" in blob, (
        f"refused read must carry an error string: {blob!r}"
    )
    assert out["messages"][-1]["content"] == FINAL_TEXT


# --- per-turn budget end-to-end (§6) ---------------------------------------------


@pytest.mark.asyncio
async def test_read_attachment_budget_enforced_through_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One turn issuing MAX+1 ``read_attachment`` calls: the extra call's
    tool return carries the budget error — enforced inside the run."""
    seam_calls: list[dict] = []

    async def stub(db, *, company_id, user_id, attachment_id, query=None, section=None):
        seam_calls.append({"attachment_id": attachment_id})
        return {
            "slices": [
                {"chunk_id": str(uuid.uuid4()), "ref": "p.1", "text": "slice"}
            ],
            "partial": False,
        }

    patch_read_document_seam(monkeypatch, stub)
    returns_seen: list[str] = []
    H.set_chat_model_override(
        make_read_attachment_driver(
            calls=[
                {"attachment_id": str(ATTACHMENT_ID), "query": f"q{i}"}
                for i in range(MAX_ATTACHMENT_READS + 1)
            ],
            returns_seen=returns_seen,
            final_text=FINAL_TEXT,
        )
    )
    with session_db(AsyncMock()):
        out = await N.chat(_chat_state())

    assert len(returns_seen) == MAX_ATTACHMENT_READS + 1, (
        f"expected {MAX_ATTACHMENT_READS + 1} tool returns, "
        f"got {len(returns_seen)} (reply: {out['messages'][-1]['content']!r})"
    )
    budget_return = returns_seen[MAX_ATTACHMENT_READS]
    assert "budget" in budget_return.lower(), (
        f"call #{MAX_ATTACHMENT_READS + 1} must carry the budget error: "
        f"{budget_return!r}"
    )
    # Within-budget calls reach the seam; the over-budget call must not.
    assert len(seam_calls) == MAX_ATTACHMENT_READS
