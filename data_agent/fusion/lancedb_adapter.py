"""Optional real LanceDB adapter for MMFE semantic vector publishing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_local_lancedb_executor(
    dataset_uri: str | Path,
    *,
    mode: str = "append",
):
    """Build a LanceDB executor compatible with build_lancedb_publisher.

    LanceDB and PyArrow are imported only when the executor runs, keeping MMFE
    core imports dependency-free.
    """

    dataset_path = str(dataset_uri)

    def executor(payload: dict[str, Any]) -> dict[str, Any]:
        return publish_payload_to_lancedb(payload, dataset_path=dataset_path, mode=mode)

    return executor


def build_local_lancedb_query_executor(
    dataset_uri: str | Path,
):
    """Build a LanceDB query executor compatible with build_lancedb_querier."""

    dataset_path = str(dataset_uri)

    def executor(payload: dict[str, Any]) -> dict[str, Any]:
        return query_lancedb_semantic_vectors(payload, dataset_path=dataset_path)

    return executor


def publish_payload_to_lancedb(
    payload: dict[str, Any],
    *,
    dataset_path: str | Path | None = None,
    mode: str = "append",
) -> dict[str, Any]:
    """Publish embedded semantic vector rows to a local LanceDB table."""

    try:
        import lancedb
        import pyarrow as pa
    except Exception as exc:  # pragma: no cover - exercised when optional deps absent.
        raise RuntimeError(
            "LanceDB publishing requires optional dependencies: lancedb and pyarrow"
        ) from exc

    rows = payload.get("rows") or []
    if not rows:
        raise ValueError("payload.rows must not be empty")
    table_name = str(payload.get("table") or payload.get("collection") or "semantic_products")
    db_uri = str(dataset_path or payload.get("dataset_uri") or "")
    if db_uri.startswith("file://"):
        db_uri = db_uri[7:]
    if not db_uri:
        raise ValueError("dataset_path or payload.dataset_uri is required")
    Path(db_uri).mkdir(parents=True, exist_ok=True)

    normalized_rows = [_normalize_lancedb_row(row, payload) for row in rows]
    schema = _arrow_schema(len(normalized_rows[0]["vector"]), pa)
    table = pa.Table.from_pylist(normalized_rows, schema=schema)

    db = lancedb.connect(db_uri)
    existing = set(_list_lancedb_tables(db))
    if table_name in existing and mode != "overwrite":
        db.open_table(table_name).add(table)
        operation = "append"
    else:
        db.create_table(table_name, data=table, mode="overwrite")
        operation = "create" if table_name not in existing else "overwrite"

    out_table = db.open_table(table_name)
    return {
        "inserted": len(normalized_rows),
        "published_count": len(normalized_rows),
        "target": "lancedb",
        "dataset_uri": db_uri,
        "table": table_name,
        "operation": operation,
        "row_count": int(out_table.count_rows()),
        "embedding_dimension": len(normalized_rows[0]["vector"]),
    }


def query_lancedb_semantic_vectors(
    payload: dict[str, Any],
    *,
    dataset_path: str | Path | None = None,
) -> dict[str, Any]:
    """Query semantic vector rows from a local LanceDB table."""

    try:
        import lancedb
    except Exception as exc:  # pragma: no cover - exercised when optional deps absent.
        raise RuntimeError("LanceDB querying requires optional dependency: lancedb") from exc

    query_embedding = payload.get("query_embedding")
    if not isinstance(query_embedding, list) or not query_embedding:
        raise ValueError("payload.query_embedding must not be empty")
    query_vector = [float(value) for value in query_embedding]
    table_name = str(payload.get("table") or payload.get("collection") or "semantic_products")
    db_uri = str(dataset_path or payload.get("dataset_uri") or "")
    if db_uri.startswith("file://"):
        db_uri = db_uri[7:]
    if not db_uri:
        raise ValueError("dataset_path or payload.dataset_uri is required")

    top_k = _safe_positive_int(payload.get("top_k"), 5)
    collection = str(payload.get("collection") or "")
    product_id = str(payload.get("product_id") or "")

    db = lancedb.connect(db_uri)
    table = db.open_table(table_name)
    rows = table.search(query_vector).limit(top_k).to_list()
    matches = []
    for row in rows:
        if collection and str(row.get("collection") or "") != collection:
            continue
        if product_id and str(row.get("product_id") or "") != product_id:
            continue
        matches.append(_normalize_lancedb_match(row))
        if len(matches) >= top_k:
            break
    return {
        "target": "lancedb",
        "dataset_uri": db_uri,
        "table": table_name,
        "collection": collection,
        "product_id": product_id,
        "top_k": top_k,
        "matches": matches,
    }


def _normalize_lancedb_row(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    embedding = row.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise ValueError(f"{row.get('record_id') or '<unknown>'}: embedding is required")
    vector = [float(value) for value in embedding]
    metadata = dict(row.get("metadata") or {})
    metadata.setdefault("collection", payload.get("collection"))
    metadata.setdefault("product_id", payload.get("product_id"))
    return {
        "record_id": str(row.get("record_id") or ""),
        "product_id": str(payload.get("product_id") or row.get("product_id") or ""),
        "collection": str(payload.get("collection") or ""),
        "text": str(row.get("text") or ""),
        "vector": vector,
        "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    }


def _list_lancedb_tables(db: Any) -> list[str]:
    if hasattr(db, "list_tables"):
        response = db.list_tables()
        if hasattr(response, "tables"):
            return [str(table) for table in response.tables]
        return [str(table) for table in response]
    return list(db.table_names())


def _arrow_schema(dimension: int, pa):
    return pa.schema(
        [
            pa.field("record_id", pa.string()),
            pa.field("product_id", pa.string()),
            pa.field("collection", pa.string()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), list_size=dimension)),
            pa.field("metadata_json", pa.string()),
        ]
    )


def _normalize_lancedb_match(row: dict[str, Any]) -> dict[str, Any]:
    distance = row.get("_distance")
    metadata_raw = row.get("metadata_json")
    try:
        metadata = json.loads(metadata_raw) if metadata_raw else {}
    except Exception:
        metadata = {"metadata_json": metadata_raw}
    match = {
        "record_id": row.get("record_id"),
        "product_id": row.get("product_id"),
        "collection": row.get("collection"),
        "text": row.get("text"),
        "metadata": metadata,
    }
    if distance is not None:
        match["distance"] = float(distance)
        match["score"] = 1.0 / (1.0 + float(distance))
    return match


def _safe_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, 1)
