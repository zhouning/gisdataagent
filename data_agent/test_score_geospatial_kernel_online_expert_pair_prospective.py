from __future__ import annotations

import hashlib
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
from scripts.score_geospatial_kernel_online_expert_pair_prospective import (
    CAMPAIGN_SCHEMA,
    ProspectiveOnlineExpertPairScoreRecord,
    compile_online_expert_pair_prospective_score,
    score_online_expert_pair_records,
)
from scripts.update_geospatial_kernel_online_expert_pair_matured_state import (
    OBSERVATION_SCHEMA,
)

START = datetime(2026, 7, 31, 0, tzinfo=UTC)


def _records(
    *,
    count: int,
    jpp_v5_error: float = 1.0,
    jpp_selector_error: float = 1.0,
    center_v4_error: float = 3.0,
    center_wwm_error: float = 1.5,
) -> list[ProspectiveOnlineExpertPairScoreRecord]:
    values = []
    for system in ("center_hill", "j_percy_priest"):
        for horizon in (1, 3, 6, 12):
            for index in range(count):
                observed = 100.0
                if system == "center_hill":
                    v5_error = 1.0
                    selector_error = 2.0
                    v4_error = center_v4_error
                    wwm_error = center_wwm_error
                else:
                    v5_error = jpp_v5_error
                    selector_error = jpp_selector_error
                    v4_error = 1.0
                    wwm_error = 3.0
                values.append(
                    ProspectiveOnlineExpertPairScoreRecord(
                        system_id=system,
                        forecast_id=f"{system}:{horizon}:{index}",
                        issue_time=START + timedelta(hours=index),
                        forecast_horizon_hours=horizon,
                        v5_prediction_m3s=max(0.0, observed + v5_error),
                        selector_prediction_m3s=max(
                            0.0,
                            observed + selector_error,
                        ),
                        v4_prediction_m3s=max(0.0, observed + v4_error),
                        wwm_prediction_m3s=max(0.0, observed + wwm_error),
                        observed_discharge_m3s=observed,
                    )
                )
    return values


def test_score_gate_passes_for_one_strict_system_and_one_exact_tie() -> None:
    result = score_online_expert_pair_records(_records(count=500))
    center = result["systems"]["center_hill"]
    jpp = result["systems"]["j_percy_priest"]
    gate = result["prospective_incremental_value_gate"]

    assert center["equal_horizon_macro_mean_mse_ratio_v5_to_selector"] == pytest.approx(0.25)
    assert center["v5_strictly_improves_selector_macro_mse"] is True
    assert jpp["equal_horizon_macro_mean_mse_ratio_v5_to_selector"] == 1.0
    assert jpp["v5_not_worse_numerically_without_cross_system_compensation"] is True
    assert gate == {
        "minimum_coverage_passed": True,
        "both_systems_not_worse_numerically_without_compensation": True,
        "at_least_one_system_strictly_improved": True,
        "strictly_improved_system_has_hac_supported_horizon": True,
        "passed": True,
    }
    assert result["best_fixed_constituent_expert_diagnostic"] == {
        "comparison_selected_after_outcome_access": True,
        "comparison_role": "secondary_harder_diagnostic_not_primary_gate",
        "both_systems_not_worse_numerically": True,
        "at_least_one_system_strictly_improved": True,
        "passed": True,
    }
    assert center["equal_horizon_macro_mean_final_average_external_regret_m6s2"] == {
        "v5": pytest.approx(-1.25),
        "selector": pytest.approx(1.75),
    }
    assert result["external_regret_diagnostic"] == {
        "best_fixed_comparator_selected_after_outcome_access": True,
        "comparison_role": "secondary_time_ordered_diagnostic_not_primary_gate",
        "both_systems_v5_regret_not_higher_than_selector": True,
        "at_least_one_system_v5_regret_strictly_lower_than_selector": True,
        "passed": True,
    }


