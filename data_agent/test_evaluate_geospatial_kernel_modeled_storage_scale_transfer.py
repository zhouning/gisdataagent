import csv
import hashlib
import io
from datetime import UTC, datetime

import pytest

from scripts.evaluate_geospatial_kernel_modeled_storage_scale_transfer import (
    compile_modeled_storage_scale_transfer_posthoc,
)


@pytest.fixture(scope="module")
def transfer_result(tmp_path_factory):
    output = tmp_path_factory.mktemp("modeled-storage-scale-transfer") / "predictions.csv"
    return compile_modeled_storage_scale_transfer_posthoc(
        output_path=output,
        issue_indices=(0, 12, 336, 348),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_real_two_system_scale_transfer_replays_sealed_nominal_and_conserves_mass(
    transfer_result,
) -> None:
    body, report = transfer_result
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))

    assert len(rows) == 2 * 4 * 3 * 4
    assert report["aggregate_gates"][
        "both_systems_nominal_replay_matches_sealed_predictions"
    ] is True
    assert report["aggregate_gates"]["both_systems_all_mass_balances_passed"] is True
    for system in report["systems"].values():
        gates = system["execution_gates"]
        assert gates["mass_balance_pass_count"] == gates["mass_balance_check_count"]
        assert gates["maximum_nominal_replay_absolute_error_m3s"] <= gates[
            "nominal_replay_tolerance_m3s"
        ]
    assert report["outputs"]["predictions"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_scale_selection_uses_only_calibration_split_and_reports_validation(
    transfer_result,
) -> None:
    _, report = transfer_result

    for system in report["systems"].values():
        assert system["execution"]["calibration_issue_count"] == 2
        assert system["execution"]["validation_issue_count"] == 2
        assert system["selected_storage_scale_factor"] in {0.8, 1.0, 1.2}
        assert set(system["validation_comparison"]["per_horizon"]) == {
            "1",
            "3",
            "6",
            "12",
        }
        assert system["claim_boundary"]["selection_uses_calibration_outcomes"] is True
        assert system["claim_boundary"]["selection_uses_validation_outcomes"] is False


def test_historical_transfer_cannot_promote_candidate(transfer_result) -> None:
    _, report = transfer_result

    assert report["information_boundary"][
        "historical_outcomes_were_exposed_before_experiment_design"
    ] is True
    assert report["aggregate_gates"]["fresh_prospective_validation_passed"] is False
    assert report["aggregate_gates"]["candidate_promotion_gate_passed"] is False
    assert report["claim_boundary"]["state_scale_candidate_admitted"] is False
    assert report["claim_boundary"]["prospective_v5_changed"] is False


def test_issue_axis_requires_calibration_and_validation_support() -> None:
    with pytest.raises(
        ValueError, match="modeled_storage_scale_transfer_issue_split_invalid"
    ):
        compile_modeled_storage_scale_transfer_posthoc(
            issue_indices=(0, 12),
            generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
