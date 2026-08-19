from __future__ import annotations

import pytest

from data_agent.cross_store_projection_compensation_chongqing_source_selection_profile import (
    ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError,
    build_chongqing_federated_compensation_profiled_source_lineage_binding,
    execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set,
)
from data_agent.cross_store_projection_compensation_federated_receipt_execution import (
    FederatedCompensationRegisteredReceiptExecutionState,
)
from data_agent.test_chongqing_compensation_execution_support import (
    _technical_execution_permit,
)
from data_agent.test_cross_store_projection_compensation_chongqing_source_selection_profile import (
    _profiled_lineage_inputs,
)
from data_agent.test_cross_store_projection_compensation_federated_receipt_execution import (
    _registry,
)
from data_agent.test_cross_store_projection_compensation_provider_receipt_set import (
    _receipt_set_inputs,
)


def _profiled_execution_inputs():
    intent, plan_set, materialization, _ = _receipt_set_inputs()
    source_catalog, deployment_binding, profile, source_lineage_set = (
        _profiled_lineage_inputs()
    )
    profiled_binding = build_chongqing_federated_compensation_profiled_source_lineage_binding(
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
    )
    return (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
        profiled_binding,
    )


def test_profiled_source_lineage_preflight_calls_each_fixture_provider_once() -> None:
    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
        profiled_binding,
    ) = _profiled_execution_inputs()
    registry, calls = _registry(materialization)

    result = execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set(
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
        profiled_binding,
        registry,
        execution_permit=_technical_execution_permit(intent, registry),
    )

    assert calls == [item.target_engine for item in materialization.bindings]
    assert result.source_selection_profile_preflight_performed is True
    assert result.source_selection_profile_sha256 == profile.profile_sha256
    assert result.source_lineage_execution.deployment_execution.state is (
        FederatedCompensationRegisteredReceiptExecutionState
        .COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
    )
    assert result.authority_admission_performed is False
    assert result.checkpoint_authority_write_performed is False
    assert result.compensation_completion_recorded is False


def test_profile_binding_drift_stops_before_any_provider_callback() -> None:
    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
        profiled_binding,
    ) = _profiled_execution_inputs()
    registry, calls = _registry(materialization)
    drifted = profiled_binding.model_copy(
        update={"source_selection_profile_sha256": "f" * 64}
    )

    with pytest.raises(
        ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError,
        match="sealed contract",
    ):
        execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            deployment_binding,
            profile,
            source_lineage_set,
            drifted,
            registry,
            execution_permit=_technical_execution_permit(intent, registry),
        )
    assert calls == []