def test_score_gate_fails_when_second_system_regresses() -> None:
    result = score_online_expert_pair_records(
        _records(count=500, jpp_v5_error=2.0, jpp_selector_error=1.0)
    )
    gate = result["prospective_incremental_value_gate"]

    assert result["systems"]["j_percy_priest"][
        "equal_horizon_macro_mean_mse_ratio_v5_to_selector"
    ] == pytest.approx(4.0)
    assert gate["both_systems_not_worse_numerically_without_compensation"] is False
    assert gate["passed"] is False


def test_primary_gate_does_not_hide_failure_against_best_fixed_expert() -> None:
    result = score_online_expert_pair_records(
        _records(
            count=500,
            center_v4_error=0.5,
            center_wwm_error=3.0,
        )
    )

    assert result["prospective_incremental_value_gate"]["passed"] is True
    assert result["systems"]["center_hill"]["horizons"]["1"][
        "best_fixed_constituent_expert_in_hindsight"
    ] == ("physical_online_residual_adaptation_v4")
    assert result["systems"]["center_hill"][
        "equal_horizon_macro_mean_mse_ratio_v5_to_best_fixed_constituent_expert"
    ] == pytest.approx(4.0)
    assert result["best_fixed_constituent_expert_diagnostic"]["passed"] is False


def test_external_regret_exposes_transient_cost_when_final_loss_ties() -> None:
    records = [
        ProspectiveOnlineExpertPairScoreRecord(
            system_id="center_hill",
            forecast_id=f"center_hill:1:{index}",
            issue_time=START + timedelta(hours=index),
            forecast_horizon_hours=1,
            v5_prediction_m3s=v5,
            selector_prediction_m3s=selector,
            v4_prediction_m3s=v4,
            wwm_prediction_m3s=wwm,
            observed_discharge_m3s=10.0,
        )
        for index, (v5, selector, v4, wwm) in enumerate(
            (
                (12.0, 10.0, 10.0, 12.0),
                (10.0, 12.0, 12.0, 10.0),
            )
        )
    ]

    horizon = score_online_expert_pair_records(records)["systems"]["center_hill"]["horizons"]["1"]

    assert horizon["best_fixed_constituent_expert_in_hindsight"] == "tie"
    assert horizon["v5_external_regret_to_best_fixed_constituent"] == {
        "final_cumulative_m6s2": 0.0,
        "final_average_per_case_m6s2": 0.0,
        "maximum_prefix_cumulative_m6s2": 4.0,
        "minimum_prefix_cumulative_m6s2": 0.0,
    }
    assert horizon["selector_external_regret_to_best_fixed_constituent"] == {
        "final_cumulative_m6s2": 0.0,
        "final_average_per_case_m6s2": 0.0,
        "maximum_prefix_cumulative_m6s2": 0.0,
        "minimum_prefix_cumulative_m6s2": 0.0,
    }


def test_score_gate_fails_closed_below_500_rows_per_system_horizon() -> None:
    result = score_online_expert_pair_records(_records(count=499))
    gate = result["prospective_incremental_value_gate"]

    assert gate["minimum_coverage_passed"] is False
    assert gate["passed"] is False


