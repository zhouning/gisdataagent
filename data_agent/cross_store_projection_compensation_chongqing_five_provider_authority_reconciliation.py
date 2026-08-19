"""Reconcile an incomplete Chongqing five-Provider authority attempt.

The Provider run and its 5/5 receipt set are immutable inputs.  Recovery only
re-reads checkpoint authority, idempotently records the same exact checkpoint
requests, and records completion when all five checkpoints are current.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .cross_store_projection_authority import PostgresProjectionCheckpointAuthority
from .cross_store_projection_compensation_checkpoint_writer import (
    ProjectionCheckpointAuthorityWriter,
)
from .cross_store_projection_compensation_chongqing_five_provider_authority import (
    ChongqingFederatedCompensationFiveProviderAuthorityResult,
    CompensationCompletionAuthority,
    record_chongqing_federated_compensation_five_provider_authority,
)
from .cross_store_projection_compensation_chongqing_five_provider_execution import (
    ChongqingFederatedCompensationFiveProviderExecutionResult,
    ChongqingFederatedCompensationFiveProviderRequestBundle,
)
from .cross_store_projection_compensation_completion_authority import (
    PostgresFederatedProjectionCompensationCompletionAuthority,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_consistency import (
    ProjectionRepairPlan,
    ProjectionTargetObservation,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class ChongqingFiveProviderAuthorityReconciliationError(ValueError):
    """An authority attempt cannot safely be resumed or closed."""


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


ReconciliationState = Literal[
    "checkpoint_authority_reconciliation_completed",
    "checkpoint_authority_reconciliation_still_pending",
]


class ChongqingFiveProviderAuthorityReconciliationResult(_FrozenModel):
    """Sealed relationship between an incomplete attempt and its recovery run."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-five-provider-authority-reconciliation-result.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    prior_authority_result_sha256: Sha256
    prior_authority_record_set_sha256: Sha256
    recovery_authority_result: ChongqingFederatedCompensationFiveProviderAuthorityResult
    prior_attempted_positions: tuple[int, ...]
    prior_uncertain_positions: tuple[int, ...]
    authority_current_replay_positions: tuple[int, ...]
    recovery_recorded_positions: tuple[int, ...]
    reconciliation_state: ReconciliationState
    checkpoint_reconciliation_performed: Literal[True] = True
    compensation_completion_recorded: bool
    provider_execution_repeated: Literal[False] = False
    cross_store_transaction_performed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFiveProviderAuthorityReconciliationResult:
        recovery = self.recovery_authority_result
        for positions in (
            self.prior_attempted_positions,
            self.prior_uncertain_positions,
            self.authority_current_replay_positions,
            self.recovery_recorded_positions,
        ):
            if positions != tuple(sorted(set(positions))):
                raise ValueError("authority reconciliation positions must be unique and ordered")
        if (
            recovery.tenant_id != self.tenant_id
            or recovery.run_id != self.run_id
            or not self.checkpoint_reconciliation_performed
            or self.provider_execution_repeated
            or self.cross_store_transaction_performed
        ):
            raise ValueError("authority reconciliation result chain differs")
        completed = recovery.authority_state != (
            "checkpoint_authority_records_incomplete_pending_reconciliation"
        )
        if completed != self.compensation_completion_recorded:
            raise ValueError("authority reconciliation completion state differs")
        expected_state = (
            "checkpoint_authority_reconciliation_completed"
            if completed
            else "checkpoint_authority_reconciliation_still_pending"
        )
        if self.reconciliation_state != expected_state:
            raise ValueError("authority reconciliation state is inconsistent")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("authority reconciliation result fingerprint is invalid")
        return self


