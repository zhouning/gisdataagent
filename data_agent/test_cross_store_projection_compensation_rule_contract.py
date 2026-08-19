from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from pydantic import ValidationError

from data_agent.cross_store_projection_compensation_customer_action_mapping import (
    CustomerCompensationRuleProviderActionMappingError,
    build_customer_compensation_rule_provider_action_map,
)
from data_agent.cross_store_projection_compensation_proposal import (
    CompensationProposalAction,
    FederatedProjectionCompensationProposal,
    build_federated_projection_compensation_proposal,
    compensation_candidate_fingerprint,
    compensation_proposal_fingerprint,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleApprovalEvidence,
    CustomerCompensationRuleAssessmentReadiness,
    CustomerCompensationRuleAssessmentStatus,
    CustomerCompensationRuleError,
    CustomerCompensationRuleStatus,
    CustomerCompensationRuleTargetScope,
    FederatedProjectionCompensationRuleAssessment,
    assess_federated_projection_compensation_rules,
    build_customer_compensation_rule,
    build_customer_compensation_rule_contract,
    customer_compensation_rule_approval_payload,
)
from data_agent.cross_store_projection_compensation_trust import (
    CustomerCompensationApprovalTrustAnchorStatus,
    build_customer_compensation_approval_trust_anchor,
    build_customer_compensation_approval_trust_registry,
)
from data_agent.test_cross_store_projection_compensation_proposal import (
    _blocked_unknown_outcome,
)

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
SIGNING_KEY = ed25519.Ed25519PrivateKey.generate()


def _proposal():
    plans, _, snapshot = _blocked_unknown_outcome()
    return build_federated_projection_compensation_proposal(plans, snapshot)


