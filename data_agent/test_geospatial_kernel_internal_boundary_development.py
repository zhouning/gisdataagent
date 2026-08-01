from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from scripts.freeze_geotransport_center_hill_internal_boundary_development_protocol import (
    CORE_CODE_PATHS,
    compile_protocol,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "smith_fork_internal_boundary_reference_report.json"
)
PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_internal_boundary_development_protocol.json"
)
REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_internal_boundary_development_report.json"
)


def _read_descriptor(descriptor: dict[str, object]) -> bytes:
    body = (REPO_ROOT / str(descriptor["path"])).read_bytes()
    assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
    assert len(body) == descriptor["size_bytes"]
    return body


def test_internal_boundary_reference_preserves_candidate_uncertainty() -> None:
    reference = json.loads(REFERENCE.read_bytes())

    assert reference["status"] == "candidate_internal_boundary_reference_compiled"
    assert reference["site"]["site_id"] == "03424730"
    assert reference["site"]["feature_id"] == 18421273
    assert reference["flow_direction_check"]["downstream_endpoint_matches"] is True
    linear = reference["linear_reference"]
    assert linear["route_link_full_length_m"] == 573.0
    assert linear["projected_downstream_fraction"] == pytest.approx(
        0.5844053908943547
    )
    assert linear["route_link_downstream_partial_length_m"] == pytest.approx(
        334.86428898246527
    )
    assert linear["point_to_line_snap_distance_m"] == pytest.approx(
        52.070872366767695
    )
    assert reference["quality_gates"][
        "point_to_line_snap_distance_below_30m"
    ] is False
    assert reference["claim_boundary"]["linear_reference_admitted"] is False
    for descriptor in reference["sources"].values():
        _read_descriptor(descriptor)


def test_internal_boundary_protocol_is_frozen_over_code_geometry_and_gates() -> None:
    protocol = json.loads(PROTOCOL.read_bytes())
    compiled = compile_protocol()

    assert protocol["schema"] == compiled["schema"]
    assert protocol["window_and_horizons"] == compiled["window_and_horizons"]
    assert protocol["gis_compilation_lock"] == compiled["gis_compilation_lock"]
    assert protocol["scenario_lock"] == compiled["scenario_lock"]
    assert protocol["baseline_and_gate_lock"] == compiled["baseline_and_gate_lock"]
    assert protocol["scenario_lock"]["scenarios"] == [
        "observed_internal_boundary",
        "modeled_cut_control",
        "zero_internal_boundary",
    ]
    assert protocol["gis_compilation_lock"]["linear_reference_admitted"] is False
    assert protocol["outcome_access_at_freeze"][
        "candidate_parameters_fitted_from_outlet_targets"
    ] is False
    for path in CORE_CODE_PATHS:
        body = (REPO_ROOT / path).read_bytes()
        assert protocol["core_code"][path]["sha256"] == hashlib.sha256(
            body
        ).hexdigest()


def test_internal_boundary_diagnostic_is_conservative_and_claim_closed() -> None:
    report = json.loads(REPORT.read_bytes())
    prediction_body = _read_descriptor(report["outputs"]["predictions"])
    rows = list(csv.DictReader(io.StringIO(prediction_body.decode("utf-8"))))

    assert report["status"] == (
        "public_development_internal_boundary_diagnostic_complete"
    )
    assert report["protocol"]["sha256"] == hashlib.sha256(
        PROTOCOL.read_bytes()
    ).hexdigest()
    assert len(rows) == 2400
    assert {int(row["horizon_hours"]) for row in rows} == {1, 3, 6, 12, 24}
    assert all(row["future_observations_assimilated"] == "False" for row in rows)
    assert report["conservation"]["all_scenarios_passed"] is True
    assert report["diagnostics"]["future_observation_update_count"] == {
        "modeled_cut_control": 0,
        "observed_internal_boundary": 0,
        "zero_internal_boundary": 0,
    }
    observed_ledger = report["conservation"][
        "unique_cycling_boundary_ledgers"
    ]["observed_internal_boundary"]
    assert observed_ledger["observed_boundary_input_volume_m3"] > 0.0
    assert observed_ledger["displaced_upstream_outflow_volume_m3"] > 0.0
    assert report["domain_compilation"]["network_admitted"] is False
    assert report["domain_compilation"]["forcing_support_admitted"] is False
    assert report["information_boundary"][
        "future_smith_fork_observation_used_within_branch"
    ] is False
    assert report["claim_boundary"]["internal_boundary_reference_admitted"] is False
    assert report["claim_boundary"]["operational_forecast_evaluated"] is False
    assert report["claim_boundary"]["forecast_closure_validated"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_internal_boundary_metrics_use_common_support_and_registered_horizons() -> None:
    report = json.loads(REPORT.read_bytes())
    names = (
        "observed_internal_boundary",
        "modeled_cut_control",
        "zero_internal_boundary",
        "parent_local_multi_gauge",
        "causal_latency_matched_persistence",
        "zero_latency_archive_persistence",
    )
    for horizon in (1, 3, 6, 12, 24):
        count = report["scoring"]["common_complete_sample_count_by_horizon"][
            str(horizon)
        ]
        assert count > 450
        assert {
            report["metrics_by_horizon"][str(horizon)][name]["sample_count"]
            for name in names
        } == {count}
    assert report["registered_gates"]["core_horizons"] == [3, 6, 12, 24]
