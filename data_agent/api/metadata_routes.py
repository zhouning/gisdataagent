"""Metadata management API routes."""
import logging
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger(__name__)

_SECRET_METADATA_KEYS = {
    "auth_config",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "access_key",
    "secret_key",
    "credential",
    "credentials",
}


def _redact_metadata(value: Any) -> Any:
    """Keep the catalog read model safe even when source metadata is user supplied."""
    if isinstance(value, dict):
        return {
            str(key): _redact_metadata(item)
            for key, item in value.items()
            if str(key).casefold() not in _SECRET_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_redact_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_metadata(item) for item in value]
    if isinstance(value, str):
        # Avoid returning credentials embedded in a URI while preserving normal URLs.
        return re.sub(r"(://[^:/\s]+:)[^@/\s]+@", r"\1[REDACTED]@", value)
    return value


def _ingestion_mode(technical: dict, operational: dict) -> str:
    storage = technical.get("storage") or {}
    source = operational.get("source") or {}
    backend = str(storage.get("backend") or "").casefold()
    source_type = str(source.get("type") or "").casefold()
    if source_type in {"virtual_source", "virtual", "remote"} or backend in {
        "virtual_source",
        "virtual",
    }:
        return "virtual_source"
    if backend in {"postgis", "postgres", "postgresql"}:
        return "postgis"
    if backend in {"file", "local", "upload", "filesystem"} or storage.get("path"):
        return "file"
    if backend in {"lakehouse", "iceberg", "s3", "minio", "hdfs", "datalake"}:
        return "physical_lake"
    return "registered_asset"


def _as_column(value: Any) -> dict | None:
    """Normalize one column declaration from catalog metadata."""
    if isinstance(value, str):
        return {"name": value, "type": "unknown", "nullable": True}
    if not isinstance(value, dict):
        return None
    name = value.get("name") or value.get("column_name") or value.get("field")
    if not name:
        return None
    return {
        "name": str(name),
        "type": str(value.get("type") or value.get("data_type") or value.get("dtype") or "unknown"),
        "nullable": bool(value.get("nullable") if value.get("nullable") is not None else value.get("is_nullable", True)),
    }


def _physical_resources(asset: dict) -> list[dict]:
    """Project legacy and current physical metadata into the catalog resource model.

    Ingestion pipelines have historically used both ``structure.columns`` and
    ``structure.column_schema``. Database assets may additionally carry a
    ``structure.tables`` inventory. The unified catalog deliberately exposes one
    stable table/field contract to the UI regardless of the producer.
    """
    technical = asset.get("technical_metadata") or {}
    structure = technical.get("structure") or {}
    storage = technical.get("storage") or {}
    raw_tables = structure.get("tables") or technical.get("tables") or []
    if isinstance(raw_tables, dict):
        raw_tables = [raw_tables]
    resources: list[dict] = []
    for raw in raw_tables:
        if isinstance(raw, str):
            raw = {"name": raw}
        if not isinstance(raw, dict):
            continue
        qualified = str(raw.get("qualified_name") or raw.get("table_name") or "")
        if not qualified and raw.get("name"):
            qualified = f"{raw.get('schema') or storage.get('schema') or 'public'}.{raw.get('name')}"
        if not qualified:
            continue
        schema, separator, name = qualified.rpartition(".")
        if not separator:
            schema = str(raw.get("schema") or storage.get("schema") or "public")
            name = qualified
        columns = [_as_column(column) for column in (raw.get("columns") or raw.get("column_schema") or [])]
        resources.append({
            "schema": schema or "public",
            "name": name,
            "qualified_name": qualified,
            "resource_type": str(raw.get("resource_type") or raw.get("type") or "table"),
            "columns": [column for column in columns if column],
            "primary_key": list(raw.get("primary_key") or raw.get("primary_keys") or []),
            "foreign_keys": list(raw.get("foreign_keys") or []),
            "indexes": list(raw.get("indexes") or []),
            "estimated_record_count": raw.get("estimated_record_count") or raw.get("row_count"),
            "comment": raw.get("comment"),
        })

    if resources:
        return sorted(resources, key=lambda item: item["qualified_name"])

    columns_raw = structure.get("columns") or structure.get("column_schema") or technical.get("column_schema") or []
    columns = [_as_column(column) for column in columns_raw]
    columns = [column for column in columns if column]
    table = str(storage.get("postgis_table") or storage.get("table_name") or asset.get("asset_name") or "asset")
    schema, separator, name = table.rpartition(".")
    if not separator:
        schema = str(storage.get("schema") or "public")
        name = table
    if not columns and not (storage.get("postgis_table") or structure.get("resource_count")):
        return []
    return [{
        "schema": schema or "public",
        "name": name,
        "qualified_name": f"{schema or 'public'}.{name}",
        "resource_type": "table" if storage.get("postgis_table") or storage.get("database_name") else "asset",
        "columns": columns,
        "primary_key": list(structure.get("primary_key") or []),
        "foreign_keys": list(structure.get("foreign_keys") or []),
        "indexes": list(structure.get("indexes") or []),
        "estimated_record_count": structure.get("estimated_record_count") or structure.get("row_count") or structure.get("feature_count"),
        "comment": structure.get("comment"),
    }]


