"""Presentation helpers for NL2SQL chat output and map handoff."""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("data_agent.nl2sql_presentation")


def parse_nl2sql_payload(raw: str | dict[str, Any]) -> dict[str, Any] | None:
    """Parse the structured NL2SQL payload returned by run_nl2semantic2sql."""
    if isinstance(raw, dict):
        if isinstance(raw.get("result"), str):
            return parse_nl2sql_payload(raw["result"])
        return raw
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict):
        return parse_nl2sql_payload(parsed)
    return None


def format_nl2sql_result_for_chat(
    raw: str | dict[str, Any],
    *,
    question: str = "",
    map_summary: str = "",
) -> str | None:
    """Convert raw NL2SQL JSON into concise Chinese Markdown for chat."""
    payload = parse_nl2sql_payload(raw)
    if not payload:
        return None

    status = payload.get("status") or "unknown"
    execution = payload.get("execution") or payload
    sql = (payload.get("sql") or "").strip()
    semantic = payload.get("semantic") or {}
    corrections = payload.get("corrections") or []
    engine = payload.get("execution_engine") or execution.get("engine") or "postgis"
    dialect = payload.get("dialect") or execution.get("dialect") or "postgres"

    lines: list[str] = ["### NL2SQL 查询结果", ""]
    lines.append("工具调用：`run_nl2semantic2sql`")
    engine_label = "治理数据湖（DuckDB → GeoParquet）" if engine == "lake" else "PostgreSQL/PostGIS"
    lines.append(f"执行引擎：**{engine_label}**；SQL 方言：`{dialect}`")
    if question:
        lines.append(f"参数 `user_question`：{question}")
    lines.append("")

    if status == "ok":
        count_info = _extract_count_value(execution)
        if count_info:
            label, value = count_info
            display_label = _friendly_count_label(label, question=question, sql=sql)
            lines.append(f"**{display_label}：{value}**")
            rows = execution.get("rows")
            if rows == 1:
                lines.append("")
                lines.append("这是聚合字段的数值，不是“返回 1 行”的行数说明。")
        else:
            message = execution.get("message") or "查询成功"
            rows = execution.get("rows")
            rows_text = f"，返回 {rows} 行" if isinstance(rows, int) else ""
            lines.append(f"**{message}{rows_text}**")
    elif status == "rejected":
        lines.append(f"**查询被安全策略拒绝：{payload.get('error') or '未知原因'}**")
    else:
        err = payload.get("error") or execution.get("error") or "未知错误"
        lines.append(f"**查询失败：{err}**")

    if map_summary:
        lines.extend(["", map_summary])

    if sql:
        lines.extend(["", "**执行 SQL**", "```sql", sql, "```"])

    candidates = semantic.get("candidate_tables") or []
    if candidates:
        lines.extend(["", f"候选表：`{'`, `'.join(candidates)}`"])

    source_bindings = execution.get("source_bindings") or []
    if engine == "lake" and source_bindings:
        projections = [
            str(binding.get("projection_id") or binding.get("projection_path") or "")
            for binding in source_bindings
            if binding.get("projection_id") or binding.get("projection_path")
        ]
        if projections:
            lines.append(f"湖上治理投影：`{'`, `'.join(projections)}`")

    few_shot_count = semantic.get("few_shot_count")
    hint_stats = semantic.get("hint_stats") or {}
    family = hint_stats.get("family")
    details: list[str] = []
    if few_shot_count is not None:
        details.append(f"few-shot: {few_shot_count}")
    if family:
        details.append(f"模型族: {family}")
    if corrections:
        details.append(f"修正: {', '.join(str(c) for c in corrections)}")
    if details:
        lines.append("；".join(details))

    return "\n".join(lines)


