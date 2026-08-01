from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2.prospective_online_expert_pair import (
    ProspectiveOnlineExpertPairState,
)
from scripts.run_geospatial_kernel_online_expert_pair_outcome_free import (
    ISSUE_SCHEMA,
    compile_outcome_free_online_expert_pair,
)
from scripts.update_geospatial_kernel_online_expert_pair_matured_state import (
    OBSERVATION_SCHEMA,
    compile_matured_online_expert_pair_state_update,
)

START = datetime(2026, 7, 31, 12, tzinfo=UTC)


def _json_body(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _write_prediction_run(tmp_path: Path) -> tuple[Path, Path, Path]:
    issue_path = tmp_path / "issue.json"
    state_path = tmp_path / "state.json"
    prediction_path = tmp_path / "predictions.json"
    run_report_path = tmp_path / "prediction-run-report.json"
    issue = {
        "schema": ISSUE_SCHEMA,
        "system_id": "j_percy_priest",
        "issue_time_utc": START.isoformat(),
        "forecasts": [
            {
                "forecast_id": f"jpp-20260731T1200Z-{horizon}h",
                "horizon_hours": horizon,
                "target_support_end_utc": (START + timedelta(hours=horizon)).isoformat(),
                "physical_online_residual_adaptation_v4_m3s": 100.0 + horizon,
                "action_innovation_wwm_m3s": 120.0 + horizon,
            }
            for horizon in (1, 3, 6, 12)
        ],
    }
    state = ProspectiveOnlineExpertPairState.empty(
        system_id="j_percy_priest",
        state_as_of=START - timedelta(minutes=5),
    )
    issue_path.write_text(_json_body(issue), encoding="utf-8")
    state_path.write_text(_json_body(state.as_dict()), encoding="utf-8")
    prediction_body, report = compile_outcome_free_online_expert_pair(
        issue_path=issue_path,
        state_path=state_path,
        output_path=prediction_path,
        executed_at=START,
    )
    prediction_path.write_bytes(prediction_body)
    run_report_path.write_text(_json_body(report), encoding="utf-8")
    return state_path, prediction_path, run_report_path


def _write_observations(
    tmp_path: Path,
    *,
    available_at: datetime | None = None,
) -> Path:
    availability = available_at or START + timedelta(hours=1, minutes=5)
    path = tmp_path / "observations.json"
    payload = {
        "schema": OBSERVATION_SCHEMA,
        "system_id": "j_percy_priest",
        "retrieved_at_utc": (availability + timedelta(minutes=5)).isoformat(),
        "source_id": "usgs:03430200:00060:approved",
        "evidence_level": "authoritative",
        "values_imputed": False,
        "observations": [
            {
                "target_support_end_utc": (START + timedelta(hours=1)).isoformat(),
                "observed_discharge_m3s": -2.0,
                "observation_available_at_utc": availability.isoformat(),
                "quality_status": "approved",
            }
        ],
    }
    path.write_text(_json_body(payload), encoding="utf-8")
    return path


def test_matured_state_update_recomputes_prediction_and_drops_raw_observation(
    tmp_path: Path,
) -> None:
    state_path, _, run_report_path = _write_prediction_run(tmp_path)
    observations_path = _write_observations(tmp_path)
    update_time = START + timedelta(hours=1, minutes=15)
    body, report = compile_matured_online_expert_pair_state_update(
        prediction_run_report_path=run_report_path,
        prior_state_path=state_path,
        observations_path=observations_path,
        output_state_path=tmp_path / "updated-state.json",
        update_time=update_time,
    )
    updated = ProspectiveOnlineExpertPairState.from_dict(json.loads(body))
    sample = updated.samples_for_horizon(1)[0]

    assert updated.state_as_of == update_time
    assert updated.sample_count_by_horizon() == {1: 1, 3: 0, 6: 0, 12: 0}
    assert sample.alternative_delta_m3s == 20.0
    assert sample.baseline_target_error_m3s == -103.0
    assert sample.coefficient_gate_shadow_squared_error_m6s2 is None
    assert b"observed_discharge_m3s" not in body
    assert report["execution"]["sealed_prediction_run_recomputed_exactly"] is True
    assert report["execution"]["signed_negative_observation_update_count"] == 1
    assert report["causal_boundary"]["raw_observation_retained_in_output_state"] is False
    assert report["claim_boundary"]["prediction_accuracy_scored"] is False


def test_matured_state_update_rejects_prediction_artifact_tampering(
    tmp_path: Path,
) -> None:
    state_path, prediction_path, run_report_path = _write_prediction_run(tmp_path)
    observations_path = _write_observations(tmp_path)
    prediction_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact_verification_failed"):
        compile_matured_online_expert_pair_state_update(
            prediction_run_report_path=run_report_path,
            prior_state_path=state_path,
            observations_path=observations_path,
            output_state_path=tmp_path / "updated-state.json",
            update_time=START + timedelta(hours=1, minutes=15),
        )


def test_matured_state_update_rejects_not_yet_available_observation(
    tmp_path: Path,
) -> None:
    state_path, _, run_report_path = _write_prediction_run(tmp_path)
    observations_path = _write_observations(
        tmp_path,
        available_at=START + timedelta(hours=2),
    )

    with pytest.raises(ValueError, match="observation_not_available"):
        compile_matured_online_expert_pair_state_update(
            prediction_run_report_path=run_report_path,
            prior_state_path=state_path,
            observations_path=observations_path,
            output_state_path=tmp_path / "updated-state.json",
            update_time=START + timedelta(hours=1, minutes=15),
        )


def test_matured_state_update_rejects_duplicate_forecast_feedback(
    tmp_path: Path,
) -> None:
    state_path, _, run_report_path = _write_prediction_run(tmp_path)
    observations_path = _write_observations(tmp_path)
    first_body, _ = compile_matured_online_expert_pair_state_update(
        prediction_run_report_path=run_report_path,
        prior_state_path=state_path,
        observations_path=observations_path,
        output_state_path=tmp_path / "updated-state.json",
        update_time=START + timedelta(hours=1, minutes=15),
    )
    updated_state_path = tmp_path / "updated-state.json"
    updated_state_path.write_bytes(first_body)

    with pytest.raises(ValueError, match="state_update_invalid"):
        compile_matured_online_expert_pair_state_update(
            prediction_run_report_path=run_report_path,
            prior_state_path=updated_state_path,
            observations_path=observations_path,
            output_state_path=tmp_path / "duplicate-state.json",
            update_time=START + timedelta(hours=1, minutes=20),
        )