def _json_body(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _artifact(path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _write_issue_pair(tmp_path: Path, system: str) -> tuple[Path, Path]:
    root = tmp_path / system
    root.mkdir()
    issue_path = root / "issue.json"
    state_path = root / "state.json"
    prediction_path = root / "predictions.json"
    run_report_path = root / "run-report.json"
    observation_path = root / "observations.json"
    issue = {
        "schema": ISSUE_SCHEMA,
        "system_id": system,
        "issue_time_utc": START.isoformat(),
        "forecasts": [
            {
                "forecast_id": f"{system}:issue-0:{horizon}h",
                "horizon_hours": horizon,
                "target_support_end_utc": (START + timedelta(hours=horizon)).isoformat(),
                "physical_online_residual_adaptation_v4_m3s": 100.0 + horizon,
                "action_innovation_wwm_m3s": 120.0 + horizon,
            }
            for horizon in (1, 3, 6, 12)
        ],
    }
    state = ProspectiveOnlineExpertPairState.empty(
        system_id=system,
        state_as_of=START,
    )
    issue_path.write_text(_json_body(issue), encoding="utf-8")
    state_path.write_text(_json_body(state.as_dict()), encoding="utf-8")
    prediction_body, run_report = compile_outcome_free_online_expert_pair(
        issue_path=issue_path,
        state_path=state_path,
        output_path=prediction_path,
        executed_at=START,
    )
    prediction_path.write_bytes(prediction_body)
    run_report_path.write_text(_json_body(run_report), encoding="utf-8")
    observations = {
        "schema": OBSERVATION_SCHEMA,
        "system_id": system,
        "retrieved_at_utc": (START + timedelta(hours=12, minutes=10)).isoformat(),
        "source_id": f"authoritative:{system}",
        "evidence_level": "authoritative",
        "values_imputed": False,
        "observations": [
            {
                "target_support_end_utc": (START + timedelta(hours=horizon)).isoformat(),
                "observed_discharge_m3s": (-2.0 if system == "j_percy_priest" else 110.0),
                "observation_available_at_utc": (
                    START + timedelta(hours=horizon, minutes=5)
                ).isoformat(),
                "quality_status": "approved",
            }
            for horizon in (1, 3, 6, 12)
        ],
    }
    observation_path.write_text(_json_body(observations), encoding="utf-8")
    return run_report_path, observation_path


def _write_campaign(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    systems = {}
    for system in ("center_hill", "j_percy_priest"):
        report, observations = _write_issue_pair(tmp_path, system)
        systems[system] = [
            {
                "prediction_run_report": _artifact(report),
                "authoritative_observations": _artifact(observations),
            }
        ]
    campaign = {
        "schema": CAMPAIGN_SCHEMA,
        "campaign_id": "fixture-campaign",
        "evaluation_time_utc": (START + timedelta(hours=13)).isoformat(),
        "expected_systems": ["center_hill", "j_percy_priest"],
        "systems": systems,
        "values_imputed": False,
    }
    path = tmp_path / "campaign.json"
    path.write_text(_json_body(campaign), encoding="utf-8")
    return path, campaign


def test_campaign_scorer_recomputes_both_systems_but_refuses_small_sample_claim(
    tmp_path: Path,
) -> None:
    campaign_path, _ = _write_campaign(tmp_path)
    report = compile_online_expert_pair_prospective_score(
        campaign_index_path=campaign_path,
    )

    assert report["status"] == "prospective_online_expert_pair_score_insufficient_coverage"
    assert report["execution"]["issue_count_by_system"] == {
        "center_hill": 1,
        "j_percy_priest": 1,
    }
    assert report["execution"]["prediction_record_count"] == 8
    assert report["execution"]["every_prediction_run_recomputed_exactly"] is True
    assert "online_expert_evaluation" in report["implementation_artifacts"]
    assert report["prospective_incremental_value_gate"]["minimum_coverage_passed"] is False
    center_1h = report["systems"]["center_hill"]["horizons"]["1"]
    assert center_1h["v4"]["rmse_m3s"] == pytest.approx(9.0)
    assert center_1h["wwm"]["rmse_m3s"] == pytest.approx(11.0)
    assert center_1h["best_fixed_constituent_expert_in_hindsight"] == (
        "physical_online_residual_adaptation_v4"
    )
    assert report["claim_boundary"]["v5_beats_best_fixed_constituent_expert_diagnostic"] is False
    assert (
        report["claim_boundary"]["v5_lower_external_regret_than_traditional_selector_diagnostic"]
        is False
    )
    assert report["claim_boundary"]["external_regret_diagnostic_is_primary_promotion_gate"] is False
    assert report["claim_boundary"]["broad_model_superiority_supported"] is False
    assert (
        report["claim_boundary"]["bounded_incremental_value_over_traditional_selector_supported"]
        is False
    )


def test_campaign_scorer_rejects_tampered_artifact_descriptor(tmp_path: Path) -> None:
    campaign_path, campaign = _write_campaign(tmp_path)
    campaign["systems"]["center_hill"][0]["prediction_run_report"][  # type: ignore[index]
        "sha256"
    ] = "0" * 64
    campaign_path.write_text(_json_body(campaign), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact_verification_failed"):
        compile_online_expert_pair_prospective_score(
            campaign_index_path=campaign_path,
        )
