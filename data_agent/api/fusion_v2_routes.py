"""Fusion v2.0 API routes — quality heatmap, lineage, conflicts, temporal preview."""

import json
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


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
        meta = json.loads(row[0]) if row[0] else {}
        return JSONResponse({
            "operation_id": operation_id,
            "quality_score": row[1],
            "quality_report": json.loads(row[2]) if row[2] else {},
            "explainability": meta,
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
            "sources": json.loads(row[0]) if row[0] else [],
            "strategy": row[1],
            "parameters": json.loads(row[2]) if row[2] else {},
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
        try:
            log_data = json.loads(log_text)
        except (json.JSONDecodeError, TypeError):
            log_data = {"raw": log_text}
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
        Route("/api/fusion/temporal-preview", fusion_temporal_preview, methods=["POST"]),
    ]
