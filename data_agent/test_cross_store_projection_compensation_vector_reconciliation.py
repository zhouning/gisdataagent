from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

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
from data_agent.cross_store_projection_compensation_vector_reconciliation import (
    FederatedProjectionCompensationVectorReconciliationConflictError,
    FederatedProjectionCompensationVectorReconciliationValidationError,
    observe_federated_compensation_vector_unknown_outcome,
    resume_federated_compensation_vector_unknown_outcome,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.test_chongqing_compensation_execution_support import (
    _technical_execution_permit,
)
from data_agent.test_cross_store_projection_compensation_vector_adapter import _chain
from data_agent.vector_projection_executor import (
    VectorProjectionRepairExecutor,
    VectorProjectionTargetRegistry,
)
from data_agent.vector_projection_executor_rehearsal import _TemporaryPostgres

NOW = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


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

    def unknown(_binding):
        raise RuntimeError("provider_timeout_after_commit")

    registry = FederatedCompensationProviderInvokerRegistry(
        {engine: unknown for engine in ProjectionEngine}
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


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_pgvector_unknown_outcome_reconciles_resume_drift_and_response_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    case = _unknown_case(chain)
    resumed_database = _TemporaryPostgres(os.environ["DATABASE_URL"])
    try:
        resumed_database.create()
        assert resumed_database.engine is not None
        registry = VectorProjectionTargetRegistry((chain.target,))
        executor = VectorProjectionRepairExecutor(resumed_database.engine, registry)

        safe = observe_federated_compensation_vector_unknown_outcome(
            chain.request,
            case,
            executor=executor,
            reconciled_by="workload:pgvector-reconciler",
            reconciled_at=NOW,
        )
        assert safe.decision == "provider_not_committed_safe_to_resume"
        assert safe.recovered_receipt is None
        assert safe.reconciled_provider_outcome is None
        resumed = resume_federated_compensation_vector_unknown_outcome(
            chain.request,
            case,
            safe,
            executor=executor,
            resumed_by="workload:pgvector-reconciler",
            resumed_at=NOW,
        )
        assert resumed.resume_state == "provider_resumed_with_new_commit"
        assert resumed.reconciled_provider_outcome.status.value == (
            "provider_mutation_committed"
        )
        assert resumed.checkpoint_authority_write_performed is False
        assert resumed.compensation_completion_recorded is False

        with resumed_database.engine.connect() as connection:
            assert connection.execute(
                text(
                    f'SELECT count(*) FROM "{chain.target.schema_name}".'
                    f'"{chain.target.table_name}"'
                )
            ).scalar_one() == len(chain.rows)
            assert connection.execute(
                text("SELECT count(*) FROM gda_provider.pgvector_projection_repair_receipt")
            ).scalar_one() == 1

        with pytest.raises(
            FederatedProjectionCompensationVectorReconciliationValidationError
        ):
            resume_federated_compensation_vector_unknown_outcome(
                chain.request,
                case,
                resumed,  # type: ignore[arg-type]
                executor=executor,
                resumed_by="workload:pgvector-reconciler",
                resumed_at=NOW,
            )
    finally:
        resumed_database.drop()

    recovered_database = _TemporaryPostgres(os.environ["DATABASE_URL"])
    try:
        recovered_database.create()
        assert recovered_database.engine is not None
        registry = VectorProjectionTargetRegistry((chain.target,))
        executor = VectorProjectionRepairExecutor(recovered_database.engine, registry)
        stale_safe = observe_federated_compensation_vector_unknown_outcome(
            chain.request,
            case,
            executor=executor,
            reconciled_by="workload:pgvector-reconciler",
            reconciled_at=NOW,
        )

        # A complete target without its same-transaction receipt is ambiguous.
        with recovered_database.engine.begin() as connection:
            connection.execute(
                text(executor._create_table_sql(chain.target, chain.target.table_name))
            )
            insert = text(executor._insert_sql(chain.target, chain.target.table_name))
            for row in chain.rows:
                connection.execute(insert, executor._row_parameters(row))
        with pytest.raises(
            FederatedProjectionCompensationVectorReconciliationConflictError,
            match="state changed after observation",
        ):
            resume_federated_compensation_vector_unknown_outcome(
                chain.request,
                case,
                stale_safe,
                executor=executor,
                resumed_by="workload:pgvector-reconciler",
                resumed_at=NOW,
            )
        indeterminate = observe_federated_compensation_vector_unknown_outcome(
            chain.request,
            case,
            executor=executor,
            reconciled_by="workload:pgvector-reconciler",
            reconciled_at=NOW,
        )
        assert indeterminate.decision == "indeterminate_operator_required"
        assert indeterminate.reason_code == (
            "receipt_absent_target_differs_from_sealed_observation"
        )

        with recovered_database.engine.begin() as connection:
            connection.execute(
                text(
                    f'DROP TABLE "{chain.target.schema_name}".'
                    f'"{chain.target.table_name}"'
                )
            )

        # The caller loses the returned value after target and receipt commit.
        executor.execute(chain.request.execution_plan, rows=chain.rows)
        confirmed = observe_federated_compensation_vector_unknown_outcome(
            chain.request,
            case,
            executor=VectorProjectionRepairExecutor(
                recovered_database.engine,
                registry,
            ),
            reconciled_by="workload:pgvector-reconciler",
            reconciled_at=NOW,
        )
        assert confirmed.decision == (
            "provider_commit_confirmed_from_persisted_receipt"
        )
        assert confirmed.recovered_receipt is not None
        assert confirmed.reconciled_provider_outcome is not None
        assert confirmed.reconciled_provider_outcome.status.value == (
            "provider_mutation_committed"
        )
    finally:
        recovered_database.drop()


def test_pgvector_unknown_reconciliation_requires_vector_unknown_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    case = _unknown_case(chain)
    assert case.items[0].target_engine is ProjectionEngine.VECTOR
    wrong_case = case.model_copy(update={"run_id": "different-run"})
    with pytest.raises(
        FederatedProjectionCompensationVectorReconciliationValidationError,
        match="violates a sealed contract",
    ):
        observe_federated_compensation_vector_unknown_outcome(
            chain.request,
            wrong_case,
            executor=object.__new__(VectorProjectionRepairExecutor),
            reconciled_by="workload:pgvector-reconciler",
            reconciled_at=NOW,
        )
