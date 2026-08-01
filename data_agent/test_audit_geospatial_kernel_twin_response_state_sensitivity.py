import csv
import hashlib
import io
from datetime import UTC, datetime

import pytest

from scripts.audit_geospatial_kernel_twin_response_state_sensitivity import (
    compile_twin_response_state_sensitivity_posthoc,
)


@pytest.fixture(scope="module")
def sensitivity_result(tmp_path_factory):
    output = tmp_path_factory.mktemp("twin-state-sensitivity") / "responses.csv"
    return compile_twin_response_state_sensitivity_posthoc(
        output_path=output,
        issue_indices=(0,),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_real_two_system_issue_state_sensitivity_is_conservative_and_not_promoted(
    sensitivity_result,
) -> None:
    body, report = sensitivity_result
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))

    assert len(rows) == 2 * 1 * 3 * 2
    assert set(report["systems"]) == {"center_hill", "j_percy_priest"}
    assert report["aggregate_gates"]["two_system_structural_gate_passed"] is True
    assert report["aggregate_gates"]["mechanistic_candidate_promotion_gate_passed"] is False
    assert report["claim_boundary"]["prospective_v5_changed"] is False
    assert report["claim_boundary"]["candidate_promoted"] is False
    assert report["outputs"]["responses"]["sha256"] == hashlib.sha256(body).hexdigest()
    assert all(row["future_outcome_observation_used"] == "False" for row in rows)


def test_stage32_rejection_and_non_universal_lag_boundary_are_preserved(
    sensitivity_result,
) -> None:
    _, report = sensitivity_result
    boundary = report["lag_evidence_boundary"]

    assert boundary["center_hill_common_empirical_support_admitted"] is False
    assert boundary["center_hill_common_supported_lags_hours"] == []
    assert boundary["center_hill_event_supported_lags_hours"] == [
        [5, 6, 7],
        [6, 7],
        [7],
        [],
    ]
    assert boundary["center_hill_event_response_detectable"] == [True, True, True, False]
    assert boundary["center_hill_empirical_lag_is_physical_travel_time"] is False
    assert boundary["j_percy_priest_independent_lag_support_bound"] is False
    assert report["diagnostic_interpretation"][
        "five_hour_reference_validated_as_travel_time"
    ] is False


def test_all_scales_preserve_mass_sign_order_and_cross_system_contrast(
    sensitivity_result,
) -> None:
    _, report = sensitivity_result

    for system in report["systems"].values():
        gates = system["structural_gates"]
        assert gates["mass_balance_pass_count"] == gates["mass_balance_check_count"]
        assert gates["signed_response_pass_count"] == gates["signed_response_check_count"]
        assert gates["release_ordering_pass_count"] == gates["release_ordering_check_count"]
        assert system["claim_boundary"]["predictive_accuracy_scored"] is False
    assert report["systems"]["center_hill"]["storage_sensitivity"][
        "comparison_pair_count"
    ] == 2
    assert report["systems"]["j_percy_priest"]["storage_sensitivity"][
        "comparison_pair_count"
    ] == 1
    assert report["systems"]["j_percy_priest"]["action_support"][
        "zero_excitation_rollout_count"
    ] == 3
    cross_system = report["cross_system_robustness"]
    assert cross_system["aligned_requested_comparison_count"] == 6
    assert cross_system["aligned_comparison_count"] == 3
    assert cross_system["excluded_zero_excitation_comparison_count"] == 3
    assert cross_system["comparable_release_deltas_m3s"] == [50.0]
    assert cross_system["center_hill_lower_outlet_recovery_pass_count"] == 3
    assert cross_system["center_hill_higher_storage_retention_pass_count"] == 3
    assert cross_system["center_hill_lower_response_gain_pass_count"] == 3
    assert cross_system["all_three_partition_rankings_preserved"] is True


def test_storage_scale_factors_must_include_nominal_and_be_ordered() -> None:
    with pytest.raises(
        ValueError, match="twin_state_sensitivity_storage_scale_factors_invalid"
    ):
        compile_twin_response_state_sensitivity_posthoc(
            issue_indices=(0,),
            storage_scale_factors=(0.8, 1.2),
            generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
