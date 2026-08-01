import csv
import hashlib
import io
from datetime import UTC, datetime
from types import SimpleNamespace

from scripts.audit_geospatial_kernel_conservative_twin_action_response import (
    _signed_response_passes,
    compile_conservative_twin_action_response_posthoc,
)


def test_real_two_system_twin_response_is_conservative_and_not_promoted(
    tmp_path,
) -> None:
    output = tmp_path / "responses.csv"
    body, report = compile_conservative_twin_action_response_posthoc(
        output_path=output,
        issue_indices=(0,),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))

    assert len(rows) == 2 * 4 * 4
    assert set(report["systems"]) == {"center_hill", "j_percy_priest"}
    assert report["aggregate_gates"]["two_system_structural_gate_passed"] is True
    assert report["aggregate_gates"]["mechanistic_candidate_promotion_gate_passed"] is False
    assert report["claim_boundary"]["prospective_v5_changed"] is False
    assert report["claim_boundary"]["candidate_promoted"] is False
    assert report["outputs"]["responses"]["sha256"] == hashlib.sha256(body).hexdigest()
    assert all(row["future_outcome_observation_used"] == "False" for row in rows)


def test_real_two_system_twin_response_partitions_action_volume(tmp_path) -> None:
    _, report = compile_conservative_twin_action_response_posthoc(
        output_path=tmp_path / "responses.csv",
        issue_indices=(0,),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    for system in report["systems"].values():
        gates = system["structural_gates"]
        assert gates["mass_balance_pass_count"] == gates["mass_balance_check_count"]
        assert gates["signed_response_pass_count"] == gates["signed_response_check_count"]
        assert gates["release_ordering_pass_count"] == gates["release_ordering_check_count"]
        partition = system["twelve_hour_partition"]
        assert (
            abs(
                partition["median_input_recovered_at_outlet_fraction"]
                + partition["median_input_retained_in_storage_fraction"]
                - 1.0
            )
            < 1e-9
        )
        assert system["claim_boundary"]["predictive_accuracy_scored"] is False


def test_response_sign_follows_scenario_history_when_current_input_delta_is_zero() -> None:
    retained_negative_response = SimpleNamespace(
        incremental_action_input_volume_m3=0.0,
        incremental_outlet_mean_flow_m3s=-0.25,
    )

    assert _signed_response_passes(-50.0, retained_negative_response) is True
    assert _signed_response_passes(50.0, retained_negative_response) is False