def build_bridge_building_map_update(
    raw: str | dict[str, Any],
    *,
    question: str = "",
    upload_dir: str | None = None,
) -> dict[str, Any] | None:
    """Build GeoJSON layers for the CQ bridge/building intersection count demo."""
    payload = parse_nl2sql_payload(raw)
    if not payload or payload.get("status") != "ok":
        return None
    sql = payload.get("sql") or ""
    if not _is_bridge_building_intersection_query(question, sql):
        return None

    try:
        from data_agent.database_tools import _inject_user_context
        from data_agent.db_engine import get_engine
        from data_agent.user_context import get_user_upload_dir

        target_dir = upload_dir or get_user_upload_dir()
        os.makedirs(target_dir, exist_ok=True)
        suffix = uuid.uuid4().hex[:8]
        building_name = f"nl2sql_bridge_buildings_{suffix}.geojson"
        road_name = f"nl2sql_bridge_roads_{suffix}.geojson"
        building_path = os.path.join(target_dir, building_name)
        road_path = os.path.join(target_dir, road_name)

        engine = get_engine(readonly=True)
        if engine is None:
            return None

        with engine.connect() as conn:
            _inject_user_context(conn)
            building_rows = conn.execute(text(_BRIDGE_BUILDING_FEATURE_SQL)).mappings().all()
            road_rows = conn.execute(text(_BRIDGE_ROAD_FEATURE_SQL)).mappings().all()
            view_row = conn.execute(text(_BRIDGE_MAP_VIEW_SQL)).mappings().first()

        if not building_rows:
            return None

        building_fc = _rows_to_feature_collection(
            building_rows,
            property_keys=("building_id", "floor", "area_m2", "result_type"),
        )
        road_fc = _rows_to_feature_collection(
            road_rows,
            property_keys=("osm_id", "name", "fclass", "bridge", "result_type"),
        )
        _write_geojson(building_path, building_fc)
        _write_geojson(road_path, road_fc)

        center = [29.56, 106.55]
        zoom = 11
        if view_row and view_row.get("lat") is not None and view_row.get("lng") is not None:
            center = [float(view_row["lat"]), float(view_row["lng"])]
            zoom = _estimate_zoom_from_extent(view_row)

        count_info = _extract_count_value(payload.get("execution") or {})
        golden_count = count_info[1] if count_info else None
        building_layer_name = f"相交建筑物轮廓 ({len(building_rows)} 个)"
        if golden_count is not None and golden_count != len(building_rows):
            building_layer_name = f"相交建筑几何行 ({len(building_rows)} 个)"

        return {
            "layers": [
                {
                    "name": building_layer_name,
                    "type": "polygon",
                    "geojson": building_name,
                    "style": {
                        "color": "#be123c",
                        "weight": 3,
                        "opacity": 0.95,
                        "fillColor": "#e11d48",
                        "fillOpacity": 0.55,
                    },
                },
                {
                    "name": f"bridge=T 道路线 ({len(road_rows)} 条)",
                    "type": "line",
                    "geojson": road_name,
                    "style": {
                        "color": "#2563eb",
                        "weight": 5,
                        "opacity": 0.9,
                    },
                },
            ],
            "center": center,
            "zoom": zoom,
            "summary": {
                "golden_building_count": golden_count,
                "building_feature_count": len(building_rows),
                "bridge_road_count": len(road_rows),
            },
        }
    except Exception as exc:
        logger.warning("Failed to build NL2SQL bridge/building map update: %s", exc)
        return None


