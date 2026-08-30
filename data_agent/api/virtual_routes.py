"""Virtual Data Sources CRUD + health-check routes (v13.0)."""

import hashlib
import json
import logging
import math
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.virtual_routes")

_CHONGQING_MAPPING_REPORT = (
    Path(__file__).resolve().parents[2]
    / "benchmarks/standard_mapping_chongqing_v0_1/acceptance_report.json"
)
_CHONGQING_SOURCE_ONBOARDING_REPORT = (
    Path(__file__).resolve().parents[2]
    / "benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_report.json"
)


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _tenant_from_user(user) -> str:
    metadata = user.metadata if isinstance(getattr(user, "metadata", None), dict) else {}
    return str(metadata.get("tenant_id") or "local-dev")


async def vsource_list(request: Request):
    """GET /api/virtual-sources — list virtual sources visible to current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    from ..virtual_sources import list_virtual_sources
    sources = list_virtual_sources(username, include_shared=True)
    return JSONResponse({"sources": sources})


async def vsource_create(request: Request):
    """POST /api/virtual-sources — register a new virtual data source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from ..virtual_sources import VALID_SOURCE_TYPES, create_virtual_source
    stype = body.get("source_type", "")
    if stype not in VALID_SOURCE_TYPES:
        return JSONResponse(
            {"error": f"source_type must be one of {sorted(VALID_SOURCE_TYPES)}"},
            status_code=400,
        )

    result = create_virtual_source(
        source_name=body.get("source_name", ""),
        source_type=stype,
        endpoint_url=body.get("endpoint_url", ""),
        owner_username=username,
        auth_config=body.get("auth_config"),
        query_config=body.get("query_config"),
        schema_mapping=body.get("schema_mapping"),
        default_crs=body.get("default_crs", "EPSG:4326"),
        spatial_extent=body.get("spatial_extent"),
        refresh_policy=body.get("refresh_policy", "on_demand"),
        is_shared=body.get("is_shared", False),
    )
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result, status_code=201)


async def vsource_detail(request: Request):
    """GET /api/virtual-sources/{id} — get virtual source detail."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params.get("id", 0))
    from ..virtual_sources import get_virtual_source
    source = get_virtual_source(source_id, username)
    if not source:
        return JSONResponse({"error": "Source not found"}, status_code=404)
    auth = source.pop("auth_config", {}) or {}
    source["credential_configured"] = bool(
        auth and auth.get("type", "none") != "none"
    )
    return JSONResponse(source)


async def vsource_update(request: Request):
    """PUT /api/virtual-sources/{id} — update a virtual source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from ..virtual_sources import update_virtual_source
    result = update_virtual_source(source_id, username, **body)
    if result.get("status") == "error":
        code = 404 if "not found" in result.get("message", "").lower() else 400
        return JSONResponse({"error": result["message"]}, status_code=code)
    return JSONResponse({"ok": True})


async def vsource_delete(request: Request):
    """DELETE /api/virtual-sources/{id} — delete a virtual source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params.get("id", 0))
    from ..virtual_sources import delete_virtual_source
    result = delete_virtual_source(source_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=404)
    return JSONResponse({"ok": True})


async def vsource_test(request: Request):
    """POST /api/virtual-sources/{id}/test — test connectivity to a virtual source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params.get("id", 0))
    from ..virtual_sources import check_source_health
    result = await check_source_health(source_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=404)
    return JSONResponse(result)


async def vsource_discover(request: Request):
    """POST /api/virtual-sources/discover — discover layers/collections from a remote service."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    source_type = body.get("source_type", "")
    endpoint_url = body.get("endpoint_url", "")
    auth_config = body.get("auth_config") or {}

    if not source_type or not endpoint_url:
        return JSONResponse({"error": "source_type and endpoint_url required"}, status_code=400)
    if source_type == "database":
        return JSONResponse(
            {
                "error": (
                    "Database discovery is only available after product registration at "
                    "/api/virtual-sources/{id}/discover"
                )
            },
            status_code=400,
        )

    from ..connectors import ConnectorRegistry
    connector = ConnectorRegistry.get(source_type)
    if not connector:
        return JSONResponse({"error": f"Unknown source type: {source_type}"}, status_code=400)

    try:
        caps = await connector.get_capabilities(endpoint_url, auth_config)
        return JSONResponse(caps)
    except Exception as e:
        logger.warning("Discover failed for %s %s: %s", source_type, endpoint_url, e)
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


async def vsource_registered_discover(request: Request):
    """POST /api/virtual-sources/{id}/discover — discover a registered source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params.get("id", 0))
    from ..virtual_sources import discover_virtual_source

    result = await discover_virtual_source(source_id, username)
    if result.get("status") == "error":
        message = result.get("message", "Discovery failed")
        status_code = 404 if "not found" in message.casefold() else 502
        return JSONResponse({"error": message}, status_code=status_code)
    return JSONResponse(result)


