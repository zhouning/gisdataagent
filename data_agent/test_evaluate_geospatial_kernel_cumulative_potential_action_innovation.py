import csv
import hashlib
import io
from datetime import UTC, datetime

import pytest

from scripts.evaluate_geospatial_kernel_cumulative_potential_action_innovation import (
    WINDOW_NAMES,
    compile_cumulative_potential_action_innovation_posthoc,
)


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    output_path = tmp_path_factory.mktemp("cumulative-potential") / "predictions.csv"
    return compile_cumulative_potential_action_innovation_posthoc(
        output_path=output_path,
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_cumulative_potential_restores_structure_but_fails_accuracy(compiled) -> None:
    body, report = compiled
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))

    assert len(rows) == 9_616
    assert tuple(report["windows"]) == WINDOW_NAMES
    assert report["aggregate_comparison_to_hard_clip"] == {
        "comparison_count": 16,
        "candidate_lower_rmse_count": 7,
        "comparator_lower_rmse_count": 9,
        "equal_rmse_count": 0,
    }
    assert report["aggregate_comparison_to_recursive_boundary"] == {
        "comparison_count": 16,
        "candidate_lower_rmse_count": 5,
        "comparator_lower_rmse_count": 11,
        "equal_rmse_count": 0,
    }
    assert report["promotion_gate"]["four_window_structural_response_gate_passed"] is True
    assert report["promotion_gate"]["four_window_numerical_response_gate_passed"] is True
    assert report["promotion_gate"]["accuracy_gate_passed"] is False
    assert report["promotion_gate"]["posthoc_technical_gate_passed"] is False
    assert report["promotion_gate"]["cumulative_potential_candidate_promotion_gate_passed"] is False
    assert report["claim_boundary"]["action_innovation_candidate_changed"] is False
    assert report["claim_boundary"]["prospective_v5_changed"] is False
    assert all(row["future_outcome_observation_used"] == "False" for row in rows)
    assert report["outputs"]["predictions"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_cumulative_potential_window_pattern_and_response_are_locked(compiled) -> None:
    _, report = compiled
    windows = report["windows"]

    assert windows["center_hill_primary"]["comparison_to_hard_clip"][
        "comparator_lower_rmse_horizons_hours"
    ] == [1, 3, 6, 12]
    assert windows["center_hill_replication"]["comparison_to_hard_clip"][
        "candidate_lower_rmse_horizons_hours"
    ] == [1, 3, 12]
    assert windows["center_hill_replication"]["comparison_to_hard_clip"][
        "comparator_lower_rmse_horizons_hours"
    ] == [6]
    for name in ("j_percy_priest_primary", "j_percy_priest_replication"):
        assert windows[name]["comparison_to_hard_clip"]["candidate_lower_rmse_horizons_hours"] == [
            1,
            3,
        ]
        assert windows[name]["comparison_to_hard_clip"]["comparator_lower_rmse_horizons_hours"] == [
            6,
            12,
        ]

    for window in windows.values():
        structural = window["counterfactual_response"]["structural_gate"]
        assert structural["monotonicity_pass_count"] == structural["monotonicity_check_count"]
        assert window["execution"]["exact_boundary_step_count"] == 0
    assert windows["j_percy_priest_primary"]["counterfactual_response"]["numerical_usability_gate"][
        "post_lag_response_collapse_fraction"
    ] == pytest.approx(0.00585335797905114)
    assert windows["j_percy_priest_replication"]["counterfactual_response"][
        "numerical_usability_gate"
    ]["post_lag_response_collapse_fraction"] == pytest.approx(0.02181208053691275)
