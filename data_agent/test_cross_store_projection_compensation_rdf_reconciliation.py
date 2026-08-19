from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_agent.cross_store_projection_compensation_chongqing_deployment import (
    build_chongqing_federated_compensation_deployment_binding,
    build_chongqing_federated_compensation_source_catalog,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage import (
    build_chongqing_federated_compensation_source_lineage_set,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage_execution import (
    execute_chongqing_federated_compensation_source_lineage_with_receipt_set,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage_reconciliation import (
    build_chongqing_federated_compensation_source_lineage_reconciliation_case,
)
from data_agent.cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
)
from data_agent.cross_store_projection_compensation_rdf_reconciliation import (
    FederatedProjectionCompensationRDFReconciliationConflictError,
    FederatedProjectionCompensationRDFReconciliationValidationError,
    observe_federated_compensation_rdf_unknown_outcome,
    resume_federated_compensation_rdf_unknown_outcome,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.rdf_projection_executor import (
    RDFProjectionRepairExecutor,
    RDFProjectionTargetRegistry,
)
from data_agent.test_chongqing_compensation_execution_support import (
    _technical_execution_permit,
)
from data_agent.test_cross_store_projection_compensation_federated_receipt_execution import (
    _NativeResult,
)
from data_agent.test_cross_store_projection_compensation_provider_receipt import (
    _receipt_document,
)
from data_agent.test_cross_store_projection_compensation_rdf_adapter import _chain
from data_agent.test_rdf_projection_executor import _provider_state, _transport

NOW = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)


def _unknown_case(chain):
    source_catalog = build_chongqing_federated_compensation_source_catalog()
    deployment_binding = build_chongqing_federated_compensation_deployment_binding(
        chain.intent,
        chain.plan_set,
        chain.materialization,
        source_catalog,
    )
    source_lineage_set = build_chongqing_federated_compensation_source_lineage_set(
        source_catalog,
        deployment_binding,
        {
            item.position: (source_catalog.sources[item.position].source_role,)
            for item in deployment_binding.items
        },
    )
    by_position = {item.position: item for item in chain.materialization.bindings}

    def invoke(binding):
        if binding.target_engine is ProjectionEngine.RDF:
            raise RuntimeError("provider_timeout_after_commit")
        materialized = by_position[binding.position]
        return _NativeResult(
            tenant_id=binding.tenant_id,
            run_id=binding.run_id,
            position=binding.position,
            materialization_binding_sha256=binding.materialization_binding_sha256,
            provider_plan_sha256=binding.provider_plan_sha256,
            provider_idempotency_key=binding.provider_idempotency_key,
            provider_execution_status="provider_mutation_committed",
            provider_execution_performed_by_adapter=True,
            checkpoint_authority_write_performed_by_adapter=False,
            compensation_completion_recorded_by_adapter=False,
            receipt=_receipt_document(materialized),
        )

    registry = FederatedCompensationProviderInvokerRegistry(
        {engine: invoke for engine in ProjectionEngine}
    )
    execution = execute_chongqing_federated_compensation_source_lineage_with_receipt_set(
        chain.intent,
        chain.plan_set,
        chain.materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
        registry,
        execution_permit=_technical_execution_permit(
            chain.intent,
            registry,
            purpose="reconciliation_fixture",
        ),
    )
    return build_chongqing_federated_compensation_source_lineage_reconciliation_case(
        deployment_binding,
        source_lineage_set,
        execution,
    )


def test_rdf_unknown_outcome_reconciles_safe_resume_drift_and_persisted_receipt(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(tmp_path, monkeypatch)
    case = _unknown_case(chain)
    state = _provider_state()
    executor = RDFProjectionRepairExecutor(
        RDFProjectionTargetRegistry((chain.target,)),
        transport=_transport(state),
    )

    safe = observe_federated_compensation_rdf_unknown_outcome(
        chain.request,
        case,
        executor=executor,
        reconciled_by="workload:rdf-reconciler",
        reconciled_at=NOW,
    )
    assert safe.decision == "provider_not_committed_safe_to_resume"
    resumed = resume_federated_compensation_rdf_unknown_outcome(
        chain.request,
        case,
        safe,
        executor=executor,
        resumed_by="workload:rdf-reconciler",
        resumed_at=NOW,
    )
    assert resumed.resume_state == "provider_resumed_with_new_commit"
    assert resumed.reconciled_provider_outcome.status.value == (
        "provider_mutation_committed"
    )
    assert state["update_calls"] == 1

    with pytest.raises(FederatedProjectionCompensationRDFReconciliationValidationError):
        resume_federated_compensation_rdf_unknown_outcome(
            chain.request,
            case,
            resumed,  # type: ignore[arg-type]
            executor=executor,
            resumed_by="workload:rdf-reconciler",
            resumed_at=NOW,
        )

    # A fresh case with a target but no receipt is indeterminate, and a stale
    # safe observation cannot authorize a later mutation.
    state = _provider_state()
    executor = RDFProjectionRepairExecutor(
        RDFProjectionTargetRegistry((chain.target,)),
        transport=_transport(state),
    )
    stale_safe = observe_federated_compensation_rdf_unknown_outcome(
        chain.request,
        case,
        executor=executor,
        reconciled_by="workload:rdf-reconciler",
        reconciled_at=NOW,
    )
    turtle, _, _ = executor._load_package(chain.target)
    state["graph"] = turtle
    with pytest.raises(
        FederatedProjectionCompensationRDFReconciliationConflictError,
        match="state changed after observation",
    ):
        resume_federated_compensation_rdf_unknown_outcome(
            chain.request,
            case,
            stale_safe,
            executor=executor,
            resumed_by="workload:rdf-reconciler",
            resumed_at=NOW,
        )
    indeterminate = observe_federated_compensation_rdf_unknown_outcome(
        chain.request,
        case,
        executor=executor,
        reconciled_by="workload:rdf-reconciler",
        reconciled_at=NOW,
    )
    assert indeterminate.decision == "indeterminate_operator_required"
    assert indeterminate.reason_code == "receipt_absent_target_differs_from_sealed_observation"

    state = _provider_state()
    executor = RDFProjectionRepairExecutor(
        RDFProjectionTargetRegistry((chain.target,)),
        transport=_transport(state),
    )
    executor.execute(chain.request.execution_plan)
    confirmed = observe_federated_compensation_rdf_unknown_outcome(
        chain.request,
        case,
        executor=executor,
        reconciled_by="workload:rdf-reconciler",
        reconciled_at=NOW,
    )
    assert confirmed.decision == "provider_commit_confirmed_from_persisted_receipt"
    assert confirmed.recovered_receipt is not None
    assert confirmed.reconciled_provider_outcome is not None


def test_rdf_unknown_reconciliation_requires_the_unknown_case_position(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(tmp_path, monkeypatch)
    case = _unknown_case(chain)
    wrong_case = case.model_copy(update={"run_id": "different-run"})
    with pytest.raises(
        FederatedProjectionCompensationRDFReconciliationValidationError,
        match="violates a sealed contract",
    ):
        observe_federated_compensation_rdf_unknown_outcome(
            chain.request,
            wrong_case,
            executor=object.__new__(RDFProjectionRepairExecutor),
            reconciled_by="workload:rdf-reconciler",
            reconciled_at=NOW,
        )
