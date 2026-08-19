"""Versioned customer-rule contracts for federated compensation proposals.

The contract layer records declared customer semantics without inventing them.
Its public assessment is read-only and never selects or executes a mutation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .cross_store_projection_compensation_proposal import (
    CompensationOntologyBinding,
    CompensationProposalAction,
    FederatedProjectionCompensationProposal,
)
from .cross_store_projection_compensation_trust import (
    CustomerCompensationApprovalTrustRegistry,
    build_customer_compensation_approval_trust_registry,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_bytes,
    canonical_json_fingerprint,
)

SemanticVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$",
    ),
]
CustomerRuleId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=96,
        pattern=(
            r"^customer\.compensation\."
            r"(corrective-forward|rollback|delete|restore|reconciliation)\.v[1-9]\d*$"
        ),
    ),
]
DetachedSignature = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=16, max_length=1024),
]
PublicKeyPem = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=32, max_length=8192),
]


class CustomerCompensationRuleError(ValueError):
    """A submitted rule set cannot be assessed against the proposal."""


class CustomerCompensationRuleStatus(StrEnum):
    DRAFT_UNREVIEWED = "draft_unreviewed"
    AWAITING_CUSTOMER_APPROVAL = "awaiting_customer_approval"
    CUSTOMER_APPROVED = "customer_approved"


class CustomerCompensationRuleAssessmentStatus(StrEnum):
    MISSING = "missing"
    DRAFT_UNREVIEWED = "draft_unreviewed"
    AWAITING_CUSTOMER_APPROVAL = "awaiting_customer_approval"
    APPROVED_BUT_NOT_EXECUTABLE = "approved_but_not_executable"
    INVALID_OR_DRIFTED = "invalid_or_drifted"


class CustomerCompensationRuleAssessmentReadiness(StrEnum):
    RULE_GAPS_REMAINING = "rule_gaps_remaining"
    RULES_APPROVED_EXECUTION_DISABLED = "rules_approved_execution_disabled"


RULE_ID_BY_ACTION: dict[CompensationProposalAction, str] = {
    CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME: (
        "customer.compensation.reconciliation.v1"
    ),
    CompensationProposalAction.CORRECTIVE_FORWARD: (
        "customer.compensation.corrective-forward.v1"
    ),
    CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX: (
        "customer.compensation.rollback.v1"
    ),
    CompensationProposalAction.DELETE_TARGET: "customer.compensation.delete.v1",
    CompensationProposalAction.RESTORE_TARGET: "customer.compensation.restore.v1",
}
ACTION_BY_RULE_ID = {rule_id: action for action, rule_id in RULE_ID_BY_ACTION.items()}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def customer_compensation_rule_fingerprint(**values: Any) -> str:
    return _fingerprint(
        CustomerCompensationRule.schema_id,
        values,
        "rule_sha256",
    )


def customer_compensation_rule_contract_fingerprint(**values: Any) -> str:
    return _fingerprint(
        CustomerCompensationRuleContract.schema_id,
        values,
        "contract_sha256",
    )


def customer_compensation_rule_assessment_fingerprint(**values: Any) -> str:
    return _fingerprint(
        FederatedProjectionCompensationRuleAssessment.schema_id,
        values,
        "assessment_sha256",
    )


def customer_compensation_rule_approval_payload(
    *,
    approval_id: str,
    customer_authority_ref: str,
    rule_id: str,
    rule_semantic_version: str,
    rule_sha256: str,
    approval_artifact_sha256: str,
    signature_algorithm: str,
    signature_key_id: str,
    public_key_sha256: str,
    signed_at: datetime,
) -> bytes:
    """Return the canonical bytes that customer approval signatures cover."""

    if signed_at.tzinfo is None or signed_at.utcoffset() is None:
        raise ValueError("customer approval signed_at must be timezone-aware")
    values = {
        "schema": "gda.customer-compensation-rule-approval-payload.v1",
        "approval_id": approval_id,
        "customer_authority_ref": customer_authority_ref,
        "rule_id": rule_id,
        "rule_semantic_version": rule_semantic_version,
        "rule_sha256": rule_sha256,
        "approval_artifact_sha256": approval_artifact_sha256,
        "signature_algorithm": signature_algorithm,
        "signature_key_id": signature_key_id,
        "public_key_sha256": public_key_sha256,
        "signed_at": signed_at.astimezone(UTC).isoformat(),
    }
    return canonical_json_bytes(values)


class CustomerCompensationRuleTargetScope(_FrozenModel):
    schema_id: ClassVar[str] = "gda.customer-compensation-rule-target-scope.v1"
    target_engine: ProjectionEngine
    target_ref: NonEmptyText


class CustomerCompensationRule(_FrozenModel):
    """One immutable customer-semantic rule body, without lifecycle claims."""

    schema_id: ClassVar[str] = "gda.customer-compensation-rule.v1"
    rule_id: CustomerRuleId
    semantic_version: SemanticVersion
    action: CompensationProposalAction
    dataset_scope: Literal["chongqing_customer_dataset"] = (
        "chongqing_customer_dataset"
    )
    ontology: CompensationOntologyBinding
    applicable_targets: tuple[CustomerCompensationRuleTargetScope, ...] = Field(
        min_length=1,
        max_length=32,
    )
    required_evidence: tuple[NonEmptyText, ...] = Field(
        min_length=1,
        max_length=32,
    )
    mutates_provider: bool
    approval_required: Literal[True] = True
    automatic_mutating_selection_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False
    rule_sha256: Sha256

    @model_validator(mode="after")
    def _bounded_rule(self) -> CustomerCompensationRule:
        expected_rule_id = RULE_ID_BY_ACTION.get(self.action)
        if expected_rule_id is None or self.rule_id != expected_rule_id:
            raise ValueError("customer compensation rule id and action differ")
        rule_major = self.rule_id.rsplit(".v", 1)[1]
        if self.semantic_version.split(".", 1)[0] != rule_major:
            raise ValueError("customer compensation rule major versions differ")
        if self.action is CompensationProposalAction.APPROVED_REAPPLY_SEALED_PLAN:
            raise ValueError("sealed-plan reapply is governed by ApprovalCase, not a rule")
        expected_mutation = (
            self.action is not CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME
        )
        if self.mutates_provider is not expected_mutation:
            raise ValueError("customer compensation rule mutation declaration differs")

        target_keys = tuple(
            (target.target_engine.value, target.target_ref)
            for target in self.applicable_targets
        )
        if tuple(sorted(set(target_keys))) != target_keys:
            raise ValueError("customer compensation rule targets must be unique and sorted")
        if tuple(sorted(set(self.required_evidence))) != self.required_evidence:
            raise ValueError("customer compensation rule evidence must be unique and sorted")

        expected = customer_compensation_rule_fingerprint(
            **self.model_dump(mode="json", exclude={"rule_sha256"})
        )
        if self.rule_sha256 != expected:
            raise ValueError("customer compensation rule fingerprint is invalid")
        return self


class CustomerCompensationRuleApprovalEvidence(_FrozenModel):
    """Cryptographically verified customer signature bound to one rule body."""

    schema_id: ClassVar[str] = "gda.customer-compensation-rule-approval-evidence.v1"
    approval_id: NonEmptyText
    customer_authority_ref: NonEmptyText
    rule_id: CustomerRuleId
    rule_semantic_version: SemanticVersion
    rule_sha256: Sha256
    approval_artifact_sha256: Sha256
    signature_algorithm: Literal[
        "ed25519",
        "ecdsa-p256-sha256",
        "rsa-pss-sha256",
    ]
    signature_key_id: NonEmptyText
    public_key_pem: PublicKeyPem
    public_key_sha256: Sha256
    detached_signature_base64: DetachedSignature
    signed_payload_sha256: Sha256
    signed_at: datetime
    signature_verification_status: Literal["verified"]
    verified_by: NonEmptyText
    verified_at: datetime

    @field_validator("signed_at", "verified_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("customer approval timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("detached_signature_base64")
    @classmethod
    def _valid_base64(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("customer approval signature must be valid base64") from exc
        if len(decoded) < 16:
            raise ValueError("customer approval signature is too short")
        return value

    @model_validator(mode="after")
    def _valid_verification_order(self) -> CustomerCompensationRuleApprovalEvidence:
        if self.verified_at < self.signed_at:
            raise ValueError("customer approval verification predates the signature")
        expected_public_key_sha256 = hashlib.sha256(
            self.public_key_pem.encode("utf-8")
        ).hexdigest()
        if self.public_key_sha256 != expected_public_key_sha256:
            raise ValueError("customer approval public-key fingerprint is invalid")

        payload = customer_compensation_rule_approval_payload(
            approval_id=self.approval_id,
            customer_authority_ref=self.customer_authority_ref,
            rule_id=self.rule_id,
            rule_semantic_version=self.rule_semantic_version,
            rule_sha256=self.rule_sha256,
            approval_artifact_sha256=self.approval_artifact_sha256,
            signature_algorithm=self.signature_algorithm,
            signature_key_id=self.signature_key_id,
            public_key_sha256=self.public_key_sha256,
            signed_at=self.signed_at,
        )
        expected_payload_sha256 = hashlib.sha256(payload).hexdigest()
        if self.signed_payload_sha256 != expected_payload_sha256:
            raise ValueError("customer approval signed-payload fingerprint is invalid")
        try:
            public_key = serialization.load_pem_public_key(
                self.public_key_pem.encode("utf-8")
            )
            signature = base64.b64decode(self.detached_signature_base64, validate=True)
            if self.signature_algorithm == "ed25519":
                if not isinstance(public_key, ed25519.Ed25519PublicKey):
                    raise ValueError("customer approval key type does not match algorithm")
                public_key.verify(signature, payload)
            elif self.signature_algorithm == "ecdsa-p256-sha256":
                if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
                    public_key.curve, ec.SECP256R1
                ):
                    raise ValueError("customer approval key type does not match algorithm")
                public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
            else:
                if not isinstance(public_key, rsa.RSAPublicKey):
                    raise ValueError("customer approval key type does not match algorithm")
                public_key.verify(
                    signature,
                    payload,
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    hashes.SHA256(),
                )
        except (InvalidSignature, ValueError, TypeError, UnsupportedAlgorithm) as exc:
            raise ValueError("customer approval signature verification failed") from exc
        return self


class CustomerCompensationRuleContract(_FrozenModel):
    """Tenant-bound rule lifecycle record that remains non-executable."""

    schema_id: ClassVar[str] = "gda.customer-compensation-rule-contract.v1"
    tenant_id: TenantId
    rule: CustomerCompensationRule
    status: CustomerCompensationRuleStatus
    approval_evidence: CustomerCompensationRuleApprovalEvidence | None = None
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    automatic_mutating_selection_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False
    contract_sha256: Sha256

    @model_validator(mode="after")
    def _bounded_lifecycle(self) -> CustomerCompensationRuleContract:
        evidence = self.approval_evidence
        if self.status is CustomerCompensationRuleStatus.CUSTOMER_APPROVED:
            if evidence is None:
                raise ValueError("customer-approved rule requires signed approval evidence")
            if (
                evidence.rule_id != self.rule.rule_id
                or evidence.rule_semantic_version != self.rule.semantic_version
                or evidence.rule_sha256 != self.rule.rule_sha256
            ):
                raise ValueError("customer approval evidence is bound to another rule")
        elif evidence is not None:
            raise ValueError("unapproved customer rule cannot carry approval evidence")

        expected = customer_compensation_rule_contract_fingerprint(
            **self.model_dump(mode="json", exclude={"contract_sha256"})
        )
        if self.contract_sha256 != expected:
            raise ValueError("customer compensation rule contract fingerprint is invalid")
        return self


class CustomerCompensationRuleAuthorityReadRequest(_FrozenModel):
    """Tenant comes from auth context; an optional rule ID narrows the read."""

    schema_id: ClassVar[str] = (
        "gda.customer-compensation-rule-authority-read-request.v1"
    )
    rule_id: CustomerRuleId | None = None


class CustomerCompensationRuleAuthorityItem(_FrozenModel):
    """One rule's current contract and complete immutable history."""

    schema_id: ClassVar[str] = "gda.customer-compensation-rule-authority-item.v1"
    tenant_id: TenantId
    rule_id: CustomerRuleId
    current: CustomerCompensationRuleContract
    history: tuple[CustomerCompensationRuleContract, ...] = Field(
        min_length=1,
        max_length=64,
    )
    history_count: int = Field(ge=1)
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    automatic_mutating_selection_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_history(self) -> CustomerCompensationRuleAuthorityItem:
        if self.history_count != len(self.history):
            raise ValueError("customer rule authority history count differs")
        if self.current != self.history[-1]:
            raise ValueError("customer rule authority current is not latest history")
        if any(
            contract.tenant_id != self.tenant_id
            or contract.rule.rule_id != self.rule_id
            for contract in self.history
        ):
            raise ValueError("customer rule authority history crosses rule identity")
        if any(
            contract.execution_allowed
            or contract.automatic_mutating_selection_allowed
            for contract in self.history
        ):
            raise ValueError("customer rule authority returned executable evidence")
        return self


