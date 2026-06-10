import json
from decimal import Decimal

from data_agent.nl2sql_presentation import (
    _is_bridge_building_intersection_query,
    _estimate_zoom_from_extent,
    _rows_to_feature_collection,
    describe_map_update,
    format_nl2sql_result_for_chat,
    parse_nl2sql_payload,
)


def _bridge_count_payload() -> dict:
    return {
        "status": "ok",
        "sql": (
            'SELECT COUNT(DISTINCT b."Id") AS building_count '
            "FROM cq_buildings_2021 AS b "
            "JOIN cq_osm_roads_2021 AS r "
            "ON ST_INTERSECTS(b.geometry, r.geometry) "
            "WHERE r.bridge = 'T';"
        ),
        "execution": {
            "status": "ok",
            "rows": 1,
            "columns": ["building_count"],
            "data": [{"building_count": 1}],
            "message": "查询成功，返回 1 行",
        },
        "semantic": {
            "candidate_tables": ["cq_buildings_2021", "cq_osm_roads_2021"],
            "few_shot_count": 1,
            "hint_stats": {"family": "gemma"},
        },
        "corrections": ["semantic_distinct_join_count"],
    }


def test_parse_nl2sql_payload_unwraps_function_response_result():
    payload = _bridge_count_payload()
    wrapped = {"result": json.dumps(payload, ensure_ascii=False)}

    assert parse_nl2sql_payload(wrapped) == payload


def test_format_nl2sql_result_highlights_count_value_not_row_count():
    text = format_nl2sql_result_for_chat(
        json.dumps(_bridge_count_payload(), ensure_ascii=False),
        question="统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量",
        map_summary="已生成地图图层。",
    )

    assert text is not None
    assert "工具调用：`run_nl2semantic2sql`" in text
    assert "参数 `user_question`" in text
    assert "**建筑物轮廓数量：1**" in text
    assert "不是“返回 1 行”的行数说明" in text
    assert "```sql" in text
    assert "cq_buildings_2021" in text
    assert "semantic_distinct_join_count" in text
    assert "已生成地图图层。" in text


def test_format_nl2sql_result_labels_road_length_metric_not_road_count():
    payload = {
        "status": "ok",
        "sql": (
            "SELECT SUM(ST_Length(geometry::geography)) / 1000.0 AS total_length_km "
            "FROM cq_osm_roads_2021 WHERE bridge = 'T'"
        ),
        "execution": {
            "status": "ok",
            "rows": 1,
            "columns": ["total_length_km"],
            "data": [{"total_length_km": 1376.5975723658505}],
            "message": "查询成功，返回 1 行",
        },
        "semantic": {"candidate_tables": ["cq_osm_roads_2021"]},
    }

    text = format_nl2sql_result_for_chat(
        json.dumps(payload, ensure_ascii=False),
        question="统计重庆2021年道路网络中所有桥梁道路（bridge = T）的总长度，单位为公里。",
    )

    assert text is not None
    assert "**道路总长度（公里）：1376.5975723658505**" in text
    assert "道路数量" not in text


def test_format_nl2sql_result_labels_poi_count_when_cte_orders_by_length():
    payload = {
        "status": "ok",
        "sql": (
            "WITH longest_bridge AS ("
            "SELECT geometry FROM cq_osm_roads_2021 WHERE bridge = 'T' "
            "ORDER BY ST_LENGTH(CAST(geometry AS GEOGRAPHY)) DESC LIMIT 1"
            ') SELECT COUNT(DISTINCT p."ID") FROM cq_amap_poi_2024 AS p, longest_bridge AS lb '
            "WHERE ST_DWITHIN(CAST(p.geometry AS GEOGRAPHY), CAST(lb.geometry AS GEOGRAPHY), 100)"
        ),
        "execution": {
            "status": "ok",
            "rows": 1,
            "columns": ["count"],
            "data": [{"count": 35}],
            "message": "查询成功，返回 1 行",
        },
        "semantic": {"candidate_tables": ["cq_amap_poi_2024", "cq_osm_roads_2021"]},
    }

    text = format_nl2sql_result_for_chat(
        json.dumps(payload, ensure_ascii=False),
        question="统计距离道路网络中最长桥梁100米范围内的高德POI数量。",
    )

    assert text is not None
    assert "**POI数量：35**" in text
    assert "道路总长度" not in text


def test_bridge_building_query_detection_requires_all_spatial_clues():
    payload = _bridge_count_payload()

    assert _is_bridge_building_intersection_query(
        "统计与桥梁相交的建筑物数量",
        payload["sql"],
    )
    assert not _is_bridge_building_intersection_query(
        "统计建筑物数量",
        "SELECT COUNT(*) FROM cq_buildings_2021",
    )


def test_rows_to_feature_collection_converts_decimal_properties():
    rows = [
        {
            "building_id": 0,
            "area_m2": Decimal("12.34"),
            "result_type": "matched_building",
            "geometry_json": '{"type":"Point","coordinates":[106.5,29.5]}',
        }
    ]

    fc = _rows_to_feature_collection(
        rows,
        property_keys=("building_id", "area_m2", "result_type"),
    )

    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["geometry"]["type"] == "Point"
    assert fc["features"][0]["properties"]["area_m2"] == 12.34


def test_describe_map_update_explains_golden_count_vs_geometry_features():
    text = describe_map_update({
        "summary": {
            "golden_building_count": 1,
            "building_feature_count": 31,
            "bridge_road_count": 19,
        }
    })

    assert "COUNT(DISTINCT b.\"Id\")" in text
    assert "计为 1" in text
    assert "建筑几何行 31 个" in text
    assert "道路线 19 条" in text


def test_estimate_zoom_from_extent_uses_lower_zoom_for_spread_features():
    assert _estimate_zoom_from_extent({
        "min_lng": 106.43,
        "min_lat": 29.51,
        "max_lng": 106.65,
        "max_lat": 29.71,
    }) == 10
    assert _estimate_zoom_from_extent({
        "min_lng": 106.43,
        "min_lat": 29.51,
        "max_lng": 106.431,
        "max_lat": 29.511,
    }) == 16
