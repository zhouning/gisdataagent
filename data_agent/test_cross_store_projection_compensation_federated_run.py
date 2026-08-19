from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from data_agent.cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
    FederatedCompensationProviderOutcome,
    FederatedCompensationProviderOutcomeStatus,
    FederatedCompensationRunConfigurationError,
    FederatedCompensationRunProviderFailureError,
    FederatedCompensationRunProviderUnknownError,
    FederatedCompensationRunState,
    FederatedCompensationRunValidationError,
    build_federated_compensation_provider_outcome_from_native_result,
    build_federated_compensation_run_bindings,
    execute_federated_compensation_registered_run,
    execute_federated_compensation_run,
)
from data_agent.cross_store_projection_compensation_vector_adapter import (
    execute_federated_compensation_vector_mutation,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.platform_contracts import canonical_json_fingerprint
from data_agent.test_cross_store_projection_compensation_vector_adapter import (
    _chain,
    _RecordingVectorExecutor,
)


def _hash(schema: str, values: dict[str, Any], field: str) -> str:
    payload = dict(values)
    payload.pop(field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def _binding(position: int, engine: ProjectionEngine) -> Any:
    values = {
        "tenant_id": "cq-federated-run",
        "run_id": "cq-five-provider-run",
        "position": position,
        "projection_id": f"cq.projection.{position}",
        "target_engine": engine,
        "target_ref": f"{engine.value}://cq-target/{position}",
        "source_plan_sha256": f"{position + 1:064x}",
        "plan_binding_sha256": f"{position + 101:064x}",
        "materialization_binding_sha256": f"{position + 201:064x}",
        "provider_plan_sha256": f"{position + 301:064x}",
        "provider_idempotency_key": f"{position + 401:064x}",
        "receipt_schema_id": f"gda.{engine.value}.receipt.v1",
    }
    from data_agent.cross_store_projection_compensation_federated_run import (
        FederatedCompensationRunBinding,
    )

    return FederatedCompensationRunBinding(
        **values,
        binding_sha256=_hash(
            FederatedCompensationRunBinding.schema_id,
            values,
            "binding_sha256",
        ),
    )


def _bindings() -> tuple[Any, ...]:
    return tuple(
        _binding(position, engine)
        for position, engine in enumerate(
            (
                ProjectionEngine.POSTGIS,
                ProjectionEngine.VECTOR,
                ProjectionEngine.RDF,
                ProjectionEngine.OBJECT_STORE,
                ProjectionEngine.LAKEHOUSE,
            )
        )
    )


def _outcome(binding, status, *, receipt=True, error_code=None):
    values = {
        "tenant_id": binding.tenant_id,
        "run_id": binding.run_id,
        "position": binding.position,
        "source_plan_sha256": binding.source_plan_sha256,
        "provider_plan_sha256": binding.provider_plan_sha256,
        "provider_idempotency_key": binding.provider_idempotency_key,
        "status": status,
        "provider_receipt_sha256": (
            f"{binding.position + 501:064x}" if receipt else None
        ),
        "error_code": error_code,
    }
    return FederatedCompensationProviderOutcome(
        **values,
        outcome_sha256=_hash(
            FederatedCompensationProviderOutcome.schema_id,
            values,
            "outcome_sha256",
        ),
    )


class _FakeNativeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    run_id: str
    position: int
    materialization_binding_sha256: str
    provider_plan_sha256: str
    provider_idempotency_key: str
    provider_execution_status: str
    provider_execution_performed_by_adapter: bool
    checkpoint_authority_write_performed_by_adapter: bool
    compensation_completion_recorded_by_adapter: bool
    receipt: dict[str, Any]


def _native_result(binding, *, status: str = "provider_mutation_committed"):
    receipt_sha256 = f"{binding.position + 601:064x}"
    return _FakeNativeResult(
        tenant_id=binding.tenant_id,
        run_id=binding.run_id,
        position=binding.position,
        materialization_binding_sha256=binding.materialization_binding_sha256,
        provider_plan_sha256=binding.provider_plan_sha256,
        provider_idempotency_key=binding.provider_idempotency_key,
        provider_execution_status=status,
        provider_execution_performed_by_adapter=True,
        checkpoint_authority_write_performed_by_adapter=False,
        compensation_completion_recorded_by_adapter=False,
        receipt={
            "tenant_id": binding.tenant_id,
            "plan_sha256": binding.provider_plan_sha256,
            "idempotency_key": binding.provider_idempotency_key,
            "provider_commit_ref": {"receipt_sha256": receipt_sha256},
        },
    )


def test_plan_materialization_chain_produces_ordered_run_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    bindings = build_federated_compensation_run_bindings(
        chain.plan_set,
        chain.materialization,
    )

    assert tuple(binding.position for binding in bindings) == (0, 1, 2)
    assert all(binding.tenant_id == chain.intent.tenant_id for binding in bindings)
    assert bindings[0].provider_plan_sha256 == (
        chain.materialization.bindings[0].provider_plan_sha256
    )


def test_all_five_provider_outcomes_complete_only_pending_authority() -> None:
    bindings = _bindings()
    calls: list[int] = []

    def invoke(binding):
        calls.append(binding.position)
        status = (
            FederatedCompensationProviderOutcomeStatus.REPLAYED
            if binding.position == 3
            else FederatedCompensationProviderOutcomeStatus.COMMITTED
        )
        return _outcome(binding, status)

    result = execute_federated_compensation_run(bindings, invoke)

    assert calls == [0, 1, 2, 3, 4]
    assert result.state is FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY
    assert result.provider_receipts_complete is True
    assert result.next_action == "admit_receipt_set"
    assert result.authority_admission_performed is False
    assert result.checkpoint_authority_write_performed is False
    assert result.compensation_completion_recorded is False


def test_known_failure_stops_after_partial_success_and_requires_reconciliation() -> None:
    bindings = _bindings()
    calls: list[int] = []

    def invoke(binding):
        calls.append(binding.position)
        if binding.position == 2:
            raise FederatedCompensationRunProviderFailureError("postgis_constraint")
        return _outcome(binding, FederatedCompensationProviderOutcomeStatus.COMMITTED)

    result = execute_federated_compensation_run(bindings, invoke)

    assert calls == [0, 1, 2]
    assert result.state is FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION
    assert result.attempted_positions == (0, 1, 2)
    assert result.unattempted_positions == (3, 4)
    assert result.provider_receipts_complete is False
    assert result.steps[-1].outcome.error_code == "postgis_constraint"


def test_unknown_outcome_stops_and_requires_reconciliation_even_without_receipt() -> None:
    bindings = _bindings()
    calls: list[int] = []

    def invoke(binding):
        calls.append(binding.position)
        if binding.position == 1:
            raise FederatedCompensationRunProviderUnknownError("fuseki_timeout")
        return _outcome(binding, FederatedCompensationProviderOutcomeStatus.COMMITTED)

    result = execute_federated_compensation_run(bindings, invoke)

    assert calls == [0, 1]
    assert result.state is FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION
    assert result.next_action == "reconcile"
    assert result.unattempted_positions == (2, 3, 4)
    assert result.steps[1].outcome.provider_receipt_sha256 is None


def test_unclassified_provider_exception_is_unknown_and_later_positions_are_not_called() -> None:
    bindings = _bindings()
    calls: list[int] = []

    def invoke(binding):
        calls.append(binding.position)
        if binding.position == 0:
            raise RuntimeError("connection dropped after commit")
        return _outcome(binding, FederatedCompensationProviderOutcomeStatus.COMMITTED)

    result = execute_federated_compensation_run(bindings, invoke)

    assert calls == [0]
    assert result.state is FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION
    assert result.steps[0].outcome.error_code == "unclassified_provider_exception"
    assert result.unattempted_positions == (1, 2, 3, 4)


def test_provider_outcome_identity_drift_fails_closed_before_aggregate_result() -> None:
    bindings = _bindings()

    def invoke(binding):
        if binding.position == 0:
            return _outcome(binding, FederatedCompensationProviderOutcomeStatus.COMMITTED)
        drifted = binding.model_copy(
            update={"provider_plan_sha256": "f" * 64}
        )
        return _outcome(drifted, FederatedCompensationProviderOutcomeStatus.COMMITTED)

    with pytest.raises(FederatedCompensationRunValidationError, match="sealed run binding"):
        execute_federated_compensation_run(bindings, invoke)


def test_native_vector_result_normalizes_to_runner_outcome_and_rejects_tampered_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    run_bindings = build_federated_compensation_run_bindings(
        chain.plan_set,
        chain.materialization,
    )
    binding = next(
        item for item in run_bindings if item.position == chain.binding.position
    )
    native = execute_federated_compensation_vector_mutation(
        chain.request,
        executor=_RecordingVectorExecutor(chain.target),
    )

    outcome = build_federated_compensation_provider_outcome_from_native_result(
        binding,
        native,
    )
    assert outcome.status is FederatedCompensationProviderOutcomeStatus.COMMITTED
    assert outcome.provider_receipt_sha256 == native.receipt.provider_commit_ref[
        "receipt_sha256"
    ]

    tampered = native.model_copy(
        update={"checkpoint_authority_write_performed_by_adapter": True}
    )
    with pytest.raises(FederatedCompensationRunValidationError, match="sealed contract"):
        build_federated_compensation_provider_outcome_from_native_result(
            binding,
            tampered,
        )


def test_provider_invoker_registry_requires_all_five_engines() -> None:
    invokers = {
        engine: (lambda binding: _native_result(binding))
        for engine in ProjectionEngine
        if engine is not ProjectionEngine.RDF
    }

    with pytest.raises(
        FederatedCompensationRunConfigurationError,
        match="missing engines: rdf",
    ):
        FederatedCompensationProviderInvokerRegistry(invokers)


def test_provider_invoker_registry_rejects_an_unknown_engine() -> None:
    invokers = {engine: (lambda binding: _native_result(binding)) for engine in ProjectionEngine}
    invokers["unregistered_provider"] = lambda binding: _native_result(binding)

    with pytest.raises(
        FederatedCompensationRunConfigurationError,
        match="unknown engine",
    ):
        FederatedCompensationProviderInvokerRegistry(invokers)


def test_registered_run_routes_callbacks_by_sealed_target_engine() -> None:
    bindings = _bindings()
    calls: list[ProjectionEngine] = []

    def make_invoker(engine: ProjectionEngine):
        def invoke(binding):
            calls.append(engine)
            assert binding.target_engine is engine
            status = (
                "provider_idempotent_replay"
                if binding.position == 3
                else "provider_mutation_committed"
            )
            return _native_result(binding, status=status)

        return invoke

    registry = FederatedCompensationProviderInvokerRegistry(
        {engine: make_invoker(engine) for engine in ProjectionEngine}
    )
    result = execute_federated_compensation_registered_run(bindings, registry)

    assert calls == [binding.target_engine for binding in bindings]
    assert result.state is FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY
    assert result.provider_receipts_complete is True


def test_registered_run_stops_after_provider_unknown_without_calling_later_engines() -> None:
    bindings = _bindings()
    calls: list[ProjectionEngine] = []

    def make_invoker(engine: ProjectionEngine):
        def invoke(binding):
            calls.append(engine)
            if engine is ProjectionEngine.RDF:
                raise FederatedCompensationRunProviderUnknownError("rdf_timeout")
            return _native_result(binding)

        return invoke

    registry = FederatedCompensationProviderInvokerRegistry(
        {engine: make_invoker(engine) for engine in ProjectionEngine}
    )
    result = execute_federated_compensation_registered_run(bindings, registry)

    assert calls == [
        ProjectionEngine.POSTGIS,
        ProjectionEngine.VECTOR,
        ProjectionEngine.RDF,
    ]
    assert result.state is FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION
    assert result.unattempted_positions == (3, 4)


def test_registered_run_stops_after_known_provider_failure() -> None:
    bindings = _bindings()
    calls: list[ProjectionEngine] = []

    def make_invoker(engine: ProjectionEngine):
        def invoke(binding):
            calls.append(engine)
            if engine is ProjectionEngine.RDF:
                raise FederatedCompensationRunProviderFailureError("rdf_rejected")
            return _native_result(binding)

        return invoke

    registry = FederatedCompensationProviderInvokerRegistry(
        {engine: make_invoker(engine) for engine in ProjectionEngine}
    )
    result = execute_federated_compensation_registered_run(bindings, registry)

    assert calls == [
        ProjectionEngine.POSTGIS,
        ProjectionEngine.VECTOR,
        ProjectionEngine.RDF,
    ]
    assert result.state is (
        FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION
    )
    assert result.unattempted_positions == (3, 4)


def test_registered_run_native_identity_drift_fails_closed() -> None:
    bindings = _bindings()

    def make_invoker(engine: ProjectionEngine):
        def invoke(binding):
            if engine is ProjectionEngine.VECTOR:
                drifted = binding.model_copy(
                    update={"provider_plan_sha256": "f" * 64}
                )
                return _native_result(drifted)
            return _native_result(binding)

        return invoke

    registry = FederatedCompensationProviderInvokerRegistry(
        {engine: make_invoker(engine) for engine in ProjectionEngine}
    )

    with pytest.raises(FederatedCompensationRunValidationError, match="sealed run binding"):
        execute_federated_compensation_registered_run(bindings, registry)
