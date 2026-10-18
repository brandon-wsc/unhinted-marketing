"""Step defs for the ADR 0047 ingest-job + upload scenarios in attachments.feature.

Uploads POST real multipart bytes to ``POST /api/sessions/{id}/attachments``
and drain the ADR 0039 job queue synchronously. Slice retrieval, library and
GC scenarios land in later steps and bind in their own modules, so this file
uses ``scenario()`` per scenario rather than ``scenarios()`` on the feature.
Steps stay sync (pytest-bdd); async work goes through ``api.run``.
"""

from __future__ import annotations

import uuid

from pytest_bdd import given, parsers, scenario, then, when

from internal.memory.document_chunk import ChunkConfig
from tests.api.attachment_helpers import (
    fetch_attachment_row,
    fetch_chunk_rows,
    make_over_cap_text,
    make_pdf_with_outline,
    make_scanned_pdf,
    none_embedder,
    patch_embedder,
    run_next_pending_job,
)
from tests.api.helpers import auth_header, register_user


@scenario(
    "../features/attachments.feature", "upload becomes lexical-ready before vectors"
)
def test_upload_becomes_lexical_ready() -> None:
    pass


@scenario("../features/attachments.feature", "scanned PDF tells the truth")
def test_scanned_pdf_tells_the_truth() -> None:
    pass


@scenario(
    "../features/attachments.feature", "oversized file ingests a capped prefix and says so"
)
def test_oversized_file_capped_prefix() -> None:
    pass


@scenario(
    "../features/attachments.feature", "a cold embedder never marks an attachment ready"
)
def test_cold_embedder_never_marks_ready() -> None:
    pass


@scenario(
    "../features/attachments.feature", "spreadsheet upload is steered to product import"
)
def test_spreadsheet_steered_to_product_import() -> None:
    pass


def _post_attachment(api, bdd_ctx, filename: str, data: bytes, content_type: str):
    """``POST /api/sessions/{id}/attachments`` — the ADR 0047 §3 upload route."""
    return api.post(
        f"/api/sessions/{bdd_ctx['session_id']}/attachments",
        files={"file": (filename, data, content_type)},
        headers=auth_header(bdd_ctx["access_token"]),
    )


def _drain_attachment_jobs(api, *, limit: int = 8) -> None:
    """Run queued attachment jobs synchronously (ingest → optional embed).

    Bounded: a cold embedder re-enqueues ``attachment_embed``, but the dedupe
    key is one-shot so the queue drains in a couple of passes.
    """
    for _ in range(limit):
        if api.run(run_next_pending_job()) is None:
            return
    raise AssertionError("attachment job queue did not drain")


def _upload_and_ingest(
    api, bdd_ctx, filename: str, data: bytes, content_type: str
) -> uuid.UUID:
    """Upload over real HTTP, run the worker jobs, return the attachment id."""
    res = _post_attachment(api, bdd_ctx, filename, data, content_type)
    assert res.status_code in (200, 201), res.text
    attachment_id = uuid.UUID(res.json()["id"])
    _drain_attachment_jobs(api)
    return attachment_id


def _attachment(api, bdd_ctx):
    return api.run(fetch_attachment_row(bdd_ctx["attachment_id"]))


@given("a member with a session")
def member_with_session(api, bdd_ctx) -> None:
    body = api.run(register_user(api.client, email="bdd-attach@example.com"))
    company_id = body["user"]["organizations"][0]["id"]
    res = api.post(
        "/api/sessions",
        json={"company_id": company_id},
        headers=auth_header(body["access_token"]),
    )
    assert res.status_code == 201, res.text
    bdd_ctx["user_id"] = uuid.UUID(body["user"]["id"])
    bdd_ctx["company_id"] = uuid.UUID(company_id)
    bdd_ctx["session_id"] = uuid.UUID(res.json()["id"])
    bdd_ctx["access_token"] = body["access_token"]


@given("the worker embedder has not finished loading")
def worker_embedder_cold(monkeypatch) -> None:
    patch_embedder(monkeypatch, none_embedder)


@when(parsers.parse('they upload "{filename}" with extractable text'))
def upload_extractable_text(api, bdd_ctx, filename: str) -> None:
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, filename, make_pdf_with_outline(), "application/pdf"
    )


@when(parsers.parse('they upload "{filename}" with no extractable text'))
def upload_no_text(api, bdd_ctx, filename: str) -> None:
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, filename, make_scanned_pdf(), "application/pdf"
    )


@when("they upload a file exceeding the chunk cap")
def upload_over_cap(api, bdd_ctx) -> None:
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, "catalog-huge.txt", make_over_cap_text(), "text/plain"
    )


@when(parsers.parse('they upload "{filename}" as an attachment'))
def upload_attachment_refused(api, bdd_ctx, filename: str) -> None:
    """Upload a file the endpoint is expected to refuse (ADR 0047 §12)."""
    content_type = "text/csv" if filename.endswith(".csv") else "application/octet-stream"
    data = b"sku,name,price\nSKU-1,Milk Tea,48\n"
    bdd_ctx["upload_response"] = _post_attachment(
        api, bdd_ctx, filename, data, content_type
    )


@then(parsers.parse('the attachment status becomes "{status}"'))
@then(parsers.parse('the attachment status is "{status}"'))
def attachment_status(api, bdd_ctx, status: str) -> None:
    assert _attachment(api, bdd_ctx).status == status


@then("the digest shows a title, a page count and an outline")
def digest_shows_profile(api, bdd_ctx) -> None:
    profile = _attachment(api, bdd_ctx).doc_profile
    assert profile["title"]
    assert isinstance(profile["pages"], int) and profile["pages"] >= 1
    assert isinstance(profile["outline"], list) and profile["outline"]


@then("the error says the file has no readable text")
def error_says_no_readable_text(api, bdd_ctx) -> None:
    error = _attachment(api, bdd_ctx).error or ""
    assert error
    assert "text" in error.lower() or "讀唔到字" in error


@then(parsers.parse('no chunk is stored without a vector under status "{status}"'))
def no_vectorless_chunk_under_status(api, bdd_ctx, status: str) -> None:
    row = _attachment(api, bdd_ctx)
    if row.status == status:
        chunks = api.run(fetch_chunk_rows(bdd_ctx["attachment_id"]))
        assert chunks
        assert all(chunk.embedding is not None for chunk in chunks)


@then("only the first capped chunks are ingested")
def capped_prefix_ingested(api, bdd_ctx) -> None:
    chunks = api.run(fetch_chunk_rows(bdd_ctx["attachment_id"]))
    assert len(chunks) == ChunkConfig().max_chunks == 150
    assert [chunk.chunk_index for chunk in chunks] == list(range(ChunkConfig().max_chunks))


@then("the digest marks the document partial")
def digest_marks_partial(api, bdd_ctx) -> None:
    assert _attachment(api, bdd_ctx).doc_profile["partial"] is True


@then("the upload is refused with a pointer to product import")
def refused_with_product_import_pointer(api, bdd_ctx) -> None:
    """ADR 0047 §12: 400 whose detail names the product import route."""
    res = bdd_ctx["upload_response"]
    assert res.status_code == 400, res.text
    assert "products/import" in res.text
