from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_compensation_approval import (
    build_federated_projection_compensation_execution_approval_case,
    build_federated_projection_compensation_execution_binding,
)
from data_agent.cross_store_projection_compensation_dispatch import (
    build_federated_projection_compensation_dispatch_intent,
)
from data_agent.cross_store_projection_compensation_execution_authority import (
    FederatedCompensationExecutionAuthorizationConsumptionReceipt,
)
from data_agent.cross_store_projection_compensation_proposal import (
    CompensationProposalAction,
)
from data_agent.cross_store_projection_compensation_provider_adapter import (
    FederatedProjectionCompensationProviderAdapterConfigurationError,
    FederatedProjectionCompensationProviderAdapterError,
    FederatedProjectionCompensationProviderAdapterResolutionRequest,
    FederatedProjectionCompensationProviderAdapterTarget,
    FederatedProjectionCompensationProviderMutationContract,
    FederatedProjectionCompensationProviderReceiptContract,
    build_federated_compensation_provider_adapter_definition,
    build_federated_compensation_provider_adapter_registry,
    load_federated_compensation_provider_adapter_registry,
    resolve_federated_compensation_provider_adapter,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.test_cross_store_projection_compensation_approval import (
    _approved_review,
)


def _inputs():
    evidence, _, review_binding, _, approved, request = _approved_review()
    execution_binding = build_federated_projection_compensation_execution_binding(
        review_binding,
        approved,
        request,
    )
    execution_case = build_federated_projection_compensation_execution_approval_case(
        execution_binding,
        request,
        requester_subject="human:operator-1",
    )
    receipt = FederatedCompensationExecutionAuthorizationConsumptionReceipt(
        tenant_id=execution_binding.tenant_id,
        execution_approval_case_ref=execution_case.approval_case_ref,
        review_approval_case_ref=execution_binding.review_approval_case_ref,
        proposal_sha256=execution_binding.proposal_sha256,
        candidate_sha256=execution_binding.candidate_sha256,
        execution_authorization_sha256=(
            execution_binding.execution_authorization_sha256
        ),
        review_binding_sha256=review_binding.binding_sha256,
        execution_decided_by="human:execution-reviewer",
        review_decided_by="human:reviewer-1",
        consumed_by="workload:controlled-compensation-executor",
        consume_reason="Reserve one approved customer-rule dispatch",
        consumed_at=datetime(2026, 8, 16, 14, tzinfo=UTC),
    )
    intent = build_federated_projection_compensation_dispatch_intent(
        evidence,
        execution_binding,
        receipt,
    )
    target_values = tuple(
        sorted(
            {
                (ProjectionEngine(binding.target_engine), binding.target_ref)
                for binding in intent.plan_bindings
            },
            key=lambda value: (value[0].value, value[1]),
        )
    )
    targets = tuple(
        FederatedProjectionCompensationProviderAdapterTarget(
            target_engine=engine,
            target_ref=target_ref,
        )
        for engine, target_ref in target_values
    )
    contracts = tuple(
        FederatedProjectionCompensationProviderReceiptContract(
            target_engine=engine,
            receipt_schema_id={
                ProjectionEngine.POSTGIS: "gda.postgis-projection-repair-receipt.v1",
                ProjectionEngine.VECTOR: "gda.vector-projection-repair-receipt.v1",
                ProjectionEngine.RDF: "gda.rdf-projection-repair-receipt.v1",
                ProjectionEngine.OBJECT_STORE: "gda.object-projection-repair-receipt.v1",
                ProjectionEngine.LAKEHOUSE: "gda.lakehouse-projection-repair-receipt.v1",
            }[engine],
        )
        for engine in sorted({engine for engine, _ in target_values}, key=lambda value: value.value)
    )
    mutation_contracts = tuple(
        FederatedProjectionCompensationProviderMutationContract(
            target_engine=engine,
            candidate_action=intent.candidate_action,
            provider_action="rebuild",
            operation_contract_sha256=f"{position + 1:064x}",
        )
        for position, engine in enumerate(
            sorted(
                {engine for engine, _ in target_values},
                key=lambda value: value.value,
            )
        )
    )
    adapter = build_federated_compensation_provider_adapter_definition(
        tenant_id=intent.tenant_id,
        adapter_id="chongqing-compensation-adapter",
        semantic_version="0.1.0",
        implementation_artifact_sha256="a" * 64,
        targets=targets,
        supported_actions=(intent.candidate_action,),
        receipt_contracts=contracts,
        mutation_contracts=mutation_contracts,
    )
    registry = build_federated_compensation_provider_adapter_registry((adapter,))
    resolution_request = FederatedProjectionCompensationProviderAdapterResolutionRequest(
        tenant_id=intent.tenant_id,
        dispatch_intent_sha256=intent.dispatch_intent_sha256,
        adapter_id=adapter.adapter_id,
        adapter_semantic_version=adapter.semantic_version,
        adapter_sha256=adapter.adapter_sha256,
        registry_sha256=registry.registry_sha256,
        requested_by="workload:controlled-compensation-executor",
    )
    return intent, adapter, registry, resolution_request


def test_registered_adapter_resolution_is_pending_and_non_executing() -> None:
    intent, adapter, registry, request = _inputs()

    resolution = resolve_federated_compensation_provider_adapter(
        intent,
        request,
        registry,
    )

    assert resolution.adapter_id == adapter.adapter_id
    assert tuple(target.target_ref for target in resolution.targets) == tuple(
        target_ref
        for _, target_ref in sorted(
            {
                (binding.target_engine, binding.target_ref)
                for binding in intent.plan_bindings
            }
        )
    )
    assert resolution.candidate_action is intent.candidate_action
    assert resolution.resolution_state == "adapter_resolved_pending_execution"
    assert resolution.provider_dispatch_performed is False
    assert resolution.execution_allowed is False
    assert resolution.review_state == "technical_baseline_unreviewed"
    assert resolution.intended_use == "assisted_precheck_not_for_production_decision"


def test_unregistered_or_drifted_adapter_fails_closed() -> None:
    intent, adapter, registry, request = _inputs()

    with pytest.raises(
        FederatedProjectionCompensationProviderAdapterError,
        match="not registered",
    ):
        resolve_federated_compensation_provider_adapter(
            intent,
            request.model_copy(update={"adapter_sha256": "f" * 64}),
            registry,
        )

    with pytest.raises(
        FederatedProjectionCompensationProviderAdapterError,
        match="targets differ",
    ):
        drifted_targets = tuple(
            target.model_copy(
                update={"target_ref": f"{target.target_ref}-drifted"}
            )
            if position == 0
            else target
            for position, target in enumerate(adapter.targets)
        )
        drifted = build_federated_compensation_provider_adapter_definition(
            tenant_id=adapter.tenant_id,
            adapter_id=adapter.adapter_id,
            semantic_version=adapter.semantic_version,
            implementation_artifact_sha256=(
                adapter.implementation_artifact_sha256
            ),
            targets=drifted_targets,
            supported_actions=adapter.supported_actions,
            receipt_contracts=adapter.receipt_contracts,
            mutation_contracts=adapter.mutation_contracts,
        )
        drifted_registry = build_federated_compensation_provider_adapter_registry(
            (drifted,)
        )
        drifted_request = request.model_copy(
            update={
                "adapter_sha256": drifted.adapter_sha256,
                "registry_sha256": drifted_registry.registry_sha256,
            }
        )
        resolve_federated_compensation_provider_adapter(
            intent,
            drifted_request,
            drifted_registry,
        )


def test_resolution_request_cannot_carry_provider_secrets_or_sql() -> None:
    _, _, _, request = _inputs()

    with pytest.raises(ValidationError):
        FederatedProjectionCompensationProviderAdapterResolutionRequest(
            **request.model_dump(mode="python"),
            endpoint="https://provider.example.invalid",
            credentials="secret",
            sql="DELETE FROM target",
        )

    assert "endpoint" not in request.model_dump(mode="json")
    assert "credentials" not in request.model_dump(mode="json")
    assert "sql" not in request.model_dump(mode="json")


def test_adapter_action_and_registry_configuration_are_fail_closed() -> None:
    intent, adapter, registry, request = _inputs()
    unsupported_mutation_contracts = tuple(
        FederatedProjectionCompensationProviderMutationContract(
            target_engine=contract.target_engine,
            candidate_action=CompensationProposalAction.DELETE_TARGET,
            provider_action="delete",
            operation_contract_sha256=f"{position + 17:064x}",
        )
        for position, contract in enumerate(adapter.receipt_contracts)
    )
    unsupported = build_federated_compensation_provider_adapter_definition(
        tenant_id=adapter.tenant_id,
        adapter_id=adapter.adapter_id,
        semantic_version="0.2.0",
        implementation_artifact_sha256=adapter.implementation_artifact_sha256,
        targets=adapter.targets,
        supported_actions=(CompensationProposalAction.DELETE_TARGET,),
        receipt_contracts=adapter.receipt_contracts,
        mutation_contracts=unsupported_mutation_contracts,
    )
    unsupported_registry = build_federated_compensation_provider_adapter_registry(
        (unsupported,)
    )
    unsupported_request = request.model_copy(
        update={
            "adapter_semantic_version": unsupported.semantic_version,
            "adapter_sha256": unsupported.adapter_sha256,
            "registry_sha256": unsupported_registry.registry_sha256,
        }
    )
    with pytest.raises(
        FederatedProjectionCompensationProviderAdapterError,
        match="does not support",
    ):
        resolve_federated_compensation_provider_adapter(
            intent,
            unsupported_request,
            unsupported_registry,
        )

    assert load_federated_compensation_provider_adapter_registry(" ").adapters == ()
    with pytest.raises(
        FederatedProjectionCompensationProviderAdapterConfigurationError,
        match="valid JSON",
    ):
        load_federated_compensation_provider_adapter_registry("{")
    with pytest.raises(
        FederatedProjectionCompensationProviderAdapterConfigurationError,
        match="JSON array",
    ):
        load_federated_compensation_provider_adapter_registry("{}")
