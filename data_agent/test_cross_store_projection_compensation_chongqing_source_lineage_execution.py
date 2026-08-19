from __future__ import annotations

import pytest

from data_agent.cross_store_projection_compensation_chongqing_deployment import (
    build_chongqing_federated_compensation_deployment_binding,
    build_chongqing_federated_compensation_source_catalog,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage import (
    build_chongqing_federated_compensation_source_lineage_set,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage_execution import (
    ChongqingFederatedCompensationSourceLineageExecutionValidationError,
    execute_chongqing_federated_compensation_source_lineage_with_receipt_set,
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


def _source_lineage_execution_inputs():
    intent, plan_set, materialization, _ = _receipt_set_inputs()
    source_catalog = build_chongqing_federated_compensation_source_catalog()
    deployment_binding = build_chongqing_federated_compensation_deployment_binding(
        intent,
        plan_set,
        materialization,
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
    return (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
    )


def test_source_lineage_preflight_executes_each_provider_once_and_keeps_authority_pending() -> None:
    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
    ) = _source_lineage_execution_inputs()
    registry, calls = _registry(materialization)

    result = execute_chongqing_federated_compensation_source_lineage_with_receipt_set(
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
        registry,
        execution_permit=_technical_execution_permit(intent, registry),
    )

    assert calls == [item.target_engine for item in materialization.bindings]
    assert result.source_lineage_preflight_performed is True
    assert result.source_lineage_set_sha256 == source_lineage_set.source_lineage_set_sha256
    assert result.deployment_execution.state is (
        FederatedCompensationRegisteredReceiptExecutionState
        .COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
    )
    assert result.authority_admission_performed is False
    assert result.checkpoint_authority_write_performed is False
    assert result.compensation_completion_recorded is False
    assert "receipt_document" not in str(result.model_dump(mode="json"))


def test_source_lineage_drift_stops_before_any_provider_callback() -> None:
    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
    ) = _source_lineage_execution_inputs()
    registry, calls = _registry(materialization)
    drifted = source_lineage_set.model_copy(
        update={"deployment_binding_sha256": "f" * 64}
    )

    with pytest.raises(
        ChongqingFederatedCompensationSourceLineageExecutionValidationError,
        match="sealed contract",
    ):
        execute_chongqing_federated_compensation_source_lineage_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            deployment_binding,
            drifted,
            registry,
            execution_permit=_technical_execution_permit(intent, registry),
        )
    assert calls == []
