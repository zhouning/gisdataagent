"""Data Classification & Anonymization REST API routes (v15.8)."""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request


async def _api_classification_summary(request: Request):
    """GET /api/classification/summary — list all assets with sensitivity labels."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        from ..db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return JSONResponse({"error": "database unavailable"}, status_code=503)
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, asset_name,
                       business_metadata->'classification'->>'sensitivity' AS sensitivity,
                       business_metadata->'classification'->>'category' AS category,
                       business_metadata->'semantic'->>'description' AS description,
                       technical_metadata->>'feature_count' AS feature_count,
                       technical_metadata->>'crs' AS crs,
                       lineage_metadata->'upstream'->>'transform_tool' AS transform_tool,
                       lineage_metadata->'upstream'->'source_tables' AS source_tables
                FROM agent_data_assets
                WHERE asset_name LIKE 'cq_%'
                ORDER BY
                  CASE business_metadata->'classification'->>'sensitivity'
                    WHEN 'secret' THEN 1 WHEN 'restricted' THEN 2
                    WHEN 'confidential' THEN 3 WHEN 'internal' THEN 4
                    WHEN 'public' THEN 5 ELSE 6
                  END, asset_name
            """)).fetchall()
            assets = []
            for r in rows:
                assets.append({
                    "id": r[0], "name": r[1],
                    "sensitivity": r[2] or "unclassified",
                    "category": r[3] or "",
                    "description": r[4] or "",
                    "feature_count": r[5],
                    "crs": r[6],
                    "derived_from": r[7],
                    "source_tables": r[8],
                })
            # Summary counts
            from collections import Counter
            level_counts = Counter(a["sensitivity"] for a in assets)
            return JSONResponse({
                "assets": assets,
                "summary": dict(level_counts),
                "total": len(assets),
            })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_classification_anonymize(request: Request):
    """POST /api/classification/anonymize — trigger grid anonymization."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    role = user.get("role", "viewer")
    if role not in ("admin", "analyst"):
        return JSONResponse({"error": "admin or analyst role required"}, status_code=403)
    try:
        body = await request.json()
        source_table = body.get("source_table", "")
        output_table = body.get("output_table", "")
        level = body.get("level", "L3")
        keep_attrs = body.get("keep_attrs", ["dlmc", "tbmj"])
        data_type = body.get("data_type", "polygon")

        if not source_table or not output_table:
            return JSONResponse({"error": "source_table and output_table required"}, status_code=400)

        from ..user_context import current_user_id
        current_user_id.set(user.get("username", "system"))

        if data_type == "point":
            from ..grid_anonymize import poi_grid_aggregate_pg
            result = poi_grid_aggregate_pg(
                source_table=source_table,
                output_table=output_table,
                category_column=body.get("category_column", "类型"),
                level=level,
                k_anonymity=body.get("k_anonymity", 5),
                top_k_categories=body.get("top_k_categories", 5),
                register_lineage=True,
            )
        else:
            from ..grid_anonymize import grid_anonymize_pg
            result = grid_anonymize_pg(
                source_table=source_table,
                output_table=output_table,
                level=level,
                keep_attrs=keep_attrs,
                agg_strategy=body.get("agg_strategy", "area_weighted"),
                k_anonymity=body.get("k_anonymity", 5),
                dp_epsilon=body.get("dp_epsilon"),
                dp_numeric_fields=body.get("dp_numeric_fields"),
                random_offset=True,
                register_lineage=True,
            )

        status_code = 200 if result.get("status") == "ok" else 500
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_classification_verify(request: Request):
    """POST /api/classification/verify — run anonymization verification."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
        source_table = body.get("source_table", "")
        output_table = body.get("output_table", "")
        if not source_table or not output_table:
            return JSONResponse({"error": "source_table and output_table required"}, status_code=400)

        from ..grid_anonymize import verify_anonymization
        result = verify_anonymization(
            source_table=source_table,
            output_table=output_table,
            sample_size=body.get("sample_size", 30),
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def get_classification_routes() -> list[Route]:
    return [
        Route("/api/classification/summary", _api_classification_summary, methods=["GET"]),
        Route("/api/classification/anonymize", _api_classification_anonymize, methods=["POST"]),
        Route("/api/classification/verify", _api_classification_verify, methods=["POST"]),
    ]
