from __future__ import annotations

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_compensation_provider_adapter import (
    resolve_federated_compensation_provider_adapter,
)
from data_agent.cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationError,
    FederatedProjectionCompensationProviderMaterializationInput,
    build_federated_compensation_provider_materialization_set,
)
from data_agent.cross_store_projection_compensation_provider_plan import (
    build_federated_compensation_provider_plan_set,
)
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)


def _plan_set():
    intent, _, registry, request = _inputs()
    resolution = resolve_federated_compensation_provider_adapter(
        intent,
        request,
        registry,
    )
    return build_federated_compensation_provider_plan_set(intent, resolution)


def _materialization_inputs(plan_set):
    return tuple(
        FederatedProjectionCompensationProviderMaterializationInput(
            position=binding.position,
            projection_id=f"customer-projection-{binding.position}",
            payload_sha256=f"{binding.position + 17:064x}",
            expected_target_exists=True,
            expected_target_content_sha256="c" * 64,
            expected_target_row_count=3,
        )
        for binding in plan_set.plan_bindings
    )


def test_materialization_seals_opaque_payload_references_without_dispatch() -> None:
    plan_set = _plan_set()
    inputs = _materialization_inputs(plan_set)

    materialization = build_federated_compensation_provider_materialization_set(
        plan_set,
        inputs,
        materialized_by="workload:chongqing-compensation-materializer",
    )
    replay = build_federated_compensation_provider_materialization_set(
        plan_set,
        inputs,
        materialized_by="workload:chongqing-compensation-materializer",
    )

    assert materialization.materialization_set_sha256 == (replay.materialization_set_sha256)
    assert tuple(binding.position for binding in materialization.bindings) == tuple(
        binding.position for binding in plan_set.plan_bindings
    )
    assert all(
        binding.materialization_state == "deployment_payload_materialized_pending_provider_dispatch"
        and binding.provider_dispatch_performed is False
        and binding.execution_allowed is False
        for binding in materialization.bindings
    )
    document = materialization.model_dump(mode="json")
    assert materialization.provider_dispatch_performed is False
    assert materialization.execution_allowed is False
    assert "payload" not in document
    assert "endpoint" not in document
    assert "credentials" not in document
    assert "sql" not in document


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_materialization_requires_every_plan_position_exactly_once(mode: str) -> None:
    plan_set = _plan_set()
    inputs = _materialization_inputs(plan_set)
    invalid = inputs[:-1] if mode == "missing" else (*inputs, inputs[0])

    with pytest.raises(
        FederatedProjectionCompensationProviderMaterializationError,
        match="every plan position exactly once",
    ):
        build_federated_compensation_provider_materialization_set(
            plan_set,
            invalid,
            materialized_by="workload:chongqing-compensation-materializer",
        )


def test_materialization_rejects_non_workload_identity_and_private_fields() -> None:
    plan_set = _plan_set()
    inputs = _materialization_inputs(plan_set)

    with pytest.raises(
        FederatedProjectionCompensationProviderMaterializationError,
        match="workload identity",
    ):
        build_federated_compensation_provider_materialization_set(
            plan_set,
            inputs,
            materialized_by="human:operator-1",
        )

    with pytest.raises(ValidationError):
        FederatedProjectionCompensationProviderMaterializationInput(
            **inputs[0].model_dump(mode="python"),
            endpoint="https://provider.example.invalid",
            credentials="secret",
            sql="DELETE FROM target",
        )
