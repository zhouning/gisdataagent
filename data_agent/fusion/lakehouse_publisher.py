"""Analytical lakehouse publisher contracts for MMFE semantic products.

This module prepares semantic fusion products for S3-backed Iceberg tables and
spatial engines such as Apache Sedona without importing those runtimes.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any


ICEBERG_PUBLISH_SCHEMA = "mmfe.iceberg_publish.v1"
SEDONA_ICEBERG_RUNNER_SCHEMA = "mmfe.sedona_iceberg_runner.v1"
STAC_PUBLISH_SCHEMA = "mmfe.stac_publish.v1"
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


def build_sedona_iceberg_runner_spec(
    task: str,
    catalog: str,
    warehouse_uri: str,
    input_tables: list[str],
    output_table: str,
    sql: str,
    spatial_engine: str = "sedona",
    spark_conf: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a dependency-free Sedona-on-Iceberg runner spec."""
    spec = {
        "schema": SEDONA_ICEBERG_RUNNER_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": "iceberg",
        "storage_layer": "analytical_lakehouse",
        "spatial_engine": spatial_engine,
        "task": task,
        "catalog": catalog,
        "warehouse_uri": warehouse_uri,
        "input_tables": list(input_tables or []),
        "output_table": output_table,
        "sql": sql,
        "spark_conf": dict(spark_conf or {}),
    }
    if metadata:
        spec["metadata"] = dict(metadata)
    return spec


def validate_sedona_iceberg_runner_spec(spec: dict) -> list[str]:
    """Return contract errors for a Sedona-on-Iceberg runner spec."""
    errors = []
    if not isinstance(spec, dict):
        return ["sedona iceberg runner spec must be an object"]
    if spec.get("schema") != SEDONA_ICEBERG_RUNNER_SCHEMA:
        errors.append(f"schema must be {SEDONA_ICEBERG_RUNNER_SCHEMA}")
    if spec.get("target") != "iceberg":
        errors.append("target must be iceberg")
    if spec.get("storage_layer", "analytical_lakehouse") != "analytical_lakehouse":
        errors.append("storage_layer must be analytical_lakehouse")
    if spec.get("spatial_engine") != "sedona":
        errors.append("spatial_engine must be sedona")
    for field in ("task", "catalog", "warehouse_uri", "output_table", "sql"):
        if not spec.get(field):
            errors.append(f"{field} is required")
    input_tables = spec.get("input_tables")
    if not isinstance(input_tables, list) or not input_tables:
        errors.append("input_tables must be a non-empty list")
    elif not all(isinstance(table, str) and table for table in input_tables):
        errors.append("input_tables must contain non-empty table identifiers")
    if not isinstance(spec.get("spark_conf", {}), dict):
        errors.append("spark_conf must be an object")
    return errors


