"""Schema tests for session file attachments (ADR 0047 §1 + §13).

The `attachments`, `document_chunks` and `attachment_sessions` tables — and the
Attachment / DocumentChunk / AttachmentSession models — do not exist yet. These
tests pin the contract and stay red until the schema step lands.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.embeddings import EMBEDDING_DIM
from internal.memory.models import Session
from tests.api.helpers import register_user

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


async def _columns(db: AsyncSession, table: str) -> dict[str, dict]:
    rows = (
        (
            await db.execute(
                text(
                    "SELECT column_name, data_type, udt_name, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :table"
                ),
                {"table": table},
            )
        )
        .mappings()
        .all()
    )
    return {r["column_name"]: dict(r) for r in rows}


async def _primary_key_columns(db: AsyncSession, table: str) -> set[str]:
    rows = (
        (
            await db.execute(
                text(
                    "SELECT kcu.column_name "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "  ON tc.constraint_name = kcu.constraint_name "
                    " AND tc.table_schema = kcu.table_schema "
                    "WHERE tc.table_schema = 'public' AND tc.table_name = :table "
                    "  AND tc.constraint_type = 'PRIMARY KEY'"
                ),
                {"table": table},
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def _foreign_keys(db: AsyncSession, table: str) -> dict[str, tuple[str, str, str]]:
    """column_name -> (referenced table, referenced column, delete rule)."""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT kcu.column_name, ccu.table_name AS ref_table, "
                    "ccu.column_name AS ref_column, rc.delete_rule "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "  ON tc.constraint_name = kcu.constraint_name "
                    " AND tc.table_schema = kcu.table_schema "
                    "JOIN information_schema.constraint_column_usage ccu "
                    "  ON tc.constraint_name = ccu.constraint_name "
                    " AND tc.table_schema = ccu.table_schema "
                    "JOIN information_schema.referential_constraints rc "
                    "  ON tc.constraint_name = rc.constraint_name "
                    " AND tc.table_schema = rc.constraint_schema "
                    "WHERE tc.table_schema = 'public' AND tc.table_name = :table "
                    "  AND tc.constraint_type = 'FOREIGN KEY'"
                ),
                {"table": table},
            )
        )
        .mappings()
        .all()
    )
    return {r["column_name"]: (r["ref_table"], r["ref_column"], r["delete_rule"]) for r in rows}


@pytest.mark.asyncio
async def test_attachments_table_shape(db_session: AsyncSession) -> None:
    cols = await _columns(db_session, "attachments")
    assert {
        "id",
        "company_id",
        "owner_scope",
        "user_id",
        "session_id",
        "filename",
        "content_type",
        "object_key",
        "status",
        "doc_profile",
        "error",
        "created_at",
        "updated_at",
    } <= set(cols)
    assert cols["id"]["udt_name"] == "uuid"
    assert cols["doc_profile"]["udt_name"] == "jsonb"
    for name in ("user_id", "session_id", "error"):
        assert cols[name]["is_nullable"] == "YES"
    for name in ("id", "company_id", "owner_scope", "filename", "content_type", "object_key"):
        assert cols[name]["is_nullable"] == "NO"
    assert await _primary_key_columns(db_session, "attachments") == {"id"}


@pytest.mark.asyncio
async def test_attachments_foreign_keys(db_session: AsyncSession) -> None:
    fks = await _foreign_keys(db_session, "attachments")
    assert fks["company_id"][:2] == ("entities", "id")
    assert fks["user_id"][:2] == ("users", "id")
    assert fks["session_id"][:2] == ("sessions", "id")


@pytest.mark.asyncio
async def test_document_chunks_table_shape(db_session: AsyncSession) -> None:
    cols = await _columns(db_session, "document_chunks")
    assert {
        "id",
        "attachment_id",
        "chunk_index",
        "text",
        "heading_path",
        "page_start",
        "page_end",
        "embedding",
        "embedding_model",
    } <= set(cols)
    assert cols["id"]["udt_name"] == "uuid"
    assert cols["chunk_index"]["data_type"] == "integer"
    assert cols["embedding"]["udt_name"] == "vector"
    for name in ("page_start", "page_end", "embedding", "embedding_model"):
        assert cols[name]["is_nullable"] == "YES"
    assert await _primary_key_columns(db_session, "document_chunks") == {"id"}

    # ADR 0047 §9: dimensionless vector — typmod stays -1, second space possible later.
    typmod = await db_session.scalar(
        text(
            "SELECT a.atttypmod FROM pg_attribute a "
            "JOIN pg_class c ON a.attrelid = c.oid "
            "JOIN pg_namespace n ON c.relnamespace = n.oid "
            "WHERE n.nspname = 'public' AND c.relname = 'document_chunks' "
            "AND a.attname = 'embedding'"
        )
    )
    assert typmod == -1


@pytest.mark.asyncio
async def test_document_chunks_attachment_fk_cascades(db_session: AsyncSession) -> None:
    fks = await _foreign_keys(db_session, "document_chunks")
    assert fks["attachment_id"] == ("attachments", "id", "CASCADE")


@pytest.mark.asyncio
async def test_attachment_sessions_table(db_session: AsyncSession) -> None:
    cols = await _columns(db_session, "attachment_sessions")
    assert {"attachment_id", "session_id"} <= set(cols)
    assert cols["attachment_id"]["is_nullable"] == "NO"
    assert cols["session_id"]["is_nullable"] == "NO"
    fks = await _foreign_keys(db_session, "attachment_sessions")
    assert fks["attachment_id"][:2] == ("attachments", "id")
    assert fks["session_id"][:2] == ("sessions", "id")


@pytest.mark.asyncio
async def test_attachment_chunks_roundtrip_and_cascade(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from sqlalchemy import select

    from internal.memory.models import Attachment, AttachmentSession, DocumentChunk

    data = await register_user(client)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])

    session = Session(user_id=user_id, company_id=company_id, mode="CHAT", state={})
    db_session.add(session)
    await db_session.flush()

    attachment = Attachment(
        company_id=company_id,
        owner_scope="session",
        user_id=user_id,
        session_id=session.id,
        filename="catalog2026.pdf",
        content_type="application/pdf",
        object_key="attachments/test-1/catalog2026.pdf",
        status="pending",
        doc_profile={"title": "catalog2026", "pages": 12, "outline": ["優惠詳情"]},
    )
    db_session.add(attachment)
    await db_session.flush()

    vector = [0.001 * (i + 1) for i in range(EMBEDDING_DIM)]
    db_session.add_all(
        [
            DocumentChunk(
                attachment_id=attachment.id,
                chunk_index=0,
                text="優惠詳情：全單九折",
                heading_path="產品目錄 > 優惠詳情",
                page_start=3,
                page_end=3,
                embedding=vector,
                embedding_model=EMBEDDING_MODEL,
            ),
            DocumentChunk(
                attachment_id=attachment.id,
                chunk_index=1,
                text="條款及細則",
                heading_path="產品目錄 > 條款",
            ),
        ]
    )
    db_session.add(AttachmentSession(attachment_id=attachment.id, session_id=session.id))
    await db_session.commit()

    fetched = await db_session.get(Attachment, attachment.id)
    assert fetched.company_id == company_id
    assert fetched.owner_scope == "session"
    assert fetched.user_id == user_id
    assert fetched.session_id == session.id
    assert fetched.filename == "catalog2026.pdf"
    assert fetched.content_type == "application/pdf"
    assert fetched.object_key == "attachments/test-1/catalog2026.pdf"
    assert fetched.status == "pending"
    assert fetched.doc_profile["title"] == "catalog2026"
    assert fetched.error is None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None

    chunks = (
        (
            await db_session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.attachment_id == attachment.id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    assert len(chunks) == 2
    assert chunks[0].text == "優惠詳情：全單九折"
    assert chunks[0].heading_path == "產品目錄 > 優惠詳情"
    assert chunks[0].page_start == 3
    assert chunks[0].page_end == 3
    assert chunks[0].embedding_model == EMBEDDING_MODEL
    assert [float(v) for v in chunks[0].embedding] == pytest.approx(vector)
    assert chunks[1].embedding is None
    assert chunks[1].embedding_model is None
    assert chunks[1].page_start is None
    assert chunks[1].page_end is None

    links = (
        (
            await db_session.execute(
                select(AttachmentSession).where(AttachmentSession.attachment_id == attachment.id)
            )
        )
        .scalars()
        .all()
    )
    assert {link.session_id for link in links} == {session.id}

    await db_session.delete(attachment)
    await db_session.commit()

    remaining = (
        (
            await db_session.execute(
                select(DocumentChunk).where(DocumentChunk.attachment_id == attachment.id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["session", "user", "org"])
async def test_attachment_owner_scope_accepts_value(
    scope: str, client: AsyncClient, db_session: AsyncSession
) -> None:
    from internal.memory.models import Attachment

    data = await register_user(client)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])

    session_id = None
    if scope == "session":
        scratch = Session(user_id=user_id, company_id=company_id, mode="CHAT", state={})
        db_session.add(scratch)
        await db_session.flush()
        session_id = scratch.id

    attachment = Attachment(
        company_id=company_id,
        owner_scope=scope,
        user_id=user_id,
        session_id=session_id,
        filename=f"{scope}-doc.pdf",
        content_type="application/pdf",
        object_key=f"attachments/test-scope/{scope}.pdf",
        status="pending",
        doc_profile={},
    )
    db_session.add(attachment)
    await db_session.commit()

    fetched = await db_session.get(Attachment, attachment.id)
    assert fetched.owner_scope == scope


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["pending", "ready_lexical", "ready", "failed", "needs_ocr"]
)
async def test_attachment_status_accepts_value(
    status: str, client: AsyncClient, db_session: AsyncSession
) -> None:
    from internal.memory.models import Attachment

    data = await register_user(client)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])

    attachment = Attachment(
        company_id=company_id,
        owner_scope="user",
        user_id=user_id,
        filename=f"{status}-doc.pdf",
        content_type="application/pdf",
        object_key=f"attachments/test-status/{status}.pdf",
        status=status,
        doc_profile={},
        error="parse failed" if status == "failed" else None,
    )
    db_session.add(attachment)
    await db_session.commit()

    fetched = await db_session.get(Attachment, attachment.id)
    assert fetched.status == status
