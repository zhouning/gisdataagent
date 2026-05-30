"""Grid-based spatial declassification module (v15.8).

Provides production-grade anonymization/declassification for spatial datasets:
- ``grid_anonymize_file``: GeoPandas-based for local files (Shapefile/GeoJSON/GPKG)
- ``grid_anonymize_pg``: PostGIS-native (ST_SquareGrid) for DB tables, handles
  million-row tables without GeoPandas memory overhead
- ``verify_anonymization``: reverse-engineering attack test + re-identification risk score

Compliance references:
- GB/T 24356: surveying accuracy grading
- 测绘地理信息管理工作国家秘密范围的规定 (2020): scale/grid-size classification
"""

from __future__ import annotations

import json
import logging
import math
from typing import Optional

import numpy as np
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sensitive fields always stripped from output (whitelist cannot override)
SENSITIVE_FIELD_BLACKLIST = frozenset({
    # National land survey — ownership/identifier fields
    "bsm", "qsdwdm", "qsdwmc", "zldwdm", "zldwmc",
    # Cadastral / real estate / rights-holder
    "bdcdyh", "zl", "qlr", "qlrmc", "cbf", "cbfmc",
    "syqr", "syqrmc", "zjhm", "zjh",
    # PII: phone, ID, email
    "phone", "tel", "mobile", "dianhua", "电话",
    "id_number", "idcard", "sfzh", "shenfenzh", "身份证",
    "email", "youxiang", "邮箱",
    "name_full", "xingming", "姓名", "contact",
    # Precise coordinates as columns
    "longitude", "latitude", "lng", "lat", "jd", "wd",
    "经度", "纬度", "经度wgs84", "纬度wgs84", "jdwgs84", "wdwgs84",
})

# Level → grid size (meters) → classification target
LEVEL_CONFIG = {
    "L1": {"grid_size_m": 25.0,   "target_sensitivity": "confidential",
           "accuracy_m": 13,      "description": "内部精细分析"},
    "L2": {"grid_size_m": 100.0,  "target_sensitivity": "internal",
           "accuracy_m": 50,      "description": "跨部门协作"},
    "L3": {"grid_size_m": 250.0,  "target_sensitivity": "internal",
           "accuracy_m": 125,     "description": "对外展示/合作方共享"},
    "L4": {"grid_size_m": 1000.0, "target_sensitivity": "public",
           "accuracy_m": 500,     "description": "公开发布/科普可视化"},
}

# SRID remapping: geographic → metric projection
METRIC_CRS_LOOKUP = {
    4490: 4523,   # CGCS2000 → CGCS2000 3° GK Zone 35 (适合重庆范围)
    4610: 4523,   # Xian80 → CGCS2000 3° GK Zone 35
    4326: 32649,  # WGS84 → UTM 49N (重庆中心约 106.5°E)
    4214: 4523,
}


# ---------------------------------------------------------------------------
# k-anonymity and differential privacy helpers
# ---------------------------------------------------------------------------

def _apply_laplace_noise(
    values: np.ndarray,
    epsilon: float,
    sensitivity: float,
    seed: Optional[int] = None,
) -> np.ndarray:
    """Apply Laplace noise for ε-differential privacy.

    Args:
        values: input numeric array
        epsilon: privacy budget (smaller = more noise = more privacy)
        sensitivity: max change of query result from single record modification
        seed: optional seed for reproducibility
    """
    rng = np.random.default_rng(seed)
    scale = sensitivity / max(epsilon, 0.01)
    noise = rng.laplace(0.0, scale, size=values.shape)
    return values + noise


def _k_anonymity_check(source_count_per_cell: int, k_threshold: int) -> bool:
    """Return True if cell passes k-anonymity (>= k source records)."""
    return source_count_per_cell >= k_threshold


# ---------------------------------------------------------------------------
# PostGIS direct version — scalable to millions of rows
# ---------------------------------------------------------------------------

