from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2.physical_online_expert_blend import (
    PhysicalOnlineExpertBlendConfig,
)
from data_agent.uwm.geospatial_kernel_v2.prospective_online_expert_pair import (
    ProspectiveOnlineExpertPairState,
)
from scripts.run_geospatial_kernel_online_expert_pair_outcome_free import (
    ISSUE_SCHEMA,
    compile_outcome_free_online_expert_pair,
)

START = datetime(2026, 7, 31, 12, tzinfo=UTC)


def _issue() -> dict[str, object]:
    return {
        "schema": ISSUE_SCHEMA,
        "system_id": "center_hill",
        "issue_time_utc": START.isoformat(),
        "forecasts": [
            {
                "forecast_id": f"center-hill-{horizon}h",
                "horizon_hours": horizon,
                "target_support_end_utc": (START + timedelta(hours=horizon)).isoformat(),
                "physical_online_residual_adaptation_v4_m3s": 100.0 + horizon,
                "action_innovation_wwm_m3s": 120.0 + horizon,
            }
            for horizon in (1, 3, 6, 12)
        ],
    }


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    issue_path = tmp_path / "issue.json"
    state_path = tmp_path / "state.json"
    issue_path.write_text(json.dumps(_issue()), encoding="utf-8")
    state = ProspectiveOnlineExpertPairState.empty(
        system_id="center_hill",
        state_as_of=START - timedelta(minutes=5),
    )
    state_path.write_text(json.dumps(state.as_dict()), encoding="utf-8")
    return issue_path, state_path


def test_outcome_free_runner_emits_candidate_and_baseline_before_scoring(
    tmp_path: Path,
) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    output_path = tmp_path / "predictions.json"
    body, report = compile_outcome_free_online_expert_pair(
        issue_path=issue_path,
        state_path=state_path,
        output_path=output_path,
        executed_at=START,
    )
    output = json.loads(body)

    assert output["prediction_count"] == 4
    assert [row["forecast_horizon_hours"] for row in output["predictions"]] == [
        1,
        3,
        6,
        12,
    ]
    for row in output["predictions"]:
        assert (
            row["physical_online_expert_blend_v5_m3s"]
            == row["physical_online_residual_adaptation_v4_m3s"]
        )
        assert (
            row["evidence_gated_follow_the_leader_m3s"]
            == row["physical_online_residual_adaptation_v4_m3s"]
        )
        assert row["raw_observation_used_for_prediction"] is False
        assert row["current_or_future_target_used_for_prediction"] is False
    assert report["execution"]["both_candidate_and_baseline_emitted_before_scoring"] is True
    assert report["data_isolation"]["raw_observation_value_loaded"] is False
    assert report["claim_boundary"]["fresh_outcome_scored"] is False
    assert report["claim_boundary"]["v5_superiority_over_traditional_selector_validated"] is False


def test_issue_contract_rejects_raw_observation_field(tmp_path: Path) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    issue = _issue()
    issue["forecasts"][0]["observed_discharge_m3s"] = 110.0  # type: ignore[index]
    issue_path.write_text(json.dumps(issue), encoding="utf-8")

    with pytest.raises(ValueError, match="issue_forecast_invalid"):
        compile_outcome_free_online_expert_pair(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START,
        )


def test_issue_contract_rejects_score_field_and_incomplete_horizon_axis(
    tmp_path: Path,
) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    issue = _issue()
    issue["score"] = 0.0
    issue_path.write_text(json.dumps(issue), encoding="utf-8")
    with pytest.raises(ValueError, match="issue_invalid"):
        compile_outcome_free_online_expert_pair(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START,
        )

    issue = _issue()
    issue["forecasts"] = issue["forecasts"][:-1]  # type: ignore[index]
    issue_path.write_text(json.dumps(issue), encoding="utf-8")
    with pytest.raises(ValueError, match="horizon_axis_invalid"):
        compile_outcome_free_online_expert_pair(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START,
        )


def test_state_must_match_system_and_precede_issue(tmp_path: Path) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    wrong_system = ProspectiveOnlineExpertPairState.empty(
        system_id="j_percy_priest",
        state_as_of=START,
    )
    state_path.write_text(json.dumps(wrong_system.as_dict()), encoding="utf-8")
    with pytest.raises(ValueError, match="issue_invalid"):
        compile_outcome_free_online_expert_pair(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START,
        )

    future_state = ProspectiveOnlineExpertPairState.empty(
        system_id="center_hill",
        state_as_of=START + timedelta(seconds=1),
    )
    state_path.write_text(json.dumps(future_state.as_dict()), encoding="utf-8")
    with pytest.raises(ValueError, match="state_after_issue"):
        compile_outcome_free_online_expert_pair(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START,
        )


def test_runner_rejects_non_frozen_algorithm_config(tmp_path: Path) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    changed = ProspectiveOnlineExpertPairState.empty(
        system_id="center_hill",
        state_as_of=START,
        config=PhysicalOnlineExpertBlendConfig(minimum_matured_sample_count=12),
    )
    state_path.write_text(json.dumps(changed.as_dict()), encoding="utf-8")

    with pytest.raises(ValueError, match="algorithm_config_not_frozen"):
        compile_outcome_free_online_expert_pair(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START,
        )


def test_runner_rejects_prediction_recorded_at_or_after_first_target(
    tmp_path: Path,
) -> None:
    issue_path, state_path = _write_inputs(tmp_path)

    with pytest.raises(ValueError, match="executed_at_invalid"):
        compile_outcome_free_online_expert_pair(
            issue_path=issue_path,
            state_path=state_path,
            output_path=tmp_path / "predictions.json",
            executed_at=START + timedelta(hours=1),
        )