def _physical_catalog_item(asset: dict, *, include_resources: bool = False) -> dict:
    technical = asset.get("technical_metadata") or {}
    business = asset.get("business_metadata") or {}
    operational = asset.get("operational_metadata") or {}
    lineage = asset.get("lineage_metadata") or {}
    mode = _ingestion_mode(technical, operational)
    asset_id = str(asset.get("id"))
    resources = _physical_resources(asset)
    item = {
        "asset_id": f"asset:{asset_id}",
        "asset_uuid": asset.get("asset_uuid"),
        "asset_name": asset.get("asset_name"),
        "display_name": asset.get("display_name") or asset.get("asset_name"),
        "asset_kind": "data_asset",
        "source_type": (operational.get("source") or {}).get("type") or mode,
        "ingestion_mode": mode,
        "source_id": (operational.get("source") or {}).get("id"),
        "source_name": (operational.get("source") or {}).get("name"),
        "source_rows_persisted": mode != "virtual_source",
        "technical_metadata": _redact_metadata(technical),
        "business_metadata": _redact_metadata(business),
        "operational_metadata": _redact_metadata(operational),
        "lineage_metadata": _redact_metadata(lineage),
        "resource_count": len(resources),
        "created_at": asset.get("created_at").isoformat() if hasattr(asset.get("created_at"), "isoformat") else asset.get("created_at"),
        "updated_at": asset.get("updated_at").isoformat() if hasattr(asset.get("updated_at"), "isoformat") else asset.get("updated_at"),
    }
    if include_resources:
        item["resources"] = _redact_metadata(resources)
    return item


def _artifact_virtual_resources(source_id: int) -> list[dict]:
    """Return field-complete current catalog evidence for governed virtual sources.

    The virtual-source discovery snapshot remains authoritative when present.
    These artifacts are a checksum-verified fallback for the two Abu Dhabi
    sources, so the global metadata catalog can still drill from a database to
    every table and field when a control-plane read is temporarily unavailable
    or an older discovery snapshot omitted column details.
    """

    source_key = {12: "liveability", 13: "makani"}.get(int(source_id))
    if not source_key:
        return []
    try:
        from ..abu_dhabi_artifact_registry import current_artifact_path

        path = current_artifact_path(source_key, "catalog")
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []

    resources: list[dict] = []
    for raw in catalog.get("resources") or []:
        physical_table = str(raw.get("physical_table") or "")
        if not physical_table:
            continue
        schema, separator, name = physical_table.rpartition(".")
        if not separator:
            schema, name = "public", physical_table
        columns = []
        for raw_field in raw.get("fields") or []:
            technical = raw_field.get("technical_metadata") or {}
            field_name = raw_field.get("physical_field") or raw_field.get("semantic_field")
            if not field_name:
                continue
            columns.append(
                {
                    "name": str(field_name),
                    "type": str(
                        raw_field.get("data_type")
                        or technical.get("data_type")
                        or "unknown"
                    ),
                    "nullable": bool(
                        raw_field.get("nullable")
                        if raw_field.get("nullable") is not None
                        else technical.get("nullable", True)
                    ),
                }
            )
        resources.append(
            {
                "schema": schema or "public",
                "name": name,
                "qualified_name": physical_table,
                "resource_type": str(raw.get("resource_type") or "table"),
                "columns": columns,
                "primary_key": list(raw.get("primary_key") or []),
                "foreign_keys": list(raw.get("foreign_keys") or []),
                "indexes": list(raw.get("indexes") or []),
                "estimated_record_count": raw.get("estimated_record_count"),
                "comment": raw.get("comment") or raw.get("description"),
            }
        )
    return sorted(resources, key=lambda item: item["qualified_name"])


