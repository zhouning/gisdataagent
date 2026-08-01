from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2.prospective_wwm_candidate import (
    ProspectiveWwmCandidateState,
)
from scripts.run_geospatial_kernel_prospective_wwm_candidate_outcome_free import (
    DEFAULT_ARX_REPORT,
    ISSUE_SCHEMA,
    _load_locked_arx_parameters,
    compile_outcome_free_prospective_wwm_candidate,
)

START = datetime(2026, 8, 1, 12, tzinfo=UTC)


def _issue() -> dict[str, object]:
    prefix = "jpp-issue-0"
    return {
        "schema": ISSUE_SCHEMA,
        "system_id": "j_percy_priest",
        "issue_time_utc": START.isoformat(),
        "forecast_id_prefix": prefix,
        "physical_at_latest_observation_m3s": 100.0,
        "latest_observed_outlet_state": {
            "valid_at_utc": (START - timedelta(hours=1)).isoformat(),
            "available_at_utc": (START - timedelta(minutes=5)).isoformat(),
            "discharge_m3s": 98.0,
            "provenance_id": "usgs-approved-issue-state-1",
            "evidence_level": "authoritative",
            "quality_status": "approved",
            "value_imputed": False,
        },
        "traditional_baseline_inputs": {
            "valid_times_utc": [
                (START + timedelta(hours=offset)).isoformat()
                for offset in range(-7, 13)
            ],
            "action_release_m3s": [80.0 + index for index in range(20)],
            "lateral_forcing_m3s": [5.0 + index / 10.0 for index in range(20)],
            "action_provenance_id": "cwms-action-vintage-1",
            "forcing_provenance_id": "nwm-forcing-vintage-1",
            "action_available_at_utc": (START - timedelta(minutes=10)).isoformat(),
            "forcing_available_at_utc": (START - timedelta(minutes=10)).isoformat(),
            "operational_vintages_verified": False,
        },
        "input_provenance": {
            "physical_forecast_provenance_id": "physical-forecast-1",
            "physical_forecast_available_at_utc": (
                START - timedelta(minutes=15)
            ).isoformat(),
            "latest_physical_state_provenance_id": "physical-state-1",
            "latest_physical_state_available_at_utc": (
                START - timedelta(minutes=10)
            ).isoformat(),
            "action_innovation_forecast_provenance_id": "wwm-forecast-1",
            "action_innovation_forecast_available_at_utc": (
                START - timedelta(minutes=5)
            ).isoformat(),
            "operational_vintages_verified": False,
        },
        "forecasts": [
            {
                "forecast_id": f"{prefix}:{horizon}h",
                "horizon_hours": horizon,
                "target_support_end_utc": (
                    START + timedelta(hours=horizon)
                ).isoformat(),
                "physical_open_loop_m3s": 100.0 + horizon,
                "action_innovation_wwm_m3s": 110.0 + horizon,
            }
            for horizon in (1, 3, 6, 12)
        ],
    }


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    issue_path = tmp_path / "issue.json"
    state_path = tmp_path / "state.json"
    issue_path.write_text(json.dumps(_issue()), encoding="utf-8")
    state = ProspectiveWwmCandidateState.empty(
        system_id="j_percy_priest",
        state_as_of=START - timedelta(hours=1),
    )
    state_path.write_text(json.dumps(state.as_dict()), encoding="utf-8")
    return issue_path, state_path


def test_integrated_runner_generates_v4_internally_before_scoring(
    tmp_path: Path,
) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    body, report = compile_outcome_free_prospective_wwm_candidate(
        issue_path=issue_path,
        state_path=state_path,
        output_path=tmp_path / "predictions.json",
        executed_at=START + timedelta(minutes=1),
    )
    output = json.loads(body)

    assert output["prediction_count"] == 4
    for row in output["predictions"]:
        assert row["physical_online_residual_adaptation_v4_m3s"] == row[
            "physical_open_loop_m3s"
        ]
        assert row["v4_state_generated_at_issue_time"] is True
        assert row["current_or_future_target_used_for_prediction"] is False
        assert row["causal_persistence_m3s"] == 98.0
        assert row["classical_arx_m3s"] >= 0.0
        assert len(row["classical_arx_parameter_sha256"]) == 64
        assert row["baseline_predictions_generated_at_issue_time"] is True
    assert report["execution"]["v4_generated_from_matured_state_at_issue_time"] is True
    assert report["execution"]["precomputed_v4_prediction_loaded"] is False
    assert report["execution"]["classical_arx_generated_from_locked_parameters"] is True
    assert report["execution"]["precomputed_persistence_or_arx_prediction_loaded"] is False
    assert report["input_provenance"]["operational_vintages_verified"] is False
    assert report["claim_boundary"]["candidate_admitted"] is False


