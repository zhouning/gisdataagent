from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    StateDependentManningClosureParameters,
)
from scripts.acquire_geotransport_forecast_closure_development_inputs import (
    compile_development_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "forecast_closure_center_hill_development_inputs_report.json"
)
TRAINING_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "forecast_closure_center_hill_development_report.json"
)


def _read_descriptor(descriptor: dict[str, object]) -> bytes:
    path = REPO_ROOT / str(descriptor["path"])
    body = path.read_bytes()
    assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
    assert len(body) == descriptor["size_bytes"]
    return body


def test_forecast_closure_development_plan_is_pre_d3_and_outcome_free() -> None:
    plan, initial, forcing, context = compile_development_plan()

    assert plan["window"] == {
        "start_inclusive_utc": "2021-12-09T01:00:00Z",
        "end_exclusive_utc": "2022-01-06T01:00:00Z",
        "hour_count": 672,
        "nwm_time_chunk": 559,
        "role": "pre_d3_public_development_only",
    }
    assert plan["feature_count"] == 435
    assert plan["feature_chunk_indices"] == [63, 87]
    assert initial.time_chunk_indices == (559,)
    assert forcing.time_chunk_indices == (559,)
    assert len(forcing.feature_ids) == len(context["feature_ids"]) == 435
    assert plan["data_isolation"] == {
        "d3_outcomes_read": False,
        "two_system_blind_outcomes_read": False,
        "only_pre_d3_development_window_requested": True,
    }
    assert all(
        row["variable"] in {"streamflow", "velocity", "q_lateral", "time"}
        for row in plan["requests"]
    )


def test_public_development_inputs_are_complete_and_hash_verified() -> None:
    report = json.loads(INPUT_REPORT.read_bytes())

    assert report["status"] == "pass_public_development_inputs_acquired"
    assert report["result"]["feature_count"] == 435
    assert report["result"]["hour_count"] == 672
    assert report["result"]["initial_streamflow_fill_value_count"] == 0
    assert report["result"]["initial_velocity_fill_value_count"] == 0
    assert report["result"]["q_lateral_fill_value_count"] == 0
    for descriptor in report["raw_artifacts"]:
        _read_descriptor(descriptor)
    for descriptor in report["decoded_arrays"].values():
        _read_descriptor(descriptor)


def test_fitted_closure_parameters_are_shared_bounded_and_temporally_isolated() -> None:
    report = json.loads(TRAINING_REPORT.read_bytes())
    parameter_body = _read_descriptor(report["outputs"]["parameters"])
    payload = json.loads(parameter_body)
    raw = payload["forecast_closure_parameters"]
    parameters = StateDependentManningClosureParameters(
        feature_ids=tuple(raw["feature_ids"]),
        reference_storage_m3=tuple(raw["reference_storage_m3"]),
        log_roughness_intercept=tuple(raw["log_roughness_intercept"]),
        log_roughness_storage_slope=tuple(
            raw["log_roughness_storage_slope"]
        ),
        training_system_ids=tuple(raw["training_system_ids"]),
        training_data_start=datetime.fromisoformat(raw["training_data_start"]),
        training_data_end=datetime.fromisoformat(raw["training_data_end"]),
        provenance_id=raw["provenance_id"],
        evidence_level=raw["evidence_level"],
        admitted=raw["admitted"],
        outcome_calibrated=raw["outcome_calibrated"],
    )

    assert payload["parameterization"]["free_parameter_count"] == 2
    assert len(parameters.feature_ids) == 435
    assert len(set(parameters.log_roughness_intercept)) == 1
    assert len(set(parameters.log_roughness_storage_slope)) == 1
    assert parameters.training_data_end < datetime.fromisoformat(
        report["window"]["activation_issue_time"].replace("Z", "+00:00")
    )
    assert payload["data_isolation"]["d3_outcomes_used"] is False
    assert payload["data_isolation"]["two_system_blind_outcomes_used"] is False


def test_development_diagnostic_keeps_persistence_gate_and_claims_closed() -> None:
    report = json.loads(TRAINING_REPORT.read_bytes())
    predictions = _read_descriptor(report["outputs"]["predictions"])
    rows = list(csv.DictReader(io.StringIO(predictions.decode("utf-8"))))

    assert report["status"] == "public_development_training_and_diagnostic_complete"
    assert len(rows) == 503
    assert report["scoring"]["primary_candidate_sample_count"] == 499
    assert report["metrics"]["candidate"]["rmse_m3s"] == pytest.approx(
        46.587876091302824
    )
    assert report["metrics"]["state_update_only"]["rmse_m3s"] == pytest.approx(
        47.179134352537595
    )
    assert report["metrics"]["one_hour_persistence"]["rmse_m3s"] == pytest.approx(
        17.414775117869517
    )
    assert report["diagnostics"]["candidate_beats_state_update_only_rmse"] is True
    assert report["diagnostics"]["candidate_beats_one_hour_persistence_rmse"] is False
    assert report["conservation"]["all_scenarios_passed"] is True
    assert report["data_isolation"]["missing_outcomes_imputed"] is False
    assert report["claim_boundary"]["forecast_closure_validated"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
