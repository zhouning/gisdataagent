"""Publisher contracts for MMFE semantic product vector indexing.

This module prepares semantic product chunks for downstream vector stores such
as pgvector or LanceDB without importing either runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SEMANTIC_VECTOR_PUBLISH_SCHEMA = "mmfe.semantic_vector_publish.v1"
SUPPORTED_VECTOR_TARGETS = {"pgvector", "lancedb"}


def build_semantic_vector_publish_spec(
    manifest: dict,
    target: str = "pgvector",
    collection: str = "mmfe_semantic_products",
    embedding_model: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a dependency-free publish spec from semantic product chunks."""
    product_id = str(manifest.get("product_id") or "")
    business_output = manifest.get("business_output") or {}
    ai_metadata = manifest.get("ai_metadata") or {}
    records = _records_from_chunks(product_id, ai_metadata.get("chunks") or [])
    spec = {
        "schema": SEMANTIC_VECTOR_PUBLISH_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "collection": collection,
        "embedding_model": embedding_model,
        "embedding_required": True,
        "product_id": product_id,
        "source_manifest": {
            "product_type": manifest.get("product_type"),
            "version": manifest.get("version"),
            "business_output_path": business_output.get("path", ""),
        },
        "records": records,
    }
    if metadata:
        spec["metadata"] = dict(metadata)
    return spec


def validate_semantic_vector_publish_spec(spec: dict) -> list[str]:
    """Return contract errors for a semantic vector publish spec."""
    errors = []
    if not isinstance(spec, dict):
        return ["semantic vector publish spec must be an object"]
    if spec.get("schema") != SEMANTIC_VECTOR_PUBLISH_SCHEMA:
        errors.append(f"schema must be {SEMANTIC_VECTOR_PUBLISH_SCHEMA}")
    if spec.get("target") not in SUPPORTED_VECTOR_TARGETS:
        errors.append("target must be one of: pgvector, lancedb")
    if not spec.get("collection"):
        errors.append("collection is required")
    if not spec.get("product_id"):
        errors.append("product_id is required")

    records = spec.get("records")
    if not isinstance(records, list):
        errors.append("records must be a list")
        return errors
    if not records:
        errors.append("records must not be empty")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"records[{index}] must be an object")
            continue
        if not record.get("record_id"):
            errors.append(f"records[{index}].record_id is required")
        if not record.get("text"):
            errors.append(f"records[{index}].text is required")
        if not isinstance(record.get("metadata"), dict):
            errors.append(f"records[{index}].metadata must be an object")
    return errors


def embed_semantic_vector_records(
    spec: dict,
    embedder=None,
) -> dict:
    """Embed publish records through an injected embedding adapter."""
    errors = validate_semantic_vector_publish_spec(spec)
    if errors:
        return _embedding_result(spec if isinstance(spec, dict) else {}, errors)
    if embedder is None:
        return _embedding_result(spec, ["embedder is required"])

    embedded_spec = dict(spec)
    records = [dict(record) for record in spec.get("records", [])]
    texts = [record.get("text", "") for record in records]
    try:
        embeddings = embedder(
            texts,
            embedding_model=spec.get("embedding_model"),
            product_id=spec.get("product_id"),
            target=spec.get("target"),
            collection=spec.get("collection"),
        )
    except Exception as exc:
        return _embedding_result(spec, [str(exc)])

    normalized, embedding_errors = _normalize_embeddings(embeddings, len(records))
    if embedding_errors:
        return _embedding_result(spec, embedding_errors)

    dimension = len(normalized[0]) if normalized else 0
    for record, embedding in zip(records, normalized):
        record["embedding"] = embedding
        metadata = dict(record.get("metadata") or {})
        metadata["embedding_model"] = spec.get("embedding_model")
        metadata["embedding_dimension"] = dimension
        record["metadata"] = metadata
    embedded_spec["records"] = records
    embedded_spec["embedding_required"] = False
    embedded_spec["embedding_dimension"] = dimension
    return _embedding_result(embedded_spec, [])


def run_semantic_vector_publish(
    spec: dict,
    publisher=None,
) -> dict:
    """Publish semantic vector records through an injected backend adapter."""
    errors = validate_semantic_vector_publish_spec(spec)
    if errors:
        return _publish_result(spec if isinstance(spec, dict) else {}, errors, None)
    if publisher is None:
        return _publish_result(spec, ["publisher is required"], None)

    try:
        backend_result = publisher(
            spec["records"],
            target=spec["target"],
            collection=spec["collection"],
            embedding_model=spec.get("embedding_model"),
            product_id=spec.get("product_id"),
            source_manifest=spec.get("source_manifest"),
            metadata=spec.get("metadata", {}),
        )
    except Exception as exc:
        return _publish_result(spec, [str(exc)], None)
    return _publish_result(spec, [], backend_result)


def _records_from_chunks(product_id: str, chunks: list[dict]) -> list[dict]:
    records = []
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            continue
        chunk_id = str(chunk.get("chunk_id") or f"chunk:{index}")
        text = str(chunk.get("text") or "")
        metadata = dict(chunk.get("metadata") or {})
        metadata.update({
            "product_id": product_id,
            "chunk_id": chunk_id,
            "chunk_index": index,
        })
        records.append({
            "record_id": f"{product_id}:{chunk_id}",
            "text": text,
            "metadata": metadata,
        })
    return records


def _publish_result(
    spec: dict,
    errors: list[str],
    backend_result: Any,
) -> dict:
    target = spec.get("target")
    collection = spec.get("collection")
    records = spec.get("records") if isinstance(spec.get("records"), list) else []
    published_count = 0
    if not errors:
        if isinstance(backend_result, dict) and backend_result.get("published_count") is not None:
            try:
                published_count = int(backend_result["published_count"])
            except (TypeError, ValueError):
                published_count = len(records)
        else:
            published_count = len(records)
    return {
        "valid": not errors,
        "errors": errors,
        "schema": spec.get("schema"),
        "target": target,
        "collection": collection,
        "product_id": spec.get("product_id"),
        "record_count": len(records),
        "published_count": published_count,
        "backend_result": backend_result,
    }


def _normalize_embeddings(
    embeddings: Any,
    expected_count: int,
) -> tuple[list[list[float]], list[str]]:
    if not isinstance(embeddings, list):
        return [], ["embedder must return a list of vectors"]
    if len(embeddings) != expected_count:
        return [], ["embedding count must match record count"]

    normalized = []
    for index, vector in enumerate(embeddings):
        if not isinstance(vector, (list, tuple)) or not vector:
            return [], [f"embeddings[{index}] must be a non-empty numeric vector"]
        values = []
        for value in vector:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                return [], [f"embeddings[{index}] must contain only numeric values"]
        normalized.append(values)
    return normalized, []


def _embedding_result(
    spec: dict,
    errors: list[str],
) -> dict:
    records = spec.get("records") if isinstance(spec.get("records"), list) else []
    embedded_count = sum(1 for record in records if isinstance(record, dict) and "embedding" in record)
    return {
        "valid": not errors,
        "errors": errors,
        "schema": spec.get("schema"),
        "target": spec.get("target"),
        "collection": spec.get("collection"),
        "product_id": spec.get("product_id"),
        "embedding_model": spec.get("embedding_model"),
        "embedding_dimension": spec.get("embedding_dimension"),
        "record_count": len(records),
        "embedded_count": embedded_count,
        "spec": spec,
    }