def build_longest_bridge_poi_map_update(
    raw: str | dict[str, Any],
    *,
    question: str = "",
    upload_dir: str | None = None,
) -> dict[str, Any] | None:
    """Build map layers for the locked longest-bridge/100m/AMap-POI query."""
    payload = parse_nl2sql_payload(raw)
    if not payload or payload.get("status") != "ok":
        return None
    sql = payload.get("sql") or ""
    if not _is_longest_bridge_poi_query(question, sql):
        return None

    count_info = _extract_count_value(payload.get("execution") or {})
    if not count_info or not isinstance(count_info[1], (int, float)):
        return None
    scalar_poi_count = int(count_info[1])

    try:
        from data_agent.database_tools import _inject_user_context
        from data_agent.db_engine import get_engine
        from data_agent.user_context import get_user_upload_dir

        target_dir = upload_dir or get_user_upload_dir()
        os.makedirs(target_dir, exist_ok=True)
        engine = get_engine(readonly=True)
        if engine is None:
            return None

        # One SQL statement gives every layer a single, consistent PostGIS snapshot.
        with engine.connect() as conn:
            _inject_user_context(conn)
            rows = conn.execute(text(_LONGEST_BRIDGE_POI_MAP_SQL)).mappings().all()

        poi_rows = [row for row in rows if row.get("feature_group") == "poi"]
        bridge_rows = [row for row in rows if row.get("feature_group") == "bridge"]
        buffer_rows = [row for row in rows if row.get("feature_group") == "buffer"]
        if (
            len(poi_rows) != scalar_poi_count
            or len(bridge_rows) != 1
            or len(buffer_rows) != 1
        ):
            logger.warning(
                "Skipping longest-bridge map because scalar/features disagree: "
                "scalar=%s poi=%s bridge=%s buffer=%s",
                scalar_poi_count,
                len(poi_rows),
                len(bridge_rows),
                len(buffer_rows),
            )
            return None

        suffix = uuid.uuid4().hex[:8]
        poi_name = f"nl2sql_longest_bridge_pois_{suffix}.geojson"
        bridge_name = f"nl2sql_longest_bridge_{suffix}.geojson"
        buffer_name = f"nl2sql_longest_bridge_100m_{suffix}.geojson"
        _write_geojson(
            os.path.join(target_dir, poi_name),
            _rows_to_feature_collection(
                poi_rows,
                property_keys=(
                    "poi_id", "poi_name", "address", "poi_type",
                    "distance_m", "result_type",
                ),
            ),
        )
        _write_geojson(
            os.path.join(target_dir, bridge_name),
            _rows_to_feature_collection(
                bridge_rows,
                property_keys=(
                    "osm_id", "bridge_name", "fclass", "bridge",
                    "length_m", "result_type",
                ),
            ),
        )
        _write_geojson(
            os.path.join(target_dir, buffer_name),
            _rows_to_feature_collection(
                buffer_rows,
                property_keys=(
                    "osm_id", "bridge_name", "length_m", "radius_m", "result_type",
                ),
            ),
        )

        view_row = rows[0]
        center = [float(view_row["center_lat"]), float(view_row["center_lng"])]
        zoom = _estimate_zoom_from_extent(view_row)
        bridge_row = bridge_rows[0]
        return {
            "schema": "map_update.v1",
            "layers": [
                {
                    "name": "最长桥梁 100 米范围",
                    "type": "polygon",
                    "geojson": buffer_name,
                    "style": {
                        "color": "#f59e0b",
                        "weight": 2,
                        "opacity": 0.9,
                        "fillColor": "#fbbf24",
                        "fillOpacity": 0.2,
                    },
                },
                {
                    "name": "道路网络中最长桥梁",
                    "type": "line",
                    "geojson": bridge_name,
                    "style": {
                        "color": "#dc2626",
                        "weight": 6,
                        "opacity": 1.0,
                    },
                },
                {
                    "name": f"100 米范围内高德 POI ({len(poi_rows)} 个)",
                    "type": "point",
                    "geojson": poi_name,
                    "style": {
                        "color": "#ffffff",
                        "weight": 2,
                        "opacity": 1.0,
                        "fillColor": "#2563eb",
                        "fillOpacity": 0.9,
                        "radius": 6,
                    },
                },
            ],
            "center": center,
            "zoom": zoom,
            "summary": {
                "query_type": "longest_bridge_poi_100m",
                "scalar_poi_count": scalar_poi_count,
                "poi_feature_count": len(poi_rows),
                "bridge_feature_count": len(bridge_rows),
                "buffer_feature_count": len(buffer_rows),
                "distance_m": 100,
                "bridge_osm_id": bridge_row.get("osm_id"),
                "bridge_name": bridge_row.get("bridge_name"),
                "bridge_length_m": _jsonable(bridge_row.get("length_m")),
                "source_tables": ["cq_osm_roads_2021", "cq_amap_poi_2024"],
                "geometry_snapshot": "single_postgis_statement",
            },
        }
    except Exception as exc:
        logger.warning("Failed to build longest-bridge POI map update: %s", exc)
        return None


def build_nl2sql_map_update(
    raw: str | dict[str, Any],
    *,
    question: str = "",
    upload_dir: str | None = None,
) -> dict[str, Any] | None:
    """Dispatch optional demo map layers for NL2SQL scalar results.

    The current map builders are a legacy Chongqing demonstration plugin, not
    a generic result-to-map renderer. Keep them disabled for arbitrary product
    data unless an operator explicitly enables ``GDA_NL2SQL_DEMO_MAPS=1``.
    """
    if os.environ.get("GDA_NL2SQL_DEMO_MAPS", "0").strip().casefold() not in {
        "1",
        "true",
        "on",
        "enabled",
    }:
        return None
    map_update = build_longest_bridge_poi_map_update(
        raw,
        question=question,
        upload_dir=upload_dir,
    )
    if map_update:
        return map_update
    return build_bridge_building_map_update(
        raw,
        question=question,
        upload_dir=upload_dir,
    )


