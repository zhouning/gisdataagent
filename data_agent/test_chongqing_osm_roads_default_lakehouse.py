"""Contract tests for the Chongqing OSM default-lakehouse acceptance."""

from __future__ import annotations

import argparse

import pytest

from scripts.smoke_chongqing_osm_roads_default_lakehouse import (
    DEFAULT_EXPECTED_BBOX,
    _parse_bbox,
    _quality_checks,
    _validated_table,
)


def test_default_lakehouse_table_identifier_is_fail_closed() -> None:
    assert _validated_table("lakehouse.gis_dwd.chongqing_osm_roads") == (
        "lakehouse",
        "gis_dwd",
        "chongqing_osm_roads",
    )
    with pytest.raises(ValueError, match="safe identifiers"):
        _validated_table("lakehouse.gis_dwd.roads;DROP TABLE source")


def test_default_lakehouse_bbox_parser_is_strict() -> None:
    assert _parse_bbox("105.30805,28.163572,110.173223,32.156202") == (
        DEFAULT_EXPECTED_BBOX
    )
    with pytest.raises(argparse.ArgumentTypeError, match="xmin"):
        _parse_bbox("110,28,105,32")


def test_default_lakehouse_quality_checks_require_semantic_equivalence() -> None:
    checks = _quality_checks(
        {
            "row_count": 50366,
            "distinct_road_ids": 50366,
            "null_road_ids": 0,
            "null_geometry": 0,
            "invalid_geometry": 0,
            "bbox": list(DEFAULT_EXPECTED_BBOX),
            "srids": [4326, 4326],
        },
        expected_rows=50366,
        expected_bbox=DEFAULT_EXPECTED_BBOX,
    )
    assert all(checks.values())

    checks["row_count_preserved"] = False
    assert not all(checks.values())
