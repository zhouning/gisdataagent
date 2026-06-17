"""Optional real pgvector adapter for MMFE semantic vector publishing."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote_plus


DEFAULT_PGVECTOR_TABLE = "agent_mmfe_semantic_vectors"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def build_pgvector_executor(
    connection_url: str | None = None,
    *,
    engine: Any = None,
    table: str = DEFAULT_PGVECTOR_TABLE,
    mode: str = "upsert",
    create_extension: bool = True,
    create_index: bool = False,
):
    """Build a pgvector executor compatible with build_pgvector_publisher.

    SQLAlchemy is imported only when the executor runs, keeping MMFE core
    imports independent from PostgreSQL runtime configuration.
    """

    def executor(payload: dict[str, Any]) -> dict[str, Any]:
        return publish_payload_to_pgvector(
            payload,
            connection_url=connection_url,
            engine=engine,
            table=table,
            mode=mode,
            create_extension=create_extension,
            create_index=create_index,
        )

    return executor


def build_pgvector_query_executor(
    connection_url: str | None = None,
    *,
    engine: Any = None,
    table: str = DEFAULT_PGVECTOR_TABLE,
):
    """Build a pgvector query executor compatible with build_pgvector_querier."""

    def executor(payload: dict[str, Any]) -> dict[str, Any]:
        return query_pgvector_semantic_vectors(
            payload,
            connection_url=connection_url,
            engine=engine,
            table=table,
        )

    return executor


def publish_payload_to_pgvector(
    payload: dict[str, Any],
    *,
    connection_url: str | None = None,
    engine: Any = None,
    table: str | None = None,
    mode: str = "upsert",
    create_extension: bool = True,
    create_index: bool = False,
) -> dict[str, Any]:
    """Publish embedded semantic vector rows to PostgreSQL/pgvector."""

    if mode not in {"append", "upsert", "overwrite"}:
        raise ValueError("mode must be one of: append, upsert, overwrite")

    rows = payload.get("rows") or []
    if not rows:
        raise ValueError("payload.rows must not be empty")

    table_name = str(table or payload.get("table") or DEFAULT_PGVECTOR_TABLE)
    table_sql, table_suffix = _qualified_table_sql(table_name)
    table_regclass = _table_regclass_name(table_name)
    normalized_rows = [_normalize_pgvector_row(row, payload) for row in rows]
    dimension = len(normalized_rows[0]["embedding_values"])
    for index, row in enumerate(normalized_rows):
        if len(row["embedding_values"]) != dimension:
            raise ValueError(f"rows[{index}].embedding dimension must match first row")
        row["embedding"] = _vector_literal(row.pop("embedding_values"))

    created_engine = False
    if engine is None:
        db_url = connection_url or _connection_url_from_env()
        if not db_url:
            raise ValueError(
                "connection_url, DATABASE_URL, MMFE_PGVECTOR_DSN, or POSTGRES_* credentials are required"
            )
        from sqlalchemy import create_engine

        engine = create_engine(db_url, pool_pre_ping=True)
        created_engine = True

    from sqlalchemy import text

    collection = str(payload.get("collection") or "")
    product_id = str(payload.get("product_id") or "")
    operation = "append" if mode == "append" else "upsert"
    try:
        with engine.begin() as conn:
            if create_extension:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            existing_dimension = _existing_vector_dimension(conn, table_regclass)
            if existing_dimension is not None and existing_dimension != dimension:
                raise ValueError(
                    f"{table_name}.embedding is vector({existing_dimension}) but payload embeddings "
                    f"are {dimension}-dimensional; use a separate pgvector table per embedding "
                    "dimension/model or drop and recreate the table"
                )
            conn.execute(text(_create_table_sql(table_sql, dimension)))
            conn.execute(text(_collection_index_sql(table_sql, table_suffix)))
            if create_index:
                conn.execute(text(_vector_index_sql(table_sql, table_suffix)))
            if mode == "overwrite":
                conn.execute(
                    text(
                        f"DELETE FROM {table_sql} "
                        "WHERE product_id = :product_id AND collection = :collection"
                    ),
                    {"product_id": product_id, "collection": collection},
                )
                operation = "overwrite"
            conn.execute(text(_insert_sql(table_sql, upsert=(mode != "append"))), normalized_rows)
            row_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table_sql} WHERE collection = :collection"),
                {"collection": collection},
            ).scalar()
    finally:
        if created_engine and hasattr(engine, "dispose"):
            engine.dispose()

    return {
        "upserted": len(normalized_rows),
        "published_count": len(normalized_rows),
        "target": "pgvector",
        "table": table_name,
        "collection": collection,
        "operation": operation,
        "row_count": int(row_count or 0),
        "embedding_dimension": dimension,
    }


def query_pgvector_semantic_vectors(
    payload: dict[str, Any],
    *,
    connection_url: str | None = None,
    engine: Any = None,
    table: str | None = None,
) -> dict[str, Any]:
    """Query semantic vector rows from PostgreSQL/pgvector."""

    query_embedding = payload.get("query_embedding")
    if not isinstance(query_embedding, list) or not query_embedding:
        raise ValueError("payload.query_embedding must not be empty")

    table_name = str(table or payload.get("table") or DEFAULT_PGVECTOR_TABLE)
    table_sql, _ = _qualified_table_sql(table_name)
    query_vector = _vector_literal([float(value) for value in query_embedding])
    top_k = _safe_positive_int(payload.get("top_k"), 5)
    collection = str(payload.get("collection") or "")
    product_id = str(payload.get("product_id") or "")

    created_engine = False
    if engine is None:
        db_url = connection_url or _connection_url_from_env()
        if not db_url:
            raise ValueError(
                "connection_url, DATABASE_URL, MMFE_PGVECTOR_DSN, or POSTGRES_* credentials are required"
            )
        from sqlalchemy import create_engine

        engine = create_engine(db_url, pool_pre_ping=True)
        created_engine = True

    from sqlalchemy import text

    where_parts = ["collection = :collection"]
    params = {"collection": collection, "product_id": product_id, "query_vector": query_vector, "top_k": top_k}
    if product_id:
        where_parts.append("product_id = :product_id")
    where_sql = " AND ".join(where_parts)
    sql = f"""
