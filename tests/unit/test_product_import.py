"""Unit tests for flexible product CSV / Excel import parsing."""

from internal.memory.product_import import parse_csv_bytes, parse_product_upload, rows_from_dicts


def test_parse_csv_flexible_headers() -> None:
    raw = b"Name,SKU,Price\nOat Latte,DRK-OL-12,48\n,,\n"
    rows, errors = parse_csv_bytes(raw)
    assert len(rows) == 1
    assert rows[0]["sku"] == "DRK-OL-12"
    assert rows[0]["name"] == "Oat Latte"
    assert "48" in rows[0]["search_document"]
    assert any("empty" in e.lower() or "Row 3" in e for e in errors)


def test_parse_csv_name_as_sku_fallback() -> None:
    raw = b"product,description\nStaff pick,Only for friends\n"
    rows, errors = parse_csv_bytes(raw)
    assert errors == []
    assert rows[0]["sku"] == "Staff pick"
    assert rows[0]["name"] == "Staff pick"


def test_unsupported_extension() -> None:
    rows, errors = parse_product_upload("products.pdf", b"x")
    assert rows == []
    assert errors


def test_build_search_document_includes_notes() -> None:
    from internal.memory.product_import import build_search_document

    doc = build_search_document(
        {"name": "Staff pick", "sku": "PER-01", "notes": "oat milk default"},
        sku="PER-01",
        name="Staff pick",
    )
    assert "oat milk default" in doc
    assert doc.startswith("Staff pick")


def test_rows_from_dicts_empty() -> None:
    rows, errors = rows_from_dicts([])
    assert rows == []
    assert errors


def test_too_many_columns_rejects_file() -> None:
    from internal.memory.product_import import MAX_IMPORT_COLUMNS

    headers = [f"col{i}" for i in range(MAX_IMPORT_COLUMNS + 1)]
    raw = (",".join(headers) + "\n" + ",".join(["x"] * len(headers)) + "\n").encode()
    rows, errors = parse_csv_bytes(raw)
    assert rows == []
    assert errors
    assert "Too many columns" in errors[0]
    assert str(MAX_IMPORT_COLUMNS) in errors[0]


def test_fifty_columns_still_ok() -> None:
    from internal.memory.product_import import MAX_IMPORT_COLUMNS

    headers = ["name", "sku"] + [f"extra{i}" for i in range(MAX_IMPORT_COLUMNS - 2)]
    assert len(headers) == MAX_IMPORT_COLUMNS
    raw = (",".join(headers) + "\nrow,SKU-1," + ",".join(["v"] * (MAX_IMPORT_COLUMNS - 2)) + "\n").encode()
    rows, errors = parse_csv_bytes(raw)
    assert errors == []
    assert len(rows) == 1
    assert rows[0]["sku"] == "SKU-1"
