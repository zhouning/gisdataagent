import csv
import hashlib
import io
from datetime import UTC, datetime

import pytest

from scripts.evaluate_geospatial_kernel_issue_state_assimilation import (
    LINEAR_DISTANCE_MODE,
    QUADRATIC_DISTANCE_MODE,
    _graph_gain_profiles,
    _mainstem_ids,
    compile_issue_state_assimilation_posthoc,
)
from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
    _network,
)


@pytest.fixture(scope="module")
def assimilation_result(tmp_path_factory):
    output = tmp_path_factory.mktemp("issue-state-assimilation") / "predictions.csv"
    return compile_issue_state_assimilation_posthoc(
        output_path=output,
        issue_indices=(0, 60, 336, 348),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_real_two_system_assimilation_replays_nominal_and_conserves_mass(
    assimilation_result,
) -> None:
    body, report = assimilation_result
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))

    assert len(rows) == 2 * 4 * 3 * 4
    assert (
        report["aggregate_gates"]["both_systems_nominal_replay_matches_sealed_predictions"] is True
    )
    assert report["aggregate_gates"]["both_systems_all_analysis_ledgers_passed"] is True
    assert report["aggregate_gates"]["both_systems_all_physical_mass_balances_passed"] is True
    assert report["outputs"]["predictions"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_mainstem_update_uses_graph_support_and_preserves_branches(
    assimilation_result,
) -> None:
    body, report = assimilation_result
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    mainstem_rows = [
        row
        for row in rows
        if row["mode"] == "mainstem_ratio_observation_update"
        and row["observation_assimilated"] == "True"
    ]

    assert mainstem_rows
    assert all(float(row["branch_analysis_increment_max_abs_m3"]) == 0.0 for row in mainstem_rows)
    for system in report["systems"].values():
        assert system["execution_gates"]["mainstem_update_preserved_all_branch_states"] is True
        expected = system["network"]["mainstem_feature_count"] - 1
        system_rows = [row for row in mainstem_rows if row["system_id"] == system["system_id"]]
        assert all(int(row["graph_updated_feature_count"]) == expected for row in system_rows)


def test_negative_jpp_issue_observation_fails_closed_to_nominal(
    assimilation_result,
) -> None:
    body, report = assimilation_result
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
    assert all(
        row["observation_fallback_reason"] == "negative_discharge_outside_forward_manning_domain"
        for row in refused
    )
    assert all(
        float(row["predicted_outlet_m3s"]) == pytest.approx(float(row["nominal_sealed_outlet_m3s"]))
        for row in refused
    )
    observation = report["systems"]["j_percy_priest"]["observation"]
    assert observation["negative_values_clipped"] is False
    assert (
        observation["fallback_issue_count_by_reason_across_observation_modes"][
            "negative_discharge_outside_forward_manning_domain"
        ]
        == 4
    )


def test_mode_selection_is_calibration_only_and_cannot_promote(
    assimilation_result,
) -> None:
    _, report = assimilation_result

    assert report["selected_mode_from_joint_calibration"] in {
        "nominal",
        "outlet_only_observation_update",
        "mainstem_ratio_observation_update",
    }
    assert report["information_boundary"]["future_target_used_for_issue_state_update"] is False
    assert report["information_boundary"]["validation_targets_used_for_mode_selection"] is False
    assert report["aggregate_gates"]["fresh_prospective_validation_passed"] is False
    assert report["aggregate_gates"]["candidate_promotion_gate_passed"] is False
    assert report["claim_boundary"]["prospective_v5_changed"] is False


def test_issue_axis_requires_calibration_and_validation_support() -> None:
    with pytest.raises(
        ValueError,
        match="modeled_storage_scale_transfer_issue_split_invalid",
    ):
        compile_issue_state_assimilation_posthoc(
            issue_indices=(0, 12),
            generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )


def test_distance_localized_profiles_decay_upstream_without_branch_updates() -> None:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    topology = json.loads(
        (
            root / "benchmarks/geotransport_v0_1/j_percy_priest_v1_full_subnetwork_report.json"
        ).read_bytes()
    )
    network_payload = json.loads(
        (root / topology["artifacts"]["full_subnetwork"]["path"]).read_bytes()
    )
    network = _network(network_payload["network"])
    mainstem_ids, _ = _mainstem_ids(
        system_id="j_percy_priest",
        topology=topology,
        network_payload=network_payload,
        network=network,
    )
    rows, reports = _graph_gain_profiles(
        network=network,
        mainstem_ids=mainstem_ids,
        modes=(
            "nominal",
            "outlet_only_observation_update",
            LINEAR_DISTANCE_MODE,
            QUADRATIC_DISTANCE_MODE,
        ),
    )
    index = {feature_id: offset for offset, feature_id in enumerate(network.feature_ids)}
    linear = [rows[LINEAR_DISTANCE_MODE][index[value]] for value in mainstem_ids]
    quadratic = [rows[QUADRATIC_DISTANCE_MODE][index[value]] for value in mainstem_ids]

    assert linear[0] == 0.0
    assert linear[-1] == 0.0
    assert linear[1:-1] == sorted(linear[1:-1])
    assert all(0.0 <= right <= left <= 1.0 for left, right in zip(linear, quadratic, strict=True))
    assert all(
        rows[LINEAR_DISTANCE_MODE][index[value]] == 0.0
        for value in set(network.feature_ids) - set(mainstem_ids)
    )
    assert reports[LINEAR_DISTANCE_MODE]["outcome_fitted"] is False
