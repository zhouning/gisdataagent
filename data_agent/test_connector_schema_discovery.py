"""Tests for deterministic JSON/GeoJSON connector schema discovery."""

from data_agent.connectors.schema_discovery import json_document_columns, json_record_columns


def test_nested_json_schema_is_stable_and_value_independent() -> None:
    first = {
        "type": "Feature",
        "id": "road-a",
        "properties": {"road_class": "primary", "lanes": 2},
        "geometry": {"type": "LineString", "coordinates": [[1, 2], [3, 4]]},
    }
    second = {
        "type": "Feature",
        "id": "road-b",
        "properties": {"road_class": "secondary", "lanes": 4},
        "geometry": {"type": "LineString", "coordinates": [[5, 6], [7, 8]]},
    }

    assert json_record_columns([first]) == json_record_columns([second])
    assert {column["name"] for column in json_record_columns([first])} == {
        "geometry.coordinates",
        "geometry.type",
        "id",
        "properties.lanes",
        "properties.road_class",
        "type",
    }


def test_json_schema_records_additive_type_and_nullability_evidence() -> None:
    columns = json_record_columns(
        [
            {"properties": {"name": "road-a", "speed": 40}},
            {"properties": {"name": None, "speed": "unknown", "district": "Yuzhong"}},
        ]
    )

    by_name = {column["name"]: column for column in columns}
    assert by_name["properties.name"] == {
        "name": "properties.name",
        "type": "null|string",
        "nullable": True,
    }
    assert by_name["properties.speed"]["type"] == "integer|string"
    assert by_name["properties.district"]["nullable"] is True


def test_geojson_feature_collection_sampling_is_bounded_and_reported() -> None:
    columns, record_count, truncated = json_document_columns(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "a", "properties": {"name": "A"}},
                {"type": "Feature", "id": "b", "properties": {"name": "B"}},
            ],
        },
        record_limit=1,
    )

    assert record_count == 2
    assert truncated
    assert {column["name"] for column in columns} == {"id", "properties.name", "type"}
