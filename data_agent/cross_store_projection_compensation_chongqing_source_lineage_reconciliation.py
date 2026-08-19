"""Prepare hash-only Chongqing source-lineage evidence for a stopped federated run.

When a federated run stops after a Provider failure or an unknown outcome, the
operator needs to know which sealed deployment positions and Chongqing customer
source selections are affected.  This module prepares that evidence without
retrying a Provider, reading a target, writing checkpoint authority, or
recording compensation completion.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_chongqing_deployment import (
    ChongqingFederatedCompensationDeploymentBinding,
)
from .cross_store_projection_compensation_chongqing_source_lineage import (
    ChongqingFederatedCompensationSourceLineageSet,
)
from .cross_store_projection_compensation_chongqing_source_lineage_execution import (
    ChongqingFederatedCompensationSourceLineageExecutionResult,
)
from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderOutcomeStatus,
    FederatedCompensationRunState,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class ChongqingFederatedCompensationSourceLineageReconciliationError(ValueError):
    """A stopped Chongqing source-lineage run cannot safely form triage evidence."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


OutcomeClass = Literal[
    "provider_mutation_committed",
    "provider_idempotent_replay",
    "provider_outcome_unknown",
    "provider_mutation_failed",
    "provider_not_attempted",
]
ReconciliationAction = Literal[
    "preserve_sealed_receipt_evidence",
    "observe_provider_outcome_before_any_retry",
    "inspect_failure_before_any_retry",
    "do_not_invoke_until_prior_position_reconciled",
]


class ChongqingFederatedCompensationSourceLineageReconciliationItem(_FrozenModel):
    """One Provider position summarized for operator reconciliation."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-source-lineage-reconciliation-item.v1"
    )
    position: int = Field(ge=0, le=31)
    deployment_item_sha256: Sha256
    lineage_item_sha256: Sha256
    source_plan_sha256: Sha256
    provider_plan_sha256: Sha256
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    customer_source_roles: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=32)
    outcome_class: OutcomeClass
    outcome_sha256: Sha256 | None = None
    reconciliation_action: ReconciliationAction
    item_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationSourceLineageReconciliationItem:
        if self.customer_source_roles != tuple(sorted(set(self.customer_source_roles))):
            raise ValueError("reconciliation customer source roles must be unique and sorted")
        expected_action = {
            "provider_mutation_committed": "preserve_sealed_receipt_evidence",
            "provider_idempotent_replay": "preserve_sealed_receipt_evidence",
            "provider_outcome_unknown": "observe_provider_outcome_before_any_retry",
            "provider_mutation_failed": "inspect_failure_before_any_retry",
            "provider_not_attempted": "do_not_invoke_until_prior_position_reconciled",
        }[self.outcome_class]
        if self.reconciliation_action != expected_action:
            raise ValueError("reconciliation action differs from Provider outcome class")
        if (self.outcome_class == "provider_not_attempted") != (
            self.outcome_sha256 is None
        ):
            raise ValueError("reconciliation outcome fingerprint presence is inconsistent")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"item_sha256"}),
            "item_sha256",
        )
        if self.item_sha256 != expected:
            raise ValueError("source lineage reconciliation item fingerprint is invalid")
        return self


class ChongqingFederatedCompensationSourceLineageReconciliationCase(_FrozenModel):
    """A non-mutating, complete-position reconciliation or operator-triage case."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-source-lineage-reconciliation-case.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    deployment_binding_sha256: Sha256
    source_lineage_set_sha256: Sha256
    source_lineage_execution_result_sha256: Sha256
    federated_run_result_sha256: Sha256
    federated_run_state: FederatedCompensationRunState
    items: tuple[ChongqingFederatedCompensationSourceLineageReconciliationItem, ...] = Field(
        min_length=1,
        max_length=32,
    )
    case_state: Literal["source_lineage_reconciliation_or_operator_required"] = (
        "source_lineage_reconciliation_or_operator_required"
    )
    provider_dispatch_performed: Literal[True] = True
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    case_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationSourceLineageReconciliationCase:
        positions = tuple(item.position for item in self.items)
        outcome_classes = tuple(item.outcome_class for item in self.items)
        if positions != tuple(range(len(self.items))):
            raise ValueError(
                "source lineage reconciliation positions must be contiguous and ordered"
            )
        if not any(
            outcome in {"provider_outcome_unknown", "provider_mutation_failed"}
            for outcome in outcome_classes
        ):
            raise ValueError("reconciliation case lacks a stopped Provider outcome")
        if self.federated_run_state not in {
            FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION,
            FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION,
            FederatedCompensationRunState.FAILED_CLOSED,
        }:
            raise ValueError("reconciliation case must not contain a completed run")
        if (
            self.federated_run_state
            is FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION
        ):
            if "provider_outcome_unknown" not in outcome_classes:
                raise ValueError("unknown reconciliation case lacks an unknown outcome")
        elif (
            self.federated_run_state
            is FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION
        ):
            if (
                "provider_mutation_failed" not in outcome_classes
                or not any(
                    outcome
                    in {"provider_mutation_committed", "provider_idempotent_replay"}
                    for outcome in outcome_classes
                )
            ):
                raise ValueError("partial reconciliation case lacks success or failure evidence")
        elif (
            outcome_classes[0] != "provider_mutation_failed"
            or any(
                outcome != "provider_not_attempted" for outcome in outcome_classes[1:]
            )
        ):
            raise ValueError("failed-closed case must stop at the first Provider position")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"case_sha256"}),
            "case_sha256",
        )
        if self.case_sha256 != expected:
            raise ValueError("source lineage reconciliation case fingerprint is invalid")
        return self


