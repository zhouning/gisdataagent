import json
from decimal import Decimal
from unittest.mock import patch

from data_agent.nl2sql_presentation import (
    _estimate_zoom_from_extent,
    _is_bridge_building_intersection_query,
    _is_longest_bridge_poi_query,
    _rows_to_feature_collection,
    build_longest_bridge_poi_map_update,
    build_nl2sql_map_update,
    describe_map_update,
    format_nl2sql_result_for_chat,
    parse_nl2sql_payload,
)


def _bridge_count_payload() -> dict:
    return {
        "status": "ok",
        "execution_engine": "postgis",
        "dialect": "postgres",
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


def _longest_bridge_poi_payload(count: int = 35) -> dict:
    return {
        "status": "ok",
        "sql": (
            "WITH longest_bridge AS ("
            "SELECT geometry FROM cq_osm_roads_2021 WHERE bridge = 'T' "
            "ORDER BY ST_LENGTH(CAST(geometry AS GEOGRAPHY)) DESC LIMIT 1"
            ') SELECT COUNT(DISTINCT p."ID") FROM cq_amap_poi_2024 AS p, '
            "longest_bridge AS lb WHERE "
            "ST_DWITHIN(CAST(p.geometry AS GEOGRAPHY), CAST(lb.geometry AS GEOGRAPHY), 100)"
        ),
        "execution": {
            "status": "ok",
            "rows": 1,
            "columns": ["count"],
            "data": [{"count": count}],
            "message": "查询成功，返回 1 行",
        },
        "semantic": {"candidate_tables": ["cq_amap_poi_2024", "cq_osm_roads_2021"]},
    }


def _longest_bridge_map_rows(poi_count: int = 35) -> list[dict]:
    view = {
        "center_lat": Decimal("29.7021"),
        "center_lng": Decimal("107.8132"),
        "min_lng": Decimal("107.801"),
        "min_lat": Decimal("29.695"),
        "max_lng": Decimal("107.825"),
        "max_lat": Decimal("29.709"),
    }
    rows = [
        {
            "feature_group": "poi",
            "poi_id": idx,
            "poi_name": f"POI {idx}",
            "address": "测试地址",
            "poi_type": "测试类型",
            "distance_m": Decimal("42.50"),
            "result_type": "matched_poi",
            "geometry_json": json.dumps({"type": "Point", "coordinates": [107.81, 29.70]}),
            **view,
        }
        for idx in range(1, poi_count + 1)
    ]
    rows.extend([
        {
            "feature_group": "bridge",
            "osm_id": "708725252",
            "bridge_name": "龙溪河大道",
            "fclass": "primary",
            "bridge": "T",
            "length_m": Decimal("2167.57"),
            "result_type": "longest_bridge",
            "geometry_json": json.dumps({
                "type": "LineString",
                "coordinates": [[107.8, 29.7], [107.82, 29.7]],
            }),
            **view,
        },
        {
            "feature_group": "buffer",
            "osm_id": "708725252",
            "bridge_name": "龙溪河大道",
            "length_m": Decimal("2167.57"),
            "radius_m": 100,
            "result_type": "search_buffer",
            "geometry_json": json.dumps({
                "type": "Polygon",
                "coordinates": [[
                    [107.8, 29.69],
                    [107.82, 29.69],
                    [107.82, 29.71],
                    [107.8, 29.69],
                ]],
            }),
            **view,
        },
    ])
    return rows


class _FakeMappings:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def all(self) -> list[dict]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeConnection:
    def __init__(self, rows: list[dict], *, fail: bool = False):
        self._rows = rows
        self._fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement):
        assert "single, consistent PostGIS snapshot" not in str(statement)
        if self._fail:
            raise RuntimeError("database unavailable")
        return _FakeResult(self._rows)


class _FakeEngine:
    def __init__(self, rows: list[dict], *, fail: bool = False):
        self._rows = rows
        self._fail = fail

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self._rows, fail=self._fail)


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
    assert "执行引擎：**PostgreSQL/PostGIS**" in text
    assert "参数 `user_question`" in text
    assert "**建筑物轮廓数量：1**" in text
    assert "不是“返回 1 行”的行数说明" in text
    assert "```sql" in text
    assert "cq_buildings_2021" in text
    assert "semantic_distinct_join_count" in text
    assert "已生成地图图层。" in text


def test_format_nl2sql_result_surfaces_lake_engine_and_projection():
    payload = {
        "status": "ok",
        "execution_engine": "lake",
        "dialect": "duckdb",
        "sql": "SELECT COUNT(*) AS count FROM land_parcel_current",
        "execution": {
            "status": "ok",
            "engine": "lake",
            "dialect": "duckdb",
            "rows": 1,
            "columns": ["count"],
            "data": [{"count": 101657}],
            "source_bindings": [
                {
                    "table_name": "land_parcel_current",
                    "projection_id": "projection-dltb-001",
                    "projection_path": "C:/GDAData/file_lake/materialized/DLTB.parquet",
                }
            ],
        },
        "semantic": {"candidate_tables": ["land_parcel_current"]},
    }

    text = format_nl2sql_result_for_chat(payload, question="地类图斑有多少条？")

    assert text is not None
    assert "执行引擎：**治理数据湖（DuckDB → GeoParquet）**" in text
    assert "SQL 方言：`duckdb`" in text
    assert "湖上治理投影：`projection-dltb-001`" in text


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