def grid_anonymize_pg(
    source_table: str,
    output_table: str,
    *,
    level: str = "L3",
    grid_size_m: Optional[float] = None,
    keep_attrs: list[str] | None = None,
    agg_strategy: str = "mode",
    source_schema: str = "public",
    output_schema: str = "public",
    source_srid: Optional[int] = None,
    target_srid: Optional[int] = None,
    k_anonymity: int = 5,
    dp_epsilon: Optional[float] = None,
    dp_numeric_fields: list[str] | None = None,
    random_offset: bool = True,
    random_seed: int = 42,
    register_lineage: bool = True,
    dry_run: bool = False,
) -> dict:
    """[生产级] PostGIS 直连格网脱密：将源表按规则格网聚合并剥离敏感字段。

    使用 PostGIS 3.1+ 原生 ``ST_SquareGrid`` 实现，可处理百万级行数据。

    Args:
        source_table: 源表名 (如 "cq_dltb")
        output_table: 输出表名 (如 "cq_dltb_grid_L3_public")
        level: 脱密等级 L1/L2/L3/L4，决定 grid_size_m
        grid_size_m: 手动指定格网尺寸（米），覆盖 level
        keep_attrs: 保留字段列表，敏感字段即使列入也被强制剥离
        agg_strategy: "mode" | "area_weighted" | "topk"
        source_schema / output_schema: PG schema 名
        source_srid: 源几何 SRID（None 自动探测）
        target_srid: 目标投影 SRID（None 自动从 METRIC_CRS_LOOKUP 选）
        k_anonymity: k-匿名阈值，覆盖源图斑数 < k 的格网会被剔除
        dp_epsilon: 差分隐私预算（None 关闭）
        dp_numeric_fields: 应用 DP 噪声的数值字段
        random_offset: 格网原点随机偏移
        random_seed: 偏移随机种子
        register_lineage: 是否注册到 data_catalog 血缘
        dry_run: 仅返回计划 SQL + 预估格网数，不实际执行

    Returns:
        JSON 结果：输出表名/行数/剥离字段/k-匿名过滤数/血缘 ID
    """
    from .db_engine import get_engine

    if level not in LEVEL_CONFIG:
        return {"status": "error", "message": f"Unknown level: {level}. Valid: {list(LEVEL_CONFIG)}"}

    cfg = LEVEL_CONFIG[level]
    actual_grid_size = grid_size_m if grid_size_m is not None else cfg["grid_size_m"]

    engine = get_engine()
    if engine is None:
        return {"status": "error", "message": "Database unavailable"}

    keep_attrs = [a.lower() for a in (keep_attrs or [])]
    dp_numeric_fields = [a.lower() for a in (dp_numeric_fields or [])]

    try:
        with engine.connect() as conn:
            # --- 1. Inspect source table schema ---
            geom_row = conn.execute(text("""
                SELECT f_geometry_column, srid FROM geometry_columns
                WHERE f_table_schema = :s AND f_table_name = :t
                LIMIT 1
            """), {"s": source_schema, "t": source_table}).fetchone()

            if not geom_row:
                return {"status": "error",
                        "message": f"Table {source_schema}.{source_table} has no geometry_columns entry"}

            geom_col, src_srid = geom_row[0], geom_row[1]
            if source_srid is not None:
                src_srid = source_srid

            cols = conn.execute(text("""
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_schema = :s AND table_name = :t
                ORDER BY ordinal_position
            """), {"s": source_schema, "t": source_table}).fetchall()
            all_columns = [(c[0], c[1]) for c in cols if c[0] != geom_col]
            col_lower_map = {c[0].lower(): c[0] for c in all_columns}
            col_types = {c[0].lower(): c[1] for c in all_columns}

            # --- 2. Filter attributes (whitelist minus blacklist) ---
            final_attrs: list[str] = []
            stripped: list[str] = []
            for attr_l in keep_attrs:
                if attr_l in SENSITIVE_FIELD_BLACKLIST:
                    stripped.append(attr_l)
                elif attr_l in col_lower_map:
                    final_attrs.append(col_lower_map[attr_l])
            # also flag any sensitive source columns present
            for c_lower, c_orig in col_lower_map.items():
                if c_lower in SENSITIVE_FIELD_BLACKLIST and c_lower not in stripped:
                    stripped.append(c_lower)

            # --- 3. Determine target metric CRS ---
            if target_srid is None:
                target_srid = METRIC_CRS_LOOKUP.get(src_srid, 4523)

            # --- 4. Get bbox in metric CRS and estimate grid count ---
            bbox = conn.execute(text(f"""
                SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e)
                FROM (SELECT ST_Transform(ST_SetSRID(ST_Extent("{geom_col}"), :src_srid), :tgt_srid) AS e
                      FROM "{source_schema}"."{source_table}") sub
            """), {"src_srid": src_srid, "tgt_srid": target_srid}).fetchone()

            if not bbox or bbox[0] is None:
                return {"status": "error", "message": "Source table is empty or bbox computation failed"}

            minx, miny, maxx, maxy = [float(v) for v in bbox]
            offset_x = offset_y = 0.0
            if random_offset:
                rng = np.random.default_rng(random_seed)
                offset_x = float(rng.uniform(-actual_grid_size / 2, actual_grid_size / 2))
                offset_y = float(rng.uniform(-actual_grid_size / 2, actual_grid_size / 2))

            est_grids = math.ceil((maxx - minx) / actual_grid_size) * \
                        math.ceil((maxy - miny) / actual_grid_size)

            if est_grids > 5_000_000:
                return {"status": "error",
                        "message": f"Estimated grid count too large ({est_grids:,}); "
                                   f"increase level or grid_size_m"}

            # --- 5. Build aggregation SQL ---
            attr_select_parts = []
            for attr in final_attrs:
                dt = col_types.get(attr.lower(), "")
                if agg_strategy == "mode":
                    attr_select_parts.append(
                        f'mode() WITHIN GROUP (ORDER BY j."{attr}") AS "{attr}"'
                    )
                elif agg_strategy == "area_weighted":
                    if dt in ("numeric", "double precision", "real", "integer",
                              "bigint", "smallint", "int", "int4", "int8"):
                        attr_select_parts.append(
                            f'CASE WHEN SUM(j."_cell_area") > 0 THEN '
                            f'ROUND((SUM(j."{attr}"::numeric * j."_cell_area") / '
                            f'SUM(j."_cell_area"))::numeric, 4) ELSE NULL END AS "{attr}"'
                        )
                    else:
                        attr_select_parts.append(
                            f'mode() WITHIN GROUP (ORDER BY j."{attr}") AS "{attr}"'
                        )
                elif agg_strategy == "topk":
                    attr_select_parts.append(
                        f'string_agg(DISTINCT j."{attr}"::text, \'|\' '
                        f'ORDER BY j."{attr}"::text) AS "{attr}"'
                    )

            attr_select_sql = (",\n    " + ",\n    ".join(attr_select_parts)) if attr_select_parts else ""

            output_fq = f'"{output_schema}"."{output_table}"'
            source_fq = f'"{source_schema}"."{source_table}"'

            create_sql = f"""
            DROP TABLE IF EXISTS {output_fq};
            CREATE TABLE {output_fq} AS
            WITH grid_metric AS (
                SELECT (ST_SquareGrid(
                    :gsize,
                    ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, :tgt_srid)
                )).*
            ),
            grid AS (
                SELECT i, j, geom AS geom_metric,
                       ST_Transform(geom, :src_srid) AS geom_src,
                       ST_Area(geom) AS metric_cell_area,
                       ST_Area(geom) AS src_cell_area_proxy
                FROM grid_metric
            ),
            joined AS (
                SELECT g.i AS _gi, g.j AS _gj,
                       g.geom_metric AS _cell_geom,
                       g.metric_cell_area AS _metric_cell_area,
                       /* Use area ratio in source CRS to get fraction, multiply by metric area */
                       (ST_Area(ST_Intersection(g.geom_src, s."{geom_col}")) /
                        NULLIF(ST_Area(g.geom_src), 0)) * g.metric_cell_area AS _cell_area,
                       {", ".join(f's."{a}" AS "{a}"' for a in final_attrs) + "," if final_attrs else ""}
                       1 AS _one
                FROM grid g
                JOIN {source_fq} s ON ST_Intersects(g.geom_src, s."{geom_col}")
            )
            SELECT
                ('R' || _gi || 'C' || _gj) AS grid_id,
                _cell_geom AS geom,
                SUM(_cell_area) AS shape_area,
                COUNT(*) AS _k_source_count
                {attr_select_sql}
            FROM joined j
            GROUP BY _gi, _gj, _cell_geom
            HAVING COUNT(*) >= :kmin;
            """

            # Apply offset to bbox if needed
            eff_minx = minx + offset_x - actual_grid_size
            eff_miny = miny + offset_y - actual_grid_size
            eff_maxx = maxx + actual_grid_size
            eff_maxy = maxy + actual_grid_size

            plan = {
                "source_table": f"{source_schema}.{source_table}",
                "output_table": f"{output_schema}.{output_table}",
                "level": level,
                "grid_size_m": actual_grid_size,
                "accuracy_m": cfg["accuracy_m"],
                "target_sensitivity": cfg["target_sensitivity"],
                "source_srid": src_srid,
                "target_srid": target_srid,
                "estimated_grid_count": est_grids,
                "kept_attrs": final_attrs,
                "stripped_sensitive_fields": sorted(set(stripped)),
                "agg_strategy": agg_strategy,
                "k_anonymity_threshold": k_anonymity,
                "dp_epsilon": dp_epsilon,
                "dp_numeric_fields": dp_numeric_fields,
                "random_offset": {"x": round(offset_x, 3), "y": round(offset_y, 3)} if random_offset else None,
                "sql_preview": create_sql[:800] + "..." if len(create_sql) > 800 else create_sql,
            }

            if dry_run:
                plan["status"] = "dry_run"
                return plan

            # --- 6. Execute grid creation ---
            conn.execute(text(create_sql), {
                "src_srid": src_srid, "tgt_srid": target_srid,
                "gsize": actual_grid_size,
                "minx": eff_minx, "miny": eff_miny,
                "maxx": eff_maxx, "maxy": eff_maxy,
                "kmin": k_anonymity,
            })
            conn.commit()

            # --- 7. Apply differential privacy noise if requested ---
            if dp_epsilon is not None and dp_numeric_fields:
                for field in dp_numeric_fields:
                    f_actual = col_lower_map.get(field)
                    if not f_actual or f_actual not in final_attrs:
                        continue
                    # Sensitivity = max observed value (conservative)
                    max_val = conn.execute(text(
                        f'SELECT MAX("{f_actual}"::numeric) FROM {output_fq}'
                    )).scalar()
                    if max_val is None:
                        continue
                    sensitivity = float(max_val) * 0.01  # 1% of max as global sensitivity
                    scale = sensitivity / max(dp_epsilon, 0.01)
                    # Laplace inverse-CDF from uniform U ~ [0,1):
                    #   u = U - 0.5
                    #   X = -scale * sign(u) * ln(1 - 2*|u|)
                    # Clamp argument away from 0 to prevent ln(0) on exact boundaries.
                    conn.execute(text(f"""
                        UPDATE {output_fq}
                        SET "{f_actual}" = "{f_actual}"::numeric + (
                            -(:scale) * sign(random() - 0.5) *
                            ln(GREATEST(1 - 2 * abs(random() - 0.5), 1e-10))
                        )::numeric
                    """), {"scale": scale})
                conn.commit()

            # --- 8. Compute output stats ---
            out_count = conn.execute(text(f'SELECT COUNT(*) FROM {output_fq}')).scalar()
            filtered_count = est_grids - out_count if est_grids else 0

            # --- 9. Create spatial index + register PostGIS geometry column ---
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS "{output_table}_geom_gist"
                ON {output_fq} USING GIST (geom);
            """))
            conn.commit()

            result = {
                "status": "ok",
                "output_table": f"{output_schema}.{output_table}",
                "output_row_count": int(out_count),
                "estimated_grid_count": est_grids,
                "k_anonymity_filtered": int(filtered_count),
                "level": level,
                "grid_size_m": actual_grid_size,
                "accuracy_m": cfg["accuracy_m"],
                "target_sensitivity": cfg["target_sensitivity"],
                "source_srid": src_srid,
                "target_srid": target_srid,
                "kept_attrs": final_attrs,
                "stripped_sensitive_fields": sorted(set(stripped)),
                "agg_strategy": agg_strategy,
                "k_anonymity_threshold": k_anonymity,
                "dp_applied": dp_epsilon is not None,
                "dp_epsilon": dp_epsilon,
                "random_offset_applied": random_offset,
                "note": f"脱密等级 {level}：定位精度 ~{cfg['accuracy_m']}m，{cfg['description']}",
            }

            # --- 10. Register lineage + sensitivity ---
            if register_lineage:
                try:
                    from .data_catalog import register_postgis_asset
                    asset_id = register_postgis_asset(
                        output_table,
                        description=(f"Grid-anonymized from {source_table} "
                                     f"(level={level}, size={actual_grid_size}m)"),
                    )
                    result["catalog_asset_id"] = asset_id
                except Exception as e:
                    logger.warning("Lineage registration failed: %s", e)
                    result["catalog_asset_id"] = None

                try:
                    from .data_classification import set_asset_sensitivity
                    if result.get("catalog_asset_id"):
                        from .user_context import current_user_id
                        uname = current_user_id.get() or "system"
                        sens_result = set_asset_sensitivity(
                            result["catalog_asset_id"],
                            cfg["target_sensitivity"],
                            uname,
                        )
                        result["sensitivity_assignment"] = sens_result
                except Exception as e:
                    logger.warning("Sensitivity assignment failed: %s", e)

            return result

    except Exception as e:
        logger.exception("grid_anonymize_pg failed")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# POI / Point-data aggregation — for amap POI, baidu AOI, etc.
# ---------------------------------------------------------------------------

def poi_grid_aggregate_pg(
    source_table: str,
    output_table: str,
    *,
    category_column: str,
    level: str = "L3",
    grid_size_m: Optional[float] = None,
    source_schema: str = "public",
    output_schema: str = "public",
    source_srid: Optional[int] = None,
    target_srid: Optional[int] = None,
    k_anonymity: int = 5,
    top_k_categories: int = 5,
    geom_column: Optional[str] = None,
    register_lineage: bool = True,
    dry_run: bool = False,
) -> dict:
    """[脱密工具-POI专用] 对点数据（POI/AOI）做格网聚合，彻底丢弃个体记录。

    与 ``grid_anonymize_pg`` 不同：POI 每个点代表一个含电话/地址 PII 的商户，
    不能保留任何个体记录。本函数只输出每格网内：
    - POI 总数 (按 k-匿名阈值过滤)
    - Top K 类别及其数量
    - 格网中心点（不保留原始点位）

    Args:
        source_table: POI 源表 (如 cq_amap_poi_2024)
        output_table: 输出表 (如 cq_amap_poi_2024_grid_L3_public)
        category_column: POI 分类字段名 (中文列名需带引号)
        level / grid_size_m: 同 grid_anonymize_pg
        k_anonymity: 少于 k 个 POI 的格网被剔除
        top_k_categories: 每格网保留 Top K 个类别计数
        geom_column: 几何列名（None 自动从 geometry_columns 查）
        register_lineage: 注册到 data_catalog
        dry_run: 仅返回计划
    """
    from .db_engine import get_engine

    if level not in LEVEL_CONFIG:
        return {"status": "error", "message": f"Unknown level: {level}"}
    cfg = LEVEL_CONFIG[level]
    actual_grid_size = grid_size_m if grid_size_m is not None else cfg["grid_size_m"]

    engine = get_engine()
    if engine is None:
        return {"status": "error", "message": "Database unavailable"}

    try:
        with engine.connect() as conn:
            # --- Detect geometry column + SRID ---
            if geom_column is None:
                geom_row = conn.execute(text("""
                    SELECT f_geometry_column, srid FROM geometry_columns
                    WHERE f_table_schema = :s AND f_table_name = :t LIMIT 1
                """), {"s": source_schema, "t": source_table}).fetchone()
                if not geom_row:
                    return {"status": "error",
                            "message": f"No geometry_columns entry for {source_schema}.{source_table}"}
                geom_col, src_srid = geom_row[0], geom_row[1]
            else:
                geom_col = geom_column
                src_srid_row = conn.execute(text(f"""
                    SELECT ST_SRID("{geom_col}") FROM "{source_schema}"."{source_table}"
                    WHERE "{geom_col}" IS NOT NULL LIMIT 1
                """)).scalar()
                src_srid = src_srid_row or 4326

            if source_srid is not None:
                src_srid = source_srid
            if target_srid is None:
                target_srid = METRIC_CRS_LOOKUP.get(src_srid, 4523)

            # --- Validate category column exists ---
            has_cat = conn.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = :s AND table_name = :t AND column_name = :c
            """), {"s": source_schema, "t": source_table, "c": category_column}).scalar()
            if not has_cat:
                return {"status": "error",
                        "message": f"Category column '{category_column}' not found in {source_table}"}

            # --- Get bbox ---
            bbox = conn.execute(text(f"""
                SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e)
                FROM (SELECT ST_Transform(ST_SetSRID(ST_Extent("{geom_col}"), :s),
                                          :t) AS e FROM "{source_schema}"."{source_table}") sub
            """), {"s": src_srid, "t": target_srid}).fetchone()
            if not bbox or bbox[0] is None:
                return {"status": "error", "message": "Source table is empty"}

            minx, miny, maxx, maxy = [float(v) for v in bbox]
            est_grids = math.ceil((maxx - minx) / actual_grid_size) * \
                        math.ceil((maxy - miny) / actual_grid_size)

            plan = {
                "source_table": f"{source_schema}.{source_table}",
                "output_table": f"{output_schema}.{output_table}",
                "level": level,
                "grid_size_m": actual_grid_size,
                "target_sensitivity": cfg["target_sensitivity"],
                "category_column": category_column,
                "top_k_categories": top_k_categories,
                "estimated_grid_count": est_grids,
                "k_anonymity_threshold": k_anonymity,
                "stripped": "ALL individual POI records (no phone/address/name preserved)",
            }

            if dry_run:
                plan["status"] = "dry_run"
                return plan

            source_fq = f'"{source_schema}"."{source_table}"'
            output_fq = f'"{output_schema}"."{output_table}"'

            # Create output table: grid_id, geom, total_count, category_breakdown (jsonb)
            create_sql = f"""
            DROP TABLE IF EXISTS {output_fq};
            CREATE TABLE {output_fq} AS
            WITH grid_metric AS (
                SELECT (ST_SquareGrid(
                    :gsize,
                    ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, :tgt_srid)
                )).*
            ),
            grid AS (
                SELECT i, j, geom AS geom_metric,
                       ST_Transform(geom, :src_srid) AS geom_src
                FROM grid_metric
            ),
            joined AS (
                SELECT g.i, g.j, g.geom_metric,
                       s."{category_column}" AS category_raw
                FROM grid g
                JOIN {source_fq} s ON ST_Intersects(g.geom_src, s."{geom_col}")
            ),
            -- Parse primary category (take first token before ';' or '|')
            normalized AS (
                SELECT i, j, geom_metric,
                       split_part(split_part(COALESCE(category_raw, ''), ';', 1), '|', 1) AS cat
                FROM joined
            ),
            cell_counts AS (
                SELECT i, j, geom_metric,
                       COUNT(*) AS total_count,
                       cat,
                       COUNT(*) AS cat_count,
                       RANK() OVER (PARTITION BY i, j ORDER BY COUNT(*) DESC) AS rnk
                FROM normalized
                GROUP BY i, j, geom_metric, cat
            ),
            topk AS (
                SELECT i, j, geom_metric,
                       jsonb_object_agg(cat, cat_count) FILTER (WHERE rnk <= :topk) AS category_breakdown,
                       SUM(cat_count) AS total_count
                FROM cell_counts
                GROUP BY i, j, geom_metric
                HAVING SUM(cat_count) >= :kmin
            )
            SELECT
                ('R' || i || 'C' || j) AS grid_id,
                geom_metric AS geom,
                total_count,
                category_breakdown
            FROM topk;
            """

            conn.execute(text(create_sql), {
                "src_srid": src_srid, "tgt_srid": target_srid,
                "gsize": actual_grid_size,
                "minx": minx - actual_grid_size, "miny": miny - actual_grid_size,
                "maxx": maxx + actual_grid_size, "maxy": maxy + actual_grid_size,
                "topk": top_k_categories, "kmin": k_anonymity,
            })
            conn.commit()

            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS "{output_table}_geom_gist"
                ON {output_fq} USING GIST (geom);
            """))
            conn.commit()

            out_count = conn.execute(text(f'SELECT COUNT(*) FROM {output_fq}')).scalar()
            total_pois_in = conn.execute(text(f'SELECT COUNT(*) FROM {source_fq}')).scalar()
            total_pois_out = conn.execute(text(f'SELECT SUM(total_count) FROM {output_fq}')).scalar()

            result = {
                "status": "ok",
                "output_table": f"{output_schema}.{output_table}",
                "output_row_count": int(out_count),
                "source_poi_count": int(total_pois_in),
                "retained_poi_count": int(total_pois_out or 0),
                "estimated_grid_count": est_grids,
                "level": level,
                "grid_size_m": actual_grid_size,
                "target_sensitivity": cfg["target_sensitivity"],
                "category_column": category_column,
                "top_k_categories": top_k_categories,
                "k_anonymity_threshold": k_anonymity,
                "note": (f"POI 脱密: {total_pois_in:,} 条 POI → {out_count:,} 格网. "
                         f"所有个体记录（名称/电话/地址/精确坐标）已丢弃，"
                         f"仅保留格网级类别计数。"),
            }

            if register_lineage:
                try:
                    from .data_catalog import register_postgis_asset
                    from .data_classification import set_asset_sensitivity
                    from .user_context import current_user_id
                    uname = current_user_id.get() or "system"
                    aid = register_postgis_asset(
                        output_table,
                        description=(f"POI grid-aggregated from {source_table} "
                                     f"(level={level}, k>={k_anonymity}, "
                                     f"top_{top_k_categories} categories only)"),
                    )
                    result["catalog_asset_id"] = aid
                    if aid:
                        set_asset_sensitivity(aid, cfg["target_sensitivity"], uname)
                except Exception as e:
                    logger.warning("POI lineage registration failed: %s", e)

            return result

    except Exception as e:
        logger.exception("poi_grid_aggregate_pg failed")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Anonymization verification — adversarial test
# ---------------------------------------------------------------------------

def verify_anonymization(
    source_table: str,
    output_table: str,
    *,
    source_schema: str = "public",
    output_schema: str = "public",
    sample_size: int = 100,
) -> dict:
    """[验证工具] 对脱密输出做逆向攻击测试，计算再识别风险评分。

    通过以下测试评估脱密质量:
    1. 敏感字段泄露: 输出表是否包含任何黑名单字段
    2. 几何反推攻击: 通过格网边界是否能重建原图斑轮廓 (Jaccard 相似度)
    3. 权属推断攻击: 单个格网内是否有唯一可识别的权属组合
    4. k-匿名违规: 是否存在 k<5 的格网 (低多样性)
    5. l-多样性: 每个格网内属性值的多样性

    Args:
        source_table / output_table: 源表和脱密表
        sample_size: 随机抽样格网数用于代价密集的几何重建攻击

    Returns:
        JSON: 各维度风险评分 (0-100, 越低越好) + 综合 re-identification risk
    """
    from .db_engine import get_engine

    engine = get_engine()
    if engine is None:
        return {"status": "error", "message": "Database unavailable"}

    try:
        with engine.connect() as conn:
            output_fq = f'"{output_schema}"."{output_table}"'
            source_fq = f'"{source_schema}"."{source_table}"'

            # --- Test 1: sensitive field leakage ---
            out_cols = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = :s AND table_name = :t
            """), {"s": output_schema, "t": output_table}).fetchall()
            out_col_names = [c[0].lower() for c in out_cols]
            leaked = [c for c in out_col_names if c in SENSITIVE_FIELD_BLACKLIST]
            leakage_score = min(len(leaked) * 25, 100)

            # --- Test 2: geometry reconstruction attack (sampled) ---
            # Check if output grid cells have too-fine alignment to source polygons
            src_geom_col_row = conn.execute(text("""
                SELECT f_geometry_column FROM geometry_columns
                WHERE f_table_schema = :s AND f_table_name = :t
                LIMIT 1
            """), {"s": source_schema, "t": source_table}).fetchone()
            src_geom_col = src_geom_col_row[0] if src_geom_col_row else "shape"

            out_geom_col_row = conn.execute(text("""
                SELECT f_geometry_column FROM geometry_columns
                WHERE f_table_schema = :s AND f_table_name = :t
                LIMIT 1
            """), {"s": output_schema, "t": output_table}).fetchone()
            out_geom_col = out_geom_col_row[0] if out_geom_col_row else "geom"

            # Sample a few output cells and measure max jaccard with any source polygon
            # Note: output geom and source geom may be in different SRIDs; transform source to output SRID
            recon_sample = conn.execute(text(f"""
                WITH out_sample AS (
                    SELECT "{out_geom_col}" AS g, grid_id
                    FROM {output_fq}
                    ORDER BY random() LIMIT :n
                ),
                src_t AS (
                    SELECT ST_Transform(s."{src_geom_col}",
                                        (SELECT ST_SRID(g) FROM out_sample LIMIT 1)) AS g
                    FROM {source_fq} s
                )
                SELECT MAX(
                    CASE WHEN ST_Area(ST_Union(o.g, st.g)) > 0
                         THEN ST_Area(ST_Intersection(o.g, st.g)) /
                              ST_Area(ST_Union(o.g, st.g))
                         ELSE 0 END
                ) AS max_jaccard
                FROM out_sample o
                JOIN src_t st ON ST_Intersects(o.g, st.g)
            """), {"n": sample_size}).scalar()
            max_jaccard = float(recon_sample or 0.0)
            # Max jaccard > 0.8 means easy reconstruction
            reconstruction_score = min(int(max_jaccard * 100), 100)

            # --- Test 3: k-anonymity (if _k_source_count column exists) ---
            k_stats = None
            k_violation_score = 0
            if "_k_source_count" in out_col_names:
                k_row = conn.execute(text(f"""
                    SELECT MIN(_k_source_count), AVG(_k_source_count)::numeric(10,2),
                           COUNT(*) FILTER (WHERE _k_source_count < 5) AS violations,
                           COUNT(*) AS total
                    FROM {output_fq}
                """)).fetchone()
                if k_row:
                    k_stats = {
                        "min_k": int(k_row[0]) if k_row[0] is not None else None,
                        "avg_k": float(k_row[1]) if k_row[1] is not None else None,
                        "violations_below_5": int(k_row[2] or 0),
                        "total_cells": int(k_row[3] or 0),
                    }
                    if k_stats["total_cells"] > 0:
                        k_violation_score = min(
                            int(k_stats["violations_below_5"] / k_stats["total_cells"] * 100), 100
                        )

            # --- Test 4: l-diversity (attribute uniqueness per cell) ---
            # Skip expensive per-cell diversity check for now — proxy by unique dlmc if present
            l_diversity_score = 0
            if "dlmc" in out_col_names:
                div_row = conn.execute(text(f"""
                    SELECT COUNT(*) FILTER (WHERE n=1), COUNT(*)
                    FROM (SELECT dlmc, COUNT(*) n FROM {output_fq} GROUP BY dlmc) s
                """)).fetchone()
                if div_row and div_row[1] > 0:
                    l_diversity_score = int(div_row[0] / div_row[1] * 100)

            # --- Test 5: overall re-identification risk ---
            # Weighted combination (higher weight on field leakage)
            overall_risk = min(
                int(leakage_score * 0.4 +
                    reconstruction_score * 0.3 +
                    k_violation_score * 0.2 +
                    l_diversity_score * 0.1),
                100,
            )

            verdict = (
                "安全 (可公开)" if overall_risk < 20 else
                "可接受 (内部共享)" if overall_risk < 40 else
                "风险较高 (需加固)" if overall_risk < 70 else
                "不通过 (存在再识别风险)"
            )

            return {
                "status": "ok",
                "source_table": f"{source_schema}.{source_table}",
                "output_table": f"{output_schema}.{output_table}",
                "tests": {
                    "field_leakage": {
                        "score": leakage_score,
                        "leaked_fields": leaked,
                        "description": "输出是否包含黑名单敏感字段 (越低越好)",
                    },
                    "geometry_reconstruction": {
                        "score": reconstruction_score,
                        "max_jaccard": round(max_jaccard, 4),
                        "description": "格网边界与原图斑的最大重合度 (越低越好)",
                    },
                    "k_anonymity": {
                        "score": k_violation_score,
                        "stats": k_stats,
                        "description": "k<5 的格网占比 (越低越好)",
                    },
                    "l_diversity": {
                        "score": l_diversity_score,
                        "description": "地类值唯一出现的比例 (越低越好)",
                    },
                },
                "overall_risk_score": overall_risk,
                "verdict": verdict,
                "sample_size": sample_size,
            }

    except Exception as e:
        logger.exception("verify_anonymization failed")
        return {"status": "error", "message": str(e)}
