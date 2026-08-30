import pytest

from data_agent.uwm.intervention_evidence_certificate import (
    GATE_IDS,
    ClaimTier,
    ControlledTruthStatus,
    GateStatus,
    evaluate_certificate,
    load_spec,
)


def _all_pass() -> dict[str, str]:
    return {gate_id: "pass" for gate_id in GATE_IDS}


def test_yaml_spec_matches_executable_gate_order_and_claim_boundary():
    spec = load_spec()

    assert [gate["id"] for gate in spec["gates"]] == list(GATE_IDS)
    assert spec["aggregation"]["type"] == "non_compensatory_vector"
    assert "urban-domain instance built on GWM" in spec["architecture_boundary"]
    assert spec["claim_tiers"][-1]["real_observational_data_available"] is False


def test_all_gates_pass_earns_external_transfer_but_not_law_recovery_without_truth():
    result = evaluate_certificate(_all_pass(), token_responsive=True)

    assert result.certificate_status is GateStatus.PASS
    assert result.first_nonpass_gate is None
    assert result.highest_claim_tier is ClaimTier.OUTCOME_SEALED_SEMANTIC_TRANSFER
    assert result.controlled_truth_status is ControlledTruthStatus.UNAVAILABLE


def test_controlled_law_recovery_requires_both_truth_checks():
    result = evaluate_certificate(
        _all_pass(),
        token_responsive=True,
        controlled_truth={
            "reference_available": True,
            "response_surface_pass": True,
            "jacobian_pass": True,
        },
    )

    assert result.highest_claim_tier is ClaimTier.CONTROLLED_INTERVENTION_LAW_RECOVERY
    assert result.controlled_truth_status is ControlledTruthStatus.PASS


def test_failed_support_gate_cannot_be_averaged_away_by_later_passes():
    gates = _all_pass()
    gates["G3"] = "fail"

    result = evaluate_certificate(gates, token_responsive=True)

    assert result.certificate_status is GateStatus.FAIL
    assert result.first_nonpass_gate == "G3"
    assert result.highest_claim_tier is ClaimTier.TOKEN_RESPONSIVENESS


def test_g6_failure_preserves_only_within_development_incremental_claim():
    gates = _all_pass()
    gates["G6"] = "fail"

    result = evaluate_certificate(gates, token_responsive=True)

    assert result.certificate_status is GateStatus.FAIL
    assert result.highest_claim_tier is ClaimTier.SEMANTIC_INCREMENTAL_PREDICTION


def test_missing_gate_is_indeterminate_and_blocks_higher_claims():
    gates = _all_pass()
    del gates["G2"]

    result = evaluate_certificate(gates, token_responsive=True)

    assert result.gate_statuses["G2"] is GateStatus.INDETERMINATE
    assert result.certificate_status is GateStatus.INDETERMINATE
    assert result.highest_claim_tier is ClaimTier.TOKEN_RESPONSIVENESS


def test_no_verified_token_response_yields_no_intervention_claim():
    result = evaluate_certificate(_all_pass(), token_responsive=None)

    assert result.highest_claim_tier is ClaimTier.NO_INTERVENTION_CLAIM


def test_unknown_gate_or_status_is_rejected():
    with pytest.raises(ValueError, match="unknown IEC gates"):
        evaluate_certificate({"G7": "pass"}, token_responsive=True)

    with pytest.raises(ValueError, match="invalid status for G0"):
        evaluate_certificate({"G0": "maybe"}, token_responsive=True)