_GOVERNED_VIRTUAL_SOURCE_KEYS = {12: "liveability", 13: "makani"}


def _artifact_semantic_index(source_id: int) -> dict[str, dict[str, Any]]:
    """Load compact business-semantic evidence for one governed source.

    The unified metadata catalog is deliberately the place where technical
    metadata and semantic evidence meet.  This helper only reads the current,
    checksum-registered artifacts; it never grants execution authority to a
    candidate and it does not expose benchmark Gold data.
    """

    source_key = _GOVERNED_VIRTUAL_SOURCE_KEYS.get(int(source_id))
    if not source_key:
        return {}
    try:
        from ..abu_dhabi_artifact_registry import current_artifact_path

        semantic = json.loads(
            current_artifact_path(source_key, "semantic").read_text(encoding="utf-8")
        )
        candidates = json.loads(
            current_artifact_path(source_key, "candidates").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError, KeyError):
        return {}

    index: dict[str, dict[str, Any]] = {}
    for binding in semantic.get("table_bindings") or []:
        if not isinstance(binding, dict):
            continue
        table = str(binding.get("physical_table") or "")
        if not table:
            continue
        index[table] = {
            "semantic_status": binding.get("semantic_coverage_status")
            or binding.get("binding_status"),
            "semantic_asset_id": None,
            "semantic_review_status": None,
            "semantic_execution_eligible": bool(binding.get("execution_eligible") is True),
            "semantic_retrieval_eligible": bool(binding.get("retrieval_eligible") is True),
            "semantic_evidence": {
                "activation_reason": binding.get("activation_reason"),
                "dictionary_status": (binding.get("dictionary_mapping") or {}).get("status"),
                "dictionary_path": (binding.get("dictionary_mapping") or {}).get("dictionary_path"),
            },
            "fields": {},
        }

    for asset in semantic.get("semantic_assets") or []:
        if not isinstance(asset, dict):
            continue
        review_status = str(asset.get("review_status") or "")
        reviewed = review_status.casefold().startswith("reviewed")
        for table in asset.get("physical_tables") or []:
            table_name = str(table or "")
            if not table_name:
                continue
            entry = index.setdefault(table_name, {"fields": {}, "semantic_evidence": {}})
            entry.update(
                {
                    "semantic_asset_id": asset.get("asset_id"),
                    "semantic_review_status": review_status or None,
                    "semantic_execution_eligible": reviewed,
                    "semantic_retrieval_eligible": reviewed,
                    "semantic_status": (
                        "reviewed_business_semantics" if reviewed else "technical_semantics_complete_business_review_pending"
                    ),
                }
            )
            for field in asset.get("fields") or []:
                if not isinstance(field, dict):
                    continue
                physical_field = str(field.get("physical_field") or "")
                if not physical_field:
                    continue
                entry["fields"][physical_field.casefold()] = {
                    "semantic_field": field.get("semantic_field"),
                    "semantic_labels": dict(field.get("labels") or {}),
                    "business_role": field.get("business_role"),
                    "semantic_status": "reviewed_business_semantics",
                    "semantic_execution_eligible": reviewed,
                    "semantic_inference": None,
                }

    for candidate in candidates.get("assets") or []:
        if not isinstance(candidate, dict):
            continue
        table = str(candidate.get("physical_table") or "")
        if not table:
            continue
        entry = index.setdefault(table, {"fields": {}, "semantic_evidence": {}})
        published = candidate.get("published_runtime_asset") or {}
        if not entry.get("semantic_asset_id") and published.get("asset_id"):
            entry["semantic_asset_id"] = published.get("asset_id")
        if not entry.get("semantic_review_status") and published.get("review_status"):
            entry["semantic_review_status"] = published.get("review_status")
        if not entry.get("semantic_status"):
            entry["semantic_status"] = candidate.get("asset_state") or "documentation_gap_review_required"
        if not entry.get("semantic_execution_eligible"):
            entry["semantic_execution_eligible"] = bool(published)
        entry["semantic_retrieval_eligible"] = bool(
            entry.get("semantic_retrieval_eligible") or candidate.get("retrieval_eligible")
        )
        alignment = candidate.get("dictionary_alignment") or {}
        evidence = entry.setdefault("semantic_evidence", {})
        evidence.update(
            {
                "candidate_id": candidate.get("candidate_id"),
                "candidate_state": candidate.get("asset_state"),
                "candidate_state_reason": candidate.get("state_reason"),
                "dictionary_alignment_status": alignment.get("status"),
                "dictionary_matched_field_count": alignment.get("matched_field_count"),
                "dictionary_matched_field_coverage": alignment.get("matched_field_coverage"),
            }
        )
        for field in candidate.get("fields") or []:
            if not isinstance(field, dict):
                continue
            physical_field = str(field.get("physical_field") or "")
            if not physical_field:
                continue
            published_field = field.get("published_semantic") or {}
            existing = entry["fields"].get(physical_field.casefold()) or {}
            entry["fields"][physical_field.casefold()] = {
                **existing,
                "semantic_field": published_field.get("semantic_field") or existing.get("semantic_field"),
                "semantic_labels": dict(published_field.get("labels") or existing.get("semantic_labels") or {}),
                "business_role": published_field.get("business_role") or existing.get("business_role"),
                "semantic_status": existing.get("semantic_status") or (
                    "reviewed_business_semantics" if published_field else "inferred_candidate"
                ),
                "semantic_execution_eligible": bool(existing.get("semantic_execution_eligible") or published_field),
                "semantic_inference": (
                    None
                    if published_field
                    else {
                        "method": "ontology_plus_dictionary_plus_technical_metadata",
                        "confidence": "low",
                        "dictionary_evidence": bool(field.get("dictionary_supported")),
                        "runtime_authority": False,
                        "review_required": True,
                    }
                ),
                "dictionary_evidence": {
                    "supported": bool(field.get("dictionary_supported")),
                    "description_available": bool(field.get("dictionary_description")),
                },
            }
    return index


