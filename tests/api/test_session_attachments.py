"""API-tier tests for the ADR 0047 upload endpoints (§3 chat import shape,
§12 spreadsheet steering, §14 scratch cap).

Pinned contract — invented names this step must satisfy:

- ``POST /api/sessions/{session_id}/attachments`` — multipart upload
  (``files={"file": (name, bytes, content_type)}``); returns 201 or 200 with
  an ``AttachmentOut`` body
  ``{id, session_id, filename, content_type, status, owner_scope, created_at}``
  where ``status == "pending"`` and ``owner_scope == "session"``.
  Side effects: ``attachments`` row (owner_scope=session, session_id set),
  ``attachment_sessions`` join row, object bytes under
  ``attachments/{attachment_id}/{filename}`` retrievable via
  ``internal.media.storage.get_bytes``, and a pending ``attachment_ingest``
  job whose payload is ``{"attachment_id": "<uuid>"}``.
- Refusals on that route:
  - ``.csv`` / ``.xlsx`` → 400 whose ``detail`` steers to the product import
    path ``POST /api/companies/{company_id}/products/import`` (mentions
    ``products/import``) — ADR 0047 §12.
  - unsupported extensions (``.exe``, ``.png``) → 400.
  - body over 20 MB → 400 or 413 (either accepted).
  - 11th session-scoped upload (scratch cap ~10, ADR 0047 §14) → **400**
    (chosen code — keeps every refusal on this endpoint in the 400 family).
  - unknown session id → 404; session owned by another user → 403
    (``_require_owned_session`` semantics); no bearer token → 401.
- ``GET /api/attachments/{attachment_id}/download`` — authenticated member
  of the attachment's company gets the original bytes (200); unauthenticated
  → 401; member of another company → 403 or 404.
- ``GET /api/media/{key}`` is restricted to the ``sessions/`` image prefix:
  ``attachments/`` keys → 404 (attachment bytes are never served by the
  unauthenticated media route), ``sessions/…`` keys still → 200.

None of these routes exist yet — every test fails on 404 / missing behavior,
never at collection time.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.media.storage import get_bytes, put_bytes
from internal.memory.models import Attachment, AttachmentSession
from tests.api.attachment_helpers import (
    ATTACHMENT_INGEST_KIND,
    fetch_jobs,
    make_pdf_with_outline,
    seed_pending_attachment,
)
from tests.api.helpers import auth_header, register_user

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0c"
    b"IDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
SCRATCH_CAP = 10


async def _member_and_session(
    client: AsyncClient,
) -> tuple[dict, dict[str, str], uuid.UUID]:
    """Register a user and create a session via the real routes."""
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    res = await client.post(
        "/api/sessions", json={"company_id": company_id}, headers=headers
    )
    assert res.status_code == 201, res.text
    return data, headers, uuid.UUID(res.json()["id"])


async def _post_attachment(
    client: AsyncClient,
    session_id: uuid.UUID,
    *,
    filename: str = "catalog2026.pdf",
    data: bytes | None = None,
    content_type: str = "application/pdf",
    headers: dict[str, str] | None = None,
):
    return await client.post(
        f"/api/sessions/{session_id}/attachments",
        files={"file": (filename, data or make_pdf_with_outline(), content_type)},
        headers=headers,
    )


# --- happy path ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_pdf_creates_pending_attachment_and_ingest_job(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    data, headers, session_id = await _member_and_session(client)
    pdf = make_pdf_with_outline()

    res = await _post_attachment(client, session_id, data=pdf, headers=headers)
    assert res.status_code in (200, 201), res.text

    body = res.json()
    assert body["filename"] == "catalog2026.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["status"] == "pending"
    attachment_id = uuid.UUID(body["id"])

    row = await db_session.get(Attachment, attachment_id)
    assert row is not None
    assert row.owner_scope == "session"
    assert row.session_id == session_id
    assert row.user_id == uuid.UUID(data["user"]["id"])
    assert row.company_id == uuid.UUID(data["user"]["organizations"][0]["id"])
    assert row.status == "pending"
    assert row.object_key.startswith("attachments/")

    join = await db_session.scalar(
        select(AttachmentSession).where(
            AttachmentSession.attachment_id == attachment_id,
            AttachmentSession.session_id == session_id,
        )
    )
    assert join is not None

    assert await get_bytes(row.object_key) == pdf

    jobs = await fetch_jobs(db_session, kind=ATTACHMENT_INGEST_KIND)
    assert len(jobs) == 1
    assert jobs[0].status == "pending"
    assert jobs[0].payload.get("attachment_id") == str(attachment_id)


# --- refusals -----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "data", "content_type"),
    [
        ("pricelist.csv", b"sku,name,price\nSKU-1,Milk Tea,48\n", "text/csv"),
        ("pricelist.xlsx", b"PK\x03\x04" + b"\x00" * 64, XLSX_CONTENT_TYPE),
    ],
    ids=["csv", "xlsx"],
)
async def test_upload_refuses_spreadsheets_with_product_import_pointer(
    client: AsyncClient, filename: str, data: bytes, content_type: str
) -> None:
    """ADR 0047 §12: CSV/XLSX stay product-path only — the endpoint refuses
    them with a pointer to ``POST /api/companies/{company_id}/products/import``."""
    _data, headers, session_id = await _member_and_session(client)

    res = await _post_attachment(
        client, session_id, filename=filename, data=data, content_type=content_type,
        headers=headers,
    )
    assert res.status_code == 400, res.text
    assert "products/import" in res.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "data", "content_type"),
    [
        ("evil.exe", b"MZ" + b"\x00" * 64, "application/octet-stream"),
        ("photo.png", PNG, "image/png"),
    ],
    ids=["exe", "png"],
)
async def test_upload_rejects_unsupported_file_types(
    client: AsyncClient, filename: str, data: bytes, content_type: str
) -> None:
    _data, headers, session_id = await _member_and_session(client)

    res = await _post_attachment(
        client, session_id, filename=filename, data=data, content_type=content_type,
        headers=headers,
    )
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_upload_rejects_file_over_size_cap(client: AsyncClient) -> None:
    _data, headers, session_id = await _member_and_session(client)
    big = b"%PDF-1.4\n" + b"0" * (MAX_ATTACHMENT_BYTES + 1)

    res = await _post_attachment(client, session_id, data=big, headers=headers)
    assert res.status_code in (400, 413), res.text


@pytest.mark.asyncio
async def test_upload_requires_auth(client: AsyncClient) -> None:
    _data, _headers, session_id = await _member_and_session(client)
    res = await _post_attachment(client, session_id)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_upload_unknown_session_is_404(client: AsyncClient) -> None:
    """Route-missing is also 404 — pin the distinction by uploading to a real
    session first (must succeed), then to a random id (must 404)."""
    _data, headers, session_id = await _member_and_session(client)
    res = await _post_attachment(client, session_id, headers=headers)
    assert res.status_code in (200, 201), res.text

    res = await _post_attachment(client, uuid.uuid4(), headers=headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_upload_other_users_session_is_403(client: AsyncClient) -> None:
    """``_require_owned_session``: existing session owned by someone else → 403."""
    _data, _headers, session_id = await _member_and_session(client)
    other = await register_user(client)
    res = await _post_attachment(
        client, session_id, headers=auth_header(other["access_token"])
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_scratch_cap_refuses_eleventh_upload(
    client: AsyncClient,
) -> None:
    """ADR 0047 §14: ~10 scratch attachments per session — the 11th is refused.
    Chosen refusal code: 400 (same family as the endpoint's other refusals)."""
    _data, headers, session_id = await _member_and_session(client)

    for i in range(SCRATCH_CAP):
        res = await _post_attachment(
            client,
            session_id,
            filename=f"note-{i}.txt",
            data=f"scratch doc {i}".encode(),
            content_type="text/plain",
            headers=headers,
        )
        assert res.status_code in (200, 201), f"upload {i + 1}: {res.text}"

    res = await _post_attachment(
        client,
        session_id,
        filename="note-10.txt",
        data=b"one too many",
        content_type="text/plain",
        headers=headers,
    )
    assert res.status_code == 400, res.text


# --- media route no longer serves attachment bytes -----------------------------


@pytest.mark.asyncio
async def test_media_route_never_serves_attachment_keys(client: AsyncClient) -> None:
    """ADR 0047 §3: the unauthenticated ``GET /api/media/{key}`` is restricted
    to the ``sessions/`` image prefix — ``attachments/`` keys 404."""
    _data, _headers, session_id = await _member_and_session(client)

    attachment_key = f"attachments/{uuid.uuid4()}/catalog2026.pdf"
    await put_bytes(
        key=attachment_key, data=make_pdf_with_outline(), content_type="application/pdf"
    )
    res = await client.get(f"/api/media/{attachment_key}")
    assert res.status_code == 404

    image_key = f"sessions/{session_id}/r1.png"
    await put_bytes(key=image_key, data=PNG, content_type="image/png")
    ok = await client.get(f"/api/media/{image_key}")
    assert ok.status_code == 200
    assert ok.content == PNG


# --- authenticated download ----------------------------------------------------


async def _seed_owned_attachment(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[dict, dict[str, str], uuid.UUID, bytes]:
    """A registered member, their session, and a seeded attachment row+bytes."""
    data, headers, session_id = await _member_and_session(client)
    pdf = make_pdf_with_outline()
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=uuid.UUID(data["user"]["id"]),
        company_id=uuid.UUID(data["user"]["organizations"][0]["id"]),
        session_id=session_id,
        filename="catalog2026.pdf",
        data=pdf,
        content_type="application/pdf",
    )
    return data, headers, attachment_id, pdf


@pytest.mark.asyncio
async def test_attachment_download_returns_bytes_to_company_member(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _data, headers, attachment_id, pdf = await _seed_owned_attachment(
        client, db_session
    )
    res = await client.get(
        f"/api/attachments/{attachment_id}/download", headers=headers
    )
    assert res.status_code == 200, res.text
    assert res.content == pdf


@pytest.mark.asyncio
async def test_attachment_download_requires_auth(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _data, _headers, attachment_id, _pdf = await _seed_owned_attachment(
        client, db_session
    )
    res = await client.get(f"/api/attachments/{attachment_id}/download")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_attachment_download_refused_for_other_company(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``require_company_access``: a member of another company never reads
    the file — 403 (or 404 if the impl hides the row). The owner's download
    must succeed first so a missing route cannot pass as a refusal."""
    _data, headers, attachment_id, pdf = await _seed_owned_attachment(
        client, db_session
    )
    own = await client.get(
        f"/api/attachments/{attachment_id}/download", headers=headers
    )
    assert own.status_code == 200 and own.content == pdf

    outsider = await register_user(client)
    res = await client.get(
        f"/api/attachments/{attachment_id}/download",
        headers=auth_header(outsider["access_token"]),
    )
    assert res.status_code in (403, 404)