def test_integrated_runner_rejects_precomputed_v4_and_future_input(
    tmp_path: Path,
) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    issue = _issue()
    issue["forecasts"][0]["physical_online_residual_adaptation_v4_m3s"] = 1.0  # type: ignore[index]
    issue_path.write_text(json.dumps(issue), encoding="utf-8")
    with pytest.raises(ValueError, match="issue_forecast_invalid"):
        compile_outcome_free_prospective_wwm_candidate(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START + timedelta(minutes=1),
        )

    issue = _issue()
    issue["input_provenance"]["physical_forecast_available_at_utc"] = (  # type: ignore[index]
        START + timedelta(seconds=1)
    ).isoformat()
    issue_path.write_text(json.dumps(issue), encoding="utf-8")
    with pytest.raises(ValueError, match="input_not_available_at_issue"):
        compile_outcome_free_prospective_wwm_candidate(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START + timedelta(minutes=1),
        )


def test_integrated_runner_rejects_execution_after_first_target(
    tmp_path: Path,
) -> None:
    issue_path, state_path = _write_inputs(tmp_path)

    with pytest.raises(ValueError, match="executed_at_invalid"):
        compile_outcome_free_prospective_wwm_candidate(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START + timedelta(hours=1),
        )


def test_integrated_runner_accepts_provisional_authoritative_issue_state(
    tmp_path: Path,
) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    issue = _issue()
    issue["latest_observed_outlet_state"]["quality_status"] = "provisional"  # type: ignore[index]
    issue_path.write_text(json.dumps(issue), encoding="utf-8")

    _, report = compile_outcome_free_prospective_wwm_candidate(
        issue_path=issue_path,
        state_path=state_path,
        output_path=tmp_path / "predictions.json",
        executed_at=START + timedelta(minutes=1),
    )

    assert report["execution"]["issue_state_quality_status"] == "provisional"
    assert report["execution"]["provisional_issue_state_used"] is True
    assert report["data_isolation"][
        "approved_outcome_still_required_for_scoring"
    ] is True


@pytest.mark.parametrize(
    "field",
    ["causal_persistence_m3s", "classical_arx_m3s"],
)
def test_integrated_runner_rejects_precomputed_strong_baseline(
    tmp_path: Path,
    field: str,
) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    issue = _issue()
    issue["forecasts"][0][field] = 1.0  # type: ignore[index]
    issue_path.write_text(json.dumps(issue), encoding="utf-8")

    with pytest.raises(ValueError, match="issue_forecast_invalid"):
        compile_outcome_free_prospective_wwm_candidate(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START + timedelta(minutes=1),
        )


def test_integrated_runner_rejects_discontinuous_baseline_axis(
    tmp_path: Path,
) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    issue = _issue()
    inputs = issue["traditional_baseline_inputs"]
    for key in (
        "valid_times_utc",
        "action_release_m3s",
        "lateral_forcing_m3s",
    ):
        inputs[key].pop(3)  # type: ignore[index,union-attr]
    issue_path.write_text(json.dumps(issue), encoding="utf-8")

    with pytest.raises(ValueError, match="baseline_time_axis_invalid"):
        compile_outcome_free_prospective_wwm_candidate(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START + timedelta(minutes=1),
        )


def test_integrated_runner_rejects_late_baseline_input(tmp_path: Path) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    issue = _issue()
    issue["traditional_baseline_inputs"]["action_available_at_utc"] = (  # type: ignore[index]
        START + timedelta(seconds=1)
    ).isoformat()
    issue_path.write_text(json.dumps(issue), encoding="utf-8")

    with pytest.raises(ValueError, match="input_not_available_at_issue"):
        compile_outcome_free_prospective_wwm_candidate(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START + timedelta(minutes=1),
        )


def test_locked_arx_loader_rejects_parameter_hash_drift(tmp_path: Path) -> None:
    report = json.loads(DEFAULT_ARX_REPORT.read_text(encoding="utf-8"))
    report["outputs"]["parameters"]["sha256"] = "0" * 64
    report_path = tmp_path / "arx-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="arx_artifact_verification_failed"):
        _load_locked_arx_parameters(report_path)
