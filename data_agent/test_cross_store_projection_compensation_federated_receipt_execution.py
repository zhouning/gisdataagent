from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from data_agent.cross_store_projection_compensation_federated_receipt_execution import (
    FederatedCompensationRegisteredReceiptExecutionState,
    FederatedCompensationRegisteredReceiptExecutionValidationError,
    execute_registered_federated_compensation_run_with_receipt_set,
)
from data_agent.cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
    FederatedCompensationRunProviderFailureError,
    FederatedCompensationRunState,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.test_cross_store_projection_compensation_provider_receipt import (
    _receipt_document,
)
from data_agent.test_cross_store_projection_compensation_provider_receipt_set import (
    _receipt_set_inputs,
)


class _NativeResult(BaseModel):
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


def _registry(
    materialization,
    *,
    fail_engine: ProjectionEngine | None = None,
    tamper_receipt_at: int | None = None,
):
    by_position = {binding.position: binding for binding in materialization.bindings}
    calls: list[ProjectionEngine] = []

    def make_invoker(engine: ProjectionEngine):
        def invoke(binding):
            calls.append(engine)
            if engine is fail_engine:
                raise FederatedCompensationRunProviderFailureError("provider_rejected")
            materialized = by_position[binding.position]
            receipt = _receipt_document(materialized)
            if binding.position == tamper_receipt_at:
                receipt["provider_commit_ref"] = {
                    **receipt["provider_commit_ref"],
                    "receipt_sha256": "f" * 64,
                }
            return _NativeResult(
                tenant_id=binding.tenant_id,
                run_id=binding.run_id,
                position=binding.position,
                materialization_binding_sha256=(
                    binding.materialization_binding_sha256
                ),
                provider_plan_sha256=binding.provider_plan_sha256,
                provider_idempotency_key=binding.provider_idempotency_key,
                provider_execution_status="provider_mutation_committed",
                provider_execution_performed_by_adapter=True,
                checkpoint_authority_write_performed_by_adapter=False,
                compensation_completion_recorded_by_adapter=False,
                receipt=receipt,
            )

        return invoke

    return (
        FederatedCompensationProviderInvokerRegistry(
            {engine: make_invoker(engine) for engine in ProjectionEngine}
        ),
        calls,
    )


def test_registered_run_validates_native_receipts_without_a_second_provider_call() -> None:
    intent, plan_set, materialization, _ = _receipt_set_inputs()
    registry, calls = _registry(materialization)

    result = execute_registered_federated_compensation_run_with_receipt_set(
        intent,
        plan_set,
        materialization,
        registry,
    )

    assert calls == [binding.target_engine for binding in materialization.bindings]
    assert result.state is (
        FederatedCompensationRegisteredReceiptExecutionState
        .COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
    )
    assert result.run_result.state is (
        FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY
    )
    assert result.receipt_validation_set is not None
    assert result.native_receipts_validated is True
    assert result.receipt_set_authority_admission_performed is False
    assert "receipt_document" not in str(result.model_dump(mode="json"))


def test_registered_run_returns_reconciliation_without_receipt_set_after_known_failure() -> None:
    intent, plan_set, materialization, _ = _receipt_set_inputs()
    registry, calls = _registry(materialization, fail_engine=ProjectionEngine.RDF)

    result = execute_registered_federated_compensation_run_with_receipt_set(
        intent,
        plan_set,
        materialization,
        registry,
    )

    assert calls == [ProjectionEngine.POSTGIS, ProjectionEngine.RDF]
    assert result.state is (
        FederatedCompensationRegisteredReceiptExecutionState
        .RECONCILIATION_OR_OPERATOR_REQUIRED
    )
    assert result.run_result.state is (
        FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION
    )
    assert result.receipt_validation_set is None
    assert result.native_receipts_validated is False


def test_registered_run_rejects_tampered_native_receipt_before_receipt_set_admission() -> None:
    intent, plan_set, materialization, _ = _receipt_set_inputs()
    registry, _ = _registry(materialization, tamper_receipt_at=0)

    with pytest.raises(
        FederatedCompensationRegisteredReceiptExecutionValidationError,
        match="cannot form a federated receipt-set candidate",
    ):
        execute_registered_federated_compensation_run_with_receipt_set(
            intent,
            plan_set,
            materialization,
            registry,
        )
