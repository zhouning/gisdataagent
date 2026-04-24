"""NL2SQL grounding: semantic resolution + schema assembly + few-shot formatting."""
from __future__ import annotations

from difflib import SequenceMatcher

from .reference_queries import fetch_nl2sql_few_shots
from .semantic_layer import (
    describe_table_semantic,
    list_semantic_sources,
    resolve_semantic_context,
)

# Minimal PostgreSQL reserved words we care about for quoting
PG_RESERVED_WORDS = {
    "user", "select", "group", "order", "where", "table", "from",
}


def _needs_quoting(column_name: str) -> bool:
    """Return True if a PostgreSQL identifier must be double-quoted."""
    if not column_name:
        return False
    if column_name.lower() != column_name:
        return True
    if column_name in PG_RESERVED_WORDS:
        return True
    if not column_name.replace("_", "a").isalnum():
        return True
    return False


def _quoted_ref(column_name: str) -> str:
    return f'"{column_name}"' if _needs_quoting(column_name) else column_name


def _estimate_table_size(table_name: str) -> int:
    """Best-effort table size estimate via pg_class.reltuples.

    Returns approximate row count, or 0 if unavailable.
    """
    try:
        from .db_engine import get_engine
        from sqlalchemy import text as sa_text
        engine = get_engine()
        if not engine:
            return 0
        with engine.connect() as conn:
            r = conn.execute(sa_text(
                "SELECT reltuples::bigint FROM pg_class WHERE relname = :t"
            ), {"t": table_name})
            row = r.fetchone()
            return max(int(row[0]), 0) if row and row[0] else 0
    except Exception:
        return 0


def _score_source(user_text: str, source: dict) -> float:
    """Simple fuzzy score for fallback source matching."""
    text = user_text.lower()
    candidates = [
        str(source.get("table_name", "")),
        str(source.get("display_name", "")),
        str(source.get("description", "")),
    ] + list(source.get("synonyms", []) or [])
    best = 0.0
    for c in candidates:
        c_low = c.lower()
        if c_low and c_low in text:
            best = max(best, 0.8)
        elif c_low:
            best = max(best, SequenceMatcher(None, text, c_low).ratio() * 0.5)
    return best


def _build_candidate_table(source: dict, schema: dict) -> dict:
    """Merge semantic source hit + describe_table_semantic() result."""
    out_columns = []
    for col in schema.get("columns", []) or []:
        column_name = col.get("column_name", "")
        aliases = col.get("aliases", []) or []
        pg_type = col.get("data_type") or col.get("udt_name") or ""
        # Detect geometry column: explicit flag OR (USER-DEFINED type + geom-like name)
        is_geom = bool(col.get("is_geometry", False))
        if not is_geom and pg_type == "USER-DEFINED" and column_name.lower() in ("geometry", "geom", "the_geom", "shape"):
            is_geom = True
        if is_geom:
            gt = schema.get("geometry_type") or source.get("geometry_type") or "Geometry"
            srid = schema.get("srid") or source.get("srid") or 4326
            pg_type = f"geometry({gt},{srid})"
        out_columns.append({
            "column_name": column_name,
            "pg_type": pg_type,
            "quoted_ref": _quoted_ref(column_name),
            "aliases": aliases,
            "semantic_domain": col.get("semantic_domain"),
            "unit": col.get("unit") or "",
            "description": col.get("description") or "",
            "is_geometry": is_geom,
            "needs_quoting": _needs_quoting(column_name),
        })
    return {
        "table_name": source.get("table_name") or schema.get("table_name"),
        "display_name": source.get("display_name") or schema.get("display_name") or source.get("table_name"),
        "description": source.get("description") or schema.get("description") or "",
        "confidence": float(source.get("confidence", 0.0)),
        "columns": out_columns,
        "row_count_hint": _estimate_table_size(source.get("table_name") or schema.get("table_name")),
    }