SELECT
    record_id,
    product_id,
    collection,
    content_text,
    metadata,
    source_manifest,
    embedding <=> CAST(:query_vector AS vector) AS distance
FROM {table_sql}
WHERE {where_sql}
ORDER BY embedding <=> CAST(:query_vector AS vector)
LIMIT :top_k
"""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
    finally:
        if created_engine and hasattr(engine, "dispose"):
            engine.dispose()

    return {
        "target": "pgvector",
        "table": table_name,
        "collection": collection,
        "product_id": product_id,
        "top_k": top_k,
        "matches": [_normalize_pgvector_match(row) for row in rows],
    }


def _normalize_pgvector_row(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    embedding = row.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise ValueError(f"{row.get('record_id') or '<unknown>'}: embedding is required")
    embedding_values = [float(value) for value in embedding]
    metadata = dict(row.get("metadata") or {})
    metadata.setdefault("collection", payload.get("collection"))
    metadata.setdefault("product_id", payload.get("product_id"))
    return {
        "record_id": str(row.get("record_id") or ""),
        "product_id": str(payload.get("product_id") or row.get("product_id") or ""),
        "collection": str(payload.get("collection") or ""),
        "content_text": str(row.get("text") or ""),
        "embedding_values": embedding_values,
        "metadata": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        "source_manifest": json.dumps(payload.get("source_manifest") or {}, ensure_ascii=False, sort_keys=True),
    }


def _connection_url_from_env() -> str | None:
    direct = os.environ.get("MMFE_PGVECTOR_DSN") or os.environ.get("DATABASE_URL")
    if direct:
        if direct.startswith("postgresql+asyncpg://"):
            return direct.replace("postgresql+asyncpg://", "postgresql://", 1)
        return direct

    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    database = os.environ.get("POSTGRES_DATABASE") or os.environ.get("POSTGRES_DB")
    if not all([user, password, database]):
        return None
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{quote_plus(password)}@{host}:{port}/{database}"


def _qualified_table_sql(name: str) -> tuple[str, str]:
    parts = name.split(".")
    if len(parts) not in (1, 2) or any(not part for part in parts):
        raise ValueError("table must be an unquoted identifier or schema.table")
    for part in parts:
        if not _IDENTIFIER_RE.match(part):
            raise ValueError(f"unsafe PostgreSQL identifier: {part}")
    return ".".join(_quote_identifier(part) for part in parts), "_".join(parts)


def _table_regclass_name(name: str) -> str:
    parts = name.split(".")
    if len(parts) not in (1, 2) or any(not part for part in parts):
        raise ValueError("table must be an unquoted identifier or schema.table")
    for part in parts:
        if not _IDENTIFIER_RE.match(part):
            raise ValueError(f"unsafe PostgreSQL identifier: {part}")
    return ".".join(parts)


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier}"'


def _index_identifier(prefix: str, table_suffix: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", f"{prefix}_{table_suffix}")
    if not clean or clean[0].isdigit():
        clean = f"idx_{clean}"
    return _quote_identifier(clean[:60])


def _create_table_sql(table_sql: str, dimension: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table_sql} (
    record_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    collection TEXT NOT NULL,
    content_text TEXT NOT NULL,
    embedding VECTOR({dimension}) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    source_manifest JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _collection_index_sql(table_sql: str, table_suffix: str) -> str:
    index_sql = _index_identifier("idx_mmfe_semantic_vectors_collection", table_suffix)
    return f"CREATE INDEX IF NOT EXISTS {index_sql} ON {table_sql} (collection, product_id)"


def _vector_index_sql(table_sql: str, table_suffix: str) -> str:
    index_sql = _index_identifier("idx_mmfe_semantic_vectors_embedding", table_suffix)
    return (
        f"CREATE INDEX IF NOT EXISTS {index_sql} "
        f"ON {table_sql} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def _insert_sql(table_sql: str, *, upsert: bool) -> str:
    base = f"""