def _validated_inputs(
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    source_lineage_set: ChongqingFederatedCompensationSourceLineageSet,
    execution_result: ChongqingFederatedCompensationSourceLineageExecutionResult,
) -> tuple[
    ChongqingFederatedCompensationDeploymentBinding,
    ChongqingFederatedCompensationSourceLineageSet,
    ChongqingFederatedCompensationSourceLineageExecutionResult,
]:
    try:
        return (
            ChongqingFederatedCompensationDeploymentBinding.model_validate(
                deployment_binding.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationSourceLineageSet.model_validate(
                source_lineage_set.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationSourceLineageExecutionResult.model_validate(
                execution_result.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationSourceLineageReconciliationError(
            "Chongqing source lineage reconciliation input violates a sealed contract"
        ) from exc


def _outcome_class(
    status: FederatedCompensationProviderOutcomeStatus,
) -> OutcomeClass:
    return {
        FederatedCompensationProviderOutcomeStatus.COMMITTED: (
            "provider_mutation_committed"
        ),
        FederatedCompensationProviderOutcomeStatus.REPLAYED: (
            "provider_idempotent_replay"
        ),
        FederatedCompensationProviderOutcomeStatus.UNKNOWN: "provider_outcome_unknown",
        FederatedCompensationProviderOutcomeStatus.FAILED: "provider_mutation_failed",
    }[status]


def _reconciliation_action(outcome_class: OutcomeClass) -> ReconciliationAction:
    return {
        "provider_mutation_committed": "preserve_sealed_receipt_evidence",
        "provider_idempotent_replay": "preserve_sealed_receipt_evidence",
        "provider_outcome_unknown": "observe_provider_outcome_before_any_retry",
        "provider_mutation_failed": "inspect_failure_before_any_retry",
        "provider_not_attempted": "do_not_invoke_until_prior_position_reconciled",
    }[outcome_class]


def build_chongqing_federated_compensation_source_lineage_reconciliation_case(
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    source_lineage_set: ChongqingFederatedCompensationSourceLineageSet,
    execution_result: ChongqingFederatedCompensationSourceLineageExecutionResult,
) -> ChongqingFederatedCompensationSourceLineageReconciliationCase:
    """Seal triage evidence for a stopped run without retrying any Provider."""

    deployment_binding, source_lineage_set, execution_result = _validated_inputs(
        deployment_binding,
        source_lineage_set,
        execution_result,
    )
    deployment_execution = execution_result.deployment_execution
    registered_execution = deployment_execution.registered_execution
    run_result = registered_execution.run_result
    if (
        source_lineage_set.tenant_id != deployment_binding.tenant_id
        or source_lineage_set.run_id != deployment_binding.run_id
        or source_lineage_set.deployment_binding_sha256
        != deployment_binding.deployment_binding_sha256
        or execution_result.tenant_id != deployment_binding.tenant_id
        or execution_result.run_id != deployment_binding.run_id
        or execution_result.deployment_binding_sha256
        != deployment_binding.deployment_binding_sha256
        or execution_result.source_lineage_set_sha256
        != source_lineage_set.source_lineage_set_sha256
        or deployment_execution.source_catalog_sha256
        != source_lineage_set.source_catalog_sha256
        or deployment_execution.field_mapping_set_sha256
        != source_lineage_set.field_mapping_set_sha256
    ):
        raise ChongqingFederatedCompensationSourceLineageReconciliationError(
            "Chongqing source lineage reconciliation evidence crosses sealed identities"
        )
    if (
        registered_execution.state.value
        != "reconciliation_or_operator_required"
        or run_result.state
        not in {
            FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION,
            FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION,
            FederatedCompensationRunState.FAILED_CLOSED,
        }
        or registered_execution.receipt_validation_set is not None
        or registered_execution.native_receipts_validated
    ):
        raise ChongqingFederatedCompensationSourceLineageReconciliationError(
            "Chongqing source lineage reconciliation requires a stopped registered run"
        )
    deployment_by_position = {
        item.position: item for item in deployment_binding.items
    }
    lineage_by_position = {item.position: item for item in source_lineage_set.items}
    outcome_by_position = {
        step.outcome.position: step.outcome for step in run_result.steps
    }
    expected_positions = tuple(item.position for item in deployment_binding.items)
    if (
        tuple(run_result.expected_positions) != expected_positions
        or set(lineage_by_position) != set(expected_positions)
        or len(outcome_by_position) != len(run_result.steps)
        or set(outcome_by_position) - set(expected_positions)
    ):
        raise ChongqingFederatedCompensationSourceLineageReconciliationError(
            "Chongqing source lineage reconciliation positions are incomplete"
        )
    items: list[ChongqingFederatedCompensationSourceLineageReconciliationItem] = []
    for position in expected_positions:
        deployment_item = deployment_by_position[position]
        lineage_item = lineage_by_position[position]
        outcome = outcome_by_position.get(position)
        if outcome is None:
            outcome_class: OutcomeClass = "provider_not_attempted"
            outcome_sha256: str | None = None
        else:
            if (
                outcome.source_plan_sha256 != deployment_item.source_plan_sha256
                or outcome.provider_plan_sha256 != deployment_item.provider_plan_sha256
                or outcome.provider_idempotency_key
                != deployment_item.provider_idempotency_key
            ):
                raise ChongqingFederatedCompensationSourceLineageReconciliationError(
                    "Provider outcome differs from its Chongqing deployment position"
                )
            outcome_class = _outcome_class(outcome.status)
            outcome_sha256 = outcome.outcome_sha256
        values = {
            "position": position,
            "deployment_item_sha256": deployment_item.item_sha256,
            "lineage_item_sha256": lineage_item.lineage_item_sha256,
            "source_plan_sha256": deployment_item.source_plan_sha256,
            "provider_plan_sha256": deployment_item.provider_plan_sha256,
            "target_engine": deployment_item.target_engine,
            "target_ref": deployment_item.target_ref,
            "customer_source_roles": tuple(
                source.source_role for source in lineage_item.customer_sources
            ),
            "outcome_class": outcome_class,
            "outcome_sha256": outcome_sha256,
            "reconciliation_action": _reconciliation_action(outcome_class),
        }
        items.append(
            ChongqingFederatedCompensationSourceLineageReconciliationItem(
                **values,
                item_sha256=_fingerprint(
                    ChongqingFederatedCompensationSourceLineageReconciliationItem.schema_id,
                    values,
                    "item_sha256",
                ),
            )
        )
    values = {
        "tenant_id": deployment_binding.tenant_id,
        "run_id": deployment_binding.run_id,
        "deployment_binding_sha256": deployment_binding.deployment_binding_sha256,
        "source_lineage_set_sha256": source_lineage_set.source_lineage_set_sha256,
        "source_lineage_execution_result_sha256": execution_result.result_sha256,
        "federated_run_result_sha256": run_result.result_sha256,
        "federated_run_state": run_result.state,
        "items": tuple(items),
        "case_state": "source_lineage_reconciliation_or_operator_required",
        "provider_dispatch_performed": True,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationSourceLineageReconciliationCase(
        **values,
        case_sha256=_fingerprint(
            ChongqingFederatedCompensationSourceLineageReconciliationCase.schema_id,
            values,
            "case_sha256",
        ),
    )


__all__ = [
    "ChongqingFederatedCompensationSourceLineageReconciliationCase",
    "ChongqingFederatedCompensationSourceLineageReconciliationError",
    "ChongqingFederatedCompensationSourceLineageReconciliationItem",
    "build_chongqing_federated_compensation_source_lineage_reconciliation_case",
]
