SKU_MAX_LEN = 200


def allocate_unique_sku(preferred: str, taken: set[str]) -> str:
    """Return ``preferred`` or ``preferred-2``, ``-3``, … not in ``taken``."""
    existing = {value.strip() for value in taken if value and value.strip()}
    base = (preferred.strip() or "SKU")[:SKU_MAX_LEN]
    if base not in existing:
        return base

    for n in range(2, 10_000):
        suffix = f"-{n}"
        sku = f"{base[: SKU_MAX_LEN - len(suffix)]}{suffix}"
        if sku not in existing:
            return sku
    return f"{base[: SKU_MAX_LEN - 9]}-overflow"
