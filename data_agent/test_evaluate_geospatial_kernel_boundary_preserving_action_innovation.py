import csv
import hashlib
import io
from datetime import UTC, datetime

import pytest

from scripts.evaluate_geospatial_kernel_boundary_preserving_action_innovation import (
    WINDOW_NAMES,
    compile_boundary_preserving_action_innovation_posthoc,
)


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    output_path = tmp_path_factory.mktemp("bounded-action-innovation") / "predictions.csv"
    return compile_boundary_preserving_action_innovation_posthoc(
        output_path=output_path,
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_boundary_candidate_is_falsified_without_changing_frozen_candidate(compiled) -> None:
    body, report = compiled
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))

    assert len(rows) == 9_616
    assert tuple(report["windows"]) == WINDOW_NAMES
    assert report["aggregate_comparison"] == {
        "comparison_count": 16,
        "boundary_lower_rmse_count": 7,
        "hard_clip_lower_rmse_count": 9,
        "equal_rmse_count": 0,
    }
    assert report["promotion_gate"]["accuracy_gate_passed"] is False
    assert report["promotion_gate"]["four_window_structural_response_gate_passed"] is False
    assert report["promotion_gate"]["posthoc_technical_gate_passed"] is False
    assert report["promotion_gate"]["boundary_preserving_candidate_promotion_gate_passed"] is False
    assert report["claim_boundary"]["action_innovation_candidate_changed"] is False
    assert report["claim_boundary"]["prospective_v5_changed"] is False
    assert all(row["future_outcome_observation_used"] == "False" for row in rows)
    assert report["outputs"]["predictions"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_boundary_candidate_trades_clipping_for_accuracy_and_monotonicity(compiled) -> None:
    _, report = compiled
    windows = report["windows"]

    assert windows["center_hill_primary"]["comparison_to_hard_clip"][
        "hard_clip_lower_rmse_horizons_hours"
    ] == [1, 3, 6, 12]
    assert windows["center_hill_replication"]["comparison_to_hard_clip"][
        "boundary_lower_rmse_horizons_hours"
    ] == [1, 3, 6, 12]
    assert windows["j_percy_priest_primary"]["comparison_to_hard_clip"][
        "boundary_lower_rmse_horizons_hours"
    ] == [1, 3]
    assert windows["j_percy_priest_replication"]["comparison_to_hard_clip"][
        "boundary_lower_rmse_horizons_hours"
    ] == [1]

    for window in windows.values():
        assert window["execution"]["exact_boundary_step_count"] == 0
        assert (
            window["comparison_to_hard_clip_response"][
                "boundary_preserving_scenario_clipped_step_fraction"
            ]
            == 0.0
        )
    assert (
        windows["center_hill_primary"]["counterfactual_response"]["structural_gate"][
            "monotonicity_pass_count"
        ]
        == 2_575
    )
    assert (
        windows["center_hill_primary"]["counterfactual_response"]["structural_gate"][
            "monotonicity_check_count"
        ]
        == 2_604
    )
    assert (
        windows["center_hill_replication"]["counterfactual_response"]["structural_gate"][
            "monotonicity_pass_count"
        ]
        == 2_605
    )
    assert (
        windows["center_hill_replication"]["counterfactual_response"]["structural_gate"][
            "monotonicity_check_count"
        ]
        == 2_608
    )

    primary_change = windows["j_percy_priest_primary"]["comparison_to_hard_clip_response"][
        "collapse_fraction_change"
    ]
    replication_change = windows["j_percy_priest_replication"]["comparison_to_hard_clip_response"][
        "collapse_fraction_change"
    ]
    assert primary_change == pytest.approx(-0.01940850277264325)
    assert replication_change == pytest.approx(-0.02181208053691275)
