from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_spatial_boundary_evidence as evidence,
)


def _ledger():
    return evidence.compile_public_spatial_boundary_evidence()


def test_stage27_binds_eleven_nldi_discovered_sites_to_usgs_metadata():
    ledger = _ledger()
    report = ledger.as_dict()

    assert len(ledger.candidates) == 11
    assert report["spatially_distinct_candidate_count"] == 10
    assert report["same_mainstem_spatial_candidate_count"] == 6
    assert report["request_boundary"]["workspace_or_private_data_sent"] is False
    assert len(ledger.source_artifacts) == 38
    assert all(len(value["sha256"]) == 64 for value in ledger.source_artifacts)


def test_stage27_preserves_comid_topology_distance_and_time_support():
    candidates = {
        value.monitoring_location_id: value for value in _ledger().candidates
    }
    upstream = candidates["USGS-03424010"]
    tributary = candidates["USGS-03424850"]
    downstream = candidates["USGS-03425000"]

    assert upstream.comid == 18421761
    assert upstream.topology_directions == ("upstream_main",)
    assert upstream.same_mainstem_as_anchor is True
    assert upstream.distance_from_anchor_m == pytest.approx(
        12018.661066894827
    )
    assert upstream.instantaneous_parameter_codes == ()
    assert dict(upstream.field_observation_counts) == {"00060": 2}
    assert tributary.topology_directions == ("upstream_tributaries",)
    assert tributary.same_mainstem_as_anchor is False
    assert downstream.topology_directions == ("downstream_main",)
    assert downstream.instantaneous_parameter_codes == ("00060",)


def test_stage27_admits_two_bracketed_spatial_discharge_snapshots():
    ledger = _ledger()
    snapshots = ledger.require_synchronized_spatial_snapshots()

    assert len(snapshots) == 2
    first, second = snapshots
    assert first.candidate.time == "2024-05-16T14:40:55+00:00"
    assert first.candidate.value == 22700.0
    assert first.anchor_before.time == "2024-05-16T14:30:00+00:00"
    assert first.anchor_after.time == "2024-05-16T15:00:00+00:00"
    assert first.anchor_bracket_mean == 22400.0
    assert first.nearest_time_difference_seconds == 655.0
    assert first.bracket_width_seconds == 1800.0
    assert first.candidate_to_anchor_bracket_mean_ratio == pytest.approx(
        22700.0 / 22400.0
    )
    assert second.candidate.time == "2026-02-10T16:49:30+00:00"
    assert second.candidate.value == 274.0
    assert second.anchor_bracket_mean == 602.0
    assert second.nearest_time_difference_seconds == 630.0
    assert all(value.fully_approved is False for value in snapshots)


def test_stage27_refuses_hydrograph_rollout_and_same_site_substitution():
    ledger = _ledger()
    report = ledger.as_dict()

    with pytest.raises(
        ValueError,
        match="public_spatial_boundary_continuous_hydrographs_unavailable",
    ):
        ledger.require_continuous_boundary_hydrographs()
    with pytest.raises(
        ValueError,
        match="public_spatial_boundary_candidate_measurements_provisional",
    ):
        ledger.require_fully_approved_spatial_snapshots()
    with pytest.raises(
        ValueError,
        match="public_spatial_boundary_snapshots_are_not_spatial_rollout",
    ):
        ledger.require_observed_spatial_rollout()
    with pytest.raises(
        ValueError,
        match="public_spatial_boundary_same_site_temporal_substitution_forbidden",
    ):
        ledger.substitute_anchor_history_for_neighbor()
    assert report["claim_boundary"][
        "two_observed_spatial_snapshot_pairs_found"
    ] is True
    assert report["claim_boundary"]["reach_boundary_conditions_observed"] is False
    assert report["decision"]["runtime_operator_admitted"] is False


def test_compiled_stage27_report_passes_with_snapshot_only_admission():
    from scripts import (
        compile_geotransport_stage27_public_spatial_boundary_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 21
    assert all(report["gates"].values())
    assert report["decision"]["spatial_snapshot_evidence_admitted"] is True
    assert report["decision"]["continuous_boundary_hydrographs_admitted"] is False
    assert report["decision"]["observed_spatial_rollout_completed"] is False
    assert report["decision"]["runtime_operator_admitted"] is False
