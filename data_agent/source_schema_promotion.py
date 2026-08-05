"""Fail-closed promotion decisions for observed source schema revisions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .platform_contracts import ApprovalCase, ApprovalCaseStatus, build_resource_urn
from .source_schema_drift_ledger import PersistedSchemaDrift, SchemaDriftStatus


class SourceSchemaPromotionBlockedError(RuntimeError):
    """A source schema revision has not satisfied its governance lifecycle."""

    def __init__(self, decision: SourceSchemaPromotionDecision) -> None:
        super().__init__(f"source schema promotion blocked: {decision.reason}")
        self.decision = decision


class SourceSchemaPromotionDecision(BaseModel):
    """Deterministic admission result for one immutable schema drift event."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal["gda.source_schema_promotion_decision.v1"] = Field(
        default="gda.source_schema_promotion_decision.v1",
        alias="schema",
    )
    drift_event_id: str
    source_id: str
    breaking: bool
    drift_status: SchemaDriftStatus
    allowed: bool
    reason: str
    approval_case_ref: str | None = None
    approval_status: ApprovalCaseStatus | None = None
    approval_case_binding_valid: bool | None = None

    @model_validator(mode="after")
    def _coherent_decision(self) -> SourceSchemaPromotionDecision:
        if self.allowed != (self.reason == "schema_drift_reconciled"):
            raise ValueError("promotion allowance must require reconciled schema drift")
        if self.approval_case_ref is None:
            if self.approval_status is not None or self.approval_case_binding_valid is not None:
                raise ValueError("approval evidence must be present together")
        elif self.approval_status is None or self.approval_case_binding_valid is None:
            raise ValueError("approval evidence must be present together")
        return self


def evaluate_source_schema_promotion(
    drift: PersistedSchemaDrift,
    *,
    approval_case: ApprovalCase | None = None,
) -> SourceSchemaPromotionDecision:
    """Allow only reconciled drift; pending or invalid approval evidence fails closed."""

    approval_case_ref = None
    approval_status = None
    binding_valid = None
    if approval_case is not None:
        approval_case_ref = approval_case.approval_case_ref
        approval_status = approval_case.status
        binding_valid = (
            approval_case.tenant_id == drift.tenant_id
            and approval_case.target_resource_urn
            == build_resource_urn(
                drift.tenant_id,
                "schema_drift",
                drift.drift_event_id,
            )
            and approval_case.target_fingerprint == drift.drift_event_id
            and approval_case.action == "source_schema_drift.reconcile"
        )

    if binding_valid is False:
        reason = "approval_case_binding_invalid"
    elif drift.status is SchemaDriftStatus.RECONCILED:
        if not drift.breaking or approval_status is ApprovalCaseStatus.APPROVED:
            reason = "schema_drift_reconciled"
        elif approval_case is None:
            reason = "approval_case_required"
        else:
            reason = "approval_case_not_approved"
    elif drift.status is SchemaDriftStatus.REJECTED:
        reason = "schema_drift_rejected"
    elif drift.breaking and approval_case is None:
        reason = "approval_case_required"
    elif (
        drift.breaking
        and drift.status is SchemaDriftStatus.APPROVAL_REQUIRED
        and approval_status is ApprovalCaseStatus.PENDING
    ):
        reason = "breaking_schema_drift_pending_approval"
    else:
        reason = "schema_drift_not_reconciled"

    return SourceSchemaPromotionDecision(
        drift_event_id=drift.drift_event_id,
        source_id=drift.source_id,
        breaking=drift.breaking,
        drift_status=drift.status,
        allowed=reason == "schema_drift_reconciled",
        reason=reason,
        approval_case_ref=approval_case_ref,
        approval_status=approval_status,
        approval_case_binding_valid=binding_valid,
    )


def require_source_schema_promotion(
    drift: PersistedSchemaDrift,
    *,
    approval_case: ApprovalCase | None = None,
) -> SourceSchemaPromotionDecision:
    """Return an allowed decision or raise with the complete denied decision."""

    decision = evaluate_source_schema_promotion(
        drift,
        approval_case=approval_case,
    )
    if not decision.allowed:
        raise SourceSchemaPromotionBlockedError(decision)
    return decision
