"""Spark/Iceberg wrapper for Provider unknown reconciliation."""

from __future__ import annotations

from datetime import datetime

from .cross_store_projection_compensation_chongqing_source_lineage_reconciliation import (
    ChongqingFederatedCompensationSourceLineageReconciliationCase,
)
from .cross_store_projection_compensation_lakehouse_adapter import (
    FederatedProjectionCompensationLakehouseAdapterConfigurationError,
    FederatedProjectionCompensationLakehouseAdapterExecutionError,
    FederatedProjectionCompensationLakehouseAdapterValidationError,
    FederatedProjectionCompensationLakehouseMutationRequest,
    execute_federated_compensation_lakehouse_mutation,
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
from .lakehouse_projection_executor import (
    LakehouseProjectionConfigurationError,
    LakehouseProjectionExecutionError,
    LakehouseProjectionRepairExecutor,
    LakehouseProjectionValidationError,
)

FederatedProjectionCompensationLakehouseReconciliationError = ProviderReconciliationError
FederatedProjectionCompensationLakehouseReconciliationValidationError = (
    ProviderReconciliationValidationError
)
FederatedProjectionCompensationLakehouseReconciliationConfigurationError = (
    ProviderReconciliationConfigurationError
)
FederatedProjectionCompensationLakehouseReconciliationExecutionError = (
    ProviderReconciliationExecutionError
)
FederatedProjectionCompensationLakehouseReconciliationConflictError = (
    ProviderReconciliationConflictError
)
FederatedProjectionCompensationLakehouseReconciliationObservation = (
    ProviderReconciliationObservation
)
FederatedProjectionCompensationLakehouseResumeResult = ProviderReconciliationResumeResult

_VALIDATION_ERRORS = (
    LakehouseProjectionValidationError,
    FederatedProjectionCompensationLakehouseAdapterValidationError,
)
_CONFIGURATION_ERRORS = (
    LakehouseProjectionConfigurationError,
    FederatedProjectionCompensationLakehouseAdapterConfigurationError,
)
_EXECUTION_ERRORS = (
    LakehouseProjectionExecutionError,
    FederatedProjectionCompensationLakehouseAdapterExecutionError,
)


def _recover(executor: LakehouseProjectionRepairExecutor, plan):
    return executor.recover_receipt(plan)


def _observe(executor: LakehouseProjectionRepairExecutor, target):
    return executor.observe(target)


def _execute(
    request: FederatedProjectionCompensationLakehouseMutationRequest,
    executor: LakehouseProjectionRepairExecutor,
):
    return execute_federated_compensation_lakehouse_mutation(request, executor=executor)


def observe_federated_compensation_lakehouse_unknown_outcome(
    request: FederatedProjectionCompensationLakehouseMutationRequest,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    *,
    executor: LakehouseProjectionRepairExecutor,
    reconciled_by: str,
    reconciled_at: datetime,
) -> FederatedProjectionCompensationLakehouseReconciliationObservation:
    """Read Iceberg snapshot-bound receipt evidence without replaying."""

    if not isinstance(executor, LakehouseProjectionRepairExecutor):
        raise ProviderReconciliationConfigurationError(
            "Lakehouse reconciliation requires the governed Iceberg executor"
        )
    return observe_provider_unknown_outcome(
        request,
        reconciliation_case,
        executor=executor,
        engine=ProjectionEngine.LAKEHOUSE,
        provider="spark_iceberg",
        recover_receipt=_recover,
        observe_target=_observe,
        validation_errors=_VALIDATION_ERRORS,
        configuration_errors=_CONFIGURATION_ERRORS,
        execution_errors=_EXECUTION_ERRORS,
        reconciled_by=reconciled_by,
        reconciled_at=reconciled_at,
    )


def resume_federated_compensation_lakehouse_unknown_outcome(
    request: FederatedProjectionCompensationLakehouseMutationRequest,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    safe_observation: FederatedProjectionCompensationLakehouseReconciliationObservation,
    *,
    executor: LakehouseProjectionRepairExecutor,
    resumed_by: str,
    resumed_at: datetime,
) -> FederatedProjectionCompensationLakehouseResumeResult:
    """Invoke Iceberg mutation only while fresh snapshot evidence remains safe."""

    if not isinstance(executor, LakehouseProjectionRepairExecutor):
        raise ProviderReconciliationConfigurationError(
            "Lakehouse reconciliation requires the governed Iceberg executor"
        )
    return resume_provider_unknown_outcome(
        request,
        reconciliation_case,
        safe_observation,
        executor=executor,
        engine=ProjectionEngine.LAKEHOUSE,
        provider="spark_iceberg",
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
    "FederatedProjectionCompensationLakehouseReconciliationConfigurationError",
    "FederatedProjectionCompensationLakehouseReconciliationConflictError",
    "FederatedProjectionCompensationLakehouseReconciliationError",
    "FederatedProjectionCompensationLakehouseReconciliationExecutionError",
    "FederatedProjectionCompensationLakehouseReconciliationObservation",
    "FederatedProjectionCompensationLakehouseReconciliationValidationError",
    "FederatedProjectionCompensationLakehouseResumeResult",
    "observe_federated_compensation_lakehouse_unknown_outcome",
    "resume_federated_compensation_lakehouse_unknown_outcome",
]
