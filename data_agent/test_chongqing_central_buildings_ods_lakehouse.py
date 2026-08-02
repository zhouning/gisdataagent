"""Contract tests for the restricted building ODS provider."""

from __future__ import annotations

import pytest

from scripts.smoke_chongqing_central_buildings_ods_lakehouse import (
    DEFAULT_EXPECTED_BBOX,
    _quality_checks,
    _validated_table,
)


def test_building_provider_is_fail_closed_to_ods() -> None:
    assert _validated_table(
        "lakehouse.gis_ods.chongqing_central_buildings_2021"
    ) == ("lakehouse", "gis_ods", "chongqing_central_buildings_2021")
    with pytest.raises(ValueError, match="only target gis_ods"):
        _validated_table("lakehouse.gis_dwd.chongqing_central_buildings_2021")


def test_building_quality_gate_accepts_only_exactly_recorded_defects() -> None:
    metrics = {
        "row_count": 107452,
        "distinct_source_fids": 107452,
        "distinct_source_ids": 1,
        "null_source_fids": 0,
        "null_geometry": 417,
        "invalid_geometry": 0,
        "duplicate_geometry": 416,
        "duplicate_non_null_geometry": 0,
        "floor_min": 1,
        "floor_max": 66,
        "bbox": list(DEFAULT_EXPECTED_BBOX),
        "srids": [4326, 4326],
    }
    checks = _quality_checks(
        metrics,
        expected_rows=107452,
        expected_null_geometry=417,
        expected_duplicate_geometry=416,
        expected_floor=(1, 66),
        expected_bbox=DEFAULT_EXPECTED_BBOX,
    )
    assert all(checks.values())

    metrics["null_geometry"] = 0
    checks = _quality_checks(
        metrics,
        expected_rows=107452,
        expected_null_geometry=417,
        expected_duplicate_geometry=416,
        expected_floor=(1, 66),
        expected_bbox=DEFAULT_EXPECTED_BBOX,
    )
    assert checks["null_geometry_defect_recorded"] is False
