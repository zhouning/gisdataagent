"""RDF/Fuseki wrapper for the Provider unknown-outcome evidence contract."""

from __future__ import annotations

from datetime import datetime

from .cross_store_projection_compensation_chongqing_source_lineage_reconciliation import (
    ChongqingFederatedCompensationSourceLineageReconciliationCase,
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
from .cross_store_projection_compensation_rdf_adapter import (
    FederatedProjectionCompensationRDFAdapterConfigurationError,
    FederatedProjectionCompensationRDFAdapterExecutionError,
    FederatedProjectionCompensationRDFAdapterValidationError,
    FederatedProjectionCompensationRDFMutationRequest,
    execute_federated_compensation_rdf_mutation,
)
from .cross_store_projection_consistency import ProjectionEngine
from .rdf_projection_executor import (
    RDFProjectionConfigurationError,
    RDFProjectionExecutionError,
    RDFProjectionRepairExecutor,
    RDFProjectionValidationError,
)

FederatedProjectionCompensationRDFReconciliationError = ProviderReconciliationError
FederatedProjectionCompensationRDFReconciliationValidationError = (
    ProviderReconciliationValidationError
)
FederatedProjectionCompensationRDFReconciliationConfigurationError = (
    ProviderReconciliationConfigurationError
)
FederatedProjectionCompensationRDFReconciliationExecutionError = (
    ProviderReconciliationExecutionError
)
FederatedProjectionCompensationRDFReconciliationConflictError = (
    ProviderReconciliationConflictError
)
FederatedProjectionCompensationRDFReconciliationObservation = (
    ProviderReconciliationObservation
)
FederatedProjectionCompensationRDFResumeResult = ProviderReconciliationResumeResult

_VALIDATION_ERRORS = (
    RDFProjectionValidationError,
    FederatedProjectionCompensationRDFAdapterValidationError,
)
_CONFIGURATION_ERRORS = (
    RDFProjectionConfigurationError,
    FederatedProjectionCompensationRDFAdapterConfigurationError,
)
_EXECUTION_ERRORS = (
    RDFProjectionExecutionError,
    FederatedProjectionCompensationRDFAdapterExecutionError,
)


def _recover(executor: RDFProjectionRepairExecutor, plan):
    return executor.recover_receipt(plan)


def _observe(executor: RDFProjectionRepairExecutor, target):
    return executor.observe(target)


def _execute(
    request: FederatedProjectionCompensationRDFMutationRequest,
    executor: RDFProjectionRepairExecutor,
):
    return execute_federated_compensation_rdf_mutation(request, executor=executor)


def observe_federated_compensation_rdf_unknown_outcome(
    request: FederatedProjectionCompensationRDFMutationRequest,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    *,
    executor: RDFProjectionRepairExecutor,
    reconciled_by: str,
    reconciled_at: datetime,
) -> FederatedProjectionCompensationRDFReconciliationObservation:
    """Read Fuseki receipt-graph and target evidence without retrying."""

    if not isinstance(executor, RDFProjectionRepairExecutor):
        raise ProviderReconciliationConfigurationError(
            "RDF reconciliation requires the governed RDF executor"
        )
    return observe_provider_unknown_outcome(
        request,
        reconciliation_case,
        executor=executor,
        engine=ProjectionEngine.RDF,
        provider="rdf_fuseki",
        recover_receipt=_recover,
        observe_target=_observe,
        validation_errors=_VALIDATION_ERRORS,
        configuration_errors=_CONFIGURATION_ERRORS,
        execution_errors=_EXECUTION_ERRORS,
        reconciled_by=reconciled_by,
        reconciled_at=reconciled_at,
    )


def resume_federated_compensation_rdf_unknown_outcome(
    request: FederatedProjectionCompensationRDFMutationRequest,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    safe_observation: FederatedProjectionCompensationRDFReconciliationObservation,
    *,
    executor: RDFProjectionRepairExecutor,
    resumed_by: str,
    resumed_at: datetime,
) -> FederatedProjectionCompensationRDFResumeResult:
    """Invoke Fuseki only after a fresh observation remains safe to resume."""

    if not isinstance(executor, RDFProjectionRepairExecutor):
        raise ProviderReconciliationConfigurationError(
            "RDF reconciliation requires the governed RDF executor"
        )
    return resume_provider_unknown_outcome(
        request,
        reconciliation_case,
        safe_observation,
        executor=executor,
        engine=ProjectionEngine.RDF,
        provider="rdf_fuseki",
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
    "FederatedProjectionCompensationRDFReconciliationConfigurationError",
    "FederatedProjectionCompensationRDFReconciliationConflictError",
    "FederatedProjectionCompensationRDFReconciliationError",
    "FederatedProjectionCompensationRDFReconciliationExecutionError",
    "FederatedProjectionCompensationRDFReconciliationObservation",
    "FederatedProjectionCompensationRDFReconciliationValidationError",
    "FederatedProjectionCompensationRDFResumeResult",
    "observe_federated_compensation_rdf_unknown_outcome",
    "resume_federated_compensation_rdf_unknown_outcome",
]
