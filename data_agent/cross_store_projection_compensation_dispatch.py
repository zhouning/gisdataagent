"""Prepare a sealed, non-executing dispatch intent after authorization consumption.

Customer compensation semantics remain external to the platform.  This module
only proves that one consumed authorization still points at the current
proposal, candidate plans, targets, and trusted rule contracts.  It never
imports or calls a Provider adapter.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cross_store_projection_compensation_approval import (
    FederatedProjectionCompensationApprovalBinding,
    FederatedProjectionCompensationExecutionBinding,
    TrustedCustomerCompensationRuleBinding,
    build_federated_projection_compensation_approval_binding,
)
from .cross_store_projection_compensation_execution_authority import (
    FederatedCompensationExecutionAuthorizationConsumptionReceipt,
)
from .cross_store_projection_compensation_proposal import (
    ONTOLOGY_CONTENT_SHA256,
    ONTOLOGY_PACKAGE_ID,
    CompensationProposalAction,
    CompensationProposalSourceBinding,
)
from .cross_store_projection_compensation_rule_contract import (
    FederatedProjectionCompensationRuleAuthorityAssessmentEvidence,
)
from .platform_contracts import (
    NonEmptyText,
    ResourceURNText,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
)


class FederatedProjectionCompensationDispatchError(ValueError):
    """Current evidence cannot produce a sealed dispatch intent."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FederatedProjectionCompensationRuleAuthorityCurrentReader(Protocol):
    """Tenant-scoped read port used immediately before Provider callbacks."""

    tenant_id: str

    def assessment_evidence_current(
        self,
        run_id: str,
    ) -> FederatedProjectionCompensationRuleAuthorityAssessmentEvidence | None:
        ...


