from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from scripts.run_geospatial_kernel_real_ensemble_first_issue import (
    DEFAULT_EXTERNAL_PROFILE_OUTPUT,
    DEFAULT_EXTERNAL_PROFILE_REPORT,
    DEFAULT_GRAPH_PARTITION_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_SEALED_ROLLOUT_REPORT,
    EXTERNAL_PROFILE_GRAPH_PARTITION_ENSEMBLE_DESIGN,
    GRAPH_PARTITION_ENSEMBLE_DESIGN,
    SYSTEM_IDS,
    compile_real_ensemble_first_issue_report,
)


@pytest.fixture(scope="module")
def real_report():
    return compile_real_ensemble_first_issue_report()


@pytest.fixture(scope="module")
def graph_partition_report():
    return compile_real_ensemble_first_issue_report(
        ensemble_design=GRAPH_PARTITION_ENSEMBLE_DESIGN
    )


@pytest.fixture(scope="module")
def external_profile_report():
    return compile_real_ensemble_first_issue_report(
        ensemble_design=EXTERNAL_PROFILE_GRAPH_PARTITION_ENSEMBLE_DESIGN
    )


def test_real_first_issue_report_replays_committed_artifact_exactly(real_report) -> None:
    assert real_report == json.loads(DEFAULT_OUTPUT.read_bytes())
    assert real_report["status"] == (
        "real_two_system_first_issue_ensemble_cycle_executed"
    )
    assert real_report["execution_gates"] == {
        "system_count": 2,
        "all_system_gates_passed": True,
    }


def test_real_two_system_cycles_reduce_issue_innovation_and_close_ledgers(
    real_report,
) -> None:
    expected_feature_counts = {"center_hill": 435, "j_percy_priest": 43}
    for system_id in SYSTEM_IDS:
        system = real_report["systems"][system_id]
        analysis = system["state_analysis"]
        mass = system["physical_mass_ledger"]
        assert system["feature_count"] == expected_feature_counts[system_id]
        assert len(system["member_ids"]) == 7
        assert abs(analysis["innovation_after_analysis_m3s"]) < abs(
            analysis["innovation_before_analysis_m3s"]
        )
        assert analysis["forecast_ensemble_std_at_gauge_m3s"] > 0.0
        assert analysis["absolute_innovation_to_prior_std_ratio"] > 0.0
        assert analysis["mass_accounting_passed"] is True
        assert mass["check_count"] == mass["pass_count"] == 91
        assert mass["all_passed"] is True
        assert all(
            row["p90_spread_m3s"] > 0.0
            for row in system["forecast_by_horizon_hours"].values()
        )


def test_real_runner_has_no_future_value_or_scoring_input(real_report) -> None:
    parameters = set(
        inspect.signature(compile_real_ensemble_first_issue_report).parameters
    )
    assert not parameters.intersection(
        {"outcome_path", "target", "future_target", "score", "loss"}
    )
    assert real_report["data_isolation"] == {
        "input_accepts_outcome_path": False,
        "input_accepts_future_target": False,
        "input_accepts_score_or_loss": False,
        "future_target_values_loaded": False,
        "outcome_artifact_loaded": False,
        "scoring_artifact_loaded": False,
        "forecast_skill_computed": False,
        "issue_observation_source": (
            "sealed_outcome_free_predictions_issue_observed_outlet_m3s"
        ),
        "historical_issue_observation_publication_at_issue_time_verified": False,
    }
    assert real_report["claim_boundary"]["development_integration_only"] is True
    assert real_report["claim_boundary"]["superiority_claim_supported"] is False


def test_real_runner_rejects_tampered_sealed_prediction_identity(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_SEALED_ROLLOUT_REPORT.read_bytes())
    payload["prediction_artifact"]["sha256"] = "0" * 64
    tampered_report = tmp_path / "tampered-rollout-report.json"
    tampered_report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="real_ensemble_artifact_identity_mismatch"):
        compile_real_ensemble_first_issue_report(
            sealed_rollout_report_path=tampered_report
        )


