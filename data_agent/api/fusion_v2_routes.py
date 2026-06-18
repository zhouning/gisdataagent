"""Fusion v2.0 API routes — quality heatmap, lineage, conflicts, temporal preview."""

import json
from pathlib import Path
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


DEFAULT_TWM_MMFE_DIR = (
    Path(__file__).resolve().parents[1]
    / "test_data"
    / "twm_bishan_demo"
    / "mmfe_semantic_fusion"
)


def _json_value(value, default):
    """Return JSON-compatible DB values from either JSONB-decoded objects or text."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        if not value.strip():
            return default
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def _compact_check(check: dict, *, label_zh: str | None = None) -> dict:
    """Return a frontend-friendly diagnostic check record."""
    return {
        "check_id": check.get("check_id", ""),
        "label_zh": label_zh or check.get("name_zh", ""),
        "status": check.get("status", "fail"),
        "severity": check.get("severity", "medium"),
        "required_for_validation": bool(check.get("required_for_validation")),
        "message_zh": check.get("message_zh", ""),
        "evidence": check.get("evidence") or {},
    }


def build_mmfe_readiness_payload(mmfe_dir: str | Path = DEFAULT_TWM_MMFE_DIR) -> dict:
    """Build the fixed local TWM/MMFE semantic-product readiness payload."""
    from .. import fusion_engine

    root = Path(mmfe_dir)
    inputs = fusion_engine.load_semantic_product_okf_inputs(root)
    diagnostic = fusion_engine.diagnose_semantic_product_readiness(
        inputs["manifest"],
        value_domain_audits=inputs["value_domain_audits"],
        standard_sources=inputs["standard_sources"],
        semantic_relations=inputs["semantic_relations"],
        state_input=inputs["state_input"],
        semantic_graph=inputs["semantic_graph"],
        semantic_trace_cards=inputs["semantic_trace_cards"],
    )
    validation = fusion_engine.validate_semantic_product_diagnostic(diagnostic)
    checks = {item["check_id"]: item for item in diagnostic.get("checks", [])}

    core_map = [
        ("standard_source_registry", "标准源"),
        ("value_domain_audit", "值域审计"),
        ("semantic_graph", "语义图谱"),
        ("semantic_trace_cards", "语义溯源"),
        ("twm_state_input", "TWM 状态输入"),
        ("semantic_relations", "语义关系"),
        ("hard_constraints", "硬约束"),
        ("multi_objective_interface", "多目标接口"),
    ]
    production_map = [
        ("production_authority", "生产权威数据"),
        ("production_metadata_contract", "生产元数据合同"),
        ("production_standard_gaps", "生产标准缺口"),
        ("standard_source_ingestion", "标准来源采集"),
    ]

    return {
        "schema": "mmfe.readiness_api.v1",
        "bundle_id": "twm_bishan_demo",
        "bundle_dir": str(root),
        "product_id": diagnostic.get("product_id"),
        "summary": diagnostic.get("summary") or {},
        "capabilities": diagnostic.get("capabilities") or {},
        "core_surfaces": [
            _compact_check(checks[check_id], label_zh=label)
            for check_id, label in core_map
            if check_id in checks
        ],
        "production_gates": [
            _compact_check(checks[check_id], label_zh=label)
            for check_id, label in production_map
            if check_id in checks
        ],
        "top_gaps": diagnostic.get("top_gaps") or [],
        "recommendations_zh": diagnostic.get("recommendations_zh") or [],
        "diagnostic_valid": bool(validation.get("valid")),
        "diagnostic_errors": validation.get("errors") or [],
    }


async def fusion_quality_detail(request: Request):
    """GET /api/fusion/quality/{operation_id} — quality heatmap + explainability."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    operation_id = int(request.path_params["operation_id"])
    try:
        from ..db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return JSONResponse({"error": "Database unavailable"}, status_code=503)
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT explainability_metadata, quality_score, quality_report "
                "FROM agent_fusion_operations WHERE id = :id"
            ), {"id": operation_id}).fetchone()
        if not row:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse({
            "operation_id": operation_id,
            "quality_score": row[1],
            "quality_report": _json_value(row[2], {}),
            "explainability": _json_value(row[0], {}),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def fusion_lineage_detail(request: Request):
    """GET /api/fusion/lineage/{operation_id} — lineage trace."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    operation_id = int(request.path_params["operation_id"])
    try:
        from ..db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return JSONResponse({"error": "Database unavailable"}, status_code=503)
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT source_files, strategy, parameters, duration_s, "
                "temporal_alignment_log, semantic_enhancement_log "
                "FROM agent_fusion_operations WHERE id = :id"
            ), {"id": operation_id}).fetchone()
        if not row:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse({
            "operation_id": operation_id,
            "sources": _json_value(row[0], []),
            "strategy": row[1],
            "parameters": _json_value(row[2], {}),
            "duration_s": row[3],
            "temporal_log": row[4],
            "semantic_log": row[5],
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def fusion_conflicts_detail(request: Request):
    """GET /api/fusion/conflicts/{operation_id} — conflict resolution log."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    operation_id = int(request.path_params["operation_id"])
    try:
        from ..db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return JSONResponse({"error": "Database unavailable"}, status_code=503)
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT conflict_resolution_log FROM agent_fusion_operations WHERE id = :id"
            ), {"id": operation_id}).fetchone()
        if not row:
            return JSONResponse({"error": "Not found"}, status_code=404)
        log_text = row[0] or "{}"
        log_data = _json_value(log_text, {"raw": log_text})
        return JSONResponse({"operation_id": operation_id, "conflict_log": log_data})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def fusion_operations_list(request: Request):
    """GET /api/fusion/operations — list fusion operations with v2 metadata."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)

    limit = int(request.query_params.get("limit", "20"))
    offset = int(request.query_params.get("offset", "0"))

    try:
        from ..db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return JSONResponse({"error": "Database unavailable"}, status_code=503)
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, username, strategy, quality_score, duration_s, created_at, "
                "temporal_alignment_log IS NOT NULL AS has_temporal, "
                "conflict_resolution_log IS NOT NULL AS has_conflict, "
                "explainability_metadata IS NOT NULL AS has_explainability "
                "FROM agent_fusion_operations "
                "WHERE username = :user OR :is_admin "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ), {
                "user": username,
                "is_admin": role == "admin",
                "limit": limit,
                "offset": offset,
            }).fetchall()

        items = []
        for row in rows:
            items.append({
                "id": row[0], "username": row[1], "strategy": row[2],
                "quality_score": row[3], "duration_s": row[4],
                "created_at": str(row[5]),
                "v2_features": {
                    "temporal": bool(row[6]),
                    "conflict": bool(row[7]),
                    "explainability": bool(row[8]),
                },
            })
        return JSONResponse({"items": items, "total": len(items)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def fusion_mmfe_readiness(request: Request):
    """GET /api/fusion/mmfe/readiness — TWM/MMFE semantic-product readiness."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        return JSONResponse(build_mmfe_readiness_payload())
    except FileNotFoundError as e:
        return JSONResponse({"error": f"MMFE bundle not found: {e}"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def fusion_temporal_preview(request: Request):
    """POST /api/fusion/temporal-preview — preview temporal alignment."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    file_path = body.get("file_path", "")
    time_column = body.get("time_column", "")

    if not file_path:
        return JSONResponse({"error": "file_path is required"}, status_code=400)

    try:
        import geopandas as gpd
        from ..fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = gpd.read_file(file_path)

        # Auto-detect temporal columns if not specified
        if not time_column:
            detected = ta.detect_temporal_columns(gdf)
            if not detected:
                return JSONResponse({"error": "No temporal columns detected"}, status_code=400)
            time_column = detected[0]

        # Validate temporal consistency
        standardized = ta.standardize_timestamps(gdf, time_column)
        report = ta.validate_temporal_consistency(standardized)

        return JSONResponse({
            "file_path": file_path,
            "time_column": time_column,
            "consistency": report,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def get_fusion_v2_routes() -> list:
    """Return Starlette routes for Fusion v2.0 endpoints."""
    return [
        Route("/api/fusion/quality/{operation_id:int}", fusion_quality_detail, methods=["GET"]),
        Route("/api/fusion/lineage/{operation_id:int}", fusion_lineage_detail, methods=["GET"]),
        Route("/api/fusion/conflicts/{operation_id:int}", fusion_conflicts_detail, methods=["GET"]),
        Route("/api/fusion/operations", fusion_operations_list, methods=["GET"]),
        Route("/api/fusion/mmfe/readiness", fusion_mmfe_readiness, methods=["GET"]),
        Route("/api/fusion/temporal-preview", fusion_temporal_preview, methods=["POST"]),
    ]
