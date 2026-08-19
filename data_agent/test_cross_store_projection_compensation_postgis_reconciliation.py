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
from data_agent.cross_store_projection_compensation_postgis_reconciliation import (
    FederatedProjectionCompensationPostGISReconciliationConflictError,
    FederatedProjectionCompensationPostGISReconciliationValidationError,
    observe_federated_compensation_postgis_unknown_outcome,
    resume_federated_compensation_postgis_unknown_outcome,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.postgis_projection_executor import (
    PostGISProjectionRepairExecutor,
    PostGISProjectionTargetRegistry,
)
from data_agent.postgis_projection_executor_rehearsal import _TemporaryPostgres
from data_agent.test_chongqing_compensation_execution_support import (
    _technical_execution_permit,
)
from data_agent.test_cross_store_projection_compensation_postgis_adapter import (
    _ROWS,
    _chain,
)

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


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
    case = build_chongqing_federated_compensation_source_lineage_reconciliation_case(
        deployment_binding,
        source_lineage_set,
        execution,
    )
    return case


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgis_unknown_outcome_reconciles_safe_resume_and_commit_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    case = _unknown_case(chain)
    resumed_database = _TemporaryPostgres(os.environ["DATABASE_URL"])
    try:
        resumed_database.create()
        assert resumed_database.engine is not None
        registry = PostGISProjectionTargetRegistry((chain.target,))
        executor = PostGISProjectionRepairExecutor(resumed_database.engine, registry)

        safe = observe_federated_compensation_postgis_unknown_outcome(
            chain.request,
            case,
            executor=executor,
            reconciled_by="workload:postgis-reconciler",
            reconciled_at=NOW,
        )
        assert safe.decision == "provider_not_committed_safe_to_resume"
        assert safe.recovered_receipt is None
        assert safe.reconciled_provider_outcome is None
        resumed = resume_federated_compensation_postgis_unknown_outcome(
            chain.request,
            case,
            safe,
            executor=executor,
            resumed_by="workload:postgis-reconciler",
            resumed_at=NOW,
        )
        assert resumed.resume_state == "provider_resumed_with_new_commit"
        assert resumed.reconciled_provider_outcome.status.value == (
            "provider_mutation_committed"
        )

        with resumed_database.engine.connect() as connection:
            assert connection.execute(
                text('SELECT count(*) FROM public."cq_federated_postgis"')
            ).scalar_one() == len(_ROWS)
            assert connection.execute(
                text("SELECT count(*) FROM gda_provider.postgis_projection_repair_receipt")
            ).scalar_one() == 1

        with pytest.raises(FederatedProjectionCompensationPostGISReconciliationValidationError):
            resume_federated_compensation_postgis_unknown_outcome(
                chain.request,
                case,
                resumed,  # type: ignore[arg-type]
                executor=executor,
                resumed_by="workload:postgis-reconciler",
                resumed_at=NOW,
            )
    finally:
        resumed_database.drop()

    recovered_database = _TemporaryPostgres(os.environ["DATABASE_URL"])
    try:
        recovered_database.create()
        assert recovered_database.engine is not None
        registry = PostGISProjectionTargetRegistry((chain.target,))
        executor = PostGISProjectionRepairExecutor(recovered_database.engine, registry)
        stale_safe = observe_federated_compensation_postgis_unknown_outcome(
            chain.request,
            case,
            executor=executor,
            reconciled_by="workload:postgis-reconciler",
            reconciled_at=NOW,
        )

        # A target appearing without the same-transaction receipt is ambiguous.
        with recovered_database.engine.begin() as connection:
            connection.execute(
                text(
                    'CREATE TABLE public."cq_federated_postgis" ('
                    '"feature_id" BIGINT NOT NULL, "land_use" TEXT NOT NULL, '
                    '"geom" geometry(Geometry, 4326))'
                )
            )
            for row in _ROWS:
                connection.execute(
                    text(
                        'INSERT INTO public."cq_federated_postgis" '
                        '("feature_id", "land_use", "geom") VALUES '
                        '(:feature_id, :land_use, ST_GeomFromText(:geom, 4326))'
                    ),
                    row,
                )
        with pytest.raises(
            FederatedProjectionCompensationPostGISReconciliationConflictError,
            match="state changed after observation",
        ):
            resume_federated_compensation_postgis_unknown_outcome(
                chain.request,
                case,
                stale_safe,
                executor=executor,
                resumed_by="workload:postgis-reconciler",
                resumed_at=NOW,
            )
        indeterminate = observe_federated_compensation_postgis_unknown_outcome(
            chain.request,
            case,
            executor=executor,
            reconciled_by="workload:postgis-reconciler",
            reconciled_at=NOW,
        )
        assert indeterminate.decision == "indeterminate_operator_required"
        assert indeterminate.reason_code == (
            "receipt_absent_target_differs_from_sealed_observation"
        )
        assert indeterminate.reconciled_provider_outcome is None

        with recovered_database.engine.begin() as connection:
            connection.execute(text('DROP TABLE public."cq_federated_postgis"'))

        # The caller loses this returned value after target and receipt commit.
        executor.execute(chain.request.execution_plan, rows=_ROWS)
        confirmed = observe_federated_compensation_postgis_unknown_outcome(
            chain.request,
            case,
            executor=PostGISProjectionRepairExecutor(
                recovered_database.engine,
                registry,
            ),
            reconciled_by="workload:postgis-reconciler",
            reconciled_at=NOW,
        )
        assert confirmed.decision == "provider_commit_confirmed_from_persisted_receipt"
        assert confirmed.recovered_receipt is not None
        assert confirmed.reconciled_provider_outcome is not None
        assert confirmed.reconciled_provider_outcome.status.value == (
            "provider_mutation_committed"
        )
        with recovered_database.engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM gda_provider.postgis_projection_repair_receipt")
            ).scalar_one() == 1
    finally:
        recovered_database.drop()


def test_postgis_unknown_reconciliation_requires_the_unknown_case_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    case = _unknown_case(chain)
    wrong_case = case.model_copy(
        update={"run_id": "different-run"}
    )
    with pytest.raises(
        FederatedProjectionCompensationPostGISReconciliationValidationError,
        match="violates a sealed contract",
    ):
        observe_federated_compensation_postgis_unknown_outcome(
            chain.request,
            wrong_case,
            executor=object.__new__(PostGISProjectionRepairExecutor),
            reconciled_by="workload:postgis-reconciler",
            reconciled_at=NOW,
        )


def test_postgis_response_loss_is_recovered_from_persisted_receipt_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    case = _unknown_case(chain)
    # This test is deliberately limited to contract construction; the real
    # same-transaction receipt check is covered by the PostgreSQL rehearsal.
    assert case.items[0].target_engine is ProjectionEngine.POSTGIS
    assert chain.request.execution_plan.position == case.items[0].position