def _format_grounding_prompt(payload: dict) -> str:
    """Format the grounding payload into a strict prompt block for the LLM."""
    lines: list[str] = []
    lines.append("[NL2SQL 上下文 — 必须严格遵循以下 schema]")
    lines.append("")
    lines.append("## 候选数据源")
    has_geometry_4326 = False
    for table in payload.get("candidate_tables", []):
        lines.append("")
        lines.append(f"### {table['table_name']} ({table.get('display_name') or table['table_name']})")
        lines.append(f"置信度: {table.get('confidence', 0.0):.2f}; 估计行数: {table.get('row_count_hint', 0)}")
        for col in table.get("columns", []):
            alias_str = ", ".join(col.get("aliases") or []) or "—"
            lines.append(f"- {col['quoted_ref']} :: {col.get('pg_type','')} | 别名: {alias_str}")
            if col.get("is_geometry"):
                has_geometry_4326 = True
        if any(c.get("needs_quoting") for c in table.get("columns", [])):
            lines.append('⚠ PostgreSQL 规则: 大小写混合列名必须使用双引号，例如 "Floor"、"Id"。')
    if has_geometry_4326:
        lines.append("")
        lines.append("## ⚠ 空间几何字段规则 (SRID 4326)")
        lines.append("- geometry 列是 EPSG:4326 经纬度坐标，单位是**度**，不是米")
        lines.append("- 计算**真实长度/面积（米/平方米）**必须先转 geography:")
        lines.append("  - 长度: `ST_Length(geometry::geography)` → 米")
        lines.append("  - 面积: `ST_Area(geometry::geography)` → 平方米")
        lines.append("  - 距离: `ST_Distance(a.geometry::geography, b.geometry::geography)` → 米")
        lines.append("  - 缓冲/距离范围: `ST_DWithin(a.geometry::geography, b.geometry::geography, 500)` → 500米范围")
        lines.append("- 空间关系（Intersects/Contains/Within）**不需要** geography 转换，直接用 geometry")
        lines.append("- KNN 最近邻排序用 `ORDER BY a.geometry <-> b.geometry LIMIT N`（空间索引优化，不需要 geography）")
    lines.append("")
    lines.append("## 语义提示")
    hints = payload.get("semantic_hints", {})
    lines.append(f"- 空间操作: {hints.get('spatial_ops') or []}")
    lines.append(f"- 区域过滤: {hints.get('region_filter')}")
    lines.append(f"- 层次匹配: {hints.get('hierarchy_matches') or []}")
    lines.append(f"- 指标提示: {hints.get('metric_hints') or []}")
    lines.append(f"- 推荐 SQL 过滤: {hints.get('sql_filters') or []}")
    few_shots = payload.get("few_shots") or []
    if few_shots:
        lines.append("")
        lines.append("## 参考 SQL")
        for shot in few_shots:
            lines.append(f"Q: {shot.get('question','')}")
            lines.append(f"SQL: {shot.get('sql','')}")
    lines.append("")
    lines.append("## 安全规则")
    lines.append("- 只允许 SELECT 查询")
    lines.append("- 大表全表扫描必须有 LIMIT")
    lines.append("- 不允许 DELETE / UPDATE / INSERT / DROP / ALTER")
    return "\n".join(lines)


def build_nl2sql_context(user_text: str) -> dict:
    """Build semantic + schema grounding payload for NL2SQL generation."""
    semantic = resolve_semantic_context(user_text)
    sources = list(semantic.get("sources") or [])

    # Supplement: fuzzy-match additional tables not already resolved by semantic layer
    source_table_names = {s.get("table_name") for s in sources}
    source_list = list_semantic_sources()
    if source_list.get("status") == "success":
        scored = []
        for source in source_list.get("sources", []):
            if source.get("table_name") in source_table_names:
                continue
            score = _score_source(user_text, source)
            if score > 0.05:
                s = dict(source)
                s["confidence"] = score
                scored.append(s)
        scored.sort(key=lambda s: s.get("confidence", 0), reverse=True)
        sources.extend(scored[:2])

    candidate_tables = []
    for source in sources[:3]:
        table_name = source.get("table_name")
        if not table_name:
            continue
        schema = describe_table_semantic(table_name)
        if schema.get("status") != "success":
            continue
        candidate_tables.append(_build_candidate_table(source, schema))

    few_shot_text = fetch_nl2sql_few_shots(user_text, top_k=3)
    few_shots = []
    if few_shot_text:
        few_shots.append({"question": "参考查询示例", "sql": few_shot_text})

    payload = {
        "candidate_tables": candidate_tables,
        "semantic_hints": {
            "spatial_ops": semantic.get("spatial_ops") or [],
            "region_filter": semantic.get("region_filter"),
            "hierarchy_matches": semantic.get("hierarchy_matches") or [],
            "metric_hints": semantic.get("metric_hints") or [],
            "sql_filters": semantic.get("sql_filters") or [],
        },
        "few_shots": few_shots,
    }
    payload["grounding_prompt"] = _format_grounding_prompt(payload)
    return payload
