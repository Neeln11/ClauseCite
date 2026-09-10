"""Column types that work on both PostgreSQL and SQLite.

The application targets PostgreSQL + pgvector in production, but the whole
pipeline — ingest, retrieve, cite, highlight — has to be runnable on a laptop
with nothing installed. SQLite is that fallback, and these three TypeDecorators
are what let one set of models serve both.

Each type compiles to the native PostgreSQL column when the dialect is
`postgresql` and to a portable equivalent otherwise. No call site needs to know
which database it is talking to.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import JSON, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Dialect


class GUID(TypeDecorator[uuid.UUID]):
    """UUID on PostgreSQL, 36-character CHAR elsewhere.

    Values are normalised to `uuid.UUID` on the way out regardless of backend,
    so `Document.id` is the same Python type in both configurations and code
    that formats or compares ids never has to branch.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class JSONType(TypeDecorator[Any]):
    """JSONB on PostgreSQL, SQLAlchemy's portable JSON elsewhere.

    JSONB is worth keeping in production for its indexing; the generic JSON type
    stores the same documents as text on SQLite and round-trips identically.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class EmbeddingType(TypeDecorator[list[float]]):
    """pgvector `vector(N)` on PostgreSQL, a JSON array of floats elsewhere.

    On SQLite there is no vector index and no distance operator, so similarity is
    computed in Python (see `app.services.retrieve`). That is O(n) over the
    corpus rather than an index lookup — fine for the thousands of chunks a
    laptop demo holds, and the reason production keeps pgvector.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        super().__init__()

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps([float(v) for v in value])

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return [float(v) for v in json.loads(value)]
        return list(value)
