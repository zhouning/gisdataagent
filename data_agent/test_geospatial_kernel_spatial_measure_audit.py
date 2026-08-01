from __future__ import annotations

import math

import pytest

from data_agent.uwm.geospatial_kernel_v2.spatial_measure_audit import (
    audit_directed_path_geometry,
    audit_endpoint_spatial_measure,
)


def _path(*, gap_degrees: float = 0.0):
    return audit_directed_path_geometry(
        path_id="test:path",
        feature_ids=(10, 20),
        raw_lines=(
            ((0.0, 0.0), (0.01, 0.0)),
            ((0.02 + gap_degrees, 0.0), (0.01 + gap_degrees, 0.0)),
        ),
        maximum_connection_gap_m=100.0,
        provenance_id="test:geometry",
        evidence_level="derived",
    )


def test_directed_path_orients_reversed_reach_and_preserves_metric_contract():
    result = _path()

    assert result.orientations == ("source_order", "reversed")
    assert result.continuous is True
    assert result.total_full_length_m == pytest.approx(2_223.9016, rel=1e-5)
    assert result.as_dict()["projection_method"].startswith(
        "local_equirectangular"
    )


def test_endpoint_measure_resolves_near_line_and_admits_measure():
    path = _path()
    result = audit_endpoint_spatial_measure(
        endpoint_role="observation_gauge",
        feature_id=20,
        point_lonlat=(0.015, 0.0001),
        oriented_line=path.oriented_lines[1],
        maximum_resolved_snap_distance_m=20.0,
        provenance_id="test:gauge",
        evidence_level="authoritative",
    )

    assert result.measure_resolved is True
    assert result.candidate_measure_fraction == pytest.approx(0.5, abs=1e-6)
    assert result.snap_distance_m == pytest.approx(11.119508, rel=1e-5)
    assert result.as_dict()["admitted_measure_from_oriented_start_m"] == pytest.approx(
        result.candidate_measure_from_oriented_start_m
    )


def test_endpoint_measure_keeps_far_projection_candidate_but_does_not_admit_it():
    path = _path()
    result = audit_endpoint_spatial_measure(
        endpoint_role="action_boundary",
        feature_id=10,
        point_lonlat=(0.005, 0.01),
        oriented_line=path.oriented_lines[0],
        maximum_resolved_snap_distance_m=100.0,
        provenance_id="test:action",
        evidence_level="derived",
    )

    payload = result.as_dict()
    assert result.measure_resolved is False
    assert math.isfinite(payload["candidate_measure_from_oriented_start_m"])
    assert payload["admitted_measure_from_oriented_start_m"] is None
    assert payload["admitted_remaining_to_oriented_end_m"] is None


def test_path_gap_is_a_failed_audit_state_not_an_infinite_measure():
    result = _path(gap_degrees=0.002)

    assert result.continuous is False
    assert len(result.connection_gaps_m) == 1
    assert math.isfinite(result.connection_gaps_m[0])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"endpoint_role": "unknown"}, "endpoint_spatial_measure_role_invalid"),
        (
            {"maximum_resolved_snap_distance_m": 0.0},
            "endpoint_spatial_measure_snap_limit_invalid",
        ),
    ],
)
def test_endpoint_measure_rejects_invalid_semantic_contract(kwargs, message):
    values = {
        "endpoint_role": "action_boundary",
        "feature_id": 10,
        "point_lonlat": (0.0, 0.0),
        "oriented_line": ((0.0, 0.0), (0.01, 0.0)),
        "maximum_resolved_snap_distance_m": 100.0,
        "provenance_id": "test:action",
        "evidence_level": "derived",
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        audit_endpoint_spatial_measure(**values)


def test_public_development_spatial_audit_fails_closed_on_unresolved_action():
    from scripts.audit_geotransport_kinematic_wave_spatial_measures import (
        compile_audit,
    )

    report = compile_audit()
    systems = {row["system_id"]: row for row in report["systems"]}

    assert systems["center_hill"]["gates"]["action_measure_resolved"] is True
    assert (
        systems["j_percy_priest"]["gates"]["action_measure_resolved"] is False
    )
    assert (
        systems["j_percy_priest"]["action_boundary_measure"][
            "admitted_measure_from_oriented_start_m"
        ]
        is None
    )
    assert all(
        row["posthoc_phase_explanatory_bound"][
            "endpoint_measure_error_can_explain_phase_failure"
        ]
        is False
        for row in systems.values()
    )
    assert report["claim_boundary"]["operator_form_admitted"] is False
