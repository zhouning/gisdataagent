"""Deterministic, non-executing proposals for federated recovery compensation.

The planner turns sealed recovery evidence into bounded operator choices.  It
never invents customer rollback semantics and never invokes a provider.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cross_store_projection_consistency import ProjectionRepairPlan
from .cross_store_projection_federated_recovery import (
    FederatedProjectionItemState,
    FederatedProjectionRecoverySnapshot,
    FederatedProjectionRecoveryState,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint

ONTOLOGY_KEY = "natural-resource-one-map"
ONTOLOGY_VERSION = "2.3.0"
ONTOLOGY_PACKAGE_ID = (
    "natural-resource-one-map:2.3.0:587915868b1221af"
)
ONTOLOGY_CONTENT_SHA256 = (
    "587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019"
)


class FederatedProjectionCompensationProposalError(ValueError):
    """Sealed recovery evidence cannot produce a bounded proposal."""


class CompensationProposalAction(StrEnum):
    RECONCILE_PROVIDER_OUTCOME = "reconcile_provider_outcome"
    APPROVED_REAPPLY_SEALED_PLAN = "approved_reapply_sealed_plan"
    CORRECTIVE_FORWARD = "corrective_forward"
    ROLLBACK_COMMITTED_PREFIX = "rollback_committed_prefix"
    DELETE_TARGET = "delete_target"
    RESTORE_TARGET = "restore_target"


class CompensationProposalReadiness(StrEnum):
    EVIDENCE_COLLECTION_READY = "evidence_collection_ready"
    APPROVAL_REQUIRED = "approval_required"
    CUSTOMER_RULE_REQUIRED = "customer_rule_required"


class CompensationProposalImplementation(StrEnum):
    SUPPORTED_BOUNDED = "supported_bounded"
    REQUIRES_CUSTOMER_RULE = "requires_customer_rule"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def compensation_candidate_fingerprint(**values: Any) -> str:
    return _fingerprint(
        FederatedProjectionCompensationCandidate.schema_id,
        values,
        "candidate_sha256",
    )


def compensation_proposal_fingerprint(**values: Any) -> str:
    return _fingerprint(
        FederatedProjectionCompensationProposal.schema_id,
        values,
        "proposal_sha256",
    )


class CompensationOntologyBinding(_FrozenModel):
    schema_id: ClassVar[str] = "gda.compensation-ontology-binding.v1"
    ontology_key: Literal["natural-resource-one-map"] = ONTOLOGY_KEY
    semantic_version: Literal["2.3.0"] = ONTOLOGY_VERSION
    package_id: Literal[
        "natural-resource-one-map:2.3.0:587915868b1221af"
    ] = ONTOLOGY_PACKAGE_ID
    content_sha256: Sha256 = ONTOLOGY_CONTENT_SHA256

    @model_validator(mode="after")
    def _exact_package(self) -> CompensationOntologyBinding:
        if self.content_sha256 != ONTOLOGY_CONTENT_SHA256:
            raise ValueError("compensation proposal ontology package differs from 2.3.0")
        return self


class CompensationProposalSourceBinding(_FrozenModel):
    position: int = Field(ge=0, le=31)
    plan_sha256: Sha256
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    target_engine: NonEmptyText
    target_ref: NonEmptyText
    sealed_action: Literal["checkpoint", "rebuild", "delete"]


class FederatedProjectionCompensationCandidate(_FrozenModel):
    schema_id: ClassVar[str] = "gda.federated-projection-compensation-candidate.v1"
    rank: int = Field(ge=1, le=6)
    action: CompensationProposalAction
    scope: Literal["blocked_plan", "committed_prefix", "federated_run"]
    plan_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=32)
    readiness: CompensationProposalReadiness
    implementation: CompensationProposalImplementation
    mutates_provider: bool
    approval_required: bool
    recommended: bool
    reason_codes: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=16)
    required_evidence: tuple[NonEmptyText, ...] = Field(max_length=16)
    missing_customer_rule_ids: tuple[NonEmptyText, ...] = Field(max_length=8)
    candidate_sha256: Sha256

    @model_validator(mode="after")
    def _bounded_candidate(self) -> FederatedProjectionCompensationCandidate:
        for values, label in (
            (self.plan_sha256s, "plan identities"),
            (self.reason_codes, "reason codes"),
            (self.required_evidence, "required evidence"),
            (self.missing_customer_rule_ids, "customer rule ids"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"compensation candidate {label} must be unique and sorted")

        if self.action is CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME:
            if (
                self.readiness
                is not CompensationProposalReadiness.EVIDENCE_COLLECTION_READY
                or self.implementation
                is not CompensationProposalImplementation.SUPPORTED_BOUNDED
                or self.mutates_provider
                or self.approval_required
                or not self.recommended
                or self.missing_customer_rule_ids
            ):
                raise ValueError("provider reconciliation candidate is not fail-closed")
        elif self.action is CompensationProposalAction.APPROVED_REAPPLY_SEALED_PLAN:
            if (
                self.readiness is not CompensationProposalReadiness.APPROVAL_REQUIRED
                or self.implementation
                is not CompensationProposalImplementation.SUPPORTED_BOUNDED
                or not self.mutates_provider
                or not self.approval_required
                or self.recommended
                or self.missing_customer_rule_ids
            ):
                raise ValueError("sealed-plan reapply candidate bypasses approval")
        elif (
            self.readiness is not CompensationProposalReadiness.CUSTOMER_RULE_REQUIRED
            or self.implementation
            is not CompensationProposalImplementation.REQUIRES_CUSTOMER_RULE
            or not self.mutates_provider
            or not self.approval_required
            or self.recommended
            or not self.missing_customer_rule_ids
        ):
            raise ValueError("customer-defined compensation candidate is executable")

        expected = compensation_candidate_fingerprint(
            **self.model_dump(mode="json", exclude={"candidate_sha256"})
        )
        if self.candidate_sha256 != expected:
            raise ValueError("compensation candidate fingerprint is invalid")
        return self


class FederatedProjectionCompensationProposal(_FrozenModel):
    """One immutable assisted-precheck artifact bound to a blocked run snapshot."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-proposal.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    source_snapshot_sha256: Sha256
    recovery_state: Literal["compensation_required", "failed_closed"]
    blocked_position: int = Field(ge=0, le=31)
    blocked_plan_sha256: Sha256
    dataset_scope: Literal["chongqing_customer_dataset"] = (
        "chongqing_customer_dataset"
    )
    ontology: CompensationOntologyBinding
    source_bindings: tuple[CompensationProposalSourceBinding, ...] = Field(
        min_length=2,
        max_length=32,
    )
    candidates: tuple[FederatedProjectionCompensationCandidate, ...] = Field(
        min_length=3,
        max_length=6,
    )
    recommended_candidate_sha256: Sha256 | None = None
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    automatic_mutating_selection_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False
    missing_customer_rule_ids: tuple[NonEmptyText, ...] = Field(max_length=8)
    proposal_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_proposal(self) -> FederatedProjectionCompensationProposal:
        if tuple(binding.position for binding in self.source_bindings) != tuple(
            range(len(self.source_bindings))
        ):
            raise ValueError("compensation proposal source positions are not contiguous")
        plan_sha256s = tuple(binding.plan_sha256 for binding in self.source_bindings)
        if len(set(plan_sha256s)) != len(plan_sha256s):
            raise ValueError("compensation proposal plans are not unique")
        if (
            self.blocked_position >= len(plan_sha256s)
            or plan_sha256s[self.blocked_position] != self.blocked_plan_sha256
        ):
            raise ValueError("compensation proposal blocked plan identity differs")
        if tuple(candidate.rank for candidate in self.candidates) != tuple(
            range(1, len(self.candidates) + 1)
        ):
            raise ValueError("compensation proposal candidate ranks are not contiguous")
        if len({candidate.action for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("compensation proposal actions are not unique")
        if len({candidate.candidate_sha256 for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("compensation proposal candidate identities are not unique")
        if any(
            not set(candidate.plan_sha256s).issubset(plan_sha256s)
            for candidate in self.candidates
        ):
            raise ValueError("compensation candidate references an unsealed plan")

        recommended = tuple(
            candidate for candidate in self.candidates if candidate.recommended
        )
        if len(recommended) > 1:
            raise ValueError("compensation proposal has multiple recommendations")
        if self.recovery_state == "compensation_required" and len(recommended) != 1:
            raise ValueError("compensation-required proposal lacks reconciliation")
        if self.recovery_state == "failed_closed" and recommended:
            raise ValueError("failed-closed proposal cannot recommend an action")
        expected_recommended = (
            recommended[0].candidate_sha256 if recommended else None
        )
        if self.recommended_candidate_sha256 != expected_recommended:
            raise ValueError("compensation proposal recommendation identity differs")
        if any(candidate.mutates_provider for candidate in recommended):
            raise ValueError("compensation proposal automatically recommends a mutation")
        if self.recovery_state == "failed_closed" and any(
            candidate.action
            in {
                CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME,
                CompensationProposalAction.APPROVED_REAPPLY_SEALED_PLAN,
            }
            for candidate in self.candidates
        ):
            raise ValueError("failed-closed proposal contains an unsupported shortcut")

        missing = tuple(
            sorted(
                {
                    rule_id
                    for candidate in self.candidates
                    for rule_id in candidate.missing_customer_rule_ids
                }
            )
        )
        if self.missing_customer_rule_ids != missing:
            raise ValueError("compensation proposal missing-rule summary differs")

        expected = compensation_proposal_fingerprint(
            **self.model_dump(mode="json", exclude={"proposal_sha256"})
        )
        if self.proposal_sha256 != expected:
            raise ValueError("compensation proposal fingerprint is invalid")
        return self


class FederatedProjectionCompensationProposalRequest(_FrozenModel):
    """Read-only input for generating a bounded compensation proposal.

    The tenant and run identity are carried by the sealed recovery snapshot;
    callers cannot submit a second identity field that could override it.
    """

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-proposal-request.v1"
    plans: tuple[ProjectionRepairPlan, ...] = Field(min_length=2, max_length=32)
    snapshot: FederatedProjectionRecoverySnapshot

    @model_validator(mode="after")
    def _request_matches_snapshot(self) -> FederatedProjectionCompensationProposalRequest:
        if len(self.plans) != len(self.snapshot.plan_sha256s):
            raise ValueError("compensation proposal plans must match snapshot length")
        if tuple(plan.plan_sha256 for plan in self.plans) != self.snapshot.plan_sha256s:
            raise ValueError("compensation proposal plans must match snapshot identities")
        if any(plan.tenant_id != self.snapshot.tenant_id for plan in self.plans):
            raise ValueError("compensation proposal plans must share the snapshot tenant")
        return self


class FederatedProjectionCompensationProposalReadRequest(_FrozenModel):
    """Tenant-independent lookup input; tenant identity comes from auth context."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-proposal-read-request.v1"
    )
    run_id: NonEmptyText = Field(
        description=(
            "Federated recovery run identifier whose persisted compensation "
            "proposal current state and immutable history should be read."
        )
    )


class FederatedProjectionCompensationProposalReadResponse(_FrozenModel):
    """Consistent current/history projection from the immutable authority."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-proposal-read-response.v1"
    )
    tenant_id: TenantId = Field(
        description="Authenticated tenant that owns every returned proposal."
    )
    run_id: NonEmptyText = Field(
        description="Federated recovery run identifier used for the lookup."
    )
    current: FederatedProjectionCompensationProposal = Field(
        description="Latest immutable proposal selected by the authority view."
    )
    history: tuple[FederatedProjectionCompensationProposal, ...] = Field(
        min_length=1,
        description="Complete immutable proposal history in ascending authority order.",
    )
    history_count: int = Field(
        ge=1,
        description="Number of immutable proposals returned in history.",
    )
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_authority_projection(
        self,
    ) -> FederatedProjectionCompensationProposalReadResponse:
        if self.history_count != len(self.history):
            raise ValueError("compensation proposal history count differs")
        if self.current != self.history[-1]:
            raise ValueError("compensation proposal current is not latest history")
        if any(
            proposal.tenant_id != self.tenant_id or proposal.run_id != self.run_id
            for proposal in self.history
        ):
            raise ValueError("compensation proposal authority response crosses identity")
        if any(proposal.execution_allowed for proposal in self.history):
            raise ValueError("compensation proposal authority returned executable evidence")
        return self


def _candidate(
    *,
    rank: int,
    action: CompensationProposalAction,
    scope: Literal["blocked_plan", "committed_prefix", "federated_run"],
    plan_sha256s: tuple[str, ...],
    readiness: CompensationProposalReadiness,
    implementation: CompensationProposalImplementation,
    mutates_provider: bool,
    approval_required: bool,
    recommended: bool,
    reason_codes: tuple[str, ...],
    required_evidence: tuple[str, ...],
    missing_customer_rule_ids: tuple[str, ...] = (),
) -> FederatedProjectionCompensationCandidate:
    values = {
        "rank": rank,
        "action": action,
        "scope": scope,
        "plan_sha256s": tuple(sorted(set(plan_sha256s))),
        "readiness": readiness,
        "implementation": implementation,
        "mutates_provider": mutates_provider,
        "approval_required": approval_required,
        "recommended": recommended,
        "reason_codes": tuple(sorted(set(reason_codes))),
        "required_evidence": tuple(sorted(set(required_evidence))),
        "missing_customer_rule_ids": tuple(sorted(set(missing_customer_rule_ids))),
    }
    return FederatedProjectionCompensationCandidate(
        **values,
        candidate_sha256=compensation_candidate_fingerprint(**values),
    )


def build_federated_projection_compensation_proposal(
    plans: tuple[ProjectionRepairPlan, ...],
    snapshot: FederatedProjectionRecoverySnapshot,
) -> FederatedProjectionCompensationProposal:
    """Build a deterministic proposal without performing or approving an action."""

    if snapshot.state not in {
        FederatedProjectionRecoveryState.COMPENSATION_REQUIRED,
        FederatedProjectionRecoveryState.FAILED_CLOSED,
    }:
        raise FederatedProjectionCompensationProposalError(
            "compensation proposal requires a blocked federated recovery snapshot"
        )
    if len(plans) != len(snapshot.items) or tuple(
        plan.plan_sha256 for plan in plans
    ) != snapshot.plan_sha256s:
        raise FederatedProjectionCompensationProposalError(
            "compensation proposal plans differ from the federated snapshot"
        )
    if any(plan.tenant_id != snapshot.tenant_id for plan in plans):
        raise FederatedProjectionCompensationProposalError(
            "compensation proposal cannot cross tenant boundaries"
        )

    position = snapshot.current_position
    if position >= len(plans):
        raise FederatedProjectionCompensationProposalError(
            "compensation proposal blocked position exceeds the plan list"
        )
    item = snapshot.items[position]
    plan = plans[position]
    if item.state not in {
        FederatedProjectionItemState.RECOVERY_REQUIRED,
        FederatedProjectionItemState.COMPENSATION_REQUIRED,
        FederatedProjectionItemState.FAILED_CLOSED,
    }:
        raise FederatedProjectionCompensationProposalError(
            "compensation proposal cursor does not identify a blocked item"
        )

    candidates: list[FederatedProjectionCompensationCandidate] = []
    blocked_plan = (plan.plan_sha256,)
    if item.state in {
        FederatedProjectionItemState.RECOVERY_REQUIRED,
        FederatedProjectionItemState.COMPENSATION_REQUIRED,
    }:
        candidates.append(
            _candidate(
                rank=len(candidates) + 1,
                action=CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME,
                scope="blocked_plan",
                plan_sha256s=blocked_plan,
                readiness=CompensationProposalReadiness.EVIDENCE_COLLECTION_READY,
                implementation=CompensationProposalImplementation.SUPPORTED_BOUNDED,
                mutates_provider=False,
                approval_required=False,
                recommended=True,
                reason_codes=(
                    "provider_outcome_or_target_state_requires_reconciliation",
                    "read_only_evidence_precedes_mutation",
                ),
                required_evidence=(
                    "fresh_provider_receipt_recovery",
                    "fresh_target_observation",
                    "plan_bound_observation_fingerprint",
                ),
            )
        )
    if item.state is FederatedProjectionItemState.COMPENSATION_REQUIRED:
        candidates.append(
            _candidate(
                rank=len(candidates) + 1,
                action=CompensationProposalAction.APPROVED_REAPPLY_SEALED_PLAN,
                scope="blocked_plan",
                plan_sha256s=blocked_plan,
                readiness=CompensationProposalReadiness.APPROVAL_REQUIRED,
                implementation=CompensationProposalImplementation.SUPPORTED_BOUNDED,
                mutates_provider=True,
                approval_required=True,
                recommended=False,
                reason_codes=(
                    "existing_plan_bound_compensation_executor",
                    "mutation_cannot_be_automatically_selected",
                ),
                required_evidence=(
                    "durable_worker_snapshot",
                    "fresh_approval_case",
                    "provider_not_committed_ruling",
                    "target_identity_match",
                ),
            )
        )

    customer_actions = (
        (
            CompensationProposalAction.CORRECTIVE_FORWARD,
            "federated_run",
            tuple(plan.plan_sha256 for plan in plans),
            "customer.compensation.corrective-forward.v1",
        ),
        (
            CompensationProposalAction.DELETE_TARGET,
            "blocked_plan",
            blocked_plan,
            "customer.compensation.delete.v1",
        ),
        (
            CompensationProposalAction.RESTORE_TARGET,
            "blocked_plan",
            blocked_plan,
            "customer.compensation.restore.v1",
        ),
    )
    committed = snapshot.committed_plan_sha256s
    if committed:
        customer_actions += (
            (
                CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX,
                "committed_prefix",
                committed,
                "customer.compensation.rollback.v1",
            ),
        )
    for action, scope, plan_sha256s, rule_id in customer_actions:
        candidates.append(
            _candidate(
                rank=len(candidates) + 1,
                action=action,
                scope=scope,
                plan_sha256s=plan_sha256s,
                readiness=CompensationProposalReadiness.CUSTOMER_RULE_REQUIRED,
                implementation=CompensationProposalImplementation.REQUIRES_CUSTOMER_RULE,
                mutates_provider=True,
                approval_required=True,
                recommended=False,
                reason_codes=(
                    "customer_business_semantics_not_registered",
                    "technical_baseline_cannot_authorize_mutation",
                ),
                required_evidence=(
                    "customer_rule_version",
                    "impact_scope_evidence",
                    "rollback_or_restore_receipt_contract",
                ),
                missing_customer_rule_ids=(rule_id,),
            )
        )

    # A bounded proposal is intentionally capped at six choices.
    candidates = candidates[:6]
    source_bindings = tuple(
        CompensationProposalSourceBinding(
            position=index,
            plan_sha256=sealed.plan_sha256,
            source_resource_version_ref=sealed.desired_state.source_resource_version_ref,
            source_content_sha256=sealed.desired_state.source_content_sha256,
            target_engine=sealed.target_engine.value,
            target_ref=sealed.target_ref,
            sealed_action=sealed.action,
        )
        for index, sealed in enumerate(plans)
    )
    recommended = next(
        (candidate.candidate_sha256 for candidate in candidates if candidate.recommended),
        None,
    )
    missing = tuple(
        sorted(
            {
                rule_id
                for candidate in candidates
                for rule_id in candidate.missing_customer_rule_ids
            }
        )
    )
    values = {
        "tenant_id": snapshot.tenant_id,
        "run_id": snapshot.run_id,
        "source_snapshot_sha256": snapshot.snapshot_sha256,
        "recovery_state": snapshot.state.value,
        "blocked_position": position,
        "blocked_plan_sha256": plan.plan_sha256,
        "dataset_scope": "chongqing_customer_dataset",
        "ontology": CompensationOntologyBinding(),
        "source_bindings": source_bindings,
        "candidates": tuple(candidates),
        "recommended_candidate_sha256": recommended,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
        "automatic_mutating_selection_allowed": False,
        "execution_allowed": False,
        "missing_customer_rule_ids": missing,
    }
    return FederatedProjectionCompensationProposal(
        **values,
        proposal_sha256=compensation_proposal_fingerprint(
            **{
                key: (
                    value.model_dump(mode="json")
                    if isinstance(value, BaseModel)
                    else [item.model_dump(mode="json") for item in value]
                    if isinstance(value, tuple)
                    and value
                    and isinstance(value[0], BaseModel)
                    else value
                )
                for key, value in values.items()
            }
        ),
    )


__all__ = [
    "CompensationOntologyBinding",
    "CompensationProposalAction",
    "CompensationProposalImplementation",
    "CompensationProposalReadiness",
    "CompensationProposalSourceBinding",
    "FederatedProjectionCompensationCandidate",
    "FederatedProjectionCompensationProposal",
    "FederatedProjectionCompensationProposalRequest",
    "FederatedProjectionCompensationProposalReadRequest",
    "FederatedProjectionCompensationProposalReadResponse",
    "FederatedProjectionCompensationProposalError",
    "build_federated_projection_compensation_proposal",
    "compensation_candidate_fingerprint",
    "compensation_proposal_fingerprint",
]