class FederatedProjectionCompensationDispatchIntent(_FrozenModel):
    """A future Provider adapter input, explicitly pending and non-executing."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-dispatch-intent.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    proposal_sha256: Sha256
    candidate_sha256: Sha256
    candidate_action: CompensationProposalAction
    candidate_scope: Literal["blocked_plan", "committed_prefix", "federated_run"]
    dataset_scope: Literal["chongqing_customer_dataset"] = (
        "chongqing_customer_dataset"
    )
    ontology_package_id: Literal[
        "natural-resource-one-map:2.3.0:587915868b1221af"
    ] = ONTOLOGY_PACKAGE_ID
    ontology_content_sha256: Sha256 = ONTOLOGY_CONTENT_SHA256
    source_snapshot_sha256: Sha256
    plan_bindings: tuple[CompensationProposalSourceBinding, ...] = Field(
        min_length=1,
        max_length=32,
    )
    approved_rule_ids: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=8)
    approved_rule_contract_sha256s: tuple[Sha256, ...] = Field(
        min_length=1,
        max_length=8,
    )
    execution_approval_case_ref: ResourceURNText
    review_approval_case_ref: ResourceURNText
    execution_authorization_sha256: Sha256
    review_binding_sha256: Sha256
    consumed_at: str
    dispatch_state: Literal["provider_adapter_pending"] = "provider_adapter_pending"
    provider_dispatch_performed: Literal[False] = False
    execution_allowed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    dispatch_intent_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_intent(
        self,
    ) -> FederatedProjectionCompensationDispatchIntent:
        if self.ontology_content_sha256 != ONTOLOGY_CONTENT_SHA256:
            raise ValueError("dispatch intent ontology package differs from 2.3.0")
        positions = tuple(binding.position for binding in self.plan_bindings)
        if positions != tuple(sorted(set(positions))):
            raise ValueError("dispatch plan bindings must be unique and ordered")
        plan_hashes = tuple(binding.plan_sha256 for binding in self.plan_bindings)
        if len(set(plan_hashes)) != len(plan_hashes):
            raise ValueError("dispatch plan bindings must be unique")
        if tuple(sorted(set(self.approved_rule_ids))) != self.approved_rule_ids:
            raise ValueError("dispatch rule IDs must be unique and sorted")
        if tuple(sorted(set(self.approved_rule_contract_sha256s))) != (
            self.approved_rule_contract_sha256s
        ):
            raise ValueError("dispatch rule contract hashes must be unique and sorted")
        for reference in (
            self.execution_approval_case_ref,
            self.review_approval_case_ref,
        ):
            identity = parse_resource_urn(reference)
            if (
                identity["tenant_id"] != self.tenant_id
                or identity["resource_kind"] != "approval_case"
            ):
                raise ValueError("dispatch ApprovalCase tenant differs")
        if self.execution_approval_case_ref == self.review_approval_case_ref:
            raise ValueError("dispatch ApprovalCase references must differ")
        expected = canonical_json_fingerprint(
            {
                "schema": self.schema_id,
                "data": self.model_dump(
                    mode="json",
                    exclude={"dispatch_intent_sha256"},
                ),
            }
        )
        if self.dispatch_intent_sha256 != expected:
            raise ValueError("compensation dispatch intent fingerprint is invalid")
        return self


class FederatedProjectionCompensationDispatchRuleCurrentBinding(_FrozenModel):
    """Bind a dispatch preflight to customer-rule authority current evidence."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-dispatch-rule-current-binding.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    dispatch_intent_sha256: Sha256
    proposal_sha256: Sha256
    candidate_sha256: Sha256
    review_binding_sha256: Sha256
    rule_assessment_sha256: Sha256
    rule_authority_evidence_sha256: Sha256
    approved_rules: tuple[TrustedCustomerCompensationRuleBinding, ...] = Field(
        min_length=1,
        max_length=8,
    )
    binding_state: Literal[
        "customer_rule_authority_current_bound_pending_provider_execution"
    ] = "customer_rule_authority_current_bound_pending_provider_execution"
    customer_approval_evidence_present: Literal[True] = True
    customer_rules_trusted: Literal[True] = True
    binding_grants_execution_authority: Literal[False] = False
    production_execution_authorized: Literal[False] = False
    provider_dispatch_performed: Literal[False] = False
    authority_write_performed: Literal[False] = False
    rule_current_binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_binding(
        self,
    ) -> FederatedProjectionCompensationDispatchRuleCurrentBinding:
        rule_ids = tuple(rule.rule_id for rule in self.approved_rules)
        if tuple(sorted(set(rule_ids))) != rule_ids:
            raise ValueError("dispatch rule-current bindings must be unique and sorted")
        expected = canonical_json_fingerprint(
            {
                "schema": self.schema_id,
                "data": self.model_dump(
                    mode="json",
                    exclude={"rule_current_binding_sha256"},
                ),
            }
        )
        if self.rule_current_binding_sha256 != expected:
            raise ValueError("dispatch rule-current binding fingerprint is invalid")
        return self


def _fingerprint_values(
    values: dict[str, Any],
) -> str:
    normalized = FederatedProjectionCompensationDispatchIntent.model_construct(
        **values
    ).model_dump(mode="json")
    return canonical_json_fingerprint(
        {
            "schema": FederatedProjectionCompensationDispatchIntent.schema_id,
            "data": {
                key: value
                for key, value in normalized.items()
                if key != "dispatch_intent_sha256"
            },
        }
    )


