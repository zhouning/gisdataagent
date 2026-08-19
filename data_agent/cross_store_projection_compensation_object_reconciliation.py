"""Versioned object-store wrapper for Provider unknown reconciliation."""

from __future__ import annotations

from datetime import datetime

from .cross_store_projection_compensation_chongqing_source_lineage_reconciliation import (
    ChongqingFederatedCompensationSourceLineageReconciliationCase,
)
from .cross_store_projection_compensation_object_adapter import (
    FederatedProjectionCompensationObjectAdapterConfigurationError,
    FederatedProjectionCompensationObjectAdapterExecutionError,
    FederatedProjectionCompensationObjectAdapterValidationError,
    FederatedProjectionCompensationObjectMutationRequest,
    execute_federated_compensation_object_mutation,
)
from .cross_store_projection_compensation_provider_reconciliation import (
    ProviderReconciliationConfigurationError,
    ProviderReconciliationConflictError,
    ProviderReconciliationError,
    ProviderReconciliationExecutionError,
    ProviderReconciliationObservation,
    ProviderReconciliationResumeResult,
    ProviderReconciliationValidationError,
    observe_provider_unknown_outcome,
    resume_provider_unknown_outcome,
)
from .cross_store_projection_consistency import ProjectionEngine
from .object_projection_executor import (
    ObjectProjectionConfigurationError,
    ObjectProjectionExecutionError,
    ObjectProjectionRepairExecutor,
    ObjectProjectionValidationError,
)

FederatedProjectionCompensationObjectReconciliationError = ProviderReconciliationError
FederatedProjectionCompensationObjectReconciliationValidationError = (
    ProviderReconciliationValidationError
)
FederatedProjectionCompensationObjectReconciliationConfigurationError = (
    ProviderReconciliationConfigurationError
)
FederatedProjectionCompensationObjectReconciliationExecutionError = (
    ProviderReconciliationExecutionError
)
FederatedProjectionCompensationObjectReconciliationConflictError = (
    ProviderReconciliationConflictError
)
FederatedProjectionCompensationObjectReconciliationObservation = (
    ProviderReconciliationObservation
)
FederatedProjectionCompensationObjectResumeResult = ProviderReconciliationResumeResult

_VALIDATION_ERRORS = (
    ObjectProjectionValidationError,
    FederatedProjectionCompensationObjectAdapterValidationError,
)
_CONFIGURATION_ERRORS = (
    ObjectProjectionConfigurationError,
    FederatedProjectionCompensationObjectAdapterConfigurationError,
)
_EXECUTION_ERRORS = (
    ObjectProjectionExecutionError,
    FederatedProjectionCompensationObjectAdapterExecutionError,
)


def _recover(executor: ObjectProjectionRepairExecutor, plan):
    return executor.recover_receipt(plan)


def _observe(executor: ObjectProjectionRepairExecutor, target):
    return executor.observe(target)


def _execute(
    request: FederatedProjectionCompensationObjectMutationRequest,
    executor: ObjectProjectionRepairExecutor,
):
    return execute_federated_compensation_object_mutation(request, executor=executor)


def observe_federated_compensation_object_unknown_outcome(
    request: FederatedProjectionCompensationObjectMutationRequest,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    *,
    executor: ObjectProjectionRepairExecutor,
    reconciled_by: str,
    reconciled_at: datetime,
) -> FederatedProjectionCompensationObjectReconciliationObservation:
    """Read version/metadata receipt evidence without retrying the object mutation."""

    if not isinstance(executor, ObjectProjectionRepairExecutor):
        raise ProviderReconciliationConfigurationError(
            "object reconciliation requires the governed object executor"
        )
    return observe_provider_unknown_outcome(
        request,
        reconciliation_case,
        executor=executor,
        engine=ProjectionEngine.OBJECT_STORE,
        provider="s3_object_store",
        recover_receipt=_recover,
        observe_target=_observe,
        validation_errors=_VALIDATION_ERRORS,
        configuration_errors=_CONFIGURATION_ERRORS,
        execution_errors=_EXECUTION_ERRORS,
        reconciled_by=reconciled_by,
        reconciled_at=reconciled_at,
    )


def resume_federated_compensation_object_unknown_outcome(
    request: FederatedProjectionCompensationObjectMutationRequest,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    safe_observation: FederatedProjectionCompensationObjectReconciliationObservation,
    *,
    executor: ObjectProjectionRepairExecutor,
    resumed_by: str,
    resumed_at: datetime,
) -> FederatedProjectionCompensationObjectResumeResult:
    """Invoke object mutation only while a fresh observation remains safe."""

    if not isinstance(executor, ObjectProjectionRepairExecutor):
        raise ProviderReconciliationConfigurationError(
            "object reconciliation requires the governed object executor"
        )
    return resume_provider_unknown_outcome(
        request,
        reconciliation_case,
        safe_observation,
        executor=executor,
        engine=ProjectionEngine.OBJECT_STORE,
        provider="s3_object_store",
        recover_receipt=_recover,
        observe_target=_observe,
        execute_mutation=_execute,
        validation_errors=_VALIDATION_ERRORS,
        configuration_errors=_CONFIGURATION_ERRORS,
        execution_errors=_EXECUTION_ERRORS,
        resumed_by=resumed_by,
        resumed_at=resumed_at,
    )


__all__ = [
    "FederatedProjectionCompensationObjectReconciliationConfigurationError",
    "FederatedProjectionCompensationObjectReconciliationConflictError",
    "FederatedProjectionCompensationObjectReconciliationError",
    "FederatedProjectionCompensationObjectReconciliationExecutionError",
    "FederatedProjectionCompensationObjectReconciliationObservation",
    "FederatedProjectionCompensationObjectReconciliationValidationError",
    "FederatedProjectionCompensationObjectResumeResult",
    "observe_federated_compensation_object_unknown_outcome",
    "resume_federated_compensation_object_unknown_outcome",
]
