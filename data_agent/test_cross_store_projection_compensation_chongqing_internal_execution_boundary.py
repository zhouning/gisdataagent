from __future__ import annotations

from importlib import import_module

import pytest

from data_agent.cross_store_projection_compensation_chongqing_deployment_execution import (
    ChongqingFederatedCompensationDeploymentExecutionValidationError,
)
from data_agent.cross_store_projection_compensation_chongqing_internal_execution import (
    ChongqingFederatedCompensationInternalExecutionPermitError,
    _issue_chongqing_federated_compensation_technical_test_execution_permit,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage_execution import (
    ChongqingFederatedCompensationSourceLineageExecutionValidationError,
)
from data_agent.cross_store_projection_compensation_chongqing_source_selection_profile import (
    ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError,
)
from data_agent.test_cross_store_projection_compensation_chongqing_deployment_execution import (
    _deployment_inputs,
)
from data_agent.test_cross_store_projection_compensation_chongqing_source_lineage_execution import (
    _source_lineage_execution_inputs,
)
from data_agent.test_cross_store_projection_compensation_federated_receipt_execution import (
    _registry,
)

deployment_execution = import_module(
    "data_agent.cross_store_projection_compensation_chongqing_deployment_execution"
)
source_lineage_execution = import_module(
    "data_agent.cross_store_projection_compensation_chongqing_source_lineage_execution"
)
source_selection_profile = import_module(
    "data_agent.cross_store_projection_compensation_chongqing_source_selection_profile"
)
profile_execution_test = import_module(
    "data_agent.test_cross_store_projection_compensation_chongqing_source_selection_profile_execution"
)
_profiled_execution_inputs = profile_execution_test._profiled_execution_inputs


@pytest.mark.parametrize(
    ("module", "function_name"),
    (
        (
            deployment_execution,
            "execute_chongqing_federated_compensation_deployment_with_receipt_set",
        ),
        (
            source_lineage_execution,
            "execute_chongqing_federated_compensation_source_lineage_with_receipt_set",
        ),
        (
            source_selection_profile,
            "execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set",
        ),
    ),
)
def test_low_level_mutating_helper_is_not_a_supported_public_export(
    module: object,
    function_name: str,
) -> None:
    assert function_name not in module.__all__


def test_deployment_helper_without_internal_permit_stops_before_callback() -> None:
    intent, plan_set, materialization, source_catalog, deployment_binding = (
        _deployment_inputs()
    )
    registry, calls = _registry(materialization)

    with pytest.raises(
        ChongqingFederatedCompensationDeploymentExecutionValidationError,
        match="internal execution permit",
    ):
        deployment_execution.execute_chongqing_federated_compensation_deployment_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            deployment_binding,
            registry,
        )

    assert calls == []


def test_source_lineage_helper_without_internal_permit_stops_before_callback() -> None:
    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
    ) = _source_lineage_execution_inputs()
    registry, calls = _registry(materialization)

    with pytest.raises(
        ChongqingFederatedCompensationSourceLineageExecutionValidationError,
        match="internal execution permit",
    ):
        source_lineage_execution.execute_chongqing_federated_compensation_source_lineage_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            deployment_binding,
            source_lineage_set,
            registry,
        )

    assert calls == []


def test_profile_helper_without_internal_permit_stops_before_callback() -> None:
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

    with pytest.raises(
        ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError,
        match="internal execution permit",
    ):
        source_selection_profile.execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            deployment_binding,
            profile,
            source_lineage_set,
            profiled_binding,
            registry,
        )

    assert calls == []


def test_technical_permit_cannot_claim_production_authorization() -> None:
    intent, _, materialization, _, _ = _deployment_inputs()
    registry, calls = _registry(materialization)

    with pytest.raises(
        ChongqingFederatedCompensationInternalExecutionPermitError,
        match="cannot authorize production execution",
    ):
        _issue_chongqing_federated_compensation_technical_test_execution_permit(
            intent=intent,
            registry=registry,
            purpose="technical_contract_test",
            production_execution_authorized=True,
        )

    assert calls == []


def test_internal_permit_cannot_be_replayed_with_another_registry() -> None:
    intent, plan_set, materialization, source_catalog, deployment_binding = (
        _deployment_inputs()
    )
    issuing_registry, issuing_calls = _registry(materialization)
    replay_registry, replay_calls = _registry(materialization)
    permit = (
        _issue_chongqing_federated_compensation_technical_test_execution_permit(
            intent=intent,
            registry=issuing_registry,
            purpose="technical_contract_test",
            production_execution_authorized=False,
        )
    )

    with pytest.raises(
        ChongqingFederatedCompensationDeploymentExecutionValidationError,
        match="internal execution permit",
    ):
        deployment_execution.execute_chongqing_federated_compensation_deployment_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            deployment_binding,
            replay_registry,
            execution_permit=permit,
        )

    assert issuing_calls == []
    assert replay_calls == []