def _attach_semantic_evidence(resources: list[dict], source_id: int) -> list[dict]:
    """Attach compact table/field semantic evidence to metadata resources."""

    index = _artifact_semantic_index(source_id)
    if not index:
        return resources
    enriched: list[dict] = []
    for resource in resources:
        table = str(resource.get("qualified_name") or "")
        evidence = index.get(table) or {}
        item = {
            **resource,
            "semantic_status": evidence.get("semantic_status"),
            "semantic_asset_id": evidence.get("semantic_asset_id"),
            "semantic_review_status": evidence.get("semantic_review_status"),
            "semantic_execution_eligible": bool(evidence.get("semantic_execution_eligible")),
            "semantic_retrieval_eligible": bool(evidence.get("semantic_retrieval_eligible")),
            "semantic_evidence": _redact_metadata(evidence.get("semantic_evidence") or {}),
        }
        fields = evidence.get("fields") or {}
        enriched_columns = []
        for column in resource.get("columns") or []:
            field = fields.get(str(column.get("name") or "").casefold()) or {}
            enriched_columns.append(
                {
                    **column,
                    "semantic_field": field.get("semantic_field"),
                    "semantic_labels": _redact_metadata(field.get("semantic_labels") or {}),
                    "business_role": field.get("business_role"),
                    "semantic_status": field.get("semantic_status"),
                    "semantic_execution_eligible": bool(field.get("semantic_execution_eligible")),
                    "semantic_inference": _redact_metadata(field.get("semantic_inference")),
                    "dictionary_evidence": _redact_metadata(field.get("dictionary_evidence") or {}),
                }
            )
        item["columns"] = enriched_columns
        enriched.append(item)
    return enriched


def _artifact_virtual_source(source_id: int) -> dict | None:
    """Build a credential-free registry fallback from a current source manifest."""

    source_key = {12: "liveability", 13: "makani"}.get(int(source_id))
    if not source_key:
        return None
    try:
        from ..abu_dhabi_artifact_registry import current_artifact_manifest

        source = current_artifact_manifest(source_key).get("source") or {}
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    database_name = str(source.get("database_name") or "")
    if not database_name:
        return None
    return {
        "id": int(source_id),
        "source_name": database_name,
        "source_type": "database",
        "query_config": {"database": database_name},
        "default_crs": "EPSG:4326",
        "enabled": True,
        "is_shared": True,
        "health_status": "artifact_evidence",
        "discovery_status": "succeeded",
        "discovery_fingerprint": source.get("discovery_fingerprint"),
        "profile_fingerprint": source.get("profile_fingerprint"),
    }