def _build_approval_evidence(
    rule,
    *,
    signature_algorithm: str = "ed25519",
    approval_artifact_sha256: str = "a" * 64,
):
    if signature_algorithm == "ed25519":
        private_key = SIGNING_KEY
    elif signature_algorithm == "ecdsa-p256-sha256":
        private_key = ec.generate_private_key(ec.SECP256R1())
    else:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    public_key_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8").strip()
    public_key_sha256 = hashlib.sha256(public_key_pem.encode("utf-8")).hexdigest()
    approval_id = f"approval:{rule.rule_id}"
    customer_authority_ref = "customer-authority:chongqing-natural-resources"
    signature_key_id = f"customer-key-{signature_algorithm}"
    signed_at = NOW
    payload = customer_compensation_rule_approval_payload(
        approval_id=approval_id,
        customer_authority_ref=customer_authority_ref,
        rule_id=rule.rule_id,
        rule_semantic_version=rule.semantic_version,
        rule_sha256=rule.rule_sha256,
        approval_artifact_sha256=approval_artifact_sha256,
        signature_algorithm=signature_algorithm,
        signature_key_id=signature_key_id,
        public_key_sha256=public_key_sha256,
        signed_at=signed_at,
    )
    if signature_algorithm == "ed25519":
        signature = private_key.sign(payload)
    elif signature_algorithm == "ecdsa-p256-sha256":
        signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    else:
        signature = private_key.sign(
            payload,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
    return CustomerCompensationRuleApprovalEvidence(
        approval_id=approval_id,
        customer_authority_ref=customer_authority_ref,
        rule_id=rule.rule_id,
        rule_semantic_version=rule.semantic_version,
        rule_sha256=rule.rule_sha256,
        approval_artifact_sha256=approval_artifact_sha256,
        signature_algorithm=signature_algorithm,
        signature_key_id=signature_key_id,
        public_key_pem=public_key_pem,
        public_key_sha256=public_key_sha256,
        detached_signature_base64=base64.b64encode(signature).decode("ascii"),
        signed_payload_sha256=hashlib.sha256(payload).hexdigest(),
        signed_at=signed_at,
        signature_verification_status="verified",
        verified_by="workload:customer-signature-verifier",
        verified_at=NOW + timedelta(minutes=1),
    )


def _rule_contract(
    proposal,
    rule_id: str,
    status: CustomerCompensationRuleStatus,
    *,
    target_override: tuple[CustomerCompensationRuleTargetScope, ...] | None = None,
):
    candidates = tuple(
        candidate
        for candidate in proposal.candidates
        if rule_id in candidate.missing_customer_rule_ids
    )
    action = candidates[0].action
    plan_sha256s = {
        plan_sha256
        for candidate in candidates
        for plan_sha256 in candidate.plan_sha256s
    }
    targets = target_override or tuple(
        sorted(
            (
                CustomerCompensationRuleTargetScope(
                    target_engine=binding.target_engine,
                    target_ref=binding.target_ref,
                )
                for binding in proposal.source_bindings
                if binding.plan_sha256 in plan_sha256s
            ),
            key=lambda target: (target.target_engine.value, target.target_ref),
        )
    )
    required_evidence = tuple(
        sorted(
            {
                evidence
                for candidate in candidates
                for evidence in candidate.required_evidence
            }
        )
    )
    rule = build_customer_compensation_rule(
        rule_id=rule_id,
        semantic_version="1.0.0",
        action=action,
        applicable_targets=targets,
        required_evidence=required_evidence,
    )
    approval = None
    if status is CustomerCompensationRuleStatus.CUSTOMER_APPROVED:
        try:
            mapping = build_customer_compensation_rule_provider_action_map(
                proposal,
                candidates[0].candidate_sha256,
                rule,
            )
        except CustomerCompensationRuleProviderActionMappingError:
            if action is not CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX:
                raise
            approval = _build_approval_evidence(
                rule,
                approval_artifact_sha256="0" * 64,
            )
        else:
            approval = _build_approval_evidence(
                rule,
                approval_artifact_sha256=mapping.action_map_sha256,
            )
    return build_customer_compensation_rule_contract(
        tenant_id=proposal.tenant_id,
        rule=rule,
        status=status,
        approval_evidence=approval,
    )


def _trust_registry(contracts):
    anchors = {}
    for contract in contracts:
        evidence = contract.approval_evidence
        assert evidence is not None
        anchor = build_customer_compensation_approval_trust_anchor(
            tenant_id=contract.tenant_id,
            customer_authority_ref=evidence.customer_authority_ref,
            signature_key_id=evidence.signature_key_id,
            signature_algorithm=evidence.signature_algorithm,
            public_key_sha256=evidence.public_key_sha256,
            valid_from=NOW - timedelta(days=3650),
            valid_until=NOW + timedelta(days=3650),
            status=CustomerCompensationApprovalTrustAnchorStatus.ACTIVE,
        )
        anchors[anchor.identity] = anchor
    return build_customer_compensation_approval_trust_registry(tuple(anchors.values()))


def test_missing_rules_are_reported_without_inventing_customer_semantics() -> None:
    proposal = _proposal()

    assessment = assess_federated_projection_compensation_rules(proposal, ())

    assert assessment.missing_rule_ids == proposal.missing_customer_rule_ids
    assert assessment.readiness is (
        CustomerCompensationRuleAssessmentReadiness.RULE_GAPS_REMAINING
    )
    assert assessment.all_required_rule_contracts_approved is False
    assert assessment.execution_allowed is False
    assert assessment.automatic_mutating_selection_allowed is False
    assert all(
        item.status is CustomerCompensationRuleAssessmentStatus.MISSING
        for item in assessment.assessments
    )


def test_draft_and_awaiting_rules_remain_rule_gaps() -> None:
    proposal = _proposal()
    rule_ids = proposal.missing_customer_rule_ids[:2]
    contracts = (
        _rule_contract(
            proposal,
            rule_ids[0],
            CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
        ),
        _rule_contract(
            proposal,
            rule_ids[1],
            CustomerCompensationRuleStatus.AWAITING_CUSTOMER_APPROVAL,
        ),
    )

    assessment = assess_federated_projection_compensation_rules(proposal, contracts)

    by_id = {item.rule_id: item for item in assessment.assessments}
    assert by_id[rule_ids[0]].status is (
        CustomerCompensationRuleAssessmentStatus.DRAFT_UNREVIEWED
    )
    assert by_id[rule_ids[1]].status is (
        CustomerCompensationRuleAssessmentStatus.AWAITING_CUSTOMER_APPROVAL
    )
    assert not any(item.customer_approval_evidence_present for item in by_id.values())
    assert assessment.execution_allowed is False


def test_contextual_target_drift_is_visible_instead_of_treated_as_approval() -> None:
    proposal = _proposal()
    rule_id = "customer.compensation.delete.v1"
    unrelated = proposal.source_bindings[0]
    drifted = _rule_contract(
        proposal,
        rule_id,
        CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
        target_override=(
            CustomerCompensationRuleTargetScope(
                target_engine=unrelated.target_engine,
                target_ref=unrelated.target_ref,
            ),
        ),
    )

    assessment = assess_federated_projection_compensation_rules(
        proposal,
        (drifted,),
    )
    item = next(item for item in assessment.assessments if item.rule_id == rule_id)

    assert item.status is CustomerCompensationRuleAssessmentStatus.INVALID_OR_DRIFTED
    assert "required_target_scope_not_covered" in item.reason_codes
    assert assessment.invalid_or_drifted_rule_ids == (rule_id,)
    assert assessment.execution_allowed is False


def test_signed_approved_rules_are_still_not_executable_or_auto_selected() -> None:
    proposal = _proposal()
    contracts = tuple(
        _rule_contract(
            proposal,
            rule_id,
            CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
        )
        for rule_id in proposal.missing_customer_rule_ids
    )

    assessment = assess_federated_projection_compensation_rules(
        proposal,
        contracts,
        _trust_registry(contracts),
    )

    assert assessment.all_required_rule_contracts_approved is True
    assert assessment.readiness is (
        CustomerCompensationRuleAssessmentReadiness.RULES_APPROVED_EXECUTION_DISABLED
    )
    assert assessment.approved_but_not_executable_rule_ids == (
        proposal.missing_customer_rule_ids
    )
    assert assessment.execution_allowed is False
    assert assessment.automatic_mutating_selection_allowed is False
    assert all(
        item.status
        is CustomerCompensationRuleAssessmentStatus.APPROVED_BUT_NOT_EXECUTABLE
        and item.customer_approval_evidence_present
        and not item.execution_allowed
        for item in assessment.assessments
    )


def test_signed_approval_without_deployment_trust_anchor_is_invalid() -> None:
    proposal = _proposal()
    rule_id = proposal.missing_customer_rule_ids[0]
    contract = _rule_contract(
        proposal,
        rule_id,
        CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
    )

    assessment = assess_federated_projection_compensation_rules(proposal, (contract,))
    item = next(item for item in assessment.assessments if item.rule_id == rule_id)

    assert item.status is CustomerCompensationRuleAssessmentStatus.INVALID_OR_DRIFTED
    assert item.customer_approval_evidence_present is True
    assert item.customer_approval_trusted is False
    assert item.reason_codes == (
        "customer_approval_evidence_present",
        "customer_approval_trust_registry_missing",
    )


def test_revoked_or_mismatched_deployment_key_is_fail_closed() -> None:
    proposal = _proposal()
    rule_id = proposal.missing_customer_rule_ids[0]
    contract = _rule_contract(
        proposal,
        rule_id,
        CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
    )
    evidence = contract.approval_evidence
    assert evidence is not None

    revoked = build_customer_compensation_approval_trust_registry(
        (
            build_customer_compensation_approval_trust_anchor(
                tenant_id=contract.tenant_id,
                customer_authority_ref=evidence.customer_authority_ref,
                signature_key_id=evidence.signature_key_id,
                signature_algorithm=evidence.signature_algorithm,
                public_key_sha256=evidence.public_key_sha256,
                valid_from=NOW - timedelta(days=3650),
                valid_until=NOW + timedelta(days=3650),
                status=CustomerCompensationApprovalTrustAnchorStatus.REVOKED,
            ),
        )
    )
    revoked_item = next(
        item
        for item in assess_federated_projection_compensation_rules(
            proposal, (contract,), revoked
        ).assessments
        if item.rule_id == rule_id
    )
    assert revoked_item.reason_codes == (
        "customer_approval_evidence_present",
        "customer_approval_key_revoked",
    )

    mismatched = build_customer_compensation_approval_trust_registry(
        (
            build_customer_compensation_approval_trust_anchor(
                tenant_id=contract.tenant_id,
                customer_authority_ref=evidence.customer_authority_ref,
                signature_key_id=evidence.signature_key_id,
                signature_algorithm=evidence.signature_algorithm,
                public_key_sha256="f" * 64,
                valid_from=NOW - timedelta(days=3650),
                valid_until=NOW + timedelta(days=3650),
                status=CustomerCompensationApprovalTrustAnchorStatus.ACTIVE,
            ),
        )
    )
    mismatched_item = next(
        item
        for item in assess_federated_projection_compensation_rules(
            proposal, (contract,), mismatched
        ).assessments
        if item.rule_id == rule_id
    )
    assert mismatched_item.reason_codes == (
        "customer_approval_evidence_present",
        "customer_approval_key_not_trusted",
    )


def test_trust_anchor_must_cover_signature_and_evaluation_window() -> None:
    proposal = _proposal()
    rule_id = proposal.missing_customer_rule_ids[0]
    contract = _rule_contract(
        proposal,
        rule_id,
        CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
    )
    evidence = contract.approval_evidence
    assert evidence is not None
    expired = build_customer_compensation_approval_trust_registry(
        (
            build_customer_compensation_approval_trust_anchor(
                tenant_id=contract.tenant_id,
                customer_authority_ref=evidence.customer_authority_ref,
                signature_key_id=evidence.signature_key_id,
                signature_algorithm=evidence.signature_algorithm,
                public_key_sha256=evidence.public_key_sha256,
                valid_from=NOW - timedelta(days=3),
                valid_until=NOW - timedelta(days=2),
                status=CustomerCompensationApprovalTrustAnchorStatus.ACTIVE,
            ),
        )
    )
    item = next(
        item
        for item in assess_federated_projection_compensation_rules(
            proposal, (contract,), expired
        ).assessments
        if item.rule_id == rule_id
    )
    assert item.reason_codes == (
        "customer_approval_evidence_present",
        "customer_approval_key_outside_validity",
    )


def test_approval_claim_requires_explicit_verified_signature_evidence() -> None:
    proposal = _proposal()
    rule_id = proposal.missing_customer_rule_ids[0]
    draft = _rule_contract(
        proposal,
        rule_id,
        CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
    )

    with pytest.raises(ValidationError, match="signed approval evidence"):
        build_customer_compensation_rule_contract(
            tenant_id=proposal.tenant_id,
            rule=draft.rule,
            status=CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
        )

    invalid_signature = base64.b64encode(b"123456789012").decode("ascii")
    with pytest.raises(ValidationError, match="too short"):
        CustomerCompensationRuleApprovalEvidence(
            approval_id="approval:invalid",
            customer_authority_ref="customer-authority:chongqing",
            rule_id=draft.rule.rule_id,
            rule_semantic_version=draft.rule.semantic_version,
            rule_sha256=draft.rule.rule_sha256,
            approval_artifact_sha256="a" * 64,
            signature_algorithm="ed25519",
            signature_key_id="customer-key",
            public_key_pem=SIGNING_KEY.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("utf-8"),
            public_key_sha256="b" * 64,
            detached_signature_base64=invalid_signature,
            signed_payload_sha256="b" * 64,
            signed_at=NOW,
            signature_verification_status="verified",
            verified_by="workload:signature-verifier",
            verified_at=NOW,
        )


def test_tampered_customer_signature_is_rejected_by_cryptographic_verifier() -> None:
    proposal = _proposal()
    contract = _rule_contract(
        proposal,
        proposal.missing_customer_rule_ids[0],
        CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
    )
    document = contract.model_dump(mode="json")
    document["approval_evidence"]["detached_signature_base64"] = base64.b64encode(
        b"tampered-signature"
    ).decode("ascii")

    with pytest.raises(ValidationError, match="signature verification failed"):
        type(contract).model_validate(document)


@pytest.mark.parametrize(
    "signature_algorithm",
    ("ecdsa-p256-sha256", "rsa-pss-sha256"),
)
def test_supported_customer_signature_algorithms_are_verified(
    signature_algorithm: str,
) -> None:
    proposal = _proposal()
    draft = _rule_contract(
        proposal,
        proposal.missing_customer_rule_ids[0],
        CustomerCompensationRuleStatus.AWAITING_CUSTOMER_APPROVAL,
    )
    evidence = _build_approval_evidence(
        draft.rule,
        signature_algorithm=signature_algorithm,
    )
    approved = build_customer_compensation_rule_contract(
        tenant_id=proposal.tenant_id,
        rule=draft.rule,
        status=CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
        approval_evidence=evidence,
    )

    assert approved.approval_evidence is not None
    assert approved.approval_evidence.signature_algorithm == signature_algorithm


def test_assessment_is_deterministic_and_rejects_tenant_or_hash_tampering() -> None:
    proposal = _proposal()
    contract = _rule_contract(
        proposal,
        proposal.missing_customer_rule_ids[0],
        CustomerCompensationRuleStatus.AWAITING_CUSTOMER_APPROVAL,
    )

    first = assess_federated_projection_compensation_rules(proposal, (contract,))
    second = assess_federated_projection_compensation_rules(proposal, (contract,))
    assert first == second
    assert FederatedProjectionCompensationRuleAssessment.model_validate(
        first.model_dump(mode="json")
    ) == first

    tampered = first.model_dump(mode="json")
    tampered["assessment_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="fingerprint"):
        FederatedProjectionCompensationRuleAssessment.model_validate(tampered)

    cross_tenant = build_customer_compensation_rule_contract(
        tenant_id="another-tenant",
        rule=contract.rule,
        status=contract.status,
    )
    with pytest.raises(CustomerCompensationRuleError, match="cross tenants"):
        assess_federated_projection_compensation_rules(proposal, (cross_tenant,))


def test_reconciliation_rule_contract_is_supported_but_not_required_by_proposal() -> None:
    proposal = _proposal()
    binding = proposal.source_bindings[proposal.blocked_position]
    rule = build_customer_compensation_rule(
        rule_id="customer.compensation.reconciliation.v1",
        semantic_version="1.0.0",
        action=CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME,
        applicable_targets=(
            CustomerCompensationRuleTargetScope(
                target_engine=binding.target_engine,
                target_ref=binding.target_ref,
            ),
        ),
        required_evidence=("fresh_target_observation",),
    )
    assert rule.mutates_provider is False
    contract = build_customer_compensation_rule_contract(
        tenant_id=proposal.tenant_id,
        rule=rule,
        status=CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
    )

    with pytest.raises(CustomerCompensationRuleError, match="not required"):
        assess_federated_projection_compensation_rules(proposal, (contract,))


def test_assessment_rejects_an_unregistered_proposal_rule_id() -> None:
    proposal_document = _proposal().model_dump(mode="json")
    unknown_rule_id = "customer.compensation.reconciliation.v9"
    for candidate in proposal_document["candidates"]:
        if candidate["missing_customer_rule_ids"]:
            candidate["missing_customer_rule_ids"] = [unknown_rule_id]
            candidate["candidate_sha256"] = compensation_candidate_fingerprint(
                **{
                    key: value
                    for key, value in candidate.items()
                    if key != "candidate_sha256"
                }
            )
            break
    proposal_document["missing_customer_rule_ids"] = sorted(
        {
            rule_id
            for candidate in proposal_document["candidates"]
            for rule_id in candidate["missing_customer_rule_ids"]
        }
    )
    proposal_document["proposal_sha256"] = compensation_proposal_fingerprint(
        **{
            key: value
            for key, value in proposal_document.items()
            if key != "proposal_sha256"
        }
    )
    proposal = FederatedProjectionCompensationProposal.model_validate(
        proposal_document
    )

    with pytest.raises(CustomerCompensationRuleError, match="unsupported"):
        assess_federated_projection_compensation_rules(proposal, ())