async def vsource_preview_columns(request: Request):
    """POST /api/virtual-sources/{id}/preview-columns — fetch remote column info."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params["id"])
    try:
        from ..virtual_sources import get_virtual_source, query_virtual_source
        source = get_virtual_source(source_id, username)
        if not source:
            return JSONResponse({"error": "数据源不存在"}, status_code=404)
        if source.get("source_type") == "database":
            snapshot = source.get("discovery_snapshot") or {}
            resources = snapshot.get("resources") or []
            if not resources:
                return JSONResponse(
                    {"error": "请先对已注册数据库执行元数据发现"},
                    status_code=409,
                )
            try:
                body = await request.json()
            except Exception:
                body = {}
            resource_name = str(
                body.get("resource_name")
                or (source.get("query_config") or {}).get("table")
                or ""
            ).strip()
            if not resource_name and len(resources) != 1:
                return JSONResponse(
                    {
                        "metadata_only": True,
                        "columns": [],
                        "resources": [
                            {
                                "name": item.get("name"),
                                "column_count": len(item.get("columns") or []),
                            }
                            for item in resources
                        ],
                    }
                )
            selected = next(
                (
                    item
                    for item in resources
                    if item.get("name") == resource_name
                ),
                resources[0] if len(resources) == 1 else None,
            )
            if selected is None:
                return JSONResponse({"error": "资源不在已发现的 schema 范围内"}, status_code=404)
            return JSONResponse(
                {
                    "metadata_only": True,
                    "resource_name": selected.get("name"),
                    "columns": [
                        {
                            "name": column.get("name"),
                            "dtype": column.get("type"),
                            "nullable": column.get("nullable", True),
                            "samples": [],
                        }
                        for column in selected.get("columns") or []
                    ],
                    "sample_count": 0,
                }
            )
        # Query a small sample to get column info
        gdf = await query_virtual_source(source, limit=5, register_result=False)
        if gdf is None or (hasattr(gdf, '__len__') and len(gdf) == 0):
            return JSONResponse({"columns": [], "sample_count": 0})
        if isinstance(gdf, dict):
            return JSONResponse({"error": gdf.get("message", "查询失败")}, status_code=500)
        columns = []
        for col in gdf.columns:
            sample_vals = gdf[col].dropna().head(3).tolist()
            columns.append({
                "name": col,
                "dtype": str(gdf[col].dtype),
                "samples": [str(v)[:80] for v in sample_vals],
            })
        return JSONResponse({"columns": columns, "sample_count": len(gdf)})
    except Exception as e:
        logger.warning("preview-columns error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


async def standard_mapping_acceptance_summary(request: Request):
    """GET a sanitized summary of the frozen Chongqing real-data benchmark."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        report = json.loads(_CHONGQING_MAPPING_REPORT.read_text(encoding="utf-8"))
        from ..standards_platform.application.acceptance import (
            acceptance_public_summary,
        )
        return JSONResponse(acceptance_public_summary(report))
    except FileNotFoundError:
        return JSONResponse(
            {"error": "重庆真实数据验收报告尚未生成"}, status_code=404,
        )
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("standard mapping acceptance summary error: %s", exc)
        return JSONResponse(
            {"error": "重庆真实数据验收报告不可用"}, status_code=500,
        )


