import copy

import pytest
import torch

from data_agent.test_uwm_geospatial_kernel_state_prior_admission import (
    _admitted_fixture,
    _dam_gk_batch_and_config,
)
from data_agent.uwm.dam_geospatial_kernel import (
    DAM_GK_STATE_PRIOR_HOLDOUT_OPENING_SCHEMA,
    DAM_GK_STATE_PRIOR_PROTOCOL_REGISTRATION_SCHEMA,
    DAM_GK_STATE_PRIOR_TRANSITION_PROTOCOL_SCHEMA,
    REQUIRED_TRANSITION_HOLDOUT_SPLITS,
    TRANSITION_EVALUATION_GATES,
    bind_admitted_state_prior_node_context,
    build_dam_gk_state_prior_transition_evaluation,
    build_dam_gk_state_prior_transition_protocol,
    build_state_prior_transition_holdout_opening,
    build_state_prior_transition_protocol_registration,
    compute_state_prior_paired_input_sha256,
    compute_state_prior_prediction_sha256,
    compute_state_prior_transition_holdout_opening_sha256,
    compute_state_prior_transition_protocol_registration_sha256,
    compute_state_prior_transition_protocol_sha256,
    validate_dam_gk_state_prior_transition_evaluation,
    validate_dam_gk_state_prior_transition_protocol,
    validate_state_prior_transition_holdout_opening,
    validate_state_prior_transition_protocol_registration,
    with_state_prior_context_control,
)


