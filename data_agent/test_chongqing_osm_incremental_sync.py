"""Contract tests for the isolated Chongqing OSM incremental acceptance."""

from __future__ import annotations

import pytest

from scripts.smoke_chongqing_osm_incremental_sync import (
    _canonical_fingerprint,
    _validate_isolated_target,
    baseline_next_cursor,
    baseline_previous_cursor,
    delta_next_cursor,
)


def test_incremental_acceptance_target_is_strictly_isolated() -> None:
    namespace = "gda_sync_cert_0123456789"
    warehouse = (
        "s3a://gis-agent-lakehouse/acceptance/source-sync/"
        f"{namespace}/warehouse"
    )
    table = f"lakehouse.{namespace}.osm_roads_incremental"
    assert _validate_isolated_target(warehouse, table) == (
        "lakehouse",
        namespace,
        "osm_roads_incremental",
    )
    with pytest.raises(ValueError, match="isolated"):
        _validate_isolated_target(
            "s3a://gis-agent-lakehouse/warehouse/iceberg",
            "lakehouse.gis_dwd.chongqing_osm_roads",
        )


def test_incremental_cursor_progression_binds_source_slices() -> None:
    baseline_sha256 = "a" * 64
    delta_sha256 = "b" * 64
    assert baseline_previous_cursor(baseline_sha256) != baseline_next_cursor(
        baseline_sha256
    )
    assert delta_next_cursor(delta_sha256) == {
        "phase": "delta_committed",
        "sequence": 1,
        "source_slice_sha256": delta_sha256,
    }


def test_delta_manifest_fingerprint_is_canonical() -> None:
    first = ({"road_id": "2", "operation": "update"}, {"road_id": "1"})
    same = ({"operation": "update", "road_id": "2"}, {"road_id": "1"})
    changed_order = tuple(reversed(first))
    assert _canonical_fingerprint(first) == _canonical_fingerprint(same)
    assert _canonical_fingerprint(first) != _canonical_fingerprint(changed_order)