def _field_complete_virtual_resources(source_id: int, discovered: Any) -> tuple[list[dict], str]:
    """Prefer live discovery while filling missing columns from catalog evidence."""

    live_resources = [dict(item) for item in discovered or [] if isinstance(item, dict)]
    artifact_resources = _artifact_virtual_resources(source_id)
    if not live_resources:
        return artifact_resources, (
            "artifact_technical_catalog_evidence" if artifact_resources else "virtual_source_discovery_snapshot"
        )
    if not artifact_resources:
        return live_resources, "virtual_source_discovery_snapshot"

    by_name = {
        str(item.get("qualified_name") or f"{item.get('schema') or 'public'}.{item.get('name') or ''}"):
        item
        for item in artifact_resources
    }
    enriched = []
    used_artifact_fields = False
    for raw in live_resources:
        qualified = str(
            raw.get("qualified_name")
            or (
                f"{raw.get('schema') or 'public'}.{raw.get('name')}"
                if raw.get("name")
                else ""
            )
        )
        fallback = by_name.get(qualified) or {}
        item = {**fallback, **raw}
        if not raw.get("columns") and fallback.get("columns"):
            item["columns"] = fallback["columns"]
            used_artifact_fields = True
        item.setdefault("qualified_name", qualified)
        enriched.append(item)
    return enriched, (
        "virtual_source_discovery_with_catalog_field_fallback"
        if used_artifact_fields
        else "virtual_source_discovery_snapshot"
    )


def _virtual_catalog_item(source: dict, discovery: dict | None, *, include_resources: bool = False) -> dict:
    snapshot = (discovery or {}).get("discovery_snapshot") or {}
    profile = (discovery or {}).get("profile_snapshot") or {}
    source_id = int(source.get("id"))
    resources, metadata_origin = _field_complete_virtual_resources(
        source_id, snapshot.get("resources") or []
    )
    resources = _attach_semantic_evidence(resources, source_id)
    source_name = str(source.get("source_name") or f"virtual-source-{source_id}")
    database = snapshot.get("database_name") or (source.get("query_config") or {}).get("database")
    technical = {
        "storage": {
            "backend": "virtual_source",
            "format": "database",
            "database_name": database,
            "source_type": source.get("source_type"),
        },
        "structure": {
            "schema_count": len({str(item.get("schema") or "public") for item in resources}),
            "resource_count": len(resources),
            "field_count": profile.get("field_count") or sum(len(item.get("columns") or []) for item in resources),
            "geometry_resource_count": profile.get("geometry_resource_count") or 0,
        },
        "spatial": {"crs": source.get("default_crs") or "EPSG:4326", "extent": source.get("spatial_extent")},
        "discovery": {
            "status": (discovery or {}).get("discovery_status") or source.get("discovery_status", "not_run"),
            "fingerprint": (discovery or {}).get("discovery_fingerprint") or source.get("discovery_fingerprint"),
            "profile_fingerprint": (discovery or {}).get("profile_fingerprint") or source.get("profile_fingerprint"),
            "last_discovery_at": (discovery or {}).get("last_discovery_at") or source.get("last_discovery_at"),
            "metadata_origin": metadata_origin,
        },
    }
    operational = {
        "source": {"type": "virtual_source", "id": source_id, "name": source_name},
        "ingestion": {"mode": "virtual_source", "source_rows_persisted": False},
        "health": {"status": source.get("health_status") or "unknown", "enabled": source.get("enabled", True)},
    }
    item = {
        "asset_id": f"virtual-source:{source_id}",
        "asset_uuid": None,
        "asset_name": source_name,
        "display_name": database or source_name,
        "asset_kind": "virtual_source",
        "source_type": source.get("source_type") or "database",
        "ingestion_mode": "virtual_source",
        "source_id": source_id,
        "source_name": source_name,
        "source_rows_persisted": False,
        "technical_metadata": _redact_metadata(technical),
        "business_metadata": _redact_metadata({"classification": {"domain": "virtual_source"}, "semantic": {"description": "Metadata-only virtual source"}}),
        "operational_metadata": _redact_metadata(operational),
        "lineage_metadata": _redact_metadata({"upstream": {"source_name": source_name, "source_id": source_id, "mode": "virtual_source"}}),
        "created_at": source.get("created_at"),
        "updated_at": source.get("updated_at"),
        "resource_count": len(resources),
        "metadata_origin": metadata_origin,
        "profile": _redact_metadata(profile),
    }
    if include_resources:
        item["resources"] = _redact_metadata(resources)
    return item