class CustomerCompensationRuleAuthorityReadResponse(_FrozenModel):
    """Read-only tenant-scoped current/history projection."""

    schema_id: ClassVar[str] = (
        "gda.customer-compensation-rule-authority-read-response.v1"
    )
    tenant_id: TenantId
    requested_rule_id: CustomerRuleId | None = None
    items: tuple[CustomerCompensationRuleAuthorityItem, ...] = Field(
        max_length=8
    )
    rule_count: int = Field(ge=0)
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    automatic_mutating_selection_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_items(
        self,
    ) -> CustomerCompensationRuleAuthorityReadResponse:
        rule_ids = tuple(item.rule_id for item in self.items)
        if tuple(sorted(set(rule_ids))) != rule_ids:
            raise ValueError("customer rule authority items must be unique and sorted")
        if self.rule_count != len(self.items):
            raise ValueError("customer rule authority count differs")
        if self.requested_rule_id is not None and rule_ids not in {
            (),
            (self.requested_rule_id,),
        }:
            raise ValueError("customer rule authority response ignores requested rule")
        if any(item.tenant_id != self.tenant_id for item in self.items):
            raise ValueError("customer rule authority response crosses tenants")
        return self


class FederatedProjectionCompensationRuleAssessmentRequest(_FrozenModel):
    """Read-only proposal and caller-supplied rule contracts to assess."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-rule-assessment-request.v1"
    )
    proposal: FederatedProjectionCompensationProposal
    rules: tuple[CustomerCompensationRuleContract, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def _bounded_submission(
        self,
    ) -> FederatedProjectionCompensationRuleAssessmentRequest:
        required_rule_ids = set(self.proposal.missing_customer_rule_ids)
        unknown = required_rule_ids - set(ACTION_BY_RULE_ID)
        if unknown:
            raise ValueError("proposal contains an unsupported customer rule id")
        if any(
            ACTION_BY_RULE_ID[rule_id] is not candidate.action
            for candidate in self.proposal.candidates
            for rule_id in candidate.missing_customer_rule_ids
        ):
            raise ValueError("proposal customer rule id and candidate action differ")
        rule_ids = tuple(contract.rule.rule_id for contract in self.rules)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("only one customer compensation contract per rule is allowed")
        if any(contract.tenant_id != self.proposal.tenant_id for contract in self.rules):
            raise ValueError("customer compensation rules cannot cross tenants")
        unexpected = set(rule_ids) - required_rule_ids
        if unexpected:
            raise ValueError("submitted customer rule is not required by the proposal")
        return self


class FederatedProjectionCompensationRuleAuthorityAssessmentRequest(_FrozenModel):
    """Read-only assessment input; tenant comes only from auth context."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-rule-authority-assessment-request.v1"
    )
    run_id: NonEmptyText = Field(
        description=(
            "Federated recovery run whose persisted proposal and customer-rule "
            "authority current states should be assessed."
        )
    )