def _validated_inputs(
    prior_result: ChongqingFederatedCompensationFiveProviderAuthorityResult,
    execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
    final_observations: tuple[ProjectionTargetObservation, ...],
) -> tuple[
    ChongqingFederatedCompensationFiveProviderAuthorityResult,
    ChongqingFederatedCompensationFiveProviderExecutionResult,
    ChongqingFederatedCompensationFiveProviderRequestBundle,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    tuple[ProjectionRepairPlan, ...],
    tuple[ProjectionTargetObservation, ...],
]:
    try:
        return (
            ChongqingFederatedCompensationFiveProviderAuthorityResult.model_validate(
                prior_result.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationFiveProviderExecutionResult.model_validate(
                execution_result.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationFiveProviderRequestBundle.model_validate(
                request_bundle.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderPlanSet.model_validate(
                plan_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            ),
            tuple(
                ProjectionRepairPlan.model_validate(plan.model_dump(mode="python"))
                for plan in repair_plans
            ),
            tuple(
                ProjectionTargetObservation.model_validate(
                    observation.model_dump(mode="python")
                )
                for observation in final_observations
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFiveProviderAuthorityReconciliationError(
            "authority reconciliation input violates a sealed contract"
        ) from exc


def _target_key(observation: ProjectionTargetObservation) -> tuple[str, str, str, str]:
    return (
        observation.tenant_id,
        observation.projection_id,
        observation.target_engine.value,
        observation.target_ref,
    )


def _assert_same_attempt(
    prior_result: ChongqingFederatedCompensationFiveProviderAuthorityResult,
    execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
    final_observations: tuple[ProjectionTargetObservation, ...],
    *,
    prepared_by: str,
    writer_subject: str,
    prepared_at: datetime,
    updated_at: datetime,
) -> None:
    if (
        prior_result.authority_state
        != "checkpoint_authority_records_incomplete_pending_reconciliation"
        or prior_result.compensation_completion_recorded
        or prior_result.completion_receipt is not None
        or prior_result.execution_result_sha256 != execution_result.result_sha256
        or prior_result.request_bundle_sha256 != request_bundle.request_bundle_sha256
        or prior_result.tenant_id != execution_result.tenant_id
        or prior_result.run_id != execution_result.run_id
        or prior_result.admission_request.plan_set != plan_set
        or prior_result.admission_request.materialization != materialization
        or prior_result.admission_request.repair_plans != repair_plans
        or prior_result.write_request_set.updated_by != writer_subject
        or prior_result.write_request_set.updated_at != updated_at
    ):
        raise ChongqingFiveProviderAuthorityReconciliationError(
            "authority reconciliation must resume the same incomplete sealed attempt"
        )
    if any(
        intent.prepared_by != prepared_by or intent.prepared_at != prepared_at
        for intent in prior_result.write_intent_set.intents
    ):
        raise ChongqingFiveProviderAuthorityReconciliationError(
            "authority reconciliation preparation identity or timestamp drifted"
        )

    expected_observations = {
        _target_key(request.final_observation): request.final_observation
        for request in prior_result.write_request_set.requests
    }
    supplied_observations = {
        _target_key(observation): observation for observation in final_observations
    }
    if (
        len(supplied_observations) != len(final_observations)
        or supplied_observations != expected_observations
    ):
        raise ChongqingFiveProviderAuthorityReconciliationError(
            "authority reconciliation final observations drifted"
        )


def _result(
    prior_result: ChongqingFederatedCompensationFiveProviderAuthorityResult,
    recovery_result: ChongqingFederatedCompensationFiveProviderAuthorityResult,
) -> ChongqingFiveProviderAuthorityReconciliationResult:
    prior_attempted = tuple(
        record.position for record in prior_result.authority_record_set.records
    )
    prior_uncertain = tuple(
        record.position
        for record in prior_result.authority_record_set.records
        if record.record_state == "unknown"
    )
    replay_positions = tuple(
        snapshot.position
        for snapshot in recovery_result.authority_read_preview.snapshots
        if snapshot.authority_current_state == "requested_checkpoint_replay"
    )
    recorded_positions = tuple(
        record.position
        for record in recovery_result.authority_record_set.records
        if record.record_state == "recorded"
    )
    completed = recovery_result.authority_state != (
        "checkpoint_authority_records_incomplete_pending_reconciliation"
    )
    values = {
        "tenant_id": prior_result.tenant_id,
        "run_id": prior_result.run_id,
        "prior_authority_result_sha256": prior_result.result_sha256,
        "prior_authority_record_set_sha256": (
            prior_result.authority_record_set.record_set_sha256
        ),
        "recovery_authority_result": recovery_result,
        "prior_attempted_positions": prior_attempted,
        "prior_uncertain_positions": prior_uncertain,
        "authority_current_replay_positions": replay_positions,
        "recovery_recorded_positions": recorded_positions,
        "reconciliation_state": (
            "checkpoint_authority_reconciliation_completed"
            if completed
            else "checkpoint_authority_reconciliation_still_pending"
        ),
        "checkpoint_reconciliation_performed": True,
        "compensation_completion_recorded": completed,
        "provider_execution_repeated": False,
        "cross_store_transaction_performed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFiveProviderAuthorityReconciliationResult(
        **values,
        result_sha256=_fingerprint(
            ChongqingFiveProviderAuthorityReconciliationResult.schema_id,
            values,
            "result_sha256",
        ),
    )


def reconcile_chongqing_five_provider_authority(
    prior_result: ChongqingFederatedCompensationFiveProviderAuthorityResult,
    execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
    final_observations: tuple[ProjectionTargetObservation, ...],
    checkpoint_authority: ProjectionCheckpointAuthorityWriter,
    completion_authority: CompensationCompletionAuthority,
    *,
    prepared_by: str,
    writer_subject: str,
    completed_by: str,
    prepared_at: datetime,
    updated_at: datetime,
) -> ChongqingFiveProviderAuthorityReconciliationResult:
    """Resume the exact incomplete authority attempt without invoking Providers."""

    (
        prior_result,
        execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
        final_observations,
    ) = _validated_inputs(
        prior_result,
        execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
        final_observations,
    )
    _assert_same_attempt(
        prior_result,
        execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
        final_observations,
        prepared_by=prepared_by,
        writer_subject=writer_subject,
        prepared_at=prepared_at,
        updated_at=updated_at,
    )
    recovery_result = record_chongqing_federated_compensation_five_provider_authority(
        execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
        final_observations,
        checkpoint_authority,
        completion_authority,
        prepared_by=prepared_by,
        writer_subject=writer_subject,
        completed_by=completed_by,
        prepared_at=prepared_at,
        updated_at=updated_at,
    )
    return _result(prior_result, recovery_result)


def reconcile_chongqing_five_provider_postgres_authority(
    prior_result: ChongqingFederatedCompensationFiveProviderAuthorityResult,
    execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
    final_observations: tuple[ProjectionTargetObservation, ...],
    engine: Any,
    *,
    prepared_by: str,
    writer_subject: str,
    completed_by: str,
    prepared_at: datetime,
    updated_at: datetime,
) -> ChongqingFiveProviderAuthorityReconciliationResult:
    """Reconcile through the PostgreSQL tenant-RLS authority implementations."""

    return reconcile_chongqing_five_provider_authority(
        prior_result,
        execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
        final_observations,
        PostgresProjectionCheckpointAuthority(engine),
        PostgresFederatedProjectionCompensationCompletionAuthority(
            execution_result.tenant_id,
            engine,
        ),
        prepared_by=prepared_by,
        writer_subject=writer_subject,
        completed_by=completed_by,
        prepared_at=prepared_at,
        updated_at=updated_at,
    )


__all__ = [
    "ChongqingFiveProviderAuthorityReconciliationError",
    "ChongqingFiveProviderAuthorityReconciliationResult",
    "reconcile_chongqing_five_provider_authority",
    "reconcile_chongqing_five_provider_postgres_authority",
]
