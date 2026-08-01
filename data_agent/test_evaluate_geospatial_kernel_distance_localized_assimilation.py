import csv
import hashlib
import io
from datetime import UTC, datetime

import pytest

from scripts.evaluate_geospatial_kernel_distance_localized_assimilation import (
    LINEAR_DISTANCE_MODE,
    QUADRATIC_DISTANCE_MODE,
    compile_distance_localized_assimilation_posthoc,
)


@pytest.fixture(scope="module")
def localization_result(tmp_path_factory):
    output = tmp_path_factory.mktemp("distance-localized-assimilation") / "predictions.csv"
    return compile_distance_localized_assimilation_posthoc(
        output_path=output,
        issue_indices=(0, 60, 336, 348),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_real_two_system_localization_replays_nominal_and_conserves_mass(
    localization_result,
) -> None:
    body, report = localization_result
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))

    assert len(rows) == 2 * 4 * 4 * 4
    assert (
        report["aggregate_gates"]["both_systems_nominal_replay_matches_sealed_predictions"] is True
    )
    assert report["aggregate_gates"]["both_systems_all_analysis_ledgers_passed"] is True
    assert report["aggregate_gates"]["both_systems_all_physical_mass_balances_passed"] is True
    assert report["outputs"]["predictions"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_localized_profiles_are_candidate_branch_preserving_and_outcome_free(
    localization_result,
) -> None:
    _, report = localization_result

    for system in report["systems"].values():
        profiles = system["network"]["graph_gain_profiles"]
        assert set(profiles) == {LINEAR_DISTANCE_MODE, QUADRATIC_DISTANCE_MODE}
        assert all(profile["outcome_fitted"] is False for profile in profiles.values())
        assert system["execution_gates"]["mainstem_update_preserved_all_branch_states"] is True
        assert (
            system["execution_gates"][
                "admitted_nominal_and_outlet_closures_and_diagnostic_mainstem_closure"
            ]
            is True
        )


def test_negative_observations_refuse_all_assimilation_modes(localization_result) -> None:
    body, report = localization_result
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    refused = [
        row
        for row in rows
        if row["system_id"] == "j_percy_priest"
        and row["issue_index"] in {"60", "336"}
        and row["mode"] != "nominal"
    ]

    assert refused
    assert all(row["observation_assimilated"] == "False" for row in refused)
    observation = report["systems"]["j_percy_priest"]["observation"]
    assert observation["fallback_issue_count"] == 2
    assert (
        observation["fallback_issue_count_by_reason_across_observation_modes"][
            "negative_discharge_outside_forward_manning_domain"
        ]
        == 6
    )


def test_localization_selection_is_calibration_only_and_cannot_promote(
    localization_result,
) -> None:
    _, report = localization_result

    assert report["selected_mode_from_joint_calibration"] in {
        "nominal",
        "outlet_only_observation_update",
        LINEAR_DISTANCE_MODE,
        QUADRATIC_DISTANCE_MODE,
    }
    assert report["information_boundary"]["validation_targets_used_for_family_selection"] is False
    assert report["aggregate_gates"]["fresh_prospective_validation_passed"] is False
    assert report["aggregate_gates"]["candidate_promotion_gate_passed"] is False
    assert report["claim_boundary"]["prospective_v5_changed"] is False