class CustomerCompensationRuleAssessmentItem(_FrozenModel):
    schema_id: ClassVar[str] = "gda.customer-compensation-rule-assessment-item.v2"
    rule_id: CustomerRuleId
    action: CompensationProposalAction
    status: CustomerCompensationRuleAssessmentStatus
    candidate_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=6)
    expected_targets: tuple[CustomerCompensationRuleTargetScope, ...] = Field(
        min_length=1,
        max_length=32,
    )
    expected_evidence: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=32)
    submitted_rule_semantic_version: SemanticVersion | None = None
    submitted_rule_sha256: Sha256 | None = None
    submitted_contract_sha256: Sha256 | None = None
    customer_approval_evidence_present: bool
    customer_approval_trusted: bool = False
    customer_approval_trust_anchor_sha256: Sha256 | None = None
    reason_codes: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=16)
    automatic_mutating_selection_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_item(self) -> CustomerCompensationRuleAssessmentItem:
        for values, label in (
            (self.candidate_sha256s, "candidate identities"),
            (self.expected_evidence, "expected evidence"),
            (self.reason_codes, "reason codes"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"rule assessment {label} must be unique and sorted")
        target_keys = tuple(
            (target.target_engine.value, target.target_ref)
            for target in self.expected_targets
        )
        if tuple(sorted(set(target_keys))) != target_keys:
            raise ValueError("rule assessment targets must be unique and sorted")

        submitted = (
            self.submitted_rule_semantic_version,
            self.submitted_rule_sha256,
            self.submitted_contract_sha256,
        )
        if self.status is CustomerCompensationRuleAssessmentStatus.MISSING:
            if any(value is not None for value in submitted):
                raise ValueError("missing rule assessment contains submitted identity")
            if self.customer_approval_evidence_present:
                raise ValueError("missing rule assessment claims approval evidence")
        elif any(value is None for value in submitted):
            raise ValueError("submitted rule assessment lacks immutable identity")
        if self.status is CustomerCompensationRuleAssessmentStatus.MISSING and (
            self.customer_approval_trusted
            or self.customer_approval_trust_anchor_sha256 is not None
        ):
            raise ValueError("missing rule assessment claims a trust anchor")
        if self.customer_approval_trusted and (
            self.status
            is not CustomerCompensationRuleAssessmentStatus.APPROVED_BUT_NOT_EXECUTABLE
            or not self.customer_approval_evidence_present
            or self.customer_approval_trust_anchor_sha256 is None
        ):
            raise ValueError("trusted approval evidence status differs")
        if (
            self.status
            is CustomerCompensationRuleAssessmentStatus.APPROVED_BUT_NOT_EXECUTABLE
            and not self.customer_approval_trusted
        ):
            raise ValueError("approved rule assessment lacks a trusted key")
        if not self.customer_approval_evidence_present and (
            self.customer_approval_trusted
            or self.customer_approval_trust_anchor_sha256 is not None
        ):
            raise ValueError("rule assessment trust metadata lacks approval evidence")
        return self


class FederatedProjectionCompensationRuleAssessment(_FrozenModel):
    """Deterministic readiness result; this artifact never authorizes execution."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-rule-assessment.v2"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    proposal_sha256: Sha256
    source_snapshot_sha256: Sha256
    dataset_scope: Literal["chongqing_customer_dataset"] = (
        "chongqing_customer_dataset"
    )
    ontology: CompensationOntologyBinding
    assessments: tuple[CustomerCompensationRuleAssessmentItem, ...] = Field(
        max_length=8
    )
    missing_rule_ids: tuple[CustomerRuleId, ...] = Field(max_length=8)
    draft_unreviewed_rule_ids: tuple[CustomerRuleId, ...] = Field(max_length=8)
    awaiting_customer_approval_rule_ids: tuple[CustomerRuleId, ...] = Field(
        max_length=8
    )
    approved_but_not_executable_rule_ids: tuple[CustomerRuleId, ...] = Field(
        max_length=8
    )
    invalid_or_drifted_rule_ids: tuple[CustomerRuleId, ...] = Field(max_length=8)
    readiness: CustomerCompensationRuleAssessmentReadiness
    all_required_rule_contracts_approved: bool
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    automatic_mutating_selection_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False
    assessment_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_summary(
        self,
    ) -> FederatedProjectionCompensationRuleAssessment:
        ids = tuple(item.rule_id for item in self.assessments)
        if tuple(sorted(set(ids))) != ids:
            raise ValueError("rule assessments must be unique and sorted")
        summaries = {
            CustomerCompensationRuleAssessmentStatus.MISSING: self.missing_rule_ids,
            CustomerCompensationRuleAssessmentStatus.DRAFT_UNREVIEWED: (
                self.draft_unreviewed_rule_ids
            ),
            CustomerCompensationRuleAssessmentStatus.AWAITING_CUSTOMER_APPROVAL: (
                self.awaiting_customer_approval_rule_ids
            ),
            CustomerCompensationRuleAssessmentStatus.APPROVED_BUT_NOT_EXECUTABLE: (
                self.approved_but_not_executable_rule_ids
            ),
            CustomerCompensationRuleAssessmentStatus.INVALID_OR_DRIFTED: (
                self.invalid_or_drifted_rule_ids
            ),
        }
        for status, summary in summaries.items():
            expected = tuple(item.rule_id for item in self.assessments if item.status is status)
            if summary != expected:
                raise ValueError("rule assessment status summary differs")
        approved = bool(self.assessments) and all(
            item.status
            is CustomerCompensationRuleAssessmentStatus.APPROVED_BUT_NOT_EXECUTABLE
            for item in self.assessments
        )
        if self.all_required_rule_contracts_approved is not approved:
            raise ValueError("rule assessment approval summary differs")
        expected_readiness = (
            CustomerCompensationRuleAssessmentReadiness.RULES_APPROVED_EXECUTION_DISABLED
            if approved
            else CustomerCompensationRuleAssessmentReadiness.RULE_GAPS_REMAINING
        )
        if self.readiness is not expected_readiness:
            raise ValueError("rule assessment readiness differs")

        expected = customer_compensation_rule_assessment_fingerprint(
            **self.model_dump(mode="json", exclude={"assessment_sha256"})
        )
        if self.assessment_sha256 != expected:
            raise ValueError("customer compensation rule assessment fingerprint is invalid")
        return self


class FederatedProjectionCompensationRuleAuthorityAssessmentEvidence(_FrozenModel):
    """One consistent authority snapshot used by downstream review admission."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-rule-authority-assessment-evidence.v1"
    )
    proposal: FederatedProjectionCompensationProposal
    current_rules: tuple[CustomerCompensationRuleContract, ...] = Field(
        max_length=8
    )
    assessment: FederatedProjectionCompensationRuleAssessment
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    automatic_mutating_selection_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_authority_evidence(
        self,
    ) -> FederatedProjectionCompensationRuleAuthorityAssessmentEvidence:
        proposal = self.proposal
        assessment = self.assessment
        if (
            assessment.tenant_id != proposal.tenant_id
            or assessment.run_id != proposal.run_id
            or assessment.proposal_sha256 != proposal.proposal_sha256
            or assessment.source_snapshot_sha256 != proposal.source_snapshot_sha256
            or assessment.ontology != proposal.ontology
        ):
            raise ValueError("rule authority assessment is bound to another proposal")
        rule_ids = tuple(contract.rule.rule_id for contract in self.current_rules)
        if tuple(sorted(set(rule_ids))) != rule_ids:
            raise ValueError("rule authority assessment current rules must be sorted")
        if not set(rule_ids).issubset(proposal.missing_customer_rule_ids):
            raise ValueError("rule authority assessment includes an unrelated rule")
        contracts = {
            contract.rule.rule_id: contract for contract in self.current_rules
        }
        for item in assessment.assessments:
            contract = contracts.get(item.rule_id)
            if item.status is CustomerCompensationRuleAssessmentStatus.MISSING:
                if contract is not None:
                    raise ValueError("missing assessment has an authority current rule")
                continue
            if contract is None or (
                item.submitted_rule_semantic_version
                != contract.rule.semantic_version
                or item.submitted_rule_sha256 != contract.rule.rule_sha256
                or item.submitted_contract_sha256 != contract.contract_sha256
            ):
                raise ValueError("rule assessment identity differs from authority current")
        return self


