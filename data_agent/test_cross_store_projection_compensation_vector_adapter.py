from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import text

import data_agent.test_cross_store_projection_compensation_approval as approval_fixtures
from data_agent.cross_store_projection_compensation_proposal import (
    build_federated_projection_compensation_proposal,
)
from data_agent.cross_store_projection_compensation_provider_adapter import (
    resolve_federated_compensation_provider_adapter,
)
from data_agent.cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationInput,
    build_federated_compensation_provider_materialization_set,
)
from data_agent.cross_store_projection_compensation_provider_plan import (
    build_federated_compensation_provider_plan_set,
)
from data_agent.cross_store_projection_compensation_provider_receipt import (
    build_federated_compensation_provider_receipt_candidate,
    validate_federated_compensation_provider_receipt_candidate,
)
from data_agent.cross_store_projection_compensation_vector_adapter import (
    FederatedProjectionCompensationVectorAdapterValidationError,
    FederatedProjectionCompensationVectorMutationRequest,
    build_federated_compensation_vector_mutation_request,
    execute_federated_compensation_vector_mutation,
    federated_compensation_vector_payload_fingerprint,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionEngine,
    build_projection_repair_plan,
)
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)
from data_agent.test_cross_store_projection_federated_recovery import (
    _coordinator,
    _dependencies,
    _plans,
)
from data_agent.test_vector_projection_executor import _plan
from data_agent.vector_projection_executor import (
    VectorProjectionRepairExecutor,
    VectorProjectionRepairReceipt,
    VectorProjectionTarget,
    VectorProjectionTargetRegistry,
    vector_projection_receipt_fingerprint,
    vector_rows_fingerprint,
)
from data_agent.vector_projection_executor_rehearsal import (
    _desired as _rehearsal_desired,
)
from data_agent.vector_projection_executor_rehearsal import _rows as _rehearsal_rows
from data_agent.vector_projection_executor_rehearsal import _target as _rehearsal_target
from data_agent.vector_projection_executor_rehearsal import _TemporaryPostgres


class _RecordingVectorExecutor(VectorProjectionRepairExecutor):
    """In-memory receipt substitute used only to test adapter rebinding."""

    def __init__(self, target: VectorProjectionTarget) -> None:
        self.registry = VectorProjectionTargetRegistry((target,))
        self.execute_calls = 0
        self._committed = False

    def execute(self, plan, *, rows=(), observed_at=None):
        self.execute_calls += 1
        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        content_sha256 = vector_rows_fingerprint(target, rows)
        commit_ref = {
            "provider": "pgvector",
            "provider_commit": f"{target.schema_name}.{target.table_name}:1",
            "provider_transaction_id": "1",
            "plan_sha256": plan.plan_sha256,
            "idempotency_key": plan.plan_idempotency_key,
        }
        receipt_sha256 = vector_projection_receipt_fingerprint(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=True,
            target_content_sha256=content_sha256,
            target_row_count=len(rows),
        )
        commit_ref["receipt_sha256"] = receipt_sha256
        status = "replayed" if self._committed else "completed"
        self._committed = True
        return VectorProjectionRepairReceipt(
            status=status,
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=True,
            target_content_sha256=content_sha256,
            target_row_count=len(rows),
            observed_at=observed_at or datetime.now(UTC),
        )


def _chain_for_plan(
    target: VectorProjectionTarget,
    rows: tuple[dict, ...],
    vector_plan,
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    original = _plans(tenant_id=target.tenant_id)
    plans = (vector_plan, original[1], original[2])
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )
    snapshot = _coordinator(plans, providers, authorities).advance()
    proposal = build_federated_projection_compensation_proposal(plans, snapshot)
    monkeypatch.setattr(approval_fixtures, "_proposal", lambda: proposal)

    intent, _, registry, resolution_request = _inputs()
    resolution = resolve_federated_compensation_provider_adapter(
        intent,
        resolution_request,
        registry,
    )
    plan_set = build_federated_compensation_provider_plan_set(intent, resolution)
    by_sha256 = {plan.plan_sha256: plan for plan in plans}
    inputs = []
    for binding in plan_set.plan_bindings:
        plan = by_sha256[binding.source_plan_sha256]
        payload_sha256 = (
            federated_compensation_vector_payload_fingerprint(target, plan.action, rows)
            if plan.target_engine is ProjectionEngine.VECTOR
            else f"{binding.position + 17:064x}"
        )
        desired = plan.desired_state
        inputs.append(
            FederatedProjectionCompensationProviderMaterializationInput(
                position=binding.position,
                projection_id=plan.projection_id,
                payload_sha256=payload_sha256,
                expected_target_exists=desired.target_exists,
                expected_target_content_sha256=desired.expected_target_content_sha256,
                expected_target_row_count=desired.expected_row_count,
            )
        )
    materialization = build_federated_compensation_provider_materialization_set(
        plan_set,
        tuple(inputs),
        materialized_by="workload:chongqing-compensation-materializer",
    )
    binding = next(
        item for item in materialization.bindings if item.target_engine is ProjectionEngine.VECTOR
    )
    request = build_federated_compensation_vector_mutation_request(
        intent,
        plan_set,
        materialization,
        vector_plan,
        target,
        rows,
        dispatched_by="workload:chongqing-compensation-dispatcher",
    )
    return SimpleNamespace(
        intent=intent,
        plan_set=plan_set,
        materialization=materialization,
        binding=binding,
        source_plan=vector_plan,
        target=target,
        rows=rows,
        request=request,
    )