def _unified_catalog_items(user_identifier: str, query: str = "", *, include_resources: bool = False) -> list[dict]:
    from ..metadata_manager import MetadataManager
    from ..virtual_sources import get_virtual_source_discovery, list_virtual_sources

    manager = MetadataManager()
    physical = manager.search_assets(query=query or None, limit=500)
    items = [_physical_catalog_item(item, include_resources=include_resources) for item in physical]
    sources = list_virtual_sources(user_identifier, include_shared=True)
    visible_source_ids = {int(source["id"]) for source in sources if source.get("id") is not None}
    for source_id in (12, 13):
        if source_id not in visible_source_ids:
            fallback = _artifact_virtual_source(source_id)
            if fallback:
                sources.append(fallback)
    for source in sources:
        discovery = get_virtual_source_discovery(int(source["id"]), user_identifier)
        items.append(_virtual_catalog_item(source, discovery, include_resources=include_resources))
    return items


def _metadata_query_match(item: dict, query: str) -> bool:
    needle = query.strip().casefold()
    if not needle:
        return True
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("asset_id", "asset_name", "display_name", "source_name", "source_type", "ingestion_mode")
    )
    return needle in haystack.casefold()


def _parse_catalog_key(asset_key: str) -> tuple[str, int] | None:
    prefix, separator, value = str(asset_key or "").partition(":")
    if not separator or prefix not in {"asset", "virtual-source"}:
        return None
    try:
        return prefix, int(value)
    except (TypeError, ValueError):
        return None


async def _api_metadata_search(request: Request):
    """GET /api/metadata/search?q=...&region=...&domain=...&source_type=..."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..metadata_manager import MetadataManager
    mgr = MetadataManager()

    q = request.query_params.get("q")
    filters = {}
    for key in ("region", "domain", "source_type"):
        val = request.query_params.get(key)
        if val:
            filters[key] = val

    limit = int(request.query_params.get("limit", "50"))
    results = mgr.search_assets(query=q, filters=filters or None, limit=limit)
    return JSONResponse({"assets": results, "total": len(results)})


async def _api_metadata_detail(request: Request):
    """GET /api/metadata/{asset_id}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..metadata_manager import MetadataManager
    mgr = MetadataManager()

    asset_id = int(request.path_params["asset_id"])
    layers_param = request.query_params.get("layers")
    layers = layers_param.split(",") if layers_param else None
    result = mgr.get_metadata(asset_id, layers=layers)
    if not result:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(result)


async def _api_metadata_update(request: Request):
    """PUT /api/metadata/{asset_id}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..metadata_manager import MetadataManager
    mgr = MetadataManager()

    asset_id = int(request.path_params["asset_id"])
    body = await request.json()
    ok = mgr.update_metadata(
        asset_id,
        technical=body.get("technical"),
        business=body.get("business"),
        operational=body.get("operational"),
        lineage=body.get("lineage"),
    )
    return JSONResponse({"updated": ok})


async def _api_metadata_lineage(request: Request):
    """GET /api/metadata/{asset_id}/lineage"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..metadata_manager import MetadataManager
    mgr = MetadataManager()

    asset_id = int(request.path_params["asset_id"])
    lineage = mgr.get_lineage(asset_id)
    return JSONResponse(lineage)