class CustomerCompensationRuleTechnicalBaselineBootstrapResult(_FrozenModel):
    """Internal draft bootstrap receipt; it never represents customer approval."""

    schema_id: ClassVar[str] = (
        "gda.customer-compensation-rule-technical-baseline-bootstrap-result.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    proposal_sha256: Sha256
    desired_draft_contracts: tuple[CustomerCompensationRuleContract, ...] = Field(
        max_length=8
    )
    created_draft_rule_ids: tuple[CustomerRuleId, ...] = Field(max_length=8)
    reused_current_rule_ids: tuple[CustomerRuleId, ...] = Field(max_length=8)
    invalid_or_drifted_rule_ids: tuple[CustomerRuleId, ...] = Field(max_length=8)
    assessment: FederatedProjectionCompensationRuleAssessment
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    automatic_mutating_selection_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_bootstrap(
        self,
    ) -> CustomerCompensationRuleTechnicalBaselineBootstrapResult:
        desired_ids = tuple(
            contract.rule.rule_id for contract in self.desired_draft_contracts
        )
        if tuple(sorted(set(desired_ids))) != desired_ids:
            raise ValueError("technical baseline draft rules must be unique and sorted")
        if any(
            contract.tenant_id != self.tenant_id
            or contract.status is not CustomerCompensationRuleStatus.DRAFT_UNREVIEWED
            or contract.approval_evidence is not None
            or contract.execution_allowed
            or contract.automatic_mutating_selection_allowed
            for contract in self.desired_draft_contracts
        ):
            raise ValueError("technical baseline contains non-draft customer evidence")
        partition = tuple(
            sorted(self.created_draft_rule_ids + self.reused_current_rule_ids)
        )
        if (
            tuple(sorted(set(self.created_draft_rule_ids)))
            != self.created_draft_rule_ids
            or tuple(sorted(set(self.reused_current_rule_ids)))
            != self.reused_current_rule_ids
            or partition != desired_ids
            or set(self.created_draft_rule_ids) & set(self.reused_current_rule_ids)
        ):
            raise ValueError("technical baseline bootstrap disposition is inconsistent")
        if (
            self.assessment.tenant_id != self.tenant_id
            or self.assessment.run_id != self.run_id
            or self.assessment.proposal_sha256 != self.proposal_sha256
            or self.invalid_or_drifted_rule_ids
            != self.assessment.invalid_or_drifted_rule_ids
            or tuple(item.rule_id for item in self.assessment.assessments) != desired_ids
        ):
            raise ValueError("technical baseline assessment differs from its proposal")
        return self


def build_customer_compensation_rule(
    *,
    rule_id: str,
    semantic_version: str,
    action: CompensationProposalAction,
    applicable_targets: tuple[CustomerCompensationRuleTargetScope, ...],
    required_evidence: tuple[str, ...],
) -> CustomerCompensationRule:
    """Seal caller-supplied semantics without adding or approving any rule."""

    targets = tuple(
        sorted(
            set(applicable_targets),
            key=lambda target: (target.target_engine.value, target.target_ref),
        )
    )
    values = {
        "rule_id": rule_id,
        "semantic_version": semantic_version,
        "action": action,
        "dataset_scope": "chongqing_customer_dataset",
        "ontology": CompensationOntologyBinding().model_dump(mode="json"),
        "applicable_targets": tuple(
            target.model_dump(mode="json") for target in targets
        ),
        "required_evidence": tuple(sorted(set(required_evidence))),
        "mutates_provider": (
            action is not CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME
        ),
        "approval_required": True,
        "automatic_mutating_selection_allowed": False,
        "execution_allowed": False,
    }
    return CustomerCompensationRule(
        **values,
        rule_sha256=customer_compensation_rule_fingerprint(**values),
    )


def build_customer_compensation_rule_contract(
    *,
    tenant_id: str,
    rule: CustomerCompensationRule,
    status: CustomerCompensationRuleStatus,
    approval_evidence: CustomerCompensationRuleApprovalEvidence | None = None,
) -> CustomerCompensationRuleContract:
    """Seal one lifecycle record; approval evidence remains mandatory if claimed."""

    values = {
        "tenant_id": tenant_id,
        "rule": rule.model_dump(mode="json"),
        "status": status,
        "approval_evidence": (
            approval_evidence.model_dump(mode="json")
            if approval_evidence is not None
            else None
        ),
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
        "automatic_mutating_selection_allowed": False,
        "execution_allowed": False,
    }
    return CustomerCompensationRuleContract(
        **values,
        contract_sha256=customer_compensation_rule_contract_fingerprint(**values),
    )


def build_customer_compensation_rule_technical_baseline_drafts(
    proposal: FederatedProjectionCompensationProposal,
) -> tuple[CustomerCompensationRuleContract, ...]:
    """Derive non-approved draft coverage from sealed proposal evidence only.

    These drafts describe the targets and evidence already present in the
    proposal. They do not choose an action, supply customer business semantics,
    or make any candidate executable.
    """

    missing = assess_federated_projection_compensation_rules(proposal, ())
    contracts = []
    for item in missing.assessments:
        major = item.rule_id.rsplit(".v", 1)[1]
        rule = build_customer_compensation_rule(
            rule_id=item.rule_id,
            semantic_version=f"{major}.0.0",
            action=item.action,
            applicable_targets=item.expected_targets,
            required_evidence=item.expected_evidence,
        )
        contracts.append(
            build_customer_compensation_rule_contract(
                tenant_id=proposal.tenant_id,
                rule=rule,
                status=CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
            )
        )
    return tuple(contracts)


def _expected_targets(
    proposal: FederatedProjectionCompensationProposal,
    plan_sha256s: set[str],
) -> tuple[CustomerCompensationRuleTargetScope, ...]:
    return tuple(
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


def assess_federated_projection_compensation_rules(
    proposal: FederatedProjectionCompensationProposal,
    rules: tuple[CustomerCompensationRuleContract, ...],
    trust_registry: CustomerCompensationApprovalTrustRegistry | None = None,
) -> FederatedProjectionCompensationRuleAssessment:
    """Assess customer-rule readiness without selecting or executing a candidate."""

    try:
        request = FederatedProjectionCompensationRuleAssessmentRequest(
            proposal=proposal,
            rules=rules,
        )
    except ValueError as exc:
        raise CustomerCompensationRuleError(str(exc)) from exc

    contracts = {contract.rule.rule_id: contract for contract in request.rules}
    registry = trust_registry or build_customer_compensation_approval_trust_registry()
    evaluated_at = datetime.now(UTC)
    proposal_targets = {
        (binding.target_engine, binding.target_ref)
        for binding in request.proposal.source_bindings
    }
    items: list[CustomerCompensationRuleAssessmentItem] = []
    for rule_id in request.proposal.missing_customer_rule_ids:
        candidates = tuple(
            candidate
            for candidate in request.proposal.candidates
            if rule_id in candidate.missing_customer_rule_ids
        )
        action = ACTION_BY_RULE_ID[rule_id]
        plan_sha256s = {
            plan_sha256
            for candidate in candidates
            for plan_sha256 in candidate.plan_sha256s
        }
        expected_targets = _expected_targets(request.proposal, plan_sha256s)
        expected_target_keys = {
            (target.target_engine.value, target.target_ref)
            for target in expected_targets
        }
        expected_evidence = tuple(
            sorted(
                {
                    evidence
                    for candidate in candidates
                    for evidence in candidate.required_evidence
                }
            )
        )
        contract = contracts.get(rule_id)
        approval_evidence_present = bool(
            contract is not None
            and contract.status is CustomerCompensationRuleStatus.CUSTOMER_APPROVED
        )
        approval_trusted = False
        approval_trust_anchor_sha256 = None
        if contract is None:
            status = CustomerCompensationRuleAssessmentStatus.MISSING
            reasons = ("customer_rule_contract_missing",)
        else:
            rule_target_keys = {
                (target.target_engine.value, target.target_ref)
                for target in contract.rule.applicable_targets
            }
            invalid_reasons: list[str] = []
            if not expected_target_keys.issubset(rule_target_keys):
                invalid_reasons.append("required_target_scope_not_covered")
            if not rule_target_keys.issubset(proposal_targets):
                invalid_reasons.append("rule_target_scope_outside_sealed_proposal")
            if not set(expected_evidence).issubset(contract.rule.required_evidence):
                invalid_reasons.append("required_evidence_contract_incomplete")

            if invalid_reasons:
                status = CustomerCompensationRuleAssessmentStatus.INVALID_OR_DRIFTED
                reasons = tuple(sorted(invalid_reasons))
            elif contract.status is CustomerCompensationRuleStatus.DRAFT_UNREVIEWED:
                status = CustomerCompensationRuleAssessmentStatus.DRAFT_UNREVIEWED
                reasons = ("customer_rule_is_draft_unreviewed",)
            elif (
                contract.status
                is CustomerCompensationRuleStatus.AWAITING_CUSTOMER_APPROVAL
            ):
                status = (
                    CustomerCompensationRuleAssessmentStatus.AWAITING_CUSTOMER_APPROVAL
                )
                reasons = ("customer_signed_approval_evidence_missing",)
            else:
                evidence = contract.approval_evidence
                assert evidence is not None
                trust = registry.evaluate(
                    tenant_id=contract.tenant_id,
                    customer_authority_ref=evidence.customer_authority_ref,
                    signature_key_id=evidence.signature_key_id,
                    signature_algorithm=evidence.signature_algorithm,
                    public_key_sha256=evidence.public_key_sha256,
                    signed_at=evidence.signed_at,
                    evaluated_at=evaluated_at,
                )
                if trust.trusted:
                    status = (
                        CustomerCompensationRuleAssessmentStatus.APPROVED_BUT_NOT_EXECUTABLE
                    )
                    reasons = (
                        "customer_approval_evidence_present",
                        "execution_path_not_implemented",
                        "mutating_selection_remains_disabled",
                    )
                    approval_trusted = True
                    approval_trust_anchor_sha256 = trust.anchor_sha256
                else:
                    status = CustomerCompensationRuleAssessmentStatus.INVALID_OR_DRIFTED
                    assert trust.reason_code is not None
                    approval_trust_anchor_sha256 = trust.anchor_sha256
                    reasons = tuple(
                        sorted(
                            {
                                "customer_approval_evidence_present",
                                trust.reason_code,
                            }
                        )
                    )

        items.append(
            CustomerCompensationRuleAssessmentItem(
                rule_id=rule_id,
                action=action,
                status=status,
                candidate_sha256s=tuple(
                    sorted(candidate.candidate_sha256 for candidate in candidates)
                ),
                expected_targets=expected_targets,
                expected_evidence=expected_evidence,
                submitted_rule_semantic_version=(
                    contract.rule.semantic_version if contract is not None else None
                ),
                submitted_rule_sha256=(
                    contract.rule.rule_sha256 if contract is not None else None
                ),
                submitted_contract_sha256=(
                    contract.contract_sha256 if contract is not None else None
                ),
                customer_approval_evidence_present=approval_evidence_present,
                customer_approval_trusted=approval_trusted,
                customer_approval_trust_anchor_sha256=approval_trust_anchor_sha256,
                reason_codes=reasons,
            )
        )

    assessments = tuple(items)
    summary = {
        status: tuple(item.rule_id for item in assessments if item.status is status)
        for status in CustomerCompensationRuleAssessmentStatus
    }
    approved = bool(assessments) and all(
        item.status
        is CustomerCompensationRuleAssessmentStatus.APPROVED_BUT_NOT_EXECUTABLE
        for item in assessments
    )
    values = {
        "tenant_id": proposal.tenant_id,
        "run_id": proposal.run_id,
        "proposal_sha256": proposal.proposal_sha256,
        "source_snapshot_sha256": proposal.source_snapshot_sha256,
        "dataset_scope": "chongqing_customer_dataset",
        "ontology": proposal.ontology.model_dump(mode="json"),
        "assessments": tuple(item.model_dump(mode="json") for item in assessments),
        "missing_rule_ids": summary[CustomerCompensationRuleAssessmentStatus.MISSING],
        "draft_unreviewed_rule_ids": summary[
            CustomerCompensationRuleAssessmentStatus.DRAFT_UNREVIEWED
        ],
        "awaiting_customer_approval_rule_ids": summary[
            CustomerCompensationRuleAssessmentStatus.AWAITING_CUSTOMER_APPROVAL
        ],
        "approved_but_not_executable_rule_ids": summary[
            CustomerCompensationRuleAssessmentStatus.APPROVED_BUT_NOT_EXECUTABLE
        ],
        "invalid_or_drifted_rule_ids": summary[
            CustomerCompensationRuleAssessmentStatus.INVALID_OR_DRIFTED
        ],
        "readiness": (
            CustomerCompensationRuleAssessmentReadiness.RULES_APPROVED_EXECUTION_DISABLED
            if approved
            else CustomerCompensationRuleAssessmentReadiness.RULE_GAPS_REMAINING
        ),
        "all_required_rule_contracts_approved": approved,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
        "automatic_mutating_selection_allowed": False,
        "execution_allowed": False,
    }
    return FederatedProjectionCompensationRuleAssessment(
        **values,
        assessment_sha256=customer_compensation_rule_assessment_fingerprint(**values),
    )


__all__ = [
    "ACTION_BY_RULE_ID",
    "RULE_ID_BY_ACTION",
    "CustomerCompensationRule",
    "CustomerCompensationRuleApprovalEvidence",
    "CustomerCompensationRuleAuthorityItem",
    "CustomerCompensationRuleAuthorityReadRequest",
    "CustomerCompensationRuleAuthorityReadResponse",
    "CustomerCompensationApprovalTrustRegistry",
    "CustomerCompensationRuleAssessmentItem",
    "CustomerCompensationRuleAssessmentReadiness",
    "CustomerCompensationRuleAssessmentStatus",
    "CustomerCompensationRuleContract",
    "CustomerCompensationRuleError",
    "CustomerCompensationRuleStatus",
    "CustomerCompensationRuleTargetScope",
    "CustomerCompensationRuleTechnicalBaselineBootstrapResult",
    "FederatedProjectionCompensationRuleAssessment",
    "FederatedProjectionCompensationRuleAuthorityAssessmentRequest",
    "FederatedProjectionCompensationRuleAuthorityAssessmentEvidence",
    "FederatedProjectionCompensationRuleAssessmentRequest",
    "assess_federated_projection_compensation_rules",
    "build_customer_compensation_rule",
    "build_customer_compensation_rule_contract",
    "build_customer_compensation_rule_technical_baseline_drafts",
    "customer_compensation_rule_assessment_fingerprint",
    "customer_compensation_rule_approval_payload",
    "customer_compensation_rule_contract_fingerprint",
    "customer_compensation_rule_fingerprint",
]
