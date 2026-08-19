from __future__ import annotations

import pytest

from data_agent.cross_store_projection_compensation_chongqing_source_lineage_execution import (
    execute_chongqing_federated_compensation_source_lineage_with_receipt_set,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage_reconciliation import (
    ChongqingFederatedCompensationSourceLineageReconciliationError,
    build_chongqing_federated_compensation_source_lineage_reconciliation_case,
)
from data_agent.cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
    FederatedCompensationRunProviderUnknownError,
    FederatedCompensationRunState,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.test_chongqing_compensation_execution_support import (
    _technical_execution_permit,
)
from data_agent.test_cross_store_projection_compensation_chongqing_source_lineage_execution import (
    _source_lineage_execution_inputs,
)
from data_agent.test_cross_store_projection_compensation_federated_receipt_execution import (
    _registry,
)


def test_partial_success_case_keeps_source_lineage_without_retrying_a_provider() -> None:
    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
    ) = _source_lineage_execution_inputs()
    registry, calls = _registry(materialization, fail_engine=ProjectionEngine.RDF)

    execution = execute_chongqing_federated_compensation_source_lineage_with_receipt_set(
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
        registry,
        execution_permit=_technical_execution_permit(
            intent,
            registry,
            purpose="reconciliation_fixture",
        ),
    )
    calls_before_case = list(calls)
    case = build_chongqing_federated_compensation_source_lineage_reconciliation_case(
        deployment_binding,
        source_lineage_set,
        execution,
    )

    assert calls == calls_before_case == [ProjectionEngine.POSTGIS, ProjectionEngine.RDF]
    assert case.federated_run_state is (
        FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION
    )
    assert tuple(item.outcome_class for item in case.items) == (
        "provider_mutation_committed",
        "provider_mutation_failed",
        "provider_not_attempted",
    )
    assert case.items[1].customer_source_roles == tuple(
        source.source_role for source in source_lineage_set.items[1].customer_sources
    )
    assert case.items[2].reconciliation_action == (
        "do_not_invoke_until_prior_position_reconciled"
    )
    assert case.provider_dispatch_performed is True
    assert case.checkpoint_authority_write_performed is False
    assert case.compensation_completion_recorded is False
    assert "receipt_document" not in str(case.model_dump(mode="json"))
    assert "provider_commit_ref" not in str(case.model_dump(mode="json"))


def test_unknown_case_requires_target_and_provider_outcome_observation_before_retry() -> None:
    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
    ) = _source_lineage_execution_inputs()
    calls: list[ProjectionEngine] = []

    def unknown(binding):
        calls.append(binding.target_engine)
        raise FederatedCompensationRunProviderUnknownError("provider_timeout_after_commit")

    registry = FederatedCompensationProviderInvokerRegistry(
        {engine: unknown for engine in ProjectionEngine}
    )
    execution = execute_chongqing_federated_compensation_source_lineage_with_receipt_set(
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
        registry,
        execution_permit=_technical_execution_permit(
            intent,
            registry,
            purpose="reconciliation_fixture",
        ),
    )
    case = build_chongqing_federated_compensation_source_lineage_reconciliation_case(
        deployment_binding,
        source_lineage_set,
        execution,
    )

    assert calls == [ProjectionEngine.POSTGIS]
    assert case.federated_run_state is (
        FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION
    )
    assert case.items[0].outcome_class == "provider_outcome_unknown"
    assert case.items[0].reconciliation_action == (
        "observe_provider_outcome_before_any_retry"
    )
    assert all(item.outcome_sha256 is None for item in case.items[1:])


def test_completed_run_cannot_be_misrepresented_as_a_reconciliation_case() -> None:
    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
    ) = _source_lineage_execution_inputs()
    registry, _ = _registry(materialization)
    execution = execute_chongqing_federated_compensation_source_lineage_with_receipt_set(
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
        registry,
        execution_permit=_technical_execution_permit(
            intent,
            registry,
            purpose="reconciliation_fixture",
        ),
    )

    with pytest.raises(
        ChongqingFederatedCompensationSourceLineageReconciliationError,
        match="requires a stopped registered run",
    ):
        build_chongqing_federated_compensation_source_lineage_reconciliation_case(
            deployment_binding,
            source_lineage_set,
            execution,
        )