async def chongqing_source_onboarding_summary(request: Request):
    """GET aggregate full-dataset quality and control-ledger registration state."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        report = json.loads(
            _CHONGQING_SOURCE_ONBOARDING_REPORT.read_text(encoding="utf-8")
        )
        target = report["control_plane"]
        source_registered = False
        evidence_registered = False
        metadata = user.metadata if isinstance(getattr(user, "metadata", None), dict) else {}
        if metadata.get("tenant_id") == target["tenant_id"]:
            from ..platform_gateway import (
                PlatformGateway,
                PlatformGatewayError,
            )

            gateway = PlatformGateway()
            try:
                version = gateway.get_resource_version(
                    target["tenant_id"], UUID(target["resource_version_id"])
                )
                source_registered = (
                    version.resource_urn == target["resource_urn"]
                    and version.content_sha256
                    == report["source"]["bundle"]["bundle_sha256"]
                )
                artifact = gateway.get_artifact(
                    target["tenant_id"], UUID(target["evidence_artifact_id"])
                )
                evidence_registered = (
                    artifact.resource_version_id == version.resource_version_id
                    and artifact.manifest.get("evidence_sha256")
                    == report["evidence_sha256"]
                )
            except PlatformGatewayError:
                pass
        from ..standards_platform.application.source_onboarding import (
            source_onboarding_public_summary,
        )

        return JSONResponse(
            source_onboarding_public_summary(
                report,
                source_registered=source_registered,
                evidence_registered=evidence_registered,
            )
        )
    except FileNotFoundError:
        return JSONResponse(
            {"error": "重庆全量源数据审计报告尚未生成"}, status_code=404,
        )
    except (KeyError, OSError, ValueError, TypeError) as exc:
        logger.warning("source onboarding summary error: %s", exc)
        return JSONResponse(
            {"error": "重庆全量源数据审计报告不可用"}, status_code=500,
        )


async def vsource_infer_mapping(request: Request):
    """POST /api/virtual-sources/{id}/infer-mapping — auto-infer schema mapping."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params["id"])
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        standard_version_id = str(body.get("standard_version_id") or "").strip()
        target_table = str(body.get("target_table") or "").strip() or None
        from ..virtual_sources import get_virtual_source, infer_schema_mapping, query_virtual_source
        source = get_virtual_source(source_id, username)
        if not source:
            return JSONResponse({"error": "数据源不存在"}, status_code=404)
        if source.get("source_type") == "database":
            resources = (source.get("discovery_snapshot") or {}).get("resources") or []
            requested_resource = target_table or str(
                (source.get("query_config") or {}).get("table") or ""
            ).strip()
            if requested_resource:
                resources = [
                    item for item in resources if item.get("name") == requested_resource
                ]
            if len(resources) != 1:
                return JSONResponse(
                    {
                        "error": (
                            "数据库语义映射需要指定已发现的 target_table，且该表必须位于授权 schema"
                        )
                    },
                    status_code=400,
                )
            source_columns = resources[0].get("columns") or []
            if standard_version_id:
                from ..standards_platform.application.contracts import SourceFieldProfile
                from ..standards_platform.application.service import (
                    propose_for_released_standard,
                )

                proposal = propose_for_released_standard(
                    standard_version_id=standard_version_id,
                    source_fields=[
                        SourceFieldProfile(
                            name=str(column.get("name")),
                            dtype=str(column.get("type") or "unknown"),
                            samples=(),
                        )
                        for column in source_columns
                    ],
                    target_table=resources[0].get("name"),
                )
                return JSONResponse(proposal)
            mapping = infer_schema_mapping(
                [str(column.get("name")) for column in source_columns]
            )
            return JSONResponse(
                {
                    "schema": "gis-data-agent.canonical-mapping-proposal.v1",
                    "mapping": mapping,
                    "source_profile": "metadata_only",
                    "target_table": resources[0].get("name"),
                    "execution_policy": {
                        "mode": "legacy_canonical_fallback",
                        "automatic_authoritative_write": False,
                        "requires_human_confirmation": True,
                    },
                }
            )
        # A small sample supports dtype evidence and a reproducible source
        # profile hash without performing ingestion or modifying source data.
        gdf = await query_virtual_source(source, limit=5, register_result=False)
        if gdf is None or isinstance(gdf, dict) or len(gdf.columns) == 0:
            return JSONResponse({"mapping": {}, "message": "无法获取远程列名"})
        if standard_version_id:
            from ..standards_platform.application.contracts import SourceFieldProfile
            from ..standards_platform.application.service import (
                propose_for_released_standard,
            )
            source_fields = []
            for column in gdf.columns:
                samples = tuple(
                    str(value)[:120]
                    for value in gdf[column].dropna().head(3).tolist()
                )
                source_fields.append(SourceFieldProfile(
                    name=str(column),
                    dtype=str(gdf[column].dtype),
                    samples=samples,
                ))
            proposal = propose_for_released_standard(
                standard_version_id=standard_version_id,
                source_fields=source_fields,
                target_table=target_table,
            )
            return JSONResponse(proposal)
        mapping = infer_schema_mapping(list(gdf.columns))
        return JSONResponse({
            "schema": "gis-data-agent.canonical-mapping-proposal.v1",
            "mapping": mapping,
            "execution_policy": {
                "mode": "legacy_canonical_fallback",
                "automatic_authoritative_write": False,
                "requires_human_confirmation": True,
            },
        })
    except LookupError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except ValueError as e:
        status = 409 if "must be released" in str(e) else 400
        return JSONResponse({"error": str(e)}, status_code=status)
    except Exception as e:
        logger.warning("infer-mapping error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


async def vsource_update_mapping(request: Request):
    """PUT /api/virtual-sources/{id}/schema-mapping — update schema mapping."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params["id"])
    try:
        body = await request.json()
        schema_mapping = body.get("schema_mapping", {})
        if not isinstance(schema_mapping, dict):
            return JSONResponse({"error": "schema_mapping 须为 JSON 对象"}, status_code=400)
        standard_version_id = str(body.get("standard_version_id") or "").strip()
        if standard_version_id:
            field_bindings = body.get("field_bindings") or []
            if not isinstance(field_bindings, list):
                return JSONResponse(
                    {"error": "field_bindings 须为数组"}, status_code=400,
                )
            from ..standards_platform.application.service import (
                confirm_virtual_source_mapping,
            )
            result = confirm_virtual_source_mapping(
                source_id=source_id,
                owner_username=username,
                standard_version_id=standard_version_id,
                source_profile_hash=body.get("source_profile_hash"),
                schema_mapping=schema_mapping,
                field_bindings=field_bindings,
                confirmed_by=username,
                source_fields=body.get("source_fields"),
                review_decisions=body.get("review_decisions"),
                target_table=body.get("target_table"),
            )
            return JSONResponse(result)
        from ..virtual_sources import update_virtual_source
        result = update_virtual_source(
            source_id, username, schema_mapping=schema_mapping,
        )
        if result.get("status") == "error":
            status = 404 if "not found" in result.get("message", "").lower() else 400
            return JSONResponse({"error": result["message"]}, status_code=status)
        return JSONResponse({"status": "ok", "mapping_count": len(schema_mapping)})
    except LookupError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except ValueError as e:
        status = 409 if "must be released" in str(e) else 400
        return JSONResponse({"error": str(e)}, status_code=status)
    except Exception as e:
        logger.warning("update-mapping error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


async def vsource_quality_preflight(request: Request):
    """Run a read-only, explicitly sampled quality preflight."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params["id"])
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            sample_limit = int(body.get("sample_limit", 200))
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "sample_limit 须为 1 到 1000 的整数"},
                status_code=400,
            )
        if sample_limit < 1 or sample_limit > 1000:
            return JSONResponse(
                {"error": "sample_limit 须为 1 到 1000 的整数"},
                status_code=400,
            )

        from ..standards_platform.application.service import (
            load_confirmed_virtual_source_mapping,
        )
        from ..virtual_sources import get_virtual_source, query_virtual_source

        source = get_virtual_source(source_id, username)
        if not source:
            return JSONResponse({"error": "数据源不存在"}, status_code=404)
        contract = load_confirmed_virtual_source_mapping(
            source_id=source_id,
            owner_username=username,
        )
        frame = await query_virtual_source(
            source,
            limit=sample_limit,
            register_result=False,
        )
        if frame is None:
            return JSONResponse({"error": "数据源预检查询失败"}, status_code=502)
        if isinstance(frame, dict):
            return JSONResponse(
                {"error": frame.get("message", "数据源预检查询失败")},
                status_code=502,
            )
        if not hasattr(frame, "columns") or not hasattr(frame, "__len__"):
            return JSONResponse({"error": "数据源未返回表格数据"}, status_code=502)

        from ..standards_platform.application.contracts import (
            DatasetColumnProfile,
            evaluate_dataset_quality_preflight,
        )

        profiles = []
        geometry_name = getattr(getattr(frame, "geometry", None), "name", None)
        for column in frame.columns:
            series = frame[column]
            null_mask = series.isna()
            invalid_geometry_count = 0
            if column == geometry_name or "geometry" in str(series.dtype).casefold():
                try:
                    populated = series[~null_mask]
                    invalid_geometry_count = int(
                        ((~populated.is_valid) | populated.is_empty).sum(),
                    )
                except (AttributeError, TypeError, ValueError):
                    invalid_geometry_count = 0
            profiles.append(DatasetColumnProfile(
                name=str(column),
                dtype=str(series.dtype),
                row_count=len(frame),
                null_count=int(null_mask.sum()),
                invalid_geometry_count=invalid_geometry_count,
            ))
        result = evaluate_dataset_quality_preflight(
            mapping_contract_id=contract["contract_id"],
            mapping_hash=contract["mapping_hash"],
            source_snapshot_hash=contract["source_snapshot_hash"],
            sample_fingerprint=_sample_frame_fingerprint(frame),
            requested_limit=sample_limit,
            observed_records=len(frame),
            columns=profiles,
            field_bindings=contract["field_bindings"],
        )
        return JSONResponse(result)
    except LookupError as exc:
        status = 409 if "mapping contract" in str(exc) else 404
        return JSONResponse({"error": str(exc)}, status_code=status)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except Exception as exc:
        logger.warning("quality preflight error: %s", exc)
        return JSONResponse({"error": "数据质量预检失败"}, status_code=500)


