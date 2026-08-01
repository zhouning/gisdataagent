import copy
import json
from datetime import UTC, datetime

import pytest

from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_CANDIDATE_ID,
    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS,
    HorizonAssimilationPolicy,
)
from scripts.freeze_geospatial_kernel_horizon_assimilation_policy import (
    DEFAULT_PARENT_REPORT,
    compile_horizon_assimilation_policy_freeze,
)

EXPECTED_MODES = {
    "1": "linear_distance_localized_mainstem_update",
    "3": "quadratic_distance_localized_mainstem_update",
    "6": "outlet_only_observation_update",
    "12": "nominal",
}


def test_policy_round_trip_routes_only_registered_horizons() -> None:
    policy = HorizonAssimilationPolicy(
        candidate_id=HORIZON_ASSIMILATION_CANDIDATE_ID,
        supported_forecast_horizons_hours=(1, 3, 6, 12),
        selected_modes=tuple(EXPECTED_MODES[str(value)] for value in (1, 3, 6, 12)),
        selection_scope="joint_two_system_calibration_split_per_horizon_only",
    )
    restored = HorizonAssimilationPolicy.from_dict(policy.as_dict())

    assert restored == policy
    assert restored.mode_for_horizon(1) == EXPECTED_MODES["1"]
    assert restored.mode_for_horizon(12) == EXPECTED_MODES["12"]
    with pytest.raises(
        ValueError,
        match="horizon_assimilation_policy_horizon_unsupported",
    ):
        restored.mode_for_horizon(2)


def test_policy_deserialization_cannot_enable_unadmitted_candidate() -> None:
    payload = {
        "schema": "gwm.geospatial_kernel.horizon_assimilation_policy.v1",
        "candidate_id": HORIZON_ASSIMILATION_CANDIDATE_ID,
        "supported_forecast_horizons_hours": list(
            HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
        ),
        "selected_mode_by_horizon_hours": EXPECTED_MODES,
        "selection_scope": "joint_two_system_calibration_split_per_horizon_only",
        "admitted": True,
        "runtime_default_enabled": True,
    }

    with pytest.raises(ValueError, match="horizon_assimilation_policy_invalid"):
        HorizonAssimilationPolicy.from_dict(payload)


def test_real_freeze_selects_each_horizon_from_calibration_only() -> None:
    report = compile_horizon_assimilation_policy_freeze(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert report["policy"]["selected_mode_by_horizon_hours"] == EXPECTED_MODES
    assert report["selection"]["validation_issue_indices_used_for_selection"] == []
    assert report["future_evaluation_contract"][
        "current_parent_validation_split_eligible_for_scoring"
    ] is False
    assert report["claim_boundary"]["prospective_v5_changed"] is False
    assert report["claim_boundary"]["runtime_default_enabled"] is False


def test_validation_metric_mutation_cannot_change_frozen_selection(tmp_path) -> None:
    parent = json.loads(DEFAULT_PARENT_REPORT.read_bytes())
    baseline = compile_horizon_assimilation_policy_freeze(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    mutated = copy.deepcopy(parent)
    mutated["joint_validation_metrics"] = {"ignored": "deliberately_corrupted"}
    mutated["joint_validation_mode_comparison"] = {"ignored": 1e300}
    for system in mutated["systems"].values():
        system["validation_metrics"] = {"ignored": -1e300}
        system["validation_comparison"] = {"ignored": "not_read"}
        system["localization_validation_comparison"] = {"ignored": "not_read"}
    path = tmp_path / "mutated_parent.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")

    candidate = compile_horizon_assimilation_policy_freeze(
        parent_report_path=path,
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert candidate["policy"] == baseline["policy"]
    assert candidate["selection"] == baseline["selection"]


def test_freeze_rejects_parent_with_compromised_implementation_hash(tmp_path) -> None:
    parent = json.loads(DEFAULT_PARENT_REPORT.read_bytes())
    parent["implementation_artifacts"]["evaluator"]["sha256"] = "0" * 64
    path = tmp_path / "compromised_parent.json"
    path.write_text(json.dumps(parent), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="horizon_assimilation_policy_artifact_identity_mismatch",
    ):
        compile_horizon_assimilation_policy_freeze(
            parent_report_path=path,
            generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
