from __future__ import annotations

from scripts import compile_geotransport_stage44_target_exposure_inventory as stage44


def test_stage44_inventory_binds_all_authoritative_exposure_artifacts():
    report = stage44.compile_report()

    assert report["status"] == stage44.STATUS
    assert report["source_artifact_count"] == 15
    assert report["exposure_record_count"] == 34
    assert all(len(value["sha256"]) == 64 for value in report["source_artifacts"])
    assert report["boundary"]["network_request_count"] == 0


def test_stage44_inventory_contains_all_broad_center_hill_windows():
    inventory = stage44.compile_inventory()
    windows = inventory.excluded_windows_utc

    expected = (
        ("2021-12-09T00:00:00Z", "2022-01-06T02:00:00Z"),
        ("2022-01-06T00:00:00Z", "2022-02-03T02:00:00Z"),
        ("2022-02-03T00:00:00Z", "2022-03-03T02:00:00Z"),
        ("2022-03-31T00:00:00Z", "2022-04-28T02:00:00Z"),
        ("2022-10-13T00:00:00Z", "2022-11-10T02:00:00Z"),
        ("2022-11-10T00:00:00Z", "2022-12-08T02:00:00Z"),
    )
    records = {(value.begin_utc, value.end_utc) for value in inventory.records}
    assert set(expected) <= records
    assert ("2021-12-09T00:00:00Z", "2022-03-03T02:00:00Z") in windows
    assert ("2022-10-13T00:00:00Z", "2022-12-08T02:00:00Z") in windows


def test_stage44_inventory_contains_stage29_through_stage43_event_windows():
    inventory = stage44.compile_inventory()
    phase_counts: dict[str, int] = {}
    for record in inventory.records:
        phase_counts[record.phase] = phase_counts.get(record.phase, 0) + 1

    assert phase_counts["stage29_blind_transfer"] == 3
    assert phase_counts["stage30_regime_validation"] == 4
    assert phase_counts["stage31_identifiable_response"] == 4
    assert phase_counts["stage32_lag_support"] == 4
    assert phase_counts["stage36_hydraulic_boundary"] == 4
    assert phase_counts["stage42_component_event_targets"] == 4
    assert inventory.overlaps("2025-04-15T16:00:00Z", "2025-04-15T16:00:00Z")
    assert inventory.overlaps("2021-07-27T03:00:00Z", "2021-07-27T03:00:00Z")


def test_stage44_inventory_adds_stage27_and_stage28_windows_missing_from_stage41():
    inventory = stage44.compile_inventory()

    assert inventory.overlaps("2024-05-16T14:40:55Z", "2024-05-16T14:40:55Z")
    assert inventory.overlaps("2026-02-10T16:49:30Z", "2026-02-10T16:49:30Z")
    assert inventory.overlaps("2026-02-09T00:00:00Z", "2026-02-12T00:00:00Z")
    assert inventory.as_dict()["boundary"]["target_values_loaded_by_inventory_compiler"] is False