def build_stac_publish_spec(
    manifest: dict,
    collection: str,
    catalog_uri: str = "",
    item_datetime: str | None = None,
    bbox: list[float] | None = None,
    geometry: dict | None = None,
    media_type: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a dependency-free STAC publish spec for semantic product discovery."""
    business_output = manifest.get("business_output") or {}
    product_id = str(manifest.get("product_id") or "")
    quality = dict(manifest.get("quality") or {})
    lineage = dict(manifest.get("lineage") or {})
    authoritative_lakehouse = _authoritative_lakehouse_from_manifest(manifest)

    properties = {
        "datetime": item_datetime or _utc_now_z(),
        "mmfe:product_type": manifest.get("product_type"),
        "mmfe:product_version": manifest.get("version"),
        "mmfe:business_output_format": business_output.get("format", ""),
        "mmfe:row_count": _safe_int(business_output.get("row_count"), 0),
        "mmfe:column_count": _safe_int(business_output.get("column_count"), 0),
        "mmfe:source_count": len(manifest.get("sources") or []),
        "mmfe:lineage": lineage,
    }
    if quality.get("score") is not None:
        properties["mmfe:quality_score"] = quality.get("score")
    epsg = _epsg_from_crs(business_output.get("crs"))
    if epsg is not None:
        properties["proj:epsg"] = epsg
    if authoritative_lakehouse:
        properties["mmfe:authoritative_lakehouse"] = authoritative_lakehouse

    output_path = business_output.get("path", "")
    item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": product_id,
        "collection": collection,
        "bbox": list(bbox or []),
        "geometry": dict(geometry) if isinstance(geometry, dict) else None,
        "properties": {key: value for key, value in properties.items() if value not in ("", None, {}, [])},
        "assets": {
            "data": {
                "href": output_path,
                "type": media_type or _media_type_for_output(business_output.get("format"), output_path),
                "roles": ["data"],
                "title": "MMFE business output",
            }
        },
        "links": _stac_links(catalog_uri, collection),
    }
    spec = {
        "schema": STAC_PUBLISH_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": "stac",
        "storage_layer": "discovery_catalog",
        "catalog_uri": catalog_uri,
        "collection": collection,
        "product_id": product_id,
        "item": item,
        "assets": item["assets"],
        "links": item["links"],
        "properties": item["properties"],
        "lineage": lineage,
        "quality": quality,
    }
    if authoritative_lakehouse:
        spec["lakehouse"] = {"iceberg": authoritative_lakehouse}
    if metadata:
        spec["metadata"] = dict(metadata)
    return spec


def validate_stac_publish_spec(spec: dict) -> list[str]:
    """Return contract errors for a STAC discovery catalog publish spec."""
    errors = []
    if not isinstance(spec, dict):
        return ["stac publish spec must be an object"]
    if spec.get("schema") != STAC_PUBLISH_SCHEMA:
        errors.append(f"schema must be {STAC_PUBLISH_SCHEMA}")
    if spec.get("target") != "stac":
        errors.append("target must be stac")
    if spec.get("storage_layer", "discovery_catalog") != "discovery_catalog":
        errors.append("storage_layer must be discovery_catalog")
    if not spec.get("collection"):
        errors.append("collection is required")
    if not spec.get("product_id"):
        errors.append("product_id is required")

    item = spec.get("item")
    if not isinstance(item, dict):
        errors.append("item must be an object")
        return errors
    if item.get("type") != "Feature":
        errors.append("item.type must be Feature")
    if not item.get("id"):
        errors.append("item.id is required")
    if not item.get("collection"):
        errors.append("item.collection is required")
    if not isinstance(item.get("properties"), dict):
        errors.append("item.properties must be an object")
    if not isinstance(item.get("links", []), list):
        errors.append("item.links must be a list")
    if not isinstance(item.get("bbox", []), list):
        errors.append("item.bbox must be a list")

    assets = item.get("assets")
    if not isinstance(assets, dict) or not assets:
        errors.append("item.assets must be a non-empty object")
        return errors
    data_asset = assets.get("data")
    if not isinstance(data_asset, dict):
        errors.append("item.assets.data is required")
        return errors
    if not data_asset.get("href"):
        errors.append("item.assets.data.href is required")
    if not data_asset.get("type"):
        errors.append("item.assets.data.type is required")
    if not isinstance(data_asset.get("roles", []), list):
        errors.append("item.assets.data.roles must be a list")
    return errors


def run_sedona_iceberg_job(
    spec: dict,
    executor=None,
) -> dict:
    """Run a Sedona-on-Iceberg job through an injected executor."""
    errors = validate_sedona_iceberg_runner_spec(spec)
    if errors:
        return _sedona_iceberg_result(spec if isinstance(spec, dict) else {}, errors, None)
    if executor is None:
        return _sedona_iceberg_result(spec, ["executor is required"], None)

    try:
        backend_result = executor(dict(spec))
    except Exception as exc:
        return _sedona_iceberg_result(spec, [str(exc)], None)

    run_errors = []
    if isinstance(backend_result, dict):
        returncode = _safe_int(backend_result.get("returncode"), 0)
        if returncode != 0:
            run_errors.append(f"executor returned non-zero status {returncode}")
    return _sedona_iceberg_result(spec, run_errors, backend_result)


def run_stac_publish(
    spec: dict,
    publisher=None,
) -> dict:
    """Publish a STAC item through an injected catalog adapter."""
    errors = validate_stac_publish_spec(spec)
    if errors:
        return _stac_publish_result(spec if isinstance(spec, dict) else {}, errors, None)
    if publisher is None:
        return _stac_publish_result(spec, ["publisher is required"], None)

    try:
        backend_result = publisher(spec)
    except Exception as exc:
        return _stac_publish_result(spec, [str(exc)], None)
    return _stac_publish_result(spec, [], backend_result)


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


def publish_semantic_product(
    manifest: dict,
    targets: list[str] | None = None,
    iceberg: dict | None = None,
    stac: dict | None = None,
    vector: dict | None = None,
) -> dict:
    """Publish a semantic product through optional dependency-free target contracts."""
    requested_targets = list(targets or [])
    current_manifest = deepcopy(manifest)
    results = {}
    errors = []

    for target in requested_targets:
        if target == "iceberg":
            result = _publish_orchestrated_iceberg(current_manifest, iceberg or {})
            results[target] = result
            if not result.get("valid"):
                errors.append({"target": target, "errors": list(result.get("errors") or [])})
                break
            current_manifest = apply_iceberg_manifest_patch(current_manifest, result.get("manifest_patch") or {})
        elif target == "stac":
            result = _publish_orchestrated_stac(current_manifest, stac or {})
            if not result.get("valid"):
                errors.append({"target": target, "errors": list(result.get("errors") or [])})
                break
            results[target] = result
            current_manifest = _apply_catalog_manifest_patch(current_manifest, result.get("manifest_patch") or {})
        elif target in ("pgvector", "lancedb"):
            result = _publish_orchestrated_vector(current_manifest, target, vector or {})
            if not result.get("valid"):
                errors.append({"target": target, "errors": list(result.get("errors") or [])})
                break
            results[target] = result
        else:
            errors.append({"target": target, "errors": [f"unsupported publish target: {target}"]})
            break

    return {
        "valid": not errors,
        "errors": errors,
        "targets": requested_targets,
        "results": results,
        "manifest": current_manifest,
    }


def build_stac_publisher(executor=None):
    """Build a STAC publisher adapter backed by an injected executor."""
    def publisher(spec: dict) -> dict:
        if executor is None:
            raise ValueError("stac executor is required")

        item = spec.get("item") or {}
        payload = {
            "target": "stac",
            "storage_layer": "discovery_catalog",
            "catalog_uri": spec.get("catalog_uri", ""),
            "collection": spec.get("collection"),
            "product_id": spec.get("product_id"),
            "item_id": item.get("id"),
            "item": dict(item),
            "assets": dict(item.get("assets") or {}),
            "links": list(item.get("links") or []),
            "properties": dict(item.get("properties") or {}),
            "metadata": dict(spec.get("metadata") or {}),
        }
        if isinstance(spec.get("lakehouse"), dict):
            payload["lakehouse"] = dict(spec["lakehouse"])
        result = executor(payload)
        if isinstance(result, dict):
            output = dict(result)
            output.setdefault("published_count", 1)
            output.setdefault("target", "stac")
            output.setdefault("collection", spec.get("collection"))
            output.setdefault("item_id", item.get("id"))
            return output
        return {
            "published_count": 1,
            "target": "stac",
            "collection": spec.get("collection"),
            "item_id": item.get("id"),
        }

    return publisher


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


def apply_iceberg_manifest_patch(manifest: dict, patch: dict) -> dict:
    """Return a copy of a semantic product manifest with Iceberg lineage merged."""
    updated = deepcopy(manifest)
    lakehouse_patch = patch.get("lakehouse") if isinstance(patch, dict) else None
    if not isinstance(lakehouse_patch, dict):
        return updated
    lakehouse = dict(updated.get("lakehouse") or {})
    if isinstance(lakehouse_patch.get("iceberg"), dict):
        existing = dict(lakehouse.get("iceberg") or {})
        existing.update(lakehouse_patch["iceberg"])
        lakehouse["iceberg"] = existing
    updated["lakehouse"] = lakehouse
    return updated


def _publish_orchestrated_iceberg(manifest: dict, config: dict) -> dict:
    spec = build_iceberg_publish_spec(
        manifest,
        catalog=config.get("catalog", ""),
        namespace=config.get("namespace", ""),
        table=config.get("table", ""),
        warehouse_uri=config.get("warehouse_uri", ""),
        object_store=config.get("object_store", "s3"),
        spatial_engine=config.get("spatial_engine", "sedona"),
        partition_by=config.get("partition_by"),
        metadata=config.get("metadata"),
    )
    return run_iceberg_publish(spec, publisher=config.get("publisher"))


def _publish_orchestrated_stac(manifest: dict, config: dict) -> dict:
    spec = build_stac_publish_spec(
        manifest,
        collection=config.get("collection", ""),
        catalog_uri=config.get("catalog_uri", ""),
        item_datetime=config.get("item_datetime"),
        bbox=config.get("bbox"),
        geometry=config.get("geometry"),
        media_type=config.get("media_type"),
        metadata=config.get("metadata"),
    )
    return run_stac_publish(spec, publisher=config.get("publisher"))


def _publish_orchestrated_vector(manifest: dict, target: str, config: dict) -> dict:
    from .semantic_publisher import (
        build_semantic_vector_publish_spec,
        embed_semantic_vector_records,
        run_semantic_vector_publish,
    )

    spec = build_semantic_vector_publish_spec(
        manifest,
        target=config.get("target", target),
        collection=config.get("collection", "mmfe_semantic_products"),
        embedding_model=config.get("embedding_model"),
        metadata=config.get("metadata"),
    )
    embedded = embed_semantic_vector_records(spec, embedder=config.get("embedder"))
    if not embedded.get("valid"):
        return {
            "valid": False,
            "errors": list(embedded.get("errors") or []),
            "schema": spec.get("schema"),
            "target": target,
            "collection": spec.get("collection"),
            "product_id": spec.get("product_id"),
            "record_count": len(spec.get("records") or []),
            "published_count": 0,
            "embedding_result": embedded,
            "backend_result": None,
        }
    result = run_semantic_vector_publish(embedded["spec"], publisher=config.get("publisher"))
    if isinstance(result, dict):
        result.setdefault("embedding_result", embedded)
    return result


def _apply_catalog_manifest_patch(manifest: dict, patch: dict) -> dict:
    updated = deepcopy(manifest)
    catalog_patch = patch.get("catalog") if isinstance(patch, dict) else None
    if not isinstance(catalog_patch, dict):
        return updated
    catalog = dict(updated.get("catalog") or {})
    if isinstance(catalog_patch.get("stac"), dict):
        existing = dict(catalog.get("stac") or {})
        existing.update(catalog_patch["stac"])
        catalog["stac"] = existing
    updated["catalog"] = catalog
    return updated


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
    manifest_patch = {}
    if not errors:
        manifest_patch = _iceberg_manifest_patch(spec, backend_result)
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
        "manifest_patch": manifest_patch,
        "backend_result": backend_result,
    }


def _iceberg_manifest_patch(spec: dict, backend_result: Any) -> dict:
    backend = backend_result if isinstance(backend_result, dict) else {}
    iceberg = {
        "storage_layer": "analytical_lakehouse",
        "object_store": spec.get("object_store"),
        "catalog": spec.get("catalog"),
        "namespace": spec.get("namespace"),
        "table": spec.get("table"),
        "table_identifier": spec.get("table_identifier"),
        "warehouse_uri": spec.get("warehouse_uri"),
        "spatial_engine": spec.get("spatial_engine"),
    }
    if backend.get("snapshot_id") is not None:
        iceberg["snapshot_id"] = backend.get("snapshot_id")
    if isinstance(backend.get("partition"), dict):
        iceberg["partition"] = dict(backend["partition"])
    return {
        "lakehouse": {
            "iceberg": {key: value for key, value in iceberg.items() if value not in ("", None, {})}
        }
    }


def _stac_publish_result(
    spec: dict,
    errors: list[str],
    backend_result: Any,
) -> dict:
    item = spec.get("item") if isinstance(spec.get("item"), dict) else {}
    published_count = 0
    if not errors:
        if isinstance(backend_result, dict) and backend_result.get("published_count") is not None:
            published_count = _safe_int(backend_result.get("published_count"), 1)
        else:
            published_count = 1
    return {
        "valid": not errors,
        "errors": errors,
        "schema": spec.get("schema"),
        "target": spec.get("target"),
        "storage_layer": spec.get("storage_layer"),
        "catalog_uri": spec.get("catalog_uri"),
        "collection": spec.get("collection"),
        "product_id": spec.get("product_id"),
        "item_id": item.get("id"),
        "published_count": published_count,
        "manifest_patch": _stac_manifest_patch(spec, backend_result) if not errors else {},
        "backend_result": backend_result,
    }


def _stac_manifest_patch(spec: dict, backend_result: Any) -> dict:
    backend = backend_result if isinstance(backend_result, dict) else {}
    item = spec.get("item") if isinstance(spec.get("item"), dict) else {}
    stac = {
        "storage_layer": "discovery_catalog",
        "catalog_uri": spec.get("catalog_uri"),
        "collection": spec.get("collection"),
        "item_id": item.get("id"),
        "item_href": backend.get("item_href"),
    }
    return {
        "catalog": {
            "stac": {key: value for key, value in stac.items() if value not in ("", None, {}, [])}
        }
    }


def _sedona_iceberg_result(
    spec: dict,
    errors: list[str],
    backend_result: Any,
) -> dict:
    backend = backend_result if isinstance(backend_result, dict) else {}
    return {
        "valid": not errors,
        "errors": errors,
        "schema": spec.get("schema"),
        "target": spec.get("target"),
        "storage_layer": spec.get("storage_layer"),
        "spatial_engine": spec.get("spatial_engine"),
        "task": spec.get("task"),
        "catalog": spec.get("catalog"),
        "warehouse_uri": spec.get("warehouse_uri"),
        "input_tables": spec.get("input_tables") if isinstance(spec.get("input_tables"), list) else [],
        "output_table": spec.get("output_table"),
        "rows_written": _safe_int(backend.get("rows_written"), 0),
        "snapshot_id": backend.get("snapshot_id"),
        "returncode": _safe_int(backend.get("returncode"), 0) if backend_result is not None else None,
        "stdout": backend.get("stdout", ""),
        "stderr": backend.get("stderr", ""),
        "backend_result": backend_result,
    }


def _table_identifier(catalog: str, namespace: str, table: str) -> str:
    parts = [str(value).strip(".") for value in (catalog, namespace, table) if value]
    return ".".join(parts)


def _authoritative_lakehouse_from_manifest(manifest: dict) -> dict:
    business_output = manifest.get("business_output") or {}
    lakehouse = manifest.get("lakehouse") or {}
    iceberg = lakehouse.get("iceberg") if isinstance(lakehouse, dict) else None
    if not isinstance(iceberg, dict):
        return {}

    authoritative = {
        "target": "iceberg",
        "storage_layer": iceberg.get("storage_layer", "analytical_lakehouse"),
        "object_store": iceberg.get("object_store", "s3"),
        "catalog": iceberg.get("catalog", ""),
        "namespace": iceberg.get("namespace", ""),
        "table": iceberg.get("table", ""),
        "table_identifier": iceberg.get("table_identifier", ""),
        "warehouse_uri": iceberg.get("warehouse_uri", ""),
        "snapshot_id": iceberg.get("snapshot_id", ""),
        "business_output_path": business_output.get("path", ""),
        "business_output_format": business_output.get("format", ""),
        "spatial_engine": iceberg.get("spatial_engine", ""),
    }
    if isinstance(iceberg.get("partition"), dict):
        authoritative["partition"] = dict(iceberg["partition"])
    return {key: value for key, value in authoritative.items() if value not in ("", None, {}, [])}


def _epsg_from_crs(crs: Any) -> int | None:
    if crs is None:
        return None
    match = re.search(r"EPSG[:/]+(?P<epsg>\d+)|EPSG::(?P<urn_epsg>\d+)", str(crs), re.IGNORECASE)
    if not match:
        return None
    value = match.group("epsg") or match.group("urn_epsg")
    return _safe_int(value, 0) or None


def _media_type_for_output(output_format: Any, path: Any) -> str:
    text = f"{output_format or ''} {path or ''}".lower()
    if "geoparquet" in text or "parquet" in text:
        return "application/vnd.apache.parquet"
    if "geojson" in text or str(path).lower().endswith((".geojson", ".json")):
        return "application/geo+json"
    if "tif" in text or str(path).lower().endswith((".tif", ".tiff")):
        return "image/tiff"
    if "csv" in text or str(path).lower().endswith(".csv"):
        return "text/csv"
    return "application/octet-stream"


def _stac_links(catalog_uri: str, collection: str) -> list[dict]:
    links = []
    if catalog_uri and collection:
        links.append({
            "rel": "collection",
            "href": f"{catalog_uri.rstrip('/')}/{collection}.json",
            "type": "application/json",
        })
    return links


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