async def vsource_ingestion_list(request: Request):
    """Return ingestion definitions and recent durable runs for a source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params["id"])
    from ..virtual_sources import get_virtual_source

    if not get_virtual_source(source_id, username):
        return JSONResponse({"error": "数据源不存在"}, status_code=404)
    try:
        from ..data_ingestion import IngestionRepository

        repository = IngestionRepository()
        return JSONResponse(_jsonable({
            "definitions": repository.list_definitions(source_id, username),
            "runs": repository.list_runs(username, source_id=source_id, limit=30),
        }))
    except Exception as exc:
        logger.warning("list ingestion state failed: %s", exc)
        return JSONResponse({"error": str(exc)[:300]}, status_code=503)


async def vsource_ingestion_create(request: Request):
    """Create/update an ArcGIS ingestion definition and optionally run it."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    from ..virtual_sources import get_virtual_source

    source = get_virtual_source(source_id, username)
    if not source:
        return JSONResponse({"error": "数据源不存在"}, status_code=404)
    if source.get("source_type") != "arcgis_rest":
        return JSONResponse(
            {"error": "当前仅 ArcGIS REST 数据源支持此 ingest 执行器"},
            status_code=400,
        )
    try:
        from ..data_ingestion import (
            IngestionDefinitionSpec,
            IngestionRepository,
            safe_table_name,
            start_embedded_ingestion_worker,
        )

        target_mode = body.get("target_mode", "lakehouse_postgis")
        target_name = str(body.get("target_name") or source["source_name"]).strip()
        target_table = body.get("target_table")
        if target_mode != "lakehouse" and not target_table:
            target_table = safe_table_name(target_name, f"arcgis_source_{source_id}")
        if target_mode == "lakehouse":
            target_table = None
        spec = IngestionDefinitionSpec.model_validate({
            "target_name": target_name,
            "target_mode": target_mode,
            "target_table": target_table,
            "schedule_policy": body.get(
                "schedule_policy", source.get("refresh_policy", "on_demand")
            ),
            "write_mode": "full_snapshot",
            "max_records": body.get("max_records", 1_000_000),
            "page_size": body.get("page_size", 2_000),
            "config": body.get("config") or {},
            "enabled": body.get("enabled", True),
        })
        repository = IngestionRepository()
        definition = repository.create_definition(
            source_id, username, _tenant_from_user(user), spec,
        )
        run = None
        if body.get("run_now", True):
            request_key = str(body.get("idempotency_key") or "").strip() or None
            run = repository.enqueue_run(
                definition,
                trigger_type="manual",
                idempotency_key=request_key,
            )
            start_embedded_ingestion_worker()
        return JSONResponse(
            _jsonable({"definition": definition, "run": run}), status_code=201,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("create ingestion definition failed")
        return JSONResponse({"error": str(exc)[:500]}, status_code=503)


async def ingestion_run_trigger(request: Request):
    """Enqueue an idempotent manual run for an ingestion definition."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    definition_id = int(request.path_params["id"])
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        from ..data_ingestion import (
            IngestionRepository,
            start_embedded_ingestion_worker,
        )

        repository = IngestionRepository()
        definition = repository.get_definition(definition_id, username)
        if definition is None:
            return JSONResponse({"error": "Ingestion definition not found"}, status_code=404)
        run = repository.enqueue_run(
            definition,
            trigger_type="manual",
            idempotency_key=str(body.get("idempotency_key") or "").strip() or None,
        )
        start_embedded_ingestion_worker()
        return JSONResponse(_jsonable(run), status_code=202)
    except Exception as exc:
        logger.exception("enqueue ingestion run failed")
        return JSONResponse({"error": str(exc)[:500]}, status_code=503)


async def ingestion_run_detail(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        from ..data_ingestion import IngestionRepository

        run = IngestionRepository().get_run(request.path_params["run_id"], username)
        if run is None:
            return JSONResponse({"error": "Ingestion run not found"}, status_code=404)
        return JSONResponse(_jsonable(run))
    except (ValueError, TypeError):
        return JSONResponse({"error": "Invalid ingestion run ID"}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)[:300]}, status_code=503)


async def ingestion_run_cancel(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        from ..data_ingestion import IngestionRepository

        run = IngestionRepository().request_cancel(
            request.path_params["run_id"], username,
        )
        if run is None:
            return JSONResponse(
                {"error": "运行不存在、已进入提交阶段或已结束"}, status_code=409,
            )
        return JSONResponse(_jsonable(run))
    except (ValueError, TypeError):
        return JSONResponse({"error": "Invalid ingestion run ID"}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)[:300]}, status_code=503)


def _sample_frame_fingerprint(frame) -> str:
    payload = {
        "columns": [str(column) for column in frame.columns],
        "records": [
            [_fingerprint_value(value) for value in row]
            for row in frame.itertuples(index=False, name=None)
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_value(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    wkb_hex = getattr(value, "wkb_hex", None)
    if wkb_hex is not None:
        return {"geometry_wkb": str(wkb_hex)}
    item = getattr(value, "item", None)
    if callable(item):
        try:
            converted = item()
            return (
                _fingerprint_value(converted)
                if converted is not value else str(value)
            )
        except (TypeError, ValueError):
            pass
    return str(value)


def get_virtual_source_routes() -> list:
    """Return Route objects for virtual source endpoints."""
    return [
        Route("/api/virtual-sources", vsource_list, methods=["GET"]),
        Route("/api/virtual-sources", vsource_create, methods=["POST"]),
        Route("/api/virtual-sources/discover", vsource_discover, methods=["POST"]),
        Route(
            "/api/virtual-sources/standard-mapping-acceptance",
            standard_mapping_acceptance_summary,
            methods=["GET"],
        ),
        Route(
            "/api/virtual-sources/chongqing-source-onboarding",
            chongqing_source_onboarding_summary,
            methods=["GET"],
        ),
        Route("/api/virtual-sources/{id:int}", vsource_detail, methods=["GET"]),
        Route("/api/virtual-sources/{id:int}", vsource_update, methods=["PUT"]),
        Route("/api/virtual-sources/{id:int}", vsource_delete, methods=["DELETE"]),
        Route("/api/virtual-sources/{id:int}/test", vsource_test, methods=["POST"]),
        Route(
            "/api/virtual-sources/{id:int}/discover",
            vsource_registered_discover,
            methods=["POST"],
        ),
        Route(
            "/api/virtual-sources/{id:int}/ingestions",
            vsource_ingestion_list,
            methods=["GET"],
        ),
        Route(
            "/api/virtual-sources/{id:int}/ingestions",
            vsource_ingestion_create,
            methods=["POST"],
        ),
        Route(
            "/api/virtual-sources/{id:int}/preview-columns",
            vsource_preview_columns,
            methods=["POST"],
        ),
        Route(
            "/api/virtual-sources/{id:int}/infer-mapping",
            vsource_infer_mapping,
            methods=["POST"],
        ),
        Route(
            "/api/virtual-sources/{id:int}/schema-mapping",
            vsource_update_mapping,
            methods=["PUT"],
        ),
        Route(
            "/api/virtual-sources/{id:int}/quality-preflight",
            vsource_quality_preflight,
            methods=["POST"],
        ),
        Route(
            "/api/ingestions/{id:int}/runs",
            ingestion_run_trigger,
            methods=["POST"],
        ),
        Route(
            "/api/ingestions/runs/{run_id:str}",
            ingestion_run_detail,
            methods=["GET"],
        ),
        Route(
            "/api/ingestions/runs/{run_id:str}/cancel",
            ingestion_run_cancel,
            methods=["POST"],
        ),
    ]
