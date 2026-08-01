import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze
from scripts import plan_geospatial_kernel_horizon_assimilation_holdout_inputs as plan

EXPECTED_POLICY_SHA256 = (
    "69d191ee497c80aa1340d39a0932a726eba23dcd1061c14c1f0f8c6e0e148278"
)


def test_holdout_protocol_locks_unused_window_and_candidate_identity() -> None:
    report = freeze.compile_holdout_protocol(
        frozen_at=datetime(2026, 8, 1, 3, tzinfo=UTC)
    )
    window = report["window"]

    assert report["status"] == "frozen_before_holdout_input_value_access"
    assert report["candidate_lock"]["policy_sha256"] == EXPECTED_POLICY_SHA256
    assert report["candidate_lock"]["policy_change_after_freeze_permitted"] is False
    assert report["time_axis_evidence"]["initial_state_time_chunk_index"] == 563
    assert report["time_axis_evidence"]["forcing_time_chunk_index"] == 564
    assert window["initial_state_valid_at_utc"] == "2022-04-28T00:00:00Z"
    assert window["start_inclusive_utc"] == "2022-04-28T01:00:00Z"
    assert window["end_exclusive_utc"] == "2022-05-26T01:00:00Z"
    assert window["hour_count"] == 672
    assert window["issue_indices"] == list(range(0, 672, 12))
    assert window["issue_count_per_system"] == 56
    assert window["horizons_hours"] == [1, 3, 6, 12]
    assert window["issue_times_utc"][0] == "2022-04-28T01:00:00Z"
    assert window["issue_times_utc"][-1] == "2022-05-25T13:00:00Z"
    assert window["target_times_utc_by_horizon"]["12"][-1] == (
        "2022-05-26T01:00:00Z"
    )


def test_holdout_protocol_keeps_scoring_and_claims_fail_closed() -> None:
    report = freeze.compile_holdout_protocol(
        frozen_at=datetime(2026, 8, 1, 3, tzinfo=UTC)
    )
    scoring = report["scoring_lock"]
    claims = report["claim_boundary"]

    assert scoring["primary_metric"] == "rmse_m3s"
    assert scoring["fixed_single_mode_comparator"] == (
        "quadratic_distance_localized_mainstem_update"
    )
    assert scoring["traditional_comparator"] == (
        "causal_issue_observation_persistence"
    )
    assert scoring["cross_system_or_cross_horizon_compensation_permitted"] is False
    assert "every_system_and_horizon" in scoring["candidate_support_gate"]
    assert report["rolling_origin_contract"][
        "next_issue_observation_request_before_current_joint_issue_seal"
    ] is False
    assert report["rolling_origin_contract"][
        "issue_observation_value_visible_only_to_matching_issue"
    ] is True
    assert claims == {
        "holdout_protocol_frozen": True,
        "holdout_inputs_acquired": False,
        "outcome_free_predictions_executed": False,
        "holdout_outcomes_acquired": False,
        "candidate_support_gate_evaluated": False,
        "geospatial_kernel_validated": False,
        "prospective_v5_changed": False,
        "candidate_promoted": False,
        "runtime_default_enabled": False,
    }


@pytest.mark.parametrize("field", ["candidate_promoted", "runtime_default_enabled"])
def test_holdout_protocol_rejects_promoted_policy_freeze(tmp_path, field: str) -> None:
    payload = json.loads(freeze.DEFAULT_POLICY_FREEZE.read_bytes())
    payload["claim_boundary"][field] = True
    path = tmp_path / "unsafe-policy-freeze.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="horizon_holdout_policy_freeze_invalid"):
        freeze.compile_holdout_protocol(
            policy_freeze_path=path,
            frozen_at=datetime(2026, 8, 1, 3, tzinfo=UTC),
        )


