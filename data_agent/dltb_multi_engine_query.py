"""Unified DLTB question route across PostGIS, lake SQL and diagnostics."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .dltb_llm_query import _append_audit, query_dltb_with_llm
from .dltb_vertical_demo import DLTBVerticalDemo
from .offline_ingest import _utc_now

QUERY_ENGINES = {"postgis", "lake", "geopandas"}


def _current_catalog_source(projection_file: Path, projection: dict[str, Any]) -> dict[str, Any]:
    catalog_path = projection_file.parent.parent / "catalog.json"
    if not catalog_path.exists():
        raise ValueError("semantic projection is not registered in the active catalog")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    source = next(
        (
            item
            for item in (catalog.get("sources") or [])
            if item.get("projection_id") == projection.get("projection_id")
        ),
        None,
    )
    if not source:
        raise ValueError("requested semantic projection is not the active DLTB catalog version")
    return source


def query_dltb(
    projection_path: str | Path,
    question: str,
    *,
    execution_engine: str = "postgis",
    limit: int = 100,
) -> dict[str, Any]:
    """Execute one natural-language question with explicit provenance."""

    engine = str(execution_engine or "postgis").strip().casefold()
    if engine not in QUERY_ENGINES:
        raise ValueError("execution_engine must be postgis, lake, or geopandas")
    projection_file = Path(projection_path).expanduser().resolve()
    if projection_file.is_dir():
        projection_file = projection_file / "semantic_projection.json"
    projection = DLTBVerticalDemo.load_projection(projection_file)
    source = _current_catalog_source(projection_file, projection)

    if engine == "geopandas":
        result = query_dltb_with_llm(
            projection_file,
            question,
            limit=limit,
        )
        result["execution_engine"] = "geopandas"
        result["dialect"] = "semantic_ast"
        result["fallback_used"] = False
        result["diagnostic_only"] = True
        result["executor"]["diagnostic_only"] = True
        return result

    binding = (source.get("execution_bindings") or {}).get(engine)
    if not isinstance(binding, dict):
        raise ValueError(
            f"semantic projection has no {engine} execution binding; "
            "publish the governed product before querying"
        )

    from .nl2sql_executor import run_nl2semantic2sql
    from .semantic_layer import current_offline_semantic_catalog_path

    catalog_path = projection_file.parent.parent / "catalog.json"
    catalog_token = current_offline_semantic_catalog_path.set(str(catalog_path))
    try:
        raw_result = run_nl2semantic2sql(question, execution_engine=engine)
    finally:
        current_offline_semantic_catalog_path.reset(catalog_token)
    try:
        execution_result = json.loads(raw_result)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("NL2Semantic2SQL returned invalid JSON") from exc
    if execution_result.get("status") not in {"ok", "succeeded"}:
        error = execution_result.get("error") or execution_result.get("execution", {}).get("error")
        raise RuntimeError(f"NL2Semantic2SQL failed: {error or 'unknown error'}")

    executed = execution_result.get("execution") or {}
    rows = executed.get("data") or []
    query_id = str(uuid.uuid4())
    result = {
        "status": "succeeded",
        "query_id": query_id,
        "query_type": "nl2semantic2sql",
        "question": str(question).strip(),
        "answer": f"智能问数执行完成，共返回 {len(rows)} 行结果。",
        "rows": rows,
        "sql": execution_result.get("sql"),
        "raw_sql": execution_result.get("raw_sql"),
        "semantic": execution_result.get("semantic") or {},
        "llm": execution_result.get("llm") or {},
        "execution_engine": engine,
        "dialect": execution_result.get("dialect"),
        "fallback_used": False,
        "diagnostic_only": False,
        "production_eligible": bool(projection.get("production_eligible")),
        "executor": {
            "engine": engine,
            "dialect": executed.get("dialect") or execution_result.get("dialect"),
            "source_kind": (
                "governed_postgis_projection" if engine == "postgis" else "governed_geoparquet"
            ),
            "projection_id": projection.get("projection_id"),
            "binding": binding,
            "source_bindings": executed.get("source_bindings") or [],
            "row_count": len(rows),
            "status": "succeeded",
            "diagnostic_only": False,
        },
        "corrections": execution_result.get("corrections") or [],
    }
    _append_audit(
        projection_file,
        {
            "schema": "gda.dltb-semantic-query-audit.v2",
            "query_id": query_id,
            "timestamp": _utc_now(),
            "question": str(question).strip(),
            "sql": result["sql"],
            "llm": result["llm"],
            "executor": result["executor"],
            "fallback_used": False,
        },
    )
    return result
