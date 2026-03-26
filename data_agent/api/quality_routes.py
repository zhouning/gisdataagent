"""Quality Rules + Trends + Resource Overview REST routes (v14.5)."""

import logging
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.quality_routes")


async def qrule_list(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    from ..quality_rules import list_rules
    rules = list_rules(username, include_shared=True)
    return JSONResponse({"rules": rules})


async def qrule_create(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    from ..quality_rules import create_rule
    result = create_rule(
        rule_name=body.get("rule_name", ""),
        rule_type=body.get("rule_type", ""),
        config=body.get("config", {}),
        owner=username,
        standard_id=body.get("standard_id"),
        severity=body.get("severity", "HIGH"),
        is_shared=body.get("is_shared", False),
    )
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result, status_code=201)


async def qrule_detail(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    rule_id = int(request.path_params.get("id", 0))
    from ..quality_rules import get_rule
    rule = get_rule(rule_id, username)
    if not rule:
        return JSONResponse({"error": "Rule not found"}, status_code=404)
    return JSONResponse(rule)


async def qrule_update(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    rule_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    from ..quality_rules import update_rule
    result = update_rule(rule_id, username, **body)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse({"ok": True})


async def qrule_delete(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    rule_id = int(request.path_params.get("id", 0))
    from ..quality_rules import delete_rule
    result = delete_rule(rule_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=404)
    return JSONResponse({"ok": True})


async def qrule_execute(request: Request):
    """POST /api/quality-rules/execute — execute rules against a file."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    file_path = body.get("file_path", "")
    rule_ids = body.get("rule_ids")
    if not file_path:
        return JSONResponse({"error": "file_path required"}, status_code=400)
    from ..quality_rules import execute_rules_batch
    result = execute_rules_batch(file_path, rule_ids=rule_ids, owner=username)
    return JSONResponse(result)


async def quality_trends(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    asset_name = request.query_params.get("asset_name")
    days = int(request.query_params.get("days", "30"))
    from ..quality_rules import get_trends
    trends = get_trends(asset_name=asset_name, days=days)
    return JSONResponse({"trends": trends})


async def resource_overview(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..quality_rules import get_resource_overview
    result = get_resource_overview()
    return JSONResponse(result)


async def qc_report_generate(request: Request):
    """POST /api/reports/generate — generate a QC report from section data."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    section_data = body.get("section_data", {})
    metadata = body.get("metadata")
    charts = body.get("charts")
    images = body.get("images")

    try:
        from ..report_generator import generate_qc_report
        path = generate_qc_report(
            section_data=section_data,
            metadata=metadata,
            charts=charts,
            images=images,
        )
        return JSONResponse({"path": path, "status": "ok"})
    except Exception as e:
        logger.exception("QC report generation failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def defect_taxonomy_list(request: Request):
    """GET /api/defect-taxonomy — list all defect types."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from ..standard_registry import DefectTaxonomy
    return JSONResponse({
        "defects": DefectTaxonomy.list_summary(),
        "categories": [{"id": c.id, "name": c.name, "description": c.description}
                       for c in DefectTaxonomy.all_categories()],
        "severity_levels": [{"code": s.code, "name": s.name, "weight": s.weight}
                           for s in DefectTaxonomy.all_severity_levels()],
    })


async def qc_reviews_list(request: Request):
    """GET /api/qc/reviews — list QC review items."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    status_filter = request.query_params.get("status", "")
    try:
        from ..db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        sql = "SELECT * FROM agent_qc_reviews"
        params = {}
        if status_filter:
            sql += " WHERE status = :s"
            params["s"] = status_filter
        sql += " ORDER BY created_at DESC LIMIT 100"
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
            return JSONResponse({"reviews": [dict(r) for r in rows]})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def qc_reviews_create(request: Request):
    """POST /api/qc/reviews — create a QC review item."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    try:
        from ..db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO agent_qc_reviews
                    (workflow_run_id, file_path, defect_code, defect_description,
                     severity, assigned_to, created_by)
                VALUES (:wrid, :fp, :dc, :dd, :sev, :at, :cb)
                RETURNING id
            """), {
                "wrid": body.get("workflow_run_id"),
                "fp": body.get("file_path", ""),
                "dc": body.get("defect_code", ""),
                "dd": body.get("defect_description", ""),
                "sev": body.get("severity", "B"),
                "at": body.get("assigned_to", ""),
                "cb": username,
            })
            row = result.fetchone()
            conn.commit()
            return JSONResponse({"id": row[0]}, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def qc_reviews_update(request: Request):
    """PUT /api/qc/reviews/{id} — update review status (approve/reject/fix)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    review_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    try:
        from ..db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        new_status = body.get("status", "")
        with engine.connect() as conn:
            sets = ["updated_at = NOW()"]
            params = {"id": review_id}
            if new_status:
                sets.append("status = :s")
                params["s"] = new_status
            if body.get("review_comment"):
                sets.append("review_comment = :rc")
                params["rc"] = body["review_comment"]
            if body.get("fix_description"):
                sets.append("fix_description = :fd")
                params["fd"] = body["fix_description"]
            if body.get("reviewer"):
                sets.append("reviewer = :rv")
                params["rv"] = body["reviewer"]
            if new_status in ("approved", "rejected"):
                sets.append("resolved_at = NOW()")

            conn.execute(text(
                f"UPDATE agent_qc_reviews SET {', '.join(sets)} WHERE id = :id"
            ), params)
            conn.commit()
            return JSONResponse({"id": review_id, "status": new_status})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def qc_dashboard(request: Request):
    """QC dashboard statistics — aggregated overview for monitoring."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..workflow_engine import list_qc_templates
    templates = list_qc_templates()

    review_stats = {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "fixed": 0}
    workflow_stats = {"total": 0, "running": 0, "completed": 0, "failed": 0, "sla_violated": 0}
    recent_reviews = []

    try:
        from ..database_tools import _get_engine
        from sqlalchemy import text
        engine = _get_engine()
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status='fixed' THEN 1 ELSE 0 END) "
                "FROM agent_qc_reviews"
            )).fetchone()
            review_stats = {
                "total": row[0] or 0, "pending": row[1] or 0,
                "approved": row[2] or 0, "rejected": row[3] or 0, "fixed": row[4] or 0,
            }

            wrow = conn.execute(text(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN status='running' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN sla_violated THEN 1 ELSE 0 END) "
                "FROM agent_workflow_runs"
            )).fetchone()
            workflow_stats = {
                "total": wrow[0] or 0, "running": wrow[1] or 0,
                "completed": wrow[2] or 0, "failed": wrow[3] or 0, "sla_violated": wrow[4] or 0,
            }

            rows = conn.execute(text(
                "SELECT id, file_path, defect_code, severity, status, created_at "
                "FROM agent_qc_reviews ORDER BY created_at DESC LIMIT 10"
            )).fetchall()
            for r in rows:
                recent_reviews.append({
                    "id": r[0], "file_path": r[1], "defect_code": r[2],
                    "severity": r[3], "status": r[4], "created_at": str(r[5]),
                })
    except Exception:
        pass

    alert_stats = {"total_rules": 0, "enabled_rules": 0, "recent_alerts": 0}
    try:
        from ..database_tools import _get_engine
        from sqlalchemy import text
        engine = _get_engine()
        with engine.connect() as conn:
            r1 = conn.execute(text("SELECT COUNT(*), SUM(CASE WHEN enabled THEN 1 ELSE 0 END) FROM agent_alert_rules")).fetchone()
            alert_stats["total_rules"] = r1[0] or 0
            alert_stats["enabled_rules"] = r1[1] or 0
            r2 = conn.execute(text("SELECT COUNT(*) FROM agent_alert_history WHERE created_at > NOW() - INTERVAL '24 hours'")).fetchone()
            alert_stats["recent_alerts"] = r2[0] or 0
    except Exception:
        pass

    return JSONResponse({
        "templates": {"count": len(templates), "items": templates},
        "reviews": review_stats,
        "workflows": workflow_stats,
        "alerts": alert_stats,
        "recent_reviews": recent_reviews,
    })


def get_quality_routes() -> list:
    return [
        Route("/api/quality-rules", qrule_list, methods=["GET"]),
        Route("/api/quality-rules", qrule_create, methods=["POST"]),
        Route("/api/quality-rules/execute", qrule_execute, methods=["POST"]),
        Route("/api/quality-rules/{id:int}", qrule_detail, methods=["GET"]),
        Route("/api/quality-rules/{id:int}", qrule_update, methods=["PUT"]),
        Route("/api/quality-rules/{id:int}", qrule_delete, methods=["DELETE"]),
        Route("/api/quality-trends", quality_trends, methods=["GET"]),
        Route("/api/resource-overview", resource_overview, methods=["GET"]),
        Route("/api/reports/generate", qc_report_generate, methods=["POST"]),
        Route("/api/defect-taxonomy", defect_taxonomy_list, methods=["GET"]),
        Route("/api/qc/reviews", qc_reviews_list, methods=["GET"]),
        Route("/api/qc/reviews", qc_reviews_create, methods=["POST"]),
        Route("/api/qc/reviews/{id:int}", qc_reviews_update, methods=["PUT"]),
        Route("/api/qc/dashboard", qc_dashboard, methods=["GET"]),
    ]
