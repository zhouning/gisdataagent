from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import target_exposure_inventory as exposure


def _record(source_id: str, begin: str, end: str) -> exposure.TargetExposureRecord:
    return exposure.TargetExposureRecord(
        source_id=source_id,
        phase="test",
        artifact_path="artifact.json",
        begin_utc=begin,
        end_utc=end,
        evidence_kind="acquisition_manifest",
    )


def test_target_exposure_inventory_merges_overlapping_and_contiguous_windows():
    inventory = exposure.compile_target_exposure_inventory(
        (
            _record("second", "2022-01-02T00:00:00Z", "2022-01-03T00:00:00Z"),
            _record("first", "2022-01-01T00:00:00Z", "2022-01-02T00:00:00Z"),
            _record("third", "2022-02-01T00:00:00Z", "2022-02-02T00:00:00Z"),
        ),
        ({"path": "artifact.json", "sha256": "a" * 64, "size_bytes": 1},),
    )

    assert inventory.excluded_windows_utc == (
        ("2022-01-01T00:00:00Z", "2022-01-03T00:00:00Z"),
        ("2022-02-01T00:00:00Z", "2022-02-02T00:00:00Z"),
    )
    assert inventory.merged_intervals[0]["source_record_count"] == 2


def test_target_exposure_inventory_overlap_is_closed_and_rejects_bad_query():
    inventory = exposure.compile_target_exposure_inventory(
        (_record("only", "2022-01-01T00:00:00Z", "2022-01-02T00:00:00Z"),),
        ({"path": "artifact.json", "sha256": "a" * 64, "size_bytes": 1},),
    )

    assert inventory.overlaps("2021-12-31T23:00:00Z", "2022-01-01T00:00:00Z")
    assert not inventory.overlaps("2022-01-02T01:00:00Z", "2022-01-03T00:00:00Z")
    with pytest.raises(ValueError, match="target_exposure_query_window_invalid"):
        inventory.overlaps("2022-01-03T00:00:00Z", "2022-01-02T00:00:00Z")