def test_holdout_protocol_rejects_tampered_policy_or_core_hash(tmp_path) -> None:
    policy_tampered = json.loads(freeze.DEFAULT_POLICY_FREEZE.read_bytes())
    policy_tampered["policy"]["selected_mode_by_horizon_hours"]["1"] = "nominal"
    policy_path = tmp_path / "tampered-policy.json"
    policy_path.write_text(json.dumps(policy_tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="horizon_holdout_policy_hash_mismatch"):
        freeze.compile_holdout_protocol(
            policy_freeze_path=policy_path,
            frozen_at=datetime(2026, 8, 1, 3, tzinfo=UTC),
        )

    core_tampered = json.loads(freeze.DEFAULT_POLICY_FREEZE.read_bytes())
    core_tampered["implementation_artifacts"]["outcome_free_rollout_core"][
        "sha256"
    ] = "0" * 64
    core_path = tmp_path / "tampered-core.json"
    core_path.write_text(json.dumps(core_tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="horizon_holdout_artifact_identity_mismatch"):
        freeze.compile_holdout_protocol(
            policy_freeze_path=core_path,
            frozen_at=datetime(2026, 8, 1, 3, tzinfo=UTC),
        )


def test_generated_protocol_is_exactly_reconstructible() -> None:
    payload = json.loads(freeze.DEFAULT_OUTPUT.read_bytes())
    frozen_at = datetime.fromisoformat(payload["frozen_at"])

    assert payload == freeze.compile_holdout_protocol(frozen_at=frozen_at)


def test_protocol_freezer_refuses_to_overwrite_frozen_artifact() -> None:
    with pytest.raises(ValueError, match="horizon_holdout_artifact_already_exists"):
        freeze._assert_pristine(freeze.DEFAULT_OUTPUT)


def test_input_plan_counts_and_issue_requests_are_strictly_causal() -> None:
    report = plan.compile_holdout_input_plan(
        generated_at=datetime(2026, 8, 1, 4, tzinfo=UTC)
    )

    assert report["request_counts"] == {
        "nwm_unique_object_count": 8,
        "cwms_action_request_count": 2,
        "usgs_issue_observation_request_count": 112,
        "usgs_full_outcome_request_count": 0,
        "total_external_request_count_if_executed": 122,
    }
    assert {(value["variable"], value["chunk_key"]) for value in report["nwm_requests"]} == {
        ("streamflow", "563.63"),
        ("streamflow", "563.87"),
        ("velocity", "563.63"),
        ("velocity", "563.87"),
        ("q_lateral", "564.63"),
        ("q_lateral", "564.87"),
        ("time", "563"),
        ("time", "564"),
    }

    issue_request_count = 0
    for system in report["systems"].values():
        assert system["full_outcome_request_included"] is False
        assert system["action_request"]["future_target_observation"] is False
        assert system["issue_observation_request_count"] == 56
        for request in system["issue_observation_requests"]:
            issue_request_count += 1
            issue_time = datetime.fromisoformat(request["issue_time_utc"])
            request_start = datetime.fromisoformat(request["request_start_utc"])
            request_end = datetime.fromisoformat(request["request_end_utc"])
            query = parse_qs(urlparse(request["url"]).query)
            assert request_end == issue_time
            assert request_start == issue_time - timedelta(minutes=5)
            assert request["post_issue_value_requested"] is False
            assert query["startDT"] == [request["request_start_utc"]]
            assert query["endDT"] == [request["issue_time_utc"]]
            assert query["parameterCd"] == ["00060"]
    assert issue_request_count == 112
    assert report["decoded_input_contract"]["target_observation_columns_permitted"] is False
    assert report["decoded_input_contract"]["score_or_loss_columns_permitted"] is False
    assert report["issue_observation_request_contract"][
        "bulk_prefetch_all_issue_observation_values_permitted"
    ] is False
    assert report["issue_observation_request_contract"][
        "next_issue_request_before_current_joint_issue_seal"
    ] is False
    assert report["data_isolation"]["network_request_executed"] is False
    assert report["data_isolation"]["dynamic_value_loaded"] is False
    assert report["data_isolation"]["full_outcome_url_compiled"] is False


def test_input_plan_rejects_any_protocol_mutation(tmp_path) -> None:
    original = json.loads(freeze.DEFAULT_OUTPUT.read_bytes())
    mutations = (
        ("window", "hour_count", 671),
        ("candidate_lock", "policy_sha256", "0" * 64),
        ("scoring_lock", "traditional_comparator", "post_issue_oracle"),
        ("claim_boundary", "holdout_inputs_acquired", True),
    )

    for index, (section, key, value) in enumerate(mutations):
        payload = copy.deepcopy(original)
        payload[section][key] = value
        path = tmp_path / f"mutated-protocol-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(
            ValueError,
            match="horizon_holdout_input_plan_protocol_invalid",
        ):
            plan.compile_holdout_input_plan(
                protocol_path=path,
                generated_at=datetime(2026, 8, 1, 4, tzinfo=UTC),
            )


def test_generated_input_plan_binds_exact_protocol_bytes() -> None:
    protocol_body = freeze.DEFAULT_OUTPUT.read_bytes()
    payload = json.loads(plan.DEFAULT_OUTPUT.read_bytes())

    assert payload["protocol"]["sha256"] == hashlib.sha256(protocol_body).hexdigest()
    assert payload["protocol"]["size_bytes"] == len(protocol_body)
    assert payload["claim_boundary"]["candidate_promoted"] is False
    assert payload["claim_boundary"]["runtime_default_enabled"] is False
