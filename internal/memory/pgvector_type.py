"""pgvector SQLAlchemy type that works with asyncpg codecs.

Stock ``VECTOR.bind_processor`` stringifies to ``[0.1,0.2,…]``. ``register_vector``
then tries ``Vector(that_string)`` and raises ``expected list or ndarray``.
"""

from __future__ import annotations

from typing import Any

from pgvector.sqlalchemy import VECTOR


class Vector(VECTOR):
    cache_ok = True

    def bind_processor(self, dialect: Any) -> Any:
        if getattr(dialect, "driver", None) == "asyncpg":

            def process(value: Any) -> list[float] | None:
                if value is None:
                    return None
                if hasattr(value, "tolist") and not isinstance(value, list):
                    value = value.tolist()
                return [float(x) for x in value]

            return process
        return super().bind_processor(dialect)
