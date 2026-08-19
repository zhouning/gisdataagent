from __future__ import annotations

import pytest

from data_agent.cross_store_projection_compensation_provider_adapter import (
    resolve_federated_compensation_provider_adapter,
)
from data_agent.cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanError,
    build_federated_compensation_provider_plan_set,
)
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)


def _plan_inputs():
    intent, adapter, registry, request = _inputs()
    resolution = resolve_federated_compensation_provider_adapter(
        intent,
        request,
        registry,
    )
    return intent, adapter, resolution


def test_provider_plan_set_binds_each_source_plan_without_payload() -> None:
    intent, adapter, resolution = _plan_inputs()

    plan_set = build_federated_compensation_provider_plan_set(intent, resolution)
    replay = build_federated_compensation_provider_plan_set(intent, resolution)

    assert plan_set.plan_set_sha256 == replay.plan_set_sha256
    assert plan_set.adapter_id == adapter.adapter_id
    assert plan_set.implementation_artifact_sha256 == (
        adapter.implementation_artifact_sha256
    )
    assert tuple(binding.position for binding in plan_set.plan_bindings) == tuple(
        binding.position for binding in intent.plan_bindings
    )
    assert len(
        {
            binding.provider_idempotency_key
            for binding in plan_set.plan_bindings
        }
    ) == len(plan_set.plan_bindings)
    assert all(
        binding.execution_material_state == "deployment_payload_not_materialized"
        and binding.provider_dispatch_performed is False
        and binding.execution_allowed is False
        for binding in plan_set.plan_bindings
    )
    assert plan_set.provider_dispatch_performed is False
    assert plan_set.execution_allowed is False
    assert "endpoint" not in plan_set.model_dump(mode="json")
    assert "credentials" not in plan_set.model_dump(mode="json")
    assert "sql" not in plan_set.model_dump(mode="json")


def test_provider_plan_set_rejects_resolution_drift() -> None:
    intent, _, resolution = _plan_inputs()
    drifted = resolution.model_copy(
        update={"dispatch_intent_sha256": "f" * 64}
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderPlanError,
        match="input violates",
    ):
        build_federated_compensation_provider_plan_set(intent, drifted)

def test_provider_plan_set_rejects_missing_operation_contract() -> None:
    intent, _, resolution = _plan_inputs()
    drifted = resolution.model_copy(update={"mutation_contracts": ()})

    with pytest.raises(
        FederatedProjectionCompensationProviderPlanError,
        match="input violates",
    ):
        build_federated_compensation_provider_plan_set(intent, drifted)