def test_paired_observed_holdout_fixture_passes_all_transition_skill_gates():
    full, zero, shuffled = _bindings()
    rows = _holdout_records()
    evaluation = _evaluation(
        full=full,
        zero=zero,
        shuffled=shuffled,
        rows=rows,
    )

    assert validate_dam_gk_state_prior_transition_evaluation(evaluation) == {
        "valid": True,
        "errors": [],
    }
    assert evaluation["state_prior_transition_evaluation_ready"] is True
    assert (
        evaluation["transition_protocol"]["schema"] == DAM_GK_STATE_PRIOR_TRANSITION_PROTOCOL_SCHEMA
    )
    assert evaluation["protocol_sha256"] == evaluation["transition_protocol"]["protocol_sha256"]
    assert set(evaluation["readiness_gates"]) == set(TRANSITION_EVALUATION_GATES)
    assert all(evaluation["readiness_gates"].values())
    assert evaluation["remaining_gates"] == []
    assert evaluation["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert evaluation["state_prior_transition_skill_improvement_claim"] is True
    assert evaluation["action_conditioned_dynamics_claim"] is False
    for split in REQUIRED_TRANSITION_HOLDOUT_SPLITS:
        metrics = evaluation["split_metrics"][split]
        assert metrics["sample_count"] == 10
        assert metrics["full_state_prior"]["mae"] < metrics["traditional_baseline"]["mae"]
        assert metrics["full_state_prior"]["mae"] < metrics["zero_state_prior"]["mae"]
        assert metrics["full_state_prior"]["mae"] < metrics["shuffled_state_prior"]["mae"]
        assert metrics["full_state_prior"]["interval_coverage"] == 1.0


@pytest.mark.parametrize(
    ("mutation", "failed_gate"),
    [
        ("zero_is_better", "full_beats_zero_prior_every_split"),
        ("coverage_failure", "calibrated_interval_coverage_every_split"),
        ("leakage", "strict_leakage_audit_passed"),
    ],
)
def test_scientific_gate_failure_returns_valid_not_for_claim_result(mutation, failed_gate):
    full, zero, shuffled = _bindings()
    rows = _holdout_records()
    leakage = _leakage_audit()
    if mutation == "zero_is_better":
        for row in rows:
            if row["split"] == "unseen_region":
                row["zero_prediction"] = row["target"]
    elif mutation == "coverage_failure":
        for row in rows:
            if row["split"] == "low_sample_region":
                row["full_interval_lower"] = row["full_prediction"] - 0.001
                row["full_interval_upper"] = row["full_prediction"] + 0.001
    else:
        leakage["state_prior_fit_used_holdout_targets"] = True
        leakage["passed"] = False

    evaluation = _evaluation(
        full=full,
        zero=zero,
        shuffled=shuffled,
        rows=rows,
        leakage_audit=leakage,
    )

    assert validate_dam_gk_state_prior_transition_evaluation(evaluation) == {
        "valid": True,
        "errors": [],
    }
    assert evaluation["state_prior_transition_evaluation_ready"] is False
    assert evaluation["readiness_gates"][failed_gate] is False
    assert failed_gate in evaluation["remaining_gates"]
    assert evaluation["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert evaluation["state_prior_transition_skill_improvement_claim"] is False


def test_public_proxy_can_only_exercise_evaluator_without_transition_claim():
    full, zero, shuffled = _bindings()
    evaluation = _evaluation(
        full=full,
        zero=zero,
        shuffled=shuffled,
        rows=_holdout_records(),
        source_evidence_kind="public_proxy",
    )

    assert evaluation["state_prior_transition_evaluation_ready"] is False
    assert evaluation["readiness_gates"]["observed_holdout_evidence_present"] is False
    assert evaluation["supported_claim"] == "state_prior_transition_evaluator_execution_only"
    assert evaluation["claim_boundary"]["max_claim_level"] == "exploratory_only"


def test_prediction_artifact_hash_or_context_binding_mismatch_is_rejected():
    full, zero, shuffled = _bindings()
    rows = _holdout_records()
    protocol = _protocol(full, zero, shuffled)
    registration, opening = _receipt_chain(protocol)
    artifacts, evidence_refs = _prediction_artifacts(
        rows,
        full,
        zero,
        shuffled,
        protocol,
        registration,
        opening,
    )
    artifacts["full_state_prior"]["predictions_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="full_state_prior_predictions_sha256_mismatch"):
        build_dam_gk_state_prior_transition_evaluation(
            evaluation_id="invalid-prediction-artifact",
            created_at="2026-08-04T16:30:00Z",
            protocol=protocol,
            protocol_registration_receipt=registration,
            holdout_opening_receipt=opening,
            full_binding=full,
            zero_binding=zero,
            shuffled_binding=shuffled,
            holdout_records=rows,
            prediction_artifacts=artifacts,
            evidence_refs=evidence_refs,
            leakage_audit=_leakage_audit(),
        )

    with pytest.raises(ValueError, match="zero_binding_required"):
        _evaluation(
            full=full,
            zero=full,
            shuffled=shuffled,
            rows=rows,
        )


def test_holdout_records_require_complete_fixed_kernel_evidence():
    full, zero, shuffled = _bindings()
    rows = _holdout_records()
    rows[0]["forcing_sha256"] = "not-a-digest"

    with pytest.raises(ValueError, match="forcing_sha256_invalid"):
        _evaluation(
            full=full,
            zero=zero,
            shuffled=shuffled,
            rows=rows,
        )

    unknown_node_rows = _holdout_records()
    unknown_node_rows[0]["node_key"] = "node-outside-binding"
    with pytest.raises(ValueError, match="holdout_node_not_in_binding"):
        _evaluation(
            full=full,
            zero=zero,
            shuffled=shuffled,
            rows=unknown_node_rows,
        )


def test_transition_evaluation_validator_blocks_claim_escalation():
    full, zero, shuffled = _bindings()
    evaluation = _evaluation(
        full=full,
        zero=zero,
        shuffled=shuffled,
        rows=_holdout_records(),
    )
    forged = copy.deepcopy(evaluation)
    forged["policy_causal_effect_claim"] = True
    forged["general_geospatial_world_model_validation_claim"] = True

    validation = validate_dam_gk_state_prior_transition_evaluation(forged)

    assert not validation["valid"]
    assert "policy_causal_effect_claim_must_be_false" in validation["errors"]
    assert "general_geospatial_world_model_validation_claim_must_be_false" in validation["errors"]


def test_transition_protocol_freezes_design_before_holdout_access():
    full, zero, shuffled = _bindings()

    protocol = _protocol(full, zero, shuffled)

    assert validate_dam_gk_state_prior_transition_protocol(protocol) == {
        "valid": True,
        "errors": [],
    }
    assert protocol["schema"] == DAM_GK_STATE_PRIOR_TRANSITION_PROTOCOL_SCHEMA
    assert protocol["created_at"] < protocol["frozen_at"] < protocol["holdout_access_not_before"]
    assert protocol["evaluation_design"]["primary_metric"] == "mae"
    assert protocol["evaluation_design"]["minimum_samples_per_split"] == 10
    assert protocol["control_definitions"]["shuffled_state_prior"]["seed"] == 17
    assert protocol["model_contract"]["candidate_control_shared_model_sha256"] == "1" * 64


@pytest.mark.parametrize("mutation", ["threshold", "model_sha256"])
def test_transition_protocol_hash_detects_frozen_design_mutation(mutation):
    full, zero, shuffled = _bindings()
    protocol = _protocol(full, zero, shuffled)
    if mutation == "threshold":
        protocol["evaluation_design"]["minimum_relative_improvement"] = 0.0
    else:
        protocol["model_contract"]["candidate_control_shared_model_sha256"] = "9" * 64

    validation = validate_dam_gk_state_prior_transition_protocol(protocol)

    assert not validation["valid"]
    assert "protocol_sha256_mismatch" in validation["errors"]


def test_transition_protocol_frozen_after_holdout_access_is_rejected():
    full, zero, shuffled = _bindings()

    with pytest.raises(ValueError, match="protocol_frozen_after_holdout_access"):
        _protocol(
            full,
            zero,
            shuffled,
            frozen_at="2026-08-04T15:55:00Z",
            holdout_access_not_before="2026-08-04T15:50:00Z",
        )


def test_prediction_artifact_with_different_protocol_is_rejected():
    full, zero, shuffled = _bindings()
    rows = _holdout_records()
    protocol = _protocol(full, zero, shuffled)
    registration, opening = _receipt_chain(protocol)
    artifacts, evidence_refs = _prediction_artifacts(
        rows,
        full,
        zero,
        shuffled,
        protocol,
        registration,
        opening,
    )
    artifacts["shuffled_state_prior"]["protocol_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="shuffled_state_prior_protocol_sha256_mismatch"):
        build_dam_gk_state_prior_transition_evaluation(
            evaluation_id="protocol-mismatched-prediction-artifact",
            created_at="2026-08-04T16:30:00Z",
            protocol=protocol,
            protocol_registration_receipt=registration,
            holdout_opening_receipt=opening,
            full_binding=full,
            zero_binding=zero,
            shuffled_binding=shuffled,
            holdout_records=rows,
            prediction_artifacts=artifacts,
            evidence_refs=evidence_refs,
            leakage_audit=_leakage_audit(),
        )


def test_transition_protocol_validator_blocks_claim_escalation_even_with_new_hash():
    full, zero, shuffled = _bindings()
    protocol = _protocol(full, zero, shuffled)
    forged = copy.deepcopy(protocol)
    forged["claim_boundary"]["policy_causal_effect_claim"] = True
    forged["policy_causal_effect_claim"] = True
    forged["protocol_sha256"] = compute_state_prior_transition_protocol_sha256(forged)

    validation = validate_dam_gk_state_prior_transition_protocol(forged)

    assert not validation["valid"]
    assert "protocol_field_set_mismatch" in validation["errors"]
    assert "protocol_claim_boundary_invalid" in validation["errors"]
    assert "protocol_sha256_mismatch" not in validation["errors"]


def test_external_registration_and_holdout_opening_form_valid_hash_chain():
    full, zero, shuffled = _bindings()
    protocol = _protocol(full, zero, shuffled)

    registration, opening = _receipt_chain(protocol)

    assert registration["schema"] == DAM_GK_STATE_PRIOR_PROTOCOL_REGISTRATION_SCHEMA
    assert opening["schema"] == DAM_GK_STATE_PRIOR_HOLDOUT_OPENING_SCHEMA
    assert validate_state_prior_transition_protocol_registration(
        registration,
        protocol=protocol,
    ) == {"valid": True, "errors": []}
    assert validate_state_prior_transition_holdout_opening(
        opening,
        protocol=protocol,
        registration_receipt=registration,
    ) == {"valid": True, "errors": []}
    assert registration["registered_at"] < opening["opened_at"]
    assert opening["protocol_sha256"] == protocol["protocol_sha256"]
    assert opening["registration_receipt_sha256"] == registration["registration_receipt_sha256"]


def test_protocol_registration_after_holdout_boundary_is_rejected():
    full, zero, shuffled = _bindings()
    protocol = _protocol(full, zero, shuffled)

    with pytest.raises(ValueError, match="registration_after_holdout_boundary"):
        _receipt_chain(protocol, registered_at="2026-08-04T15:50:00Z")


def test_registration_receipt_hash_detects_registry_record_mutation():
    full, zero, shuffled = _bindings()
    protocol = _protocol(full, zero, shuffled)
    registration, _ = _receipt_chain(protocol)
    registration["registry_record_sha256"] = "9" * 64

    validation = validate_state_prior_transition_protocol_registration(
        registration,
        protocol=protocol,
    )

    assert not validation["valid"]
    assert "registration_receipt_sha256_mismatch" in validation["errors"]


@pytest.mark.parametrize(
    ("opened_at", "error"),
    [
        ("2026-08-04T15:44:00Z", "holdout_opened_before_registration"),
        ("2026-08-04T15:49:00Z", "holdout_opened_before_protocol_boundary"),
    ],
)
def test_holdout_opening_chronology_is_fail_closed(opened_at, error):
    full, zero, shuffled = _bindings()
    protocol = _protocol(full, zero, shuffled)

    with pytest.raises(ValueError, match=error):
        _receipt_chain(protocol, opened_at=opened_at)


def test_prediction_artifact_with_different_receipt_chain_is_rejected():
    full, zero, shuffled = _bindings()
    rows = _holdout_records()
    protocol = _protocol(full, zero, shuffled)
    registration, opening = _receipt_chain(protocol)
    artifacts, evidence_refs = _prediction_artifacts(
        rows,
        full,
        zero,
        shuffled,
        protocol,
        registration,
        opening,
    )
    artifacts["full_state_prior"]["holdout_opening_receipt_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="full_state_prior_opening_sha256_mismatch"):
        build_dam_gk_state_prior_transition_evaluation(
            evaluation_id="receipt-mismatched-prediction-artifact",
            created_at="2026-08-04T16:30:00Z",
            protocol=protocol,
            protocol_registration_receipt=registration,
            holdout_opening_receipt=opening,
            full_binding=full,
            zero_binding=zero,
            shuffled_binding=shuffled,
            holdout_records=rows,
            prediction_artifacts=artifacts,
            evidence_refs=evidence_refs,
            leakage_audit=_leakage_audit(),
        )


@pytest.mark.parametrize("receipt_kind", ["registration", "opening"])
def test_transition_receipt_claim_escalation_is_rejected_after_rehash(receipt_kind):
    full, zero, shuffled = _bindings()
    protocol = _protocol(full, zero, shuffled)
    registration, opening = _receipt_chain(protocol)
    if receipt_kind == "registration":
        registration["claim_boundary"]["scientific_result_claim"] = True
        registration["registration_receipt_sha256"] = (
            compute_state_prior_transition_protocol_registration_sha256(registration)
        )
        validation = validate_state_prior_transition_protocol_registration(
            registration,
            protocol=protocol,
        )
        expected_error = "registration_receipt_claim_boundary_invalid"
    else:
        opening["claim_boundary"]["scientific_result_claim"] = True
        opening["holdout_opening_receipt_sha256"] = (
            compute_state_prior_transition_holdout_opening_sha256(opening)
        )
        validation = validate_state_prior_transition_holdout_opening(
            opening,
            protocol=protocol,
            registration_receipt=registration,
        )
        expected_error = "holdout_opening_receipt_claim_boundary_invalid"

    assert not validation["valid"]
    assert expected_error in validation["errors"]


def _bindings():
    batch, config = _dam_gk_batch_and_config()
    full = bind_admitted_state_prior_node_context(
        batch=batch,
        config=config,
        admission=_admitted_fixture(),
        node_keys=["node-a", "node-b", "node-c"],
        base_context_feature_names=["x", "y"],
        state_prior_feature_names=["fixture_state"],
        state_prior_values=torch.tensor([[0.15], [0.35], [0.75]]),
        context_artifact_sha256="a" * 64,
    )
    return (
        full,
        with_state_prior_context_control(full, mode="zero", seed=17),
        with_state_prior_context_control(full, mode="shuffle_nodes", seed=17),
    )


def _holdout_records() -> list[dict]:
    rows = []
    for split_index, split in enumerate(REQUIRED_TRANSITION_HOLDOUT_SPLITS):
        for index in range(10):
            target = 2.0 * split_index + 0.2 * index
            full_prediction = target + (0.05 if index % 2 == 0 else -0.05)
            rows.append(
                {
                    "sample_id": f"{split}-{index}",
                    "split": split,
                    "node_key": ("node-a", "node-b", "node-c")[index % 3],
                    "action_id": f"action-{index % 2}",
                    "target": target,
                    "full_prediction": full_prediction,
                    "zero_prediction": target + 0.4,
                    "shuffled_prediction": target - 0.5,
                    "baseline_prediction": target + 0.7,
                    "full_interval_lower": full_prediction - 0.2,
                    "full_interval_upper": full_prediction + 0.2,
                    "target_evidence_ref": "evidence://observed-transition-targets",
                    "action_evidence_ref": "evidence://observed-actions",
                    "action_sha256": "3" * 64,
                    "forcing_sha256": "4" * 64,
                    "topology_sha256": "5" * 64,
                }
            )
    return rows


def _prediction_artifacts(
    rows,
    full,
    zero,
    shuffled,
    protocol,
    registration,
    opening,
):
    paired_input = compute_state_prior_paired_input_sha256(rows)
    binding_by_method = {
        "full_state_prior": full,
        "zero_state_prior": zero,
        "shuffled_state_prior": shuffled,
    }
    artifacts = {}
    evidence_refs = [
        "evidence://observed-transition-targets",
        "evidence://observed-actions",
    ]
    for method in (
        "full_state_prior",
        "zero_state_prior",
        "shuffled_state_prior",
        "traditional_baseline",
    ):
        uri = f"artifact://{method}-predictions"
        evidence_refs.append(uri)
        artifacts[method] = {
            "uri": uri,
            "created_at": "2026-08-04T15:57:00Z",
            "protocol_sha256": protocol["protocol_sha256"],
            "protocol_registration_receipt_sha256": registration["registration_receipt_sha256"],
            "holdout_opening_receipt_sha256": opening["holdout_opening_receipt_sha256"],
            "holdout_manifest_sha256": opening["holdout_manifest_sha256"],
            "paired_input_sha256": paired_input,
            "predictions_sha256": compute_state_prior_prediction_sha256(rows, method),
            "model_sha256": "2" * 64 if method == "traditional_baseline" else "1" * 64,
            "context_values_sha256": (
                None
                if method == "traditional_baseline"
                else binding_by_method[method].context_values_sha256
            ),
        }
    return artifacts, evidence_refs


def _leakage_audit() -> dict:
    return {
        "passed": True,
        "train_holdout_sample_overlap_count": 0,
        "state_prior_fit_used_holdout_targets": False,
        "normalization_fit_used_holdout": False,
        "action_outcomes_used_as_context": False,
        "by_split": {
            "unseen_region": {
                "passed": True,
                "train_holdout_region_overlap_count": 0,
            },
            "low_sample_region": {
                "passed": True,
                "maximum_training_samples_per_holdout_region": 3,
                "predeclared_maximum_training_samples": 5,
            },
            "future_action_conditioned": {
                "passed": True,
                "future_ordering_verified": True,
                "action_outcome_pair_overlap_count": 0,
            },
        },
    }


def _evaluation(
    *,
    full,
    zero,
    shuffled,
    rows,
    source_evidence_kind="observed_holdout",
    leakage_audit=None,
):
    protocol = _protocol(
        full,
        zero,
        shuffled,
        source_evidence_kind=source_evidence_kind,
    )
    registration, opening = _receipt_chain(protocol)
    artifacts, evidence_refs = _prediction_artifacts(
        rows,
        full,
        zero,
        shuffled,
        protocol,
        registration,
        opening,
    )
    return build_dam_gk_state_prior_transition_evaluation(
        evaluation_id="paired-state-prior-transition-fixture",
        created_at="2026-08-04T16:00:00Z",
        protocol=protocol,
        protocol_registration_receipt=registration,
        holdout_opening_receipt=opening,
        full_binding=full,
        zero_binding=zero,
        shuffled_binding=shuffled,
        holdout_records=rows,
        prediction_artifacts=artifacts,
        evidence_refs=evidence_refs,
        leakage_audit=leakage_audit or _leakage_audit(),
    )


def _protocol(
    full,
    zero,
    shuffled,
    *,
    source_evidence_kind="observed_holdout",
    frozen_at="2026-08-04T15:40:00Z",
    holdout_access_not_before="2026-08-04T15:50:00Z",
):
    return build_dam_gk_state_prior_transition_protocol(
        protocol_id="paired-state-prior-transition-protocol-fixture",
        created_at="2026-08-04T15:30:00Z",
        frozen_at=frozen_at,
        holdout_access_not_before=holdout_access_not_before,
        full_binding=full,
        zero_binding=zero,
        shuffled_binding=shuffled,
        candidate_control_model_sha256="1" * 64,
        traditional_baseline_model_sha256="2" * 64,
        source_evidence_kind=source_evidence_kind,
        evidence_refs=[
            *full.evidence_refs,
            "evidence://state-prior-transition-protocol-freeze",
        ],
        minimum_samples_per_split=10,
        minimum_relative_improvement=0.01,
        coverage_tolerance=0.05,
        low_sample_maximum_training_samples=5,
    )


def _receipt_chain(
    protocol,
    *,
    registered_at="2026-08-04T15:45:00Z",
    opened_at="2026-08-04T15:55:00Z",
):
    registration = build_state_prior_transition_protocol_registration(
        protocol=protocol,
        registration_id="state-prior-transition-registration-fixture",
        registered_at=registered_at,
        registry_kind="write_once_artifact_store",
        registry_uri="registry://state-prior-transition/protocol-fixture",
        registry_record_sha256="6" * 64,
        registrar_id="fixture-registry-writer",
        registry_evidence_ref="evidence://state-prior-transition-registry-record",
        evidence_refs=["evidence://state-prior-transition-registry-record"],
    )
    opening = build_state_prior_transition_holdout_opening(
        protocol=protocol,
        registration_receipt=registration,
        opening_id="state-prior-transition-holdout-opening-fixture",
        opened_at=opened_at,
        holdout_dataset_id="observed-transition-holdout-fixture",
        holdout_manifest_sha256="7" * 64,
        accessor_id="fixture-holdout-accessor",
        access_log_ref="evidence://state-prior-transition-holdout-access-log",
        access_log_sha256="8" * 64,
        evidence_refs=["evidence://state-prior-transition-holdout-access-log"],
    )
    return registration, opening