INSERT INTO {table_sql}
    (record_id, product_id, collection, content_text, embedding, metadata, source_manifest, updated_at)
VALUES
    (
        :record_id,
        :product_id,
        :collection,
        :content_text,
        CAST(:embedding AS vector),
        CAST(:metadata AS jsonb),
        CAST(:source_manifest AS jsonb),
        NOW()
    )
"""
    if not upsert:
        return base
    return (
        base
        + """
ON CONFLICT (record_id) DO UPDATE SET
    product_id = EXCLUDED.product_id,
    collection = EXCLUDED.collection,
    content_text = EXCLUDED.content_text,
    embedding = EXCLUDED.embedding,
    metadata = EXCLUDED.metadata,
    source_manifest = EXCLUDED.source_manifest,
    updated_at = NOW()
"""
    )


def _existing_vector_dimension(conn: Any, table_regclass: str) -> int | None:
    from sqlalchemy import text

    type_name = conn.execute(
        text(
            """
SELECT format_type(a.atttypid, a.atttypmod) AS type_name
FROM pg_attribute a
WHERE a.attrelid = to_regclass(:table_regclass)
  AND a.attname = 'embedding'
  AND NOT a.attisdropped
"""
        ),
        {"table_regclass": table_regclass},
    ).scalar()
    return _vector_dimension_from_format_type(type_name)


def _vector_dimension_from_format_type(type_name: Any) -> int | None:
    match = re.fullmatch(r"vector\((\d+)\)", str(type_name or ""))
    if not match:
        return None
    return int(match.group(1))


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def _normalize_pgvector_match(row: Any) -> dict[str, Any]:
    distance = row.get("distance")
    metadata = _json_obj(row.get("metadata"))
    match = {
        "record_id": row.get("record_id"),
        "product_id": row.get("product_id"),
        "collection": row.get("collection"),
        "text": row.get("content_text"),
        "metadata": metadata,
        "source_manifest": _json_obj(row.get("source_manifest")),
    }
    if distance is not None:
        match["distance"] = float(distance)
        match["score"] = 1.0 / (1.0 + float(distance))
    return match


def _json_obj(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _safe_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, 1)
