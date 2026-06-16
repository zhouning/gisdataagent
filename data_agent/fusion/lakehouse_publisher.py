"""Analytical lakehouse publisher contracts for MMFE semantic products.

This module prepares semantic fusion products for S3-backed Iceberg tables and
spatial engines such as Apache Sedona without importing those runtimes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


ICEBERG_PUBLISH_SCHEMA = "mmfe.iceberg_publish.v1"
SUPPORTED_OBJECT_STORES = {"s3"}
SUPPORTED_SPATIAL_ENGINES = {"sedona", "none"}


def build_iceberg_publish_spec(
    manifest: dict,
    catalog: str,
    namespace: str,
    table: str,
    warehouse_uri: str,
    object_store: str = "s3",
    spatial_engine: str = "sedona",
    partition_by: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a dependency-free Iceberg publish spec from a semantic product."""
    business_output = manifest.get("business_output") or {}
    spec = {
        "schema": ICEBERG_PUBLISH_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": "iceberg",
        "storage_layer": "analytical_lakehouse",
        "object_store": object_store,
        "warehouse_uri": warehouse_uri,
        "catalog": catalog,
        "namespace": namespace,
        "table": table,
        "table_identifier": _table_identifier(catalog, namespace, table),
        "spatial_engine": spatial_engine,
        "partition_by": list(partition_by or []),
        "product_id": str(manifest.get("product_id") or ""),
        "product_type": manifest.get("product_type"),
        "version": manifest.get("version"),
        "business_output": {
            "path": business_output.get("path", ""),
            "format": business_output.get("format", ""),
            "row_count": _safe_int(business_output.get("row_count"), 0),
            "column_count": _safe_int(business_output.get("column_count"), 0),
            "crs": business_output.get("crs", ""),
        },
        "sources": list(manifest.get("sources") or []),
        "lineage": dict(manifest.get("lineage") or {}),
        "quality": dict(manifest.get("quality") or {}),
    }
    if metadata:
        spec["metadata"] = dict(metadata)
    return spec


def validate_iceberg_publish_spec(spec: dict) -> list[str]:
    """Return contract errors for an Iceberg analytical lakehouse spec."""
    errors = []
    if not isinstance(spec, dict):
        return ["iceberg publish spec must be an object"]
    if spec.get("schema") != ICEBERG_PUBLISH_SCHEMA:
        errors.append(f"schema must be {ICEBERG_PUBLISH_SCHEMA}")
    if spec.get("target") != "iceberg":
        errors.append("target must be iceberg")
    if spec.get("storage_layer") != "analytical_lakehouse":
        errors.append("storage_layer must be analytical_lakehouse")
    if spec.get("object_store") not in SUPPORTED_OBJECT_STORES:
        errors.append("object_store must be one of: s3")
    if spec.get("spatial_engine") not in SUPPORTED_SPATIAL_ENGINES:
        errors.append("spatial_engine must be one of: sedona, none")
    for field in ("catalog", "namespace", "table", "warehouse_uri", "product_id"):
        if not spec.get(field):
            errors.append(f"{field} is required")
    business_output = spec.get("business_output")
    if not isinstance(business_output, dict):
        errors.append("business_output must be an object")
    else:
        if not business_output.get("path"):
            errors.append("business_output.path is required")
        if not business_output.get("format"):
            errors.append("business_output.format is required")
    if not isinstance(spec.get("partition_by", []), list):
        errors.append("partition_by must be a list")
    return errors


def run_iceberg_publish(
    spec: dict,
    publisher=None,
) -> dict:
    """Publish an MMFE analytical product through an injected Iceberg adapter."""
    errors = validate_iceberg_publish_spec(spec)
    if errors:
        return _iceberg_publish_result(spec if isinstance(spec, dict) else {}, errors, None)
    if publisher is None:
        return _iceberg_publish_result(spec, ["publisher is required"], None)

    try:
        backend_result = publisher(spec)
    except Exception as exc:
        return _iceberg_publish_result(spec, [str(exc)], None)
    return _iceberg_publish_result(spec, [], backend_result)


def build_iceberg_publisher(executor=None):
    """Build an Iceberg publisher adapter backed by an injected executor."""
    def publisher(spec: dict) -> dict:
        if executor is None:
            raise ValueError("iceberg executor is required")

        business_output = spec.get("business_output") or {}
        payload = {
            "target": "iceberg",
            "storage_layer": "analytical_lakehouse",
            "object_store": spec.get("object_store"),
            "warehouse_uri": spec.get("warehouse_uri"),
            "catalog": spec.get("catalog"),
            "namespace": spec.get("namespace"),
            "table": spec.get("table"),
            "table_identifier": spec.get("table_identifier"),
            "spatial_engine": spec.get("spatial_engine"),
            "partition_by": list(spec.get("partition_by") or []),
            "product_id": spec.get("product_id"),
            "product_type": spec.get("product_type"),
            "source_path": business_output.get("path", ""),
            "source_format": business_output.get("format", ""),
            "row_count": _safe_int(business_output.get("row_count"), 0),
            "column_count": _safe_int(business_output.get("column_count"), 0),
            "crs": business_output.get("crs", ""),
            "sources": list(spec.get("sources") or []),
            "lineage": dict(spec.get("lineage") or {}),
            "quality": dict(spec.get("quality") or {}),
            "metadata": dict(spec.get("metadata") or {}),
        }
        result = executor(payload)
        if isinstance(result, dict):
            output = dict(result)
            output.setdefault("rows_written", _safe_int(output.get("rows_written"), payload["row_count"]))
            output.setdefault("target", "iceberg")
            output.setdefault("table_identifier", spec.get("table_identifier"))
            return output
        return {
            "rows_written": payload["row_count"],
            "target": "iceberg",
            "table_identifier": spec.get("table_identifier"),
        }

    return publisher


def _iceberg_publish_result(
    spec: dict,
    errors: list[str],
    backend_result: Any,
) -> dict:
    rows_written = 0
    if not errors:
        business_output = spec.get("business_output") if isinstance(spec.get("business_output"), dict) else {}
        rows_written = _safe_int(business_output.get("row_count"), 0)
        if isinstance(backend_result, dict) and backend_result.get("rows_written") is not None:
            rows_written = _safe_int(backend_result.get("rows_written"), rows_written)
    return {
        "valid": not errors,
        "errors": errors,
        "schema": spec.get("schema"),
        "target": spec.get("target"),
        "storage_layer": spec.get("storage_layer"),
        "object_store": spec.get("object_store"),
        "catalog": spec.get("catalog"),
        "namespace": spec.get("namespace"),
        "table": spec.get("table"),
        "table_identifier": spec.get("table_identifier"),
        "product_id": spec.get("product_id"),
        "rows_written": rows_written,
        "backend_result": backend_result,
    }


def _table_identifier(catalog: str, namespace: str, table: str) -> str:
    parts = [str(value).strip(".") for value in (catalog, namespace, table) if value]
    return ".".join(parts)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