def test_longest_bridge_poi_query_detection_is_locked_to_prompt_and_sql():
    payload = _longest_bridge_poi_payload()

    assert _is_longest_bridge_poi_query(
        "@NL2SQL 统计距离道路网络中最长桥梁 100 米范围内的高德 POI 数量。",
        payload["sql"],
    )
    assert not _is_longest_bridge_poi_query(
        "统计距离任意桥梁100米范围内的高德POI数量。",
        payload["sql"],
    )
    assert not _is_longest_bridge_poi_query(
        "统计距离道路网络中最长桥梁100米范围内的高德POI数量。",
        "SELECT COUNT(*) FROM cq_amap_poi_2024",
    )


def test_longest_bridge_poi_map_has_three_snapshot_consistent_layers(tmp_path):
    rows = _longest_bridge_map_rows()
    with (
        patch("data_agent.db_engine.get_engine", return_value=_FakeEngine(rows)),
        patch("data_agent.database_tools._inject_user_context"),
    ):
        result = build_longest_bridge_poi_map_update(
            _longest_bridge_poi_payload(),
            question="统计距离道路网络中最长桥梁100米范围内的高德POI数量。",
            upload_dir=str(tmp_path),
        )

    assert result is not None
    assert [layer["type"] for layer in result["layers"]] == ["polygon", "line", "point"]
    assert result["summary"]["scalar_poi_count"] == 35
    assert result["summary"]["poi_feature_count"] == 35
    assert result["summary"]["bridge_feature_count"] == 1
    assert result["summary"]["buffer_feature_count"] == 1
    assert result["summary"]["geometry_snapshot"] == "single_postgis_statement"
    assert result["summary"]["bridge_osm_id"] == "708725252"

    poi_layer = next(layer for layer in result["layers"] if layer["type"] == "point")
    poi_geojson = json.loads((tmp_path / poi_layer["geojson"]).read_text(encoding="utf-8"))
    assert len(poi_geojson["features"]) == 35
    assert poi_geojson["features"][0]["properties"]["result_type"] == "matched_poi"
    assert all((tmp_path / layer["geojson"]).is_file() for layer in result["layers"])

    description = describe_map_update(result)
    assert "高德 POI 35 个" in description
    assert "最长桥梁 1 条" in description
    assert "同一 PostGIS 查询快照" in description


def test_longest_bridge_poi_map_skips_scalar_feature_count_mismatch(tmp_path):
    engine = _FakeEngine(_longest_bridge_map_rows(34))
    with (
        patch("data_agent.db_engine.get_engine", return_value=engine),
        patch("data_agent.database_tools._inject_user_context"),
    ):
        result = build_longest_bridge_poi_map_update(
            _longest_bridge_poi_payload(count=35),
            question="统计距离道路网络中最长桥梁100米范围内的高德POI数量。",
            upload_dir=str(tmp_path),
        )

    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_nl2sql_map_dispatcher_does_not_trigger_for_unrelated_query(tmp_path):
    payload = {
        "status": "ok",
        "sql": "SELECT COUNT(*) FROM cq_amap_poi_2024",
        "execution": {"data": [{"count": 1194351}]},
    }
    with patch.dict("os.environ", {"GDA_NL2SQL_DEMO_MAPS": "1"}), patch(
        "data_agent.db_engine.get_engine"
    ) as get_engine:
        result = build_nl2sql_map_update(
            payload,
            question="统计高德POI总数。",
            upload_dir=str(tmp_path),
        )

    assert result is None
    get_engine.assert_not_called()


def test_nl2sql_map_dispatcher_preserves_bridge_building_fallback(tmp_path):
    expected = {"layers": [{"name": "existing bridge/building layer"}]}
    with (
        patch.dict("os.environ", {"GDA_NL2SQL_DEMO_MAPS": "1"}),
        patch(
            "data_agent.nl2sql_presentation.build_longest_bridge_poi_map_update",
            return_value=None,
        ) as longest_builder,
        patch(
            "data_agent.nl2sql_presentation.build_bridge_building_map_update",
            return_value=expected,
        ) as building_builder,
    ):
        result = build_nl2sql_map_update(
            _bridge_count_payload(),
            question="统计与桥梁相交的建筑物数量",
            upload_dir=str(tmp_path),
        )

    assert result is expected
    longest_builder.assert_called_once()
    building_builder.assert_called_once()


def test_longest_bridge_poi_map_database_failure_preserves_scalar_path(tmp_path):
    with (
        patch("data_agent.db_engine.get_engine", return_value=_FakeEngine([], fail=True)),
        patch("data_agent.database_tools._inject_user_context"),
    ):
        result = build_longest_bridge_poi_map_update(
            _longest_bridge_poi_payload(),
            question="统计距离道路网络中最长桥梁100米范围内的高德POI数量。",
            upload_dir=str(tmp_path),
        )

    assert result is None
    chat_text = format_nl2sql_result_for_chat(
        _longest_bridge_poi_payload(),
        question="统计距离道路网络中最长桥梁100米范围内的高德POI数量。",
    )
    assert chat_text is not None
    assert "**POI数量：35**" in chat_text


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
