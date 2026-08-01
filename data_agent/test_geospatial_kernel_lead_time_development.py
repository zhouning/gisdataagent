from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

from scripts.freeze_geotransport_center_hill_lead_time_development_protocol import (
    compile_protocol,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_lead_time_development_protocol.json"
)
REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_lead_time_development_report.json"
)


def _read_descriptor(descriptor: dict[str, object]) -> bytes:
    body = (REPO_ROOT / str(descriptor["path"])).read_bytes()
    assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
    assert len(body) == descriptor["size_bytes"]
    return body


def test_lead_time_protocol_freezes_information_boundaries_before_execution() -> None:
    protocol = json.loads(PROTOCOL.read_bytes())
    compiled = compile_protocol()

    assert protocol["schema"] == compiled["schema"]
    assert protocol["status"] == "frozen_before_lead_time_development_execution"
    assert protocol["horizon_lock"] == compiled["horizon_lock"]
    assert protocol["window"] == compiled["window"]
    assert protocol["horizon_lock"]["diagnostic_horizons_hours"] == [1]
    assert protocol["horizon_lock"]["core_horizons_hours"] == [3, 6, 12, 24]
    assert protocol["window"]["issue_count"] == 480
    assert protocol["forecast_cycle_lock"]["observations_after_issue_time"] == (
        "forbidden"
    )
    assert protocol["outcome_access_at_freeze"][
        "window_outcomes_previously_accessed"
    ] is True
    assert protocol["outcome_access_at_freeze"][
        "prospective_or_blind_claim_permitted"
    ] is False
    assert protocol["information_tracks"]["operational_forecast"][
        "executable"
    ] is False
    assert protocol["claim_boundary_before_execution"][
        "geospatial_kernel_validated"
    ] is False


def test_lead_time_diagnostic_is_causal_within_rollout_and_claim_closed() -> None:
    report = json.loads(REPORT.read_bytes())
    predictions = _read_descriptor(report["outputs"]["predictions"])
    rows = list(csv.DictReader(io.StringIO(predictions.decode("utf-8"))))

    assert report["status"] == "public_development_lead_time_diagnostic_complete"
    assert report["protocol"]["sha256"] == hashlib.sha256(
        PROTOCOL.read_bytes()
    ).hexdigest()
    assert len(rows) == 2400
    assert {int(row["horizon_hours"]) for row in rows} == {1, 3, 6, 12, 24}
    assert all(row["future_observations_assimilated"] == "False" for row in rows)
    assert report["diagnostics"]["future_observation_update_count"] == {
        "graph_multi_gauge": 0,
        "local_multi_gauge": 0,
        "outlet_only": 0,
    }
    assert report["diagnostics"]["one_hour_parent_prediction_regression"][
        "passed"
    ] is True
    assert report["conservation"]["all_executed_scenarios_passed"] is True
    assert report["information_tracks"]["operational_forecast"][
        "metrics_by_horizon"
    ] is None
    assert report["data_isolation"]["graph_parameters_reused_without_refit"] is True
    assert report["data_isolation"]["future_target_outcomes_used_by_model"] is False
    assert report["claim_boundary"]["operational_forecast_executed"] is False
    assert report["claim_boundary"]["forecast_closure_validated"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_lead_time_scoring_uses_common_complete_support_per_horizon() -> None:
    report = json.loads(REPORT.read_bytes())
    track = report["information_tracks"]["retrospective_oracle_forcing"]
    metrics = track["metrics_by_horizon"]
    counts = track["scoring"]["common_complete_sample_count_by_horizon"]

    for horizon in (1, 3, 6, 12, 24):
        names = (
            "graph_multi_gauge",
            "local_multi_gauge",
            "outlet_only",
            "causal_latency_matched_persistence",
            "zero_latency_archive_persistence",
        )
        assert {metrics[str(horizon)][name]["sample_count"] for name in names} == {
            counts[str(horizon)]
        }
        assert counts[str(horizon)] > 450
    assert report["registered_gates"]["core_horizons"] == [3, 6, 12, 24]
    assert report["registered_gates"]["operational_gate_assessable"] is False
