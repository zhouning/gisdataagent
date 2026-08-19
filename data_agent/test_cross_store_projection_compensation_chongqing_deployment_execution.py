from __future__ import annotations

import pytest

from data_agent.cross_store_projection_compensation_chongqing_deployment import (
    build_chongqing_federated_compensation_deployment_binding,
    build_chongqing_federated_compensation_source_catalog,
)
from data_agent.cross_store_projection_compensation_chongqing_deployment_execution import (
    ChongqingFederatedCompensationDeploymentExecutionValidationError,
    execute_chongqing_federated_compensation_deployment_with_receipt_set,
)
from data_agent.cross_store_projection_compensation_federated_receipt_execution import (
    FederatedCompensationRegisteredReceiptExecutionState,
)
from data_agent.test_chongqing_compensation_execution_support import (
    _technical_execution_permit,
)
from data_agent.test_cross_store_projection_compensation_federated_receipt_execution import (
    _registry,
)
from data_agent.test_cross_store_projection_compensation_provider_receipt_set import (
    _receipt_set_inputs,
)


def _deployment_inputs():
    intent, plan_set, materialization, _ = _receipt_set_inputs()
    source_catalog = build_chongqing_federated_compensation_source_catalog()
    deployment_binding = build_chongqing_federated_compensation_deployment_binding(
        intent,
        plan_set,
        materialization,
        source_catalog,
    )
    return intent, plan_set, materialization, source_catalog, deployment_binding


def test_chongqing_preflight_runs_registered_providers_once_and_keeps_authority_pending() -> None:
    intent, plan_set, materialization, source_catalog, deployment_binding = (
        _deployment_inputs()
    )
    registry, calls = _registry(materialization)

    result = execute_chongqing_federated_compensation_deployment_with_receipt_set(
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        registry,
        execution_permit=_technical_execution_permit(intent, registry),
    )

    assert calls == [item.target_engine for item in materialization.bindings]
    assert result.state is (
        FederatedCompensationRegisteredReceiptExecutionState
        .COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
    )
    assert result.customer_catalog_preflight_performed is True
    assert result.authority_admission_performed is False
    assert result.checkpoint_authority_write_performed is False
    assert result.compensation_completion_recorded is False
    assert "receipt_document" not in str(result.model_dump(mode="json"))


def test_chongqing_deployment_drift_stops_before_any_provider_callback() -> None:
    intent, plan_set, materialization, source_catalog, deployment_binding = (
        _deployment_inputs()
    )
    registry, calls = _registry(materialization)
    drifted = deployment_binding.model_copy(
        update={"source_catalog_sha256": "f" * 64}
    )

    with pytest.raises(
        ChongqingFederatedCompensationDeploymentExecutionValidationError,
        match="sealed contract",
    ):
        execute_chongqing_federated_compensation_deployment_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            drifted,
            registry,
            execution_permit=_technical_execution_permit(intent, registry),
        )
    assert calls == []