def describe_map_update(map_update: dict[str, Any] | None) -> str:
    if not map_update:
        return ""
    summary = map_update.get("summary") or {}
    if summary.get("query_type") == "longest_bridge_poi_100m":
        return (
            f"已默认加载地图：高德 POI {summary.get('poi_feature_count')} 个、"
            f"最长桥梁 1 条及其 {summary.get('distance_m')} 米范围；"
            "三个图层来自同一 PostGIS 查询快照。"
        )
    golden_count = summary.get("golden_building_count")
    feature_count = summary.get("building_feature_count")
    road_count = summary.get("bridge_road_count")
    if feature_count is None or road_count is None:
        return "已生成地图图层，可在右侧地图中查看空间结果。"
    if golden_count is not None and golden_count != feature_count:
        return (
            f"已生成地图图层：golden SQL 按 `COUNT(DISTINCT b.\"Id\")` 计为 {golden_count}；"
            f"右侧地图展示满足相交条件的建筑几何行 {feature_count} 个，"
            f"以及相关 `bridge=T` 道路线 {road_count} 条。"
        )
    return (
        f"已生成地图图层：相交建筑物轮廓 {feature_count} 个，"
        f"相关 `bridge=T` 道路线 {road_count} 条，可在右侧地图中直观查看。"
    )


def _extract_count_value(execution: dict[str, Any]) -> tuple[str, Any] | None:
    data = execution.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        return None
    row = data[0]
    preferred = [
        "building_count", "count", "cnt", "total", "num", "数量",
        "COUNT", "COUNT(*)", "count_1",
    ]
    for key in preferred:
        if key in row:
            return key, row[key]
    for key, value in row.items():
        if re.search(r"(count|cnt|total|num|数量)", str(key), re.IGNORECASE):
            return str(key), value
    if len(row) == 1:
        key, value = next(iter(row.items()))
        if isinstance(value, (int, float)):
            return str(key), value
    return None


def _friendly_count_label(label: str, *, question: str, sql: str) -> str:
    joined = f"{question}\n{sql}".lower()
    is_count = _is_count_metric_label(label)
    if is_count and ("poi" in joined or "高德" in question):
        return "POI数量"
    if "building_count" in label.lower() or (
        ("建筑" in question or "cq_buildings_2021" in joined)
        and ("桥" in question or "bridge" in joined)
    ):
        return "建筑物轮廓数量"
    if _is_length_metric_result(label, joined, count_metric=is_count):
        length_unit_tokens = ("公里", "千米", "kilometer", "kilometre", "_km", " km")
        if any(token in joined for token in length_unit_tokens):
            if "道路" in question or "road" in joined:
                return "道路总长度（公里）"
            return "总长度（公里）"
        return "道路总长度" if "道路" in question or "road" in joined else "总长度"
    if "road" in label.lower() or "道路" in question:
        return "道路数量"
    return "数量"


def _is_count_metric_label(label: str) -> bool:
    label_low = (label or "").lower()
    return bool(re.search(r"(count|cnt|num|数量)", label_low))


def _is_length_metric_result(label: str, joined: str, *, count_metric: bool = False) -> bool:
    label_low = (label or "").lower()
    if count_metric:
        return False
    return (
        any(token in label_low for token in ("length", "len", "km", "meter", "metre"))
        or "st_length" in (joined or "")
        or any(token in (joined or "") for token in ("总长度", "长度", "公里", "千米"))
    )


def _is_bridge_building_intersection_query(question: str, sql: str) -> bool:
    joined = f"{question}\n{sql}".lower()
    has_building = "建筑" in question or "cq_buildings_2021" in joined
    has_bridge = "桥" in question or "bridge" in joined
    has_intersection = (
        "相交" in question
        or "intersects" in joined
        or "st_intersects" in joined
    )
    has_cq_roads = "cq_osm_roads_2021" in joined or "cq_osm_roads" in joined
    return has_building and has_bridge and has_intersection and has_cq_roads