async def _api_unified_metadata_list(request: Request):
    """GET /api/metadata/unified — one catalog for all ingestion modes."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)
    try:
        limit = max(1, min(int(request.query_params.get("limit", "50")), 200))
        offset = max(0, int(request.query_params.get("offset", "0")))
    except ValueError:
        return JSONResponse({"error": "invalid pagination"}, status_code=400)
    query = request.query_params.get("q", "").strip()
    items = [item for item in _unified_catalog_items(username, query=query) if _metadata_query_match(item, query)]
    ingestion_mode = request.query_params.get("ingestion_mode", "").strip().casefold()
    source_type = request.query_params.get("source_type", "").strip().casefold()
    region = request.query_params.get("region", "").strip().casefold()
    domain = request.query_params.get("domain", "").strip().casefold()
    source_id = request.query_params.get("source_id", "").strip()
    if ingestion_mode:
        items = [item for item in items if str(item.get("ingestion_mode") or "").casefold() == ingestion_mode]
    if source_type:
        items = [item for item in items if str(item.get("source_type") or "").casefold() == source_type]
    if region:
        items = [
            item for item in items
            if region in {
                str(tag).casefold()
                for tag in ((item.get("business_metadata") or {}).get("geography") or {}).get("region_tags") or []
            }
        ]
    if domain:
        items = [
            item for item in items
            if str((((item.get("business_metadata") or {}).get("classification") or {}).get("domain") or "")).casefold() == domain
        ]
    if source_id:
        items = [item for item in items if str(item.get("source_id") or "") == source_id]
    items.sort(key=lambda item: (str(item.get("display_name") or item.get("asset_name") or "").casefold(), str(item.get("asset_id"))))
    total = len(items)
    return JSONResponse(
        {
            "schema": "gda.unified-metadata-catalog.v1",
            "items": items[offset : offset + limit],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
            "supported_ingestion_modes": ["physical_lake", "virtual_source", "file", "postgis", "database", "registered_asset"],
            "source_rows_persisted_semantics": "per_asset",
        }
    )


async def _api_unified_metadata_detail(request: Request):
    """GET /api/metadata/unified/{asset_key} — detail with a stable catalog key."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)
    parsed = _parse_catalog_key(request.path_params.get("asset_key", ""))
    if not parsed:
        return JSONResponse({"error": "invalid_asset_key"}, status_code=400)
    prefix, identifier = parsed
    if prefix == "virtual-source":
        from ..virtual_sources import get_virtual_source, get_virtual_source_discovery

        source = get_virtual_source(identifier, username) or _artifact_virtual_source(identifier)
        if not source:
            return JSONResponse({"error": "Not found"}, status_code=404)
        item = _virtual_catalog_item(source, get_virtual_source_discovery(identifier, username), include_resources=True)
        return JSONResponse({"schema": "gda.unified-metadata-catalog.v1", "item": item})
    from ..metadata_manager import MetadataManager

    manager = MetadataManager()
    item = next(
        (candidate for candidate in _unified_catalog_items(username, include_resources=True) if candidate.get("asset_id") == f"asset:{identifier}"),
        None,
    )
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    # Keep the existing metadata manager as the authority for the four layers.
    layers = manager.get_metadata(identifier)
    if layers:
        item.update({f"{key}_metadata": _redact_metadata(value or {}) for key, value in layers.items()})
    return JSONResponse({"schema": "gda.unified-metadata-catalog.v1", "item": item})


async def _api_unified_metadata_refresh(request: Request):
    """POST /api/metadata/unified/{asset_key}/refresh — refresh metadata only."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)
    parsed = _parse_catalog_key(request.path_params.get("asset_key", ""))
    if not parsed:
        return JSONResponse({"error": "invalid_asset_key"}, status_code=400)
    prefix, identifier = parsed
    if prefix != "virtual-source":
        return JSONResponse(
            {"status": "not_required", "asset_id": f"asset:{identifier}", "message": "physical asset metadata is managed by its ingestion/catalog pipeline"}
        )
    from ..virtual_sources import discover_virtual_source

    result = await discover_virtual_source(identifier, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result.get("message", "metadata_refresh_failed")}, status_code=502)
    return JSONResponse(
        {
            "schema": "gda.unified-metadata-catalog.v1",
            "status": "refreshed",
            "asset_id": f"virtual-source:{identifier}",
            "source_rows_persisted": False,
            "discovery": _redact_metadata(result),
        }
    )


def get_metadata_routes():
    return [
        Route("/api/metadata/unified", endpoint=_api_unified_metadata_list, methods=["GET"]),
        Route("/api/metadata/unified/{asset_key:path}/refresh", endpoint=_api_unified_metadata_refresh, methods=["POST"]),
        Route("/api/metadata/unified/{asset_key:path}", endpoint=_api_unified_metadata_detail, methods=["GET"]),
        Route("/api/metadata/search", endpoint=_api_metadata_search, methods=["GET"]),
        Route("/api/metadata/{asset_id:int}", endpoint=_api_metadata_detail, methods=["GET"]),
        Route("/api/metadata/{asset_id:int}", endpoint=_api_metadata_update, methods=["PUT"]),
        Route("/api/metadata/{asset_id:int}/lineage", endpoint=_api_metadata_lineage, methods=["GET"]),
    ]
