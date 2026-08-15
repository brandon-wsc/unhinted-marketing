from internal.memory.product_sku import allocate_unique_sku


def test_allocate_unique_sku_returns_preferred_when_free() -> None:
    assert allocate_unique_sku("DRK-OL-12", {"DRK-CB-01"}) == "DRK-OL-12"


def test_allocate_unique_sku_increments_suffix() -> None:
    assert allocate_unique_sku("ABC", {"ABC"}) == "ABC-2"
    assert allocate_unique_sku("ABC", {"ABC", "ABC-2"}) == "ABC-3"


def test_allocate_unique_sku_respects_max_length() -> None:
    base = "X" * 200
    next_sku = allocate_unique_sku(base, {base})
    assert len(next_sku) <= 200
    assert next_sku.endswith("-2")