def _chain(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    target, rows, plan = _plan()
    return _chain_for_plan(target, rows, plan, monkeypatch)


def test_vector_request_is_deterministic_and_excludes_sql_and_connectivity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    replay = build_federated_compensation_vector_mutation_request(
        chain.intent,
        chain.plan_set,
        chain.materialization,
        chain.source_plan,
        chain.target,
        chain.rows,
        dispatched_by="workload:chongqing-compensation-dispatcher",
    )

    assert replay == chain.request
    document = json.dumps(chain.request.model_dump(mode="json"), sort_keys=True)
    for forbidden in ("sql", "credentials", "database_url", "endpoint", "password"):
        assert f'"{forbidden}":' not in document
    with pytest.raises(ValidationError):
        FederatedProjectionCompensationVectorMutationRequest(
            **chain.request.model_dump(mode="python"),
            sql="DROP TABLE public.land_semantic_vectors",
        )


def test_vector_row_engine_and_registry_drift_are_rejected_before_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    drifted_rows = (
        {**chain.rows[0], "content_text": "tampered vector payload"},
        chain.rows[1],
    )
    with pytest.raises(
        FederatedProjectionCompensationVectorAdapterValidationError,
        match="payload differs",
    ):
        build_federated_compensation_vector_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            chain.source_plan,
            chain.target,
            drifted_rows,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )
    with pytest.raises(
        FederatedProjectionCompensationVectorAdapterValidationError,
        match="source plan differs",
    ):
        build_federated_compensation_vector_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            _plans(tenant_id=chain.target.tenant_id)[1],
            chain.target,
            chain.rows,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )

    drifted_target = chain.target.model_copy(update={"embedding_dimension": 4})
    executor = _RecordingVectorExecutor(drifted_target)
    with pytest.raises(
        FederatedProjectionCompensationVectorAdapterValidationError,
        match="rows violate",
    ):
        execute_federated_compensation_vector_mutation(chain.request, executor=executor)
    assert executor.execute_calls == 0


def test_vector_transaction_receipt_replay_and_candidate_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    executor = _RecordingVectorExecutor(chain.target)
    first = execute_federated_compensation_vector_mutation(chain.request, executor=executor)
    replay = execute_federated_compensation_vector_mutation(chain.request, executor=executor)

    assert first.provider_execution_status == "provider_mutation_committed"
    assert first.provider_mutation_performed is True
    assert first.receipt.provider_commit_ref["provider"] == "pgvector"
    assert replay.provider_execution_status == "provider_idempotent_replay"
    assert replay.provider_mutation_performed is False
    assert executor.execute_calls == 2
    assert first.checkpoint_authority_write_performed_by_adapter is False
    assert first.compensation_completion_recorded_by_adapter is False

    candidate = build_federated_compensation_provider_receipt_candidate(
        chain.materialization,
        chain.binding,
        first.receipt.model_dump(mode="python"),
    )
    validation = validate_federated_compensation_provider_receipt_candidate(
        chain.materialization,
        candidate,
    )
    assert validation.validation_state == "validated_not_authority_admitted"
    assert validation.provider_plan_sha256 == chain.binding.provider_plan_sha256


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured for real PostgreSQL/pgvector verification",
)
def test_real_pgvector_transaction_receipt_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = _TemporaryPostgres(os.environ["DATABASE_URL"])
    try:
        temporary.create()
        assert temporary.engine is not None
        target = _rehearsal_target()
        rows = _rehearsal_rows()
        executor = VectorProjectionRepairExecutor(
            temporary.engine,
            VectorProjectionTargetRegistry((target,)),
        )
        missing = executor.observe(target)
        plan = build_projection_repair_plan(
            _rehearsal_desired(target, rows, "a" * 64),
            missing,
            None,
        )
        chain = _chain_for_plan(target, rows, plan, monkeypatch)

        first = execute_federated_compensation_vector_mutation(chain.request, executor=executor)
        restarted = VectorProjectionRepairExecutor(
            temporary.engine,
            VectorProjectionTargetRegistry((target,)),
        )
        replay = execute_federated_compensation_vector_mutation(
            chain.request,
            executor=restarted,
        )

        assert first.provider_execution_status == "provider_mutation_committed"
        assert first.receipt.provider_commit_ref["provider"] == "pgvector"
        assert first.receipt.provider_commit_ref["provider_transaction_id"]
        assert replay.provider_execution_status == "provider_idempotent_replay"
        candidate = build_federated_compensation_provider_receipt_candidate(
            chain.materialization,
            chain.binding,
            first.receipt.model_dump(mode="python"),
        )
        assert validate_federated_compensation_provider_receipt_candidate(
            chain.materialization,
            candidate,
        ).validation_state == "validated_not_authority_admitted"
        with temporary.engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM gda_provider.pgvector_projection_repair_receipt")
            ).scalar_one() == 1
    finally:
        temporary.drop()
