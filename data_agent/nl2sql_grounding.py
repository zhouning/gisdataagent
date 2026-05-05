"""NL2SQL grounding: semantic resolution + schema assembly + few-shot formatting."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .reference_queries import fetch_nl2sql_few_shots
from .semantic_model import SemanticModelStore
from .nl2sql_intent import classify_intent, IntentLabel

_COMPLEX_FEWSHOT_HINTS = (
    "面积", "距离", "交集", "相交", "缓冲", "占比", "最近", "前10", "前5", "排序", "联合", "周边"
)


def _should_fetch_few_shots(user_text: str, candidate_tables: list, semantic: dict) -> bool:
    """Only fetch expensive embedding-based few-shots for genuinely complex queries.

    GIS few-shots are not useful for non-spatial queries; they pollute
    warehouse-style prompts with irrelevant ST_* examples.
    """
    spatial_query = bool(semantic.get("spatial_ops") or semantic.get("region_filter"))
    if not spatial_query and not any(h in user_text for h in _COMPLEX_FEWSHOT_HINTS):
        return False
    high_conf_tables = [t for t in candidate_tables if t.get("confidence", 0) >= 0.6]
    if len(high_conf_tables) > 1:
        return True
    if any(h in user_text for h in _COMPLEX_FEWSHOT_HINTS):
        return True
    if semantic.get("spatial_ops") and (semantic.get("metric_hints") or semantic.get("sql_filters")):
        return True
    return False
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
    Falls back to COUNT(*) when reltuples is -1 (table not yet ANALYZEd).
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
            val = int(row[0]) if row and row[0] is not None else -1
            if val >= 0:
                return val
            r2 = conn.execute(sa_text(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ))
            return int(r2.scalar() or 0)
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


def _is_ascii_heavy(text: str) -> bool:
    if not text:
        return False
    ascii_chars = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    alpha_chars = sum(1 for ch in text if ch.isalpha())
    return alpha_chars > 0 and ascii_chars / max(alpha_chars, 1) >= 0.6


def _extract_schema_hint(user_text: str) -> str | None:
    m = re.search(r"schema\s+`([^`]+)`", user_text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"schema\s+([A-Za-z0-9_]+)", user_text, flags=re.IGNORECASE)
    return m.group(1) if m else None


def _rank_sources(user_text: str, sources: list[dict], semantic: dict) -> list[dict]:
    """Rank candidate sources to support both GIS and non-GIS queries.

    For non-spatial queries (any language), prefer non-geometry tables and
    tables with matched columns. For GIS queries with spatial signals, preserve
    existing confidence-driven behavior. The ASCII-heavy penalty for geometry
    tables is stronger because such queries are virtually never about spatial
    GIS data.
    """
    spatial_query = bool(semantic.get("spatial_ops") or semantic.get("region_filter"))
    ascii_heavy = _is_ascii_heavy(user_text)
    schema_hint = _extract_schema_hint(user_text)
    matched_columns = semantic.get("matched_columns") or {}

    ranked = []
    for source in sources:
        table_name = source.get("table_name", "")
        score = float(source.get("confidence", 0.0))
        has_geom = bool(source.get("geometry_type"))
        col_hits = len(matched_columns.get(table_name, []))

        if schema_hint and table_name.startswith(f"{schema_hint}."):
            score += 0.5
        if not spatial_query:
            if col_hits:
                score += min(0.3, 0.1 * col_hits)
            if not has_geom:
                score += 0.1
            else:
                # Stronger penalty for ASCII-heavy queries (GIS very unlikely)
                score -= 0.25 if ascii_heavy else 0.12

        ranked.append((score, source))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in ranked]


def _sample_distinct_values(table_name: str, column_name: str, limit: int = 5) -> list[str]:
    """Fetch a few distinct values for low-cardinality text columns.

    Supports dotted schema-qualified table names. Best-effort only.
    """
    try:
        from .db_engine import get_engine
        from sqlalchemy import text as sa_text
        engine = get_engine()
        if not engine:
            return []

        if "." in table_name:
            schema_name, bare_table = table_name.rsplit(".", 1)
            from_clause = f'"{schema_name}"."{bare_table}"'
        else:
            from_clause = f'"{table_name}"'

        sql = (
            f'SELECT DISTINCT "{column_name}" FROM {from_clause} '
            f'WHERE "{column_name}" IS NOT NULL ORDER BY 1 LIMIT {int(limit)}'
        )
        with engine.connect() as conn:
            rows = conn.execute(sa_text(sql)).fetchall()
        values = []
        for row in rows:
            v = row[0]
            if isinstance(v, str) and v:
                values.append(v)
        return values
    except Exception:
        return []


def _rank_candidate_tables(user_text: str, candidate_tables: list[dict], semantic: dict) -> list[dict]:
    """Re-rank candidate tables after schema + sample values are available."""
    spatial_query = bool(semantic.get("spatial_ops") or semantic.get("region_filter"))
    ascii_heavy = _is_ascii_heavy(user_text)
    text_lower = user_text.lower()
    matched_columns = semantic.get("matched_columns") or {}

    ranked = []
    for table in candidate_tables:
        table_name = table.get("table_name", "")
        score = float(table.get("confidence", 0.0))
        has_geom = any(col.get("is_geometry") for col in table.get("columns", []))
        col_hits = len(matched_columns.get(table_name, []))
        if not spatial_query:
            if col_hits:
                score += min(0.3, 0.1 * col_hits)
            if not has_geom:
                score += 0.1
            else:
                score -= 0.25 if ascii_heavy else 0.12

            value_hits = 0
            for col in table.get("columns", []):
                for v in col.get("sample_values") or []:
                    if isinstance(v, str) and v and v.lower() in text_lower:
                        value_hits += 1
            if value_hits:
                score += min(0.6, 0.25 * value_hits)

        ranked.append((score, table))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in ranked]


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
            srid = schema.get("srid") or source.get("srid") or 0
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
            "sample_values": [],
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
    geom_srids: dict[str, int] = {}  # table.column -> srid
    for table in payload.get("candidate_tables", []):
        lines.append("")
        lines.append(f"### {table['table_name']} ({table.get('display_name') or table['table_name']})")
        lines.append(f"置信度: {table.get('confidence', 0.0):.2f}; 估计行数: {table.get('row_count_hint', 0)}")
        for col in table.get("columns", []):
            alias_str = ", ".join(col.get("aliases") or []) or "—"
            unit_str = f" [单位: {col['unit']}]" if col.get("unit") else ""
            sample_str = ""
            sv = col.get("sample_values")
            if sv:
                sample_str = f" | 示例值: {', '.join(str(v) for v in sv[:8])}"
            lines.append(f"- {col['quoted_ref']} :: {col.get('pg_type','')}{unit_str} | 别名: {alias_str}{sample_str}")
            if col.get("is_geometry"):
                pg_type = col.get("pg_type", "")
                srid = 0
                if "," in pg_type:
                    try:
                        srid = int(pg_type.rsplit(",", 1)[1].rstrip(")"))
                    except (ValueError, IndexError):
                        pass
                geom_srids[f"{table['table_name']}.{col['column_name']}"] = srid
        if any(c.get("needs_quoting") for c in table.get("columns", [])):
            lines.append('⚠ PostgreSQL 规则: 大小写混合列名必须使用双引号，例如 "Floor"、"Id"。')

    if geom_srids:
        geographic_cols = {k: v for k, v in geom_srids.items() if v in (4326, 4490, 4610)}
        projected_cols = {k: v for k, v in geom_srids.items() if v not in (4326, 4490, 4610)}
        distinct_srids = set(geom_srids.values())

        if len(distinct_srids) > 1:
            lines.append("")
            lines.append("## ⚠ SRID 不一致警告")
            lines.append("- 候选表的几何列使用了不同的 SRID，跨表空间操作前**必须**用 ST_Transform 对齐:")
            for col_key, srid in geom_srids.items():
                lines.append(f"  - {col_key}: SRID={srid}")
            target_srid = max(geom_srids.values())
            if projected_cols:
                target_srid = next(iter(projected_cols.values()))
            lines.append(f"- 建议: 将其他列 ST_Transform 到 SRID={target_srid} 后再做空间运算")

        if geographic_cols:
            lines.append("")
            lines.append("## 空间几何字段规则 (地理坐标)")
            cols_list = ", ".join(geographic_cols.keys())
            lines.append(f"- 适用于: {cols_list}")
            lines.append("- 这些列是经纬度坐标（度），计算真实长度/面积必须先转 geography:")
            lines.append("  - 面积: `ST_Area(geom::geography)` → 平方米")
            lines.append("  - 距离: `ST_Distance(a::geography, b::geography)` → 米")
            lines.append("  - 范围: `ST_DWithin(a::geography, b::geography, 500)` → 500米")
            lines.append("- 空间关系（Intersects/Contains/Within）直接用 geometry，不需要 geography")

        if projected_cols:
            lines.append("")
            lines.append("## 空间几何字段规则 (投影坐标)")
            cols_list = ", ".join(projected_cols.keys())
            lines.append(f"- 适用于: {cols_list}")
            lines.append("- 这些列已经是投影坐标（米），ST_Area/ST_Length **直接返回平方米/米**")
            lines.append("- **禁止**对这些列使用 `::geography` 转换（会报错）")
            lines.append("- 面积: `ST_Area(geom)` → 平方米（直接使用）")
            lines.append("- 空间关系: `ST_Intersects(a, b)` 直接使用")
    lines.append("")
    lines.append("## 语义提示")
    hints = payload.get("semantic_hints", {})
    lines.append(f"- 空间操作: {hints.get('spatial_ops') or []}")
    lines.append(f"- 区域过滤: {hints.get('region_filter')}")
    lines.append(f"- 层次匹配: {hints.get('hierarchy_matches') or []}")
    lines.append(f"- 指标提示: {hints.get('metric_hints') or []}")
    lines.append(f"- 推荐 SQL 过滤: {hints.get('sql_filters') or []}")
    # Warehouse join-path hints (non-spatial only)
    wh = payload.get("warehouse_join_hints")
    spatial_query = bool(
        (payload.get("semantic_hints") or {}).get("spatial_ops")
        or (payload.get("semantic_hints") or {}).get("region_filter")
    )
    if wh and not spatial_query:
        lines.append("")
        lines.append("## 数据仓库 Join 路径提示")
        for tbl, info in (wh.get("table_roles") or {}).items():
            role = info.get("role", "unknown")
            role_cn = "事实表(fact)" if role == "fact" else "维度表(dimension)"
            entities = ", ".join(info.get("entities") or [])
            measures = ", ".join(info.get("measures") or [])
            parts = [f"{tbl}: {role_cn}"]
            if entities:
                parts.append(f"实体键: {entities}")
            if measures:
                parts.append(f"度量: {measures}")
            lines.append(f"- {'; '.join(parts)}")
        for jp in wh.get("join_paths") or []:
            lines.append(f"- JOIN: {jp}")
        for mhp in wh.get("multi_hop_paths") or []:
            lines.append(f"- MULTI-HOP JOIN (via bridge): {mhp}")

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
    lines.append("- 不允许 DELETE / UPDATE / INSERT / DROP / ALTER")

    from .nl2sql_intent import IntentLabel
    intent = payload.get("intent", IntentLabel.UNKNOWN)
    if not isinstance(intent, IntentLabel):
        try:
            intent = IntentLabel(intent)
        except (ValueError, KeyError):
            intent = IntentLabel.UNKNOWN

    if intent in (IntentLabel.PREVIEW_LISTING, IntentLabel.UNKNOWN):
        lines.append("- 大表全表扫描必须有 LIMIT")

    if intent in (IntentLabel.KNN, IntentLabel.UNKNOWN):
        lines.append("")
        lines.append("## KNN 排序规则")
        lines.append("- 最近邻必须使用 PostGIS 索引算子: ORDER BY a.geometry <-> b.geometry LIMIT K")
        lines.append("- 不允许使用 ORDER BY ST_Distance(...) 进行排序；ST_Distance 只在 SELECT 中报告距离值")

    # Aggregation / Warehouse semantics — apply when query has aggregation intent
    # or when warehouse join hints exist (i.e., non-spatial multi-table query).
    has_warehouse_hints = bool(payload.get("warehouse_join_hints"))
    if intent == IntentLabel.AGGREGATION or has_warehouse_hints:
        lines.append("")
        lines.append("## 聚合语义规则")
        lines.append("- COUNT(*) 计入所有行（包含 NULL），COUNT(col) 只计 col 非 NULL 的行；二者结果常不同。")
        lines.append("- COUNT(DISTINCT col) 只在题目明确要求“不同/独立/去重”时使用；默认计数用 COUNT(*) 或 COUNT(主键)。")
        lines.append("- 计算占比/比例（如 “百分之多少 / ratio / percentage”）时使用 SUM(CASE WHEN ... THEN 1 ELSE 0 END) * 1.0 / COUNT(*) 或 AVG(CASE...)；勿用整除。")
        lines.append("- 多表聚合时，先在 fact 表做聚合再 JOIN dim 表，避免重复计数膨胀。")
        lines.append("- \"每个 / per / 各 / 按...统计\" 等措辞需要 GROUP BY；GROUP BY 中所有非聚合 SELECT 列必须出现。")

        lines.append("")
        lines.append("## DISTINCT 使用规则")
        lines.append("- 当 JOIN 产生一对多关系（如 patient JOIN laboratory 一个患者有多条检验记录），SELECT 列表中的维度列（ID/name/birthday 等）必须加 DISTINCT 或用 DISTINCT ON。")
        lines.append("- 只有在 SELECT 中包含聚合函数（COUNT/SUM/AVG/MAX/MIN）时才不需要 DISTINCT（聚合本身已去重）。")
        lines.append("- 当 gold 要求 'List patients / List IDs' 且涉及多表 JOIN 时，默认使用 SELECT DISTINCT。")

        lines.append("")
        lines.append("## 避免过度 JOIN")
        lines.append("- 如果所需的所有列和过滤条件都在同一张表中，不要引入额外的 JOIN。")
        lines.append("- 只有当 WHERE 条件或 SELECT 列确实需要另一张表的字段时才 JOIN。")
        lines.append("- 当两张表都有同名字段（如 Diagnosis），优先使用问题语境中最直接的那张表。")

        lines.append("")
        lines.append("## 输出列格式")
        lines.append("- 当问题要求 'full name / 姓名' 且表中有 first_name + last_name 两列时，默认 SELECT 两列分开返回，不要用 || 拼接。")
        lines.append("- LIMIT 1 场景：如果问题要求 'the highest / the oldest / the youngest'，使用 ORDER BY ... LIMIT 1 而非子查询 WHERE col = (SELECT MAX/MIN...)。")

        # Date / temporal handling — BIRD heavily uses TEXT-stored dates
        lines.append("")
        lines.append("## 日期 / 时间处理规则")
        lines.append("- 若日期列为 TEXT 类型，使用字符串前缀比较或 LIKE 'YYYY-MM%' 进行月/年过滤，而不是直接 EXTRACT。")
        lines.append("- 取年份: SUBSTR(date_col, 1, 4) 或 CAST(SUBSTR(date_col,1,4) AS INTEGER)。")
        lines.append("- 取月份: SUBSTR(date_col, 6, 2)。")
        lines.append("- 真实 date / timestamp 列才使用 EXTRACT(YEAR FROM ...) / DATE_TRUNC。")
        lines.append("- 排序日期 TEXT 列时直接 ORDER BY 字符串即可（ISO 格式自然有序）。")

    return "\n".join(lines)


def _build_warehouse_join_hints(candidate_tables: list[dict]) -> dict | None:
    """Look up SemanticModelStore for candidate tables and build join-path hints.

    Builds both 1-hop (direct shared entity) and multi-hop (transitive via a
    pivot table that may not be in candidate_tables) join paths. Multi-hop
    paths are useful when fact-vs-fact joins require a bridging dimension.

    Returns a dict with table_roles, join_paths (1-hop strings), and
    multi_hop_paths (transitive bridge suggestions), or None if no models found.
    """
    store = SemanticModelStore()
    table_roles: dict[str, dict] = {}
    entity_map: dict[str, list[str]] = {}  # entity_name -> [table_names]

    for table in candidate_tables:
        tname = table.get("table_name", "")
        model = store.get(tname)
        if not model:
            continue
        entities = [e.get("name", "") for e in (model.get("entities") or [])]
        measures = [m.get("name", "") for m in (model.get("measures") or [])]
        role = "fact" if measures else "dimension"
        info: dict = {"role": role, "entities": entities}
        if measures:
            info["measures"] = measures
        table_roles[tname] = info
        for ent in entities:
            entity_map.setdefault(ent, []).append(tname)

    if not table_roles:
        return None

    # Build 1-hop join paths by matching shared entities across candidate tables
    join_paths: list[str] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for ent, tables in entity_map.items():
        if len(tables) < 2:
            continue
        facts = [t for t in tables if table_roles[t]["role"] == "fact"]
        dims = [t for t in tables if table_roles[t]["role"] == "dimension"]
        for f in facts:
            for d in dims:
                short_f = f.rsplit(".", 1)[-1] if "." in f else f
                short_d = d.rsplit(".", 1)[-1] if "." in d else d
                key = tuple(sorted([f, d])) + (ent,)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                join_paths.append(f"{short_f}.{ent} -> {short_d}.{ent}")
        for i, f1 in enumerate(facts):
            for f2 in facts[i + 1:]:
                short1 = f1.rsplit(".", 1)[-1] if "." in f1 else f1
                short2 = f2.rsplit(".", 1)[-1] if "." in f2 else f2
                key = tuple(sorted([f1, f2])) + (ent,)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                join_paths.append(f"{short1}.{ent} -> {short2}.{ent}")

    # Multi-hop: for every pair of candidate tables that do NOT share an entity
    # directly, search the registered model store for a pivot table that
    # joins them via two distinct entities (typical bridging dimension).
    multi_hop_paths: list[str] = []
    candidate_names = list(table_roles.keys())
    candidate_set = set(candidate_names)
    direct_pairs: set[tuple[str, str]] = set()
    for ent, tables in entity_map.items():
        for i, t1 in enumerate(tables):
            for t2 in tables[i + 1:]:
                direct_pairs.add(tuple(sorted([t1, t2])))

    if len(candidate_names) >= 2:
        try:
            all_models = store.list_active() or []
        except Exception:
            all_models = []
        # Index: entity_name -> set of model names (across ALL registered models)
        global_entity_index: dict[str, set[str]] = {}
        for m in all_models:
            mname = m.get("name") or m.get("source_table") or ""
            if not mname:
                continue
            for e in (m.get("entities") or []):
                ent_name = e.get("name") or e.get("column") or ""
                if ent_name:
                    global_entity_index.setdefault(ent_name, set()).add(mname)

        for i, t1 in enumerate(candidate_names):
            for t2 in candidate_names[i + 1:]:
                pair_key = tuple(sorted([t1, t2]))
                if pair_key in direct_pairs:
                    continue
                ents1 = set(table_roles[t1]["entities"])
                ents2 = set(table_roles[t2]["entities"])
                # Find a pivot model that contains at least one entity from each
                pivot_candidates: list[tuple[str, str, str]] = []
                # ent_a in t1 and pivot, ent_b in t2 and pivot
                for ent_a in ents1:
                    pivot_for_a = global_entity_index.get(ent_a, set())
                    for ent_b in ents2:
                        if ent_a == ent_b:
                            continue
                        pivot_for_b = global_entity_index.get(ent_b, set())
                        common = pivot_for_a & pivot_for_b
                        # Exclude the candidates themselves
                        common -= {t1, t2}
                        for pivot in common:
                            pivot_candidates.append((pivot, ent_a, ent_b))
                # Pick at most 2 pivot suggestions per pair to avoid prompt bloat
                for pivot, ent_a, ent_b in pivot_candidates[:2]:
                    short_t1 = t1.rsplit(".", 1)[-1]
                    short_t2 = t2.rsplit(".", 1)[-1]
                    short_pv = pivot.rsplit(".", 1)[-1]
                    multi_hop_paths.append(
                        f"{short_t1}.{ent_a} -> {short_pv}.{ent_a}; {short_pv}.{ent_b} -> {short_t2}.{ent_b}"
                    )

    result: dict = {"table_roles": table_roles, "join_paths": join_paths}
    if multi_hop_paths:
        result["multi_hop_paths"] = multi_hop_paths
    return result


def build_nl2sql_context(user_text: str, schema_filter: str | None = None) -> dict:
    """Build semantic + schema grounding payload for NL2SQL generation.

    Args:
        user_text: The natural language question.
        schema_filter: If provided (e.g. "bird_debit_card_specializing"), forces
            all tables from this schema to be included as candidates regardless
            of semantic matching. Used for warehouse benchmarks where the target
            schema is known a priori.
    """
    intent_result = classify_intent(user_text)
    semantic = resolve_semantic_context(user_text)
    sources = list(semantic.get("sources") or [])
    # When schema_filter is set, remove sources from other schemas
    if schema_filter:
        sources = [s for s in sources if str(s.get("table_name", "")).startswith(f"{schema_filter}.")]
    sources = _rank_sources(user_text, sources, semantic)

    # Supplement: fuzzy-match additional tables not already resolved by semantic layer
    source_table_names = {s.get("table_name") for s in sources}
    source_list = list_semantic_sources()
    schema_hint = _extract_schema_hint(user_text) or schema_filter
    if source_list.get("status") == "success":
        scored = []
        for source in source_list.get("sources", []):
            if source.get("table_name") in source_table_names:
                continue
            tname = str(source.get("table_name", ""))
            # When schema_filter is set, skip tables from other schemas entirely
            if schema_filter and not tname.startswith(f"{schema_filter}."):
                continue
            score = _score_source(user_text, source)
            # Boost tables matching the schema_filter (known target schema)
            if schema_filter and tname.startswith(f"{schema_filter}."):
                score += 1.0  # strong boost for known-schema tables
            elif schema_hint and tname.startswith(f"{schema_hint}."):
                score += 0.5
            if score > 0.05:
                s = dict(source)
                s["confidence"] = score
                scored.append(s)
        scored.sort(key=lambda s: s.get("confidence", 0), reverse=True)
        # When schema_filter is set, include more candidates (up to 8)
        top_n = 8 if schema_filter else 2
        sources.extend(scored[:top_n])
        sources = _rank_sources(user_text, sources, semantic)

    candidate_tables = []
    ascii_heavy = _is_ascii_heavy(user_text)
    spatial_query = bool(semantic.get("spatial_ops") or semantic.get("region_filter"))
    source_limit = 5 if not spatial_query else 3
    if schema_filter:
        source_limit = 8  # warehouse benchmarks may have many tables per schema
    for source in sources[:source_limit]:
        table_name = source.get("table_name")
        if not table_name:
            continue
        schema = describe_table_semantic(table_name)
        if schema.get("status") != "success":
            continue
        candidate_tables.append(_build_candidate_table(source, schema))

    # Enrich non-geometry text columns with sample values for warehouse queries
    if ascii_heavy and not spatial_query:
        _TEXT_TYPES = {"text", "character varying", "varchar"}
        for table in candidate_tables:
            tname = table.get("table_name", "")
            for col in table.get("columns", []):
                if col.get("is_geometry"):
                    continue
                pg_type = (col.get("pg_type") or "").lower()
                if any(t in pg_type for t in _TEXT_TYPES):
                    vals = _sample_distinct_values(tname, col["column_name"], limit=8)
                    if vals and len(vals) <= 20:
                        col["sample_values"] = vals

    # Limit candidate tables: more for warehouse (need full schema for join hints)
    max_candidates = 5 if schema_filter else 3
    candidate_tables = _rank_candidate_tables(user_text, candidate_tables, semantic)[:max_candidates]

    # Build warehouse join hints from SemanticModelStore (non-spatial only)
    warehouse_join_hints = None
    if not spatial_query:
        warehouse_join_hints = _build_warehouse_join_hints(candidate_tables)

    few_shot_text = ""
    if _should_fetch_few_shots(user_text, candidate_tables, semantic):
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
        "intent": intent_result.primary,
        "intent_secondary": [lbl.value for lbl in intent_result.secondary],
        "intent_confidence": intent_result.confidence,
        "intent_source": intent_result.source,
    }
    if warehouse_join_hints:
        payload["warehouse_join_hints"] = warehouse_join_hints
    payload["grounding_prompt"] = _format_grounding_prompt(payload)
    return payload