def test_graph_partition_report_replays_and_preserves_marginal_variance(
    real_report,
    graph_partition_report,
) -> None:
    assert graph_partition_report == json.loads(
        DEFAULT_GRAPH_PARTITION_OUTPUT.read_bytes()
    )
    assert graph_partition_report["design"]["ensemble_design"] == (
        GRAPH_PARTITION_ENSEMBLE_DESIGN
    )
    assert graph_partition_report["design"]["ensemble_member_count"] == 25
    assert graph_partition_report["design"][
        "per_feature_sample_variance_by_source"
    ] == real_report["design"]["per_feature_sample_variance_by_source"]
    assert graph_partition_report["design"][
        "issue_observation_used_to_construct_members"
    ] is False


def test_graph_partition_real_cycles_increase_state_rank_and_close_ledgers(
    real_report,
    graph_partition_report,
) -> None:
    for system_id in SYSTEM_IDS:
        baseline = real_report["systems"][system_id]
        structured = graph_partition_report["systems"][system_id]
        assert structured["ensemble_member_count"] == 25
        assert structured["prior_state_ensemble"]["anomaly_matrix_rank"] > (
            baseline["prior_state_ensemble"]["anomaly_matrix_rank"]
        )
        assert structured["prior_state_ensemble"]["covariance_effective_rank"] > (
            baseline["prior_state_ensemble"]["covariance_effective_rank"]
        )
        assert structured["physical_mass_ledger"]["check_count"] == 325
        assert structured["physical_mass_ledger"]["pass_count"] == 325
        assert structured["execution_gates"]["all_passed"] is True


def test_external_profile_cycle_replays_and_reduces_underdispersion(
    graph_partition_report,
    external_profile_report,
) -> None:
    assert external_profile_report == json.loads(
        DEFAULT_EXTERNAL_PROFILE_OUTPUT.read_bytes()
    )
    assert external_profile_report["design"]["ensemble_design"] == (
        EXTERNAL_PROFILE_GRAPH_PARTITION_ENSEMBLE_DESIGN
    )
    assert external_profile_report["design"]["ensemble_member_count"] == 25
    for system_id in SYSTEM_IDS:
        baseline = graph_partition_report["systems"][system_id]
        external = external_profile_report["systems"][system_id]
        assert external["state_analysis"][
            "forecast_ensemble_std_at_gauge_m3s"
        ] > baseline["state_analysis"]["forecast_ensemble_std_at_gauge_m3s"]
        assert external["state_analysis"][
            "absolute_innovation_to_prior_std_ratio"
        ] < baseline["state_analysis"]["absolute_innovation_to_prior_std_ratio"]
        assert external["physical_mass_ledger"]["check_count"] == 325
        assert external["physical_mass_ledger"]["pass_count"] == 325
        assert external["external_uncertainty_profile"]["admitted"] is False
        assert external["execution_gates"]["all_passed"] is True


def test_external_profile_cycle_keeps_claim_boundary_diagnostic(
    external_profile_report,
) -> None:
    claims = external_profile_report["claim_boundary"]
    assert claims["external_physical_uncertainty_profile_executed"] is True
    assert claims["forecast_skill_scored"] is False
    assert claims["candidate_admitted"] is False
    assert claims["runtime_default_enabled"] is False
    assert claims["superiority_claim_supported"] is False


def test_external_profile_cycle_rejects_tampered_isolation_claim(
    tmp_path: Path,
) -> None:
    payload = json.loads(DEFAULT_EXTERNAL_PROFILE_REPORT.read_bytes())
    payload["data_isolation"]["evaluation_outcome_loaded"] = True
    tampered_report = tmp_path / "tampered-external-profile.json"
    tampered_report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="external_profile_report_invalid"):
        compile_real_ensemble_first_issue_report(
            external_profile_report_path=tampered_report,
            ensemble_design=EXTERNAL_PROFILE_GRAPH_PARTITION_ENSEMBLE_DESIGN,
        )


def test_real_runner_rejects_unknown_ensemble_design() -> None:
    with pytest.raises(ValueError, match="real_ensemble_design_invalid"):
        compile_real_ensemble_first_issue_report(ensemble_design="unknown")