def build_federated_projection_compensation_dispatch_rule_current_binding(
    evidence: FederatedProjectionCompensationRuleAuthorityAssessmentEvidence,
    intent: FederatedProjectionCompensationDispatchIntent,
) -> FederatedProjectionCompensationDispatchRuleCurrentBinding:
    """Rebuild trusted rule current immediately before Provider execution."""

    try:
        evidence = FederatedProjectionCompensationRuleAuthorityAssessmentEvidence.model_validate(
            evidence.model_dump(mode="python")
        )
        intent = FederatedProjectionCompensationDispatchIntent.model_validate(
            intent.model_dump(mode="python")
        )
        current = build_federated_projection_compensation_approval_binding(
            evidence,
            intent.candidate_sha256,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise FederatedProjectionCompensationDispatchError(
            "customer-rule authority current cannot pass execution preflight"
        ) from exc

    plan_sha256s = tuple(sorted(binding.plan_sha256 for binding in intent.plan_bindings))
    rule_ids = tuple(rule.rule_id for rule in current.approved_rules)
    rule_contract_sha256s = tuple(
        sorted(rule.contract_sha256 for rule in current.approved_rules)
    )
    if (
        current.tenant_id != intent.tenant_id
        or current.run_id != intent.run_id
        or current.proposal_sha256 != intent.proposal_sha256
        or current.source_snapshot_sha256 != intent.source_snapshot_sha256
        or current.candidate_sha256 != intent.candidate_sha256
        or current.candidate_action is not intent.candidate_action
        or current.candidate_scope != intent.candidate_scope
        or current.candidate_plan_sha256s != plan_sha256s
        or current.binding_sha256 != intent.review_binding_sha256
        or current.rule_assessment_sha256 != evidence.assessment.assessment_sha256
        or rule_ids != intent.approved_rule_ids
        or rule_contract_sha256s != intent.approved_rule_contract_sha256s
    ):
        raise FederatedProjectionCompensationDispatchError(
            "customer-rule authority current differs from the sealed dispatch"
        )

    values = {
        "tenant_id": intent.tenant_id,
        "run_id": intent.run_id,
        "dispatch_intent_sha256": intent.dispatch_intent_sha256,
        "proposal_sha256": intent.proposal_sha256,
        "candidate_sha256": intent.candidate_sha256,
        "review_binding_sha256": current.binding_sha256,
        "rule_assessment_sha256": current.rule_assessment_sha256,
        "rule_authority_evidence_sha256": canonical_json_fingerprint(
            {
                "schema": evidence.schema_id,
                "data": evidence.model_dump(mode="json"),
            }
        ),
        "approved_rules": current.approved_rules,
        "binding_state": (
            "customer_rule_authority_current_bound_pending_provider_execution"
        ),
        "customer_approval_evidence_present": True,
        "customer_rules_trusted": True,
        "binding_grants_execution_authority": False,
        "production_execution_authorized": False,
        "provider_dispatch_performed": False,
        "authority_write_performed": False,
    }
    binding_sha256 = canonical_json_fingerprint(
        {
            "schema": FederatedProjectionCompensationDispatchRuleCurrentBinding.schema_id,
            "data": FederatedProjectionCompensationDispatchRuleCurrentBinding.model_construct(
                **values
            ).model_dump(mode="json"),
        }
    )
    return FederatedProjectionCompensationDispatchRuleCurrentBinding(
        **values,
        rule_current_binding_sha256=binding_sha256,
    )


def _matching_review_binding(
    evidence: FederatedProjectionCompensationRuleAuthorityAssessmentEvidence,
    execution_binding: FederatedProjectionCompensationExecutionBinding,
) -> FederatedProjectionCompensationApprovalBinding:
    try:
        current = build_federated_projection_compensation_approval_binding(
            evidence,
            execution_binding.candidate_sha256,
        )
    except ValueError as exc:
        raise FederatedProjectionCompensationDispatchError(
            "current proposal or customer rule evidence cannot rebuild dispatch binding"
        ) from exc
    if current != execution_binding.review_binding:
        raise FederatedProjectionCompensationDispatchError(
            "execution binding differs from current proposal or customer rules"
        )
    return current


def build_federated_projection_compensation_dispatch_intent(
    evidence: FederatedProjectionCompensationRuleAuthorityAssessmentEvidence,
    execution_binding: FederatedProjectionCompensationExecutionBinding,
    receipt: FederatedCompensationExecutionAuthorizationConsumptionReceipt,
) -> FederatedProjectionCompensationDispatchIntent:
    """Bind consumed authorization to current plans and targets without dispatch."""

    if (
        receipt.tenant_id != execution_binding.tenant_id
        or receipt.review_approval_case_ref
        != execution_binding.review_approval_case_ref
        or receipt.proposal_sha256 != execution_binding.proposal_sha256
        or receipt.candidate_sha256 != execution_binding.candidate_sha256
        or receipt.execution_authorization_sha256
        != execution_binding.execution_authorization_sha256
        or receipt.review_binding_sha256
        != execution_binding.review_binding.binding_sha256
        or not receipt.authorization_consumed
        or receipt.provider_execution_performed
    ):
        raise FederatedProjectionCompensationDispatchError(
            "authorization receipt does not match the execution binding"
        )
    if receipt.execution_approval_case_ref == receipt.review_approval_case_ref:
        raise FederatedProjectionCompensationDispatchError(
            "authorization receipt ApprovalCase references must differ"
        )
    expected_execution_case_ref = build_resource_urn(
        execution_binding.tenant_id,
        "approval_case",
        f"compensation-execute-{execution_binding.execution_authorization_sha256}",
    )
    if receipt.execution_approval_case_ref != expected_execution_case_ref:
        raise FederatedProjectionCompensationDispatchError(
            "authorization receipt execution ApprovalCase differs from binding"
        )
    if execution_binding.candidate_action not in {
        CompensationProposalAction.CORRECTIVE_FORWARD,
        CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX,
        CompensationProposalAction.DELETE_TARGET,
        CompensationProposalAction.RESTORE_TARGET,
    }:
        raise FederatedProjectionCompensationDispatchError(
            "dispatch intent only accepts customer-rule compensation actions"
        )

    review_binding = _matching_review_binding(evidence, execution_binding)
    proposal = evidence.proposal
    candidate = next(
        (
            item
            for item in proposal.candidates
            if item.candidate_sha256 == execution_binding.candidate_sha256
        ),
        None,
    )
    if candidate is None or candidate.action is not execution_binding.candidate_action:
        raise FederatedProjectionCompensationDispatchError(
            "dispatch candidate is not present in proposal current"
        )
    if (
        candidate.plan_sha256s != review_binding.candidate_plan_sha256s
        or candidate.missing_customer_rule_ids
        != tuple(rule.rule_id for rule in review_binding.approved_rules)
        or candidate.recommended
        or not candidate.mutates_provider
        or not candidate.approval_required
    ):
        raise FederatedProjectionCompensationDispatchError(
            "dispatch candidate is not a sealed customer-rule mutation"
        )
    plan_by_sha = {binding.plan_sha256: binding for binding in proposal.source_bindings}
    try:
        plan_bindings = tuple(
            sorted(
                (plan_by_sha[plan_sha] for plan_sha in candidate.plan_sha256s),
                key=lambda binding: binding.position,
            )
        )
    except KeyError as exc:
        raise FederatedProjectionCompensationDispatchError(
            "dispatch candidate references an unsealed plan"
        ) from exc

    rule_ids = tuple(rule.rule_id for rule in review_binding.approved_rules)
    rule_contracts = tuple(
        rule.contract_sha256 for rule in review_binding.approved_rules
    )
    values = {
        "tenant_id": proposal.tenant_id,
        "run_id": proposal.run_id,
        "proposal_sha256": proposal.proposal_sha256,
        "candidate_sha256": candidate.candidate_sha256,
        "candidate_action": candidate.action,
        "candidate_scope": candidate.scope,
        "dataset_scope": proposal.dataset_scope,
        "ontology_package_id": proposal.ontology.package_id,
        "ontology_content_sha256": proposal.ontology.content_sha256,
        "source_snapshot_sha256": proposal.source_snapshot_sha256,
        "plan_bindings": plan_bindings,
        "approved_rule_ids": rule_ids,
        "approved_rule_contract_sha256s": tuple(
            sorted(rule_contracts)
        ),
        "execution_approval_case_ref": receipt.execution_approval_case_ref,
        "review_approval_case_ref": receipt.review_approval_case_ref,
        "execution_authorization_sha256": (
            receipt.execution_authorization_sha256
        ),
        "review_binding_sha256": receipt.review_binding_sha256,
        "consumed_at": receipt.consumed_at.isoformat(),
        "dispatch_state": "provider_adapter_pending",
        "provider_dispatch_performed": False,
        "execution_allowed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return FederatedProjectionCompensationDispatchIntent(
        **values,
        dispatch_intent_sha256=_fingerprint_values(values),
    )


__all__ = [
    "FederatedProjectionCompensationDispatchError",
    "FederatedProjectionCompensationDispatchIntent",
    "FederatedProjectionCompensationDispatchRuleCurrentBinding",
    "FederatedProjectionCompensationRuleAuthorityCurrentReader",
    "build_federated_projection_compensation_dispatch_intent",
    "build_federated_projection_compensation_dispatch_rule_current_binding",
]