def _is_longest_bridge_poi_query(question: str, sql: str) -> bool:
    normalized_question = re.sub(r"[\s。！？?!，,；;：:]+", "", question or "").lower()
    normalized_question = re.sub(r"^@nl2sql", "", normalized_question)
    if normalized_question != "统计距离道路网络中最长桥梁100米范围内的高德poi数量":
        return False

    sql_low = re.sub(r"\s+", " ", sql or "").lower()
    required_sql_clues = (
        "cq_osm_roads_2021",
        "cq_amap_poi_2024",
        "bridge",
        "st_length",
        "geography",
        "order by",
        "desc",
        "limit 1",
        "st_dwithin",
        "100",
        "count",
    )
    return all(clue in sql_low for clue in required_sql_clues)


def _rows_to_feature_collection(
    rows: list[Any],
    *,
    property_keys: tuple[str, ...],
) -> dict[str, Any]:
    features = []
    for row in rows:
        geom = row.get("geometry_json")
        if not geom:
            continue
        if isinstance(geom, str):
            geometry = json.loads(geom)
        else:
            geometry = geom
        properties = {key: _jsonable(row.get(key)) for key in property_keys if key in row}
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": properties,
        })
    return {"type": "FeatureCollection", "features": features}


def _write_geojson(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _estimate_zoom_from_extent(extent: Any) -> int:
    try:
        min_lng = float(extent.get("min_lng"))
        min_lat = float(extent.get("min_lat"))
        max_lng = float(extent.get("max_lng"))
        max_lat = float(extent.get("max_lat"))
    except Exception:
        return 11
    span = max(abs(max_lng - min_lng), abs(max_lat - min_lat))
    if span >= 1.0:
        return 8
    if span >= 0.5:
        return 9
    if span >= 0.18:
        return 10
    if span >= 0.09:
        return 11
    if span >= 0.045:
        return 12
    if span >= 0.022:
        return 13
    if span >= 0.011:
        return 14
    if span >= 0.006:
        return 15
    return 16


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        import decimal
        if isinstance(value, decimal.Decimal):
            return float(value)
    except Exception:
        pass
    return str(value)


_BRIDGE_BUILDING_FEATURE_SQL = """
WITH matched_buildings AS (
    SELECT DISTINCT b."Id" AS building_id, b."Floor" AS floor, b.geometry
    FROM cq_buildings_2021 AS b
    JOIN cq_osm_roads_2021 AS r
      ON ST_Intersects(b.geometry, r.geometry)
    WHERE r.bridge = 'T'
)
SELECT
    building_id,
    floor,
    ROUND(ST_Area(geometry::geography)::numeric, 2) AS area_m2,
    'matched_building' AS result_type,
    ST_AsGeoJSON(geometry)::text AS geometry_json
FROM matched_buildings
ORDER BY building_id
"""

_BRIDGE_ROAD_FEATURE_SQL = """
WITH matched_buildings AS (
    SELECT DISTINCT b."Id" AS building_id, b.geometry
    FROM cq_buildings_2021 AS b
    JOIN cq_osm_roads_2021 AS r
      ON ST_Intersects(b.geometry, r.geometry)
    WHERE r.bridge = 'T'
)
SELECT DISTINCT
    r.osm_id,
    r.name,
    r.fclass,
    r.bridge,
    'bridge_road' AS result_type,
    ST_AsGeoJSON(r.geometry)::text AS geometry_json
FROM cq_osm_roads_2021 AS r
JOIN matched_buildings AS b
  ON ST_Intersects(b.geometry, r.geometry)
WHERE r.bridge = 'T'
ORDER BY r.osm_id
"""

_BRIDGE_MAP_VIEW_SQL = """
WITH matched_buildings AS (
    SELECT DISTINCT b."Id" AS building_id, b."Floor" AS floor, b.geometry
    FROM cq_buildings_2021 AS b
    JOIN cq_osm_roads_2021 AS r
      ON ST_Intersects(b.geometry, r.geometry)
    WHERE r.bridge = 'T'
),
matched_roads AS (
    SELECT DISTINCT r.osm_id, r.geometry
    FROM cq_osm_roads_2021 AS r
    JOIN matched_buildings AS b
      ON ST_Intersects(b.geometry, r.geometry)
    WHERE r.bridge = 'T'
),
features AS (
    SELECT geometry FROM matched_buildings
    UNION ALL
    SELECT geometry FROM matched_roads
),
extent AS (
    SELECT ST_Envelope(ST_Collect(geometry)) AS geometry
    FROM features
)
SELECT
    ST_Y(ST_Centroid(ST_Collect(geometry))) AS lat,
    ST_X(ST_Centroid(ST_Collect(geometry))) AS lng,
    ST_XMin(Box3D(ST_Collect(geometry))) AS min_lng,
    ST_YMin(Box3D(ST_Collect(geometry))) AS min_lat,
    ST_XMax(Box3D(ST_Collect(geometry))) AS max_lng,
    ST_YMax(Box3D(ST_Collect(geometry))) AS max_lat
FROM extent
"""


_LONGEST_BRIDGE_POI_MAP_SQL = """
WITH longest_bridge AS (
    SELECT osm_id, name, fclass, bridge, geometry,
           ST_Length(geometry::geography) AS length_m
    FROM cq_osm_roads_2021
    WHERE bridge = 'T'
    ORDER BY ST_Length(geometry::geography) DESC, osm_id
    LIMIT 1
),
matched_pois AS (
    SELECT DISTINCT ON (p."ID")
           p."ID" AS poi_id,
           p."名称" AS poi_name,
           p."地址" AS address,
           p."类型" AS poi_type,
           ST_Distance(p.geometry::geography, lb.geometry::geography) AS distance_m,
           p.geometry
    FROM cq_amap_poi_2024 AS p
    CROSS JOIN longest_bridge AS lb
    WHERE ST_DWithin(p.geometry::geography, lb.geometry::geography, 100)
    ORDER BY p."ID"
),
bridge_buffer AS (
    SELECT osm_id, name, length_m,
           ST_Buffer(geometry::geography, 100)::geometry AS geometry
    FROM longest_bridge
),
map_view AS (
    SELECT
        ST_Y(ST_Centroid(geometry)) AS center_lat,
        ST_X(ST_Centroid(geometry)) AS center_lng,
        ST_XMin(Box3D(geometry)) AS min_lng,
        ST_YMin(Box3D(geometry)) AS min_lat,
        ST_XMax(Box3D(geometry)) AS max_lng,
        ST_YMax(Box3D(geometry)) AS max_lat
    FROM bridge_buffer
),
features AS (
    SELECT
        'poi'::text AS feature_group,
        p.poi_id,
        p.poi_name,
        p.address,
        p.poi_type,
        ROUND(p.distance_m::numeric, 2) AS distance_m,
        NULL::text AS osm_id,
        NULL::text AS bridge_name,
        NULL::text AS fclass,
        NULL::text AS bridge,
        NULL::numeric AS length_m,
        NULL::integer AS radius_m,
        'matched_poi'::text AS result_type,
        p.geometry
    FROM matched_pois AS p
    UNION ALL
    SELECT
        'bridge', NULL::bigint, NULL, NULL, NULL, NULL,
        lb.osm_id, lb.name, lb.fclass, lb.bridge,
        ROUND(lb.length_m::numeric, 2), NULL,
        'longest_bridge', lb.geometry
    FROM longest_bridge AS lb
    UNION ALL
    SELECT
        'buffer', NULL::bigint, NULL, NULL, NULL, NULL,
        bb.osm_id, bb.name, NULL, NULL,
        ROUND(bb.length_m::numeric, 2), 100,
        'search_buffer', bb.geometry
    FROM bridge_buffer AS bb
)
SELECT
    f.feature_group, f.poi_id, f.poi_name, f.address, f.poi_type,
    f.distance_m, f.osm_id, f.bridge_name, f.fclass, f.bridge,
    f.length_m, f.radius_m, f.result_type,
    ST_AsGeoJSON(f.geometry)::text AS geometry_json,
    v.center_lat, v.center_lng,
    v.min_lng, v.min_lat, v.max_lng, v.max_lat
FROM features AS f
CROSS JOIN map_view AS v
ORDER BY CASE f.feature_group WHEN 'buffer' THEN 1 WHEN 'bridge' THEN 2 ELSE 3 END,
         f.poi_id NULLS FIRST
"""
