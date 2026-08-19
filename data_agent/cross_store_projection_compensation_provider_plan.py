"""Seal non-executing Provider plan bindings for customer compensation.

The plan set maps a current dispatch intent to deployment-owned adapter
contracts.  It deliberately contains no Provider payload, endpoint, SQL, or
credential.  Building it is evidence preparation only and never invokes an
adapter or Provider.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_proposal import CompensationProposalAction
from .cross_store_projection_compensation_provider_adapter import (
    FederatedProjectionCompensationProviderAdapterResolution,
    FederatedProjectionCompensationProviderReceiptContract,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    ShortName,
    TenantId,
    canonical_json_fingerprint,
)


class FederatedProjectionCompensationProviderPlanError(ValueError):
    """A dispatch and adapter resolution cannot form a sealed plan set."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def federated_compensation_provider_plan_idempotency_key(
    **values: Any,
) -> str:
    payload = dict(values)
    payload.pop("provider_idempotency_key", None)
    payload.pop("plan_binding_sha256", None)
    return canonical_json_fingerprint(
        {
            "schema": "gda.federated-projection-compensation-provider-plan-idempotency.v1",
            "data": payload,
        }
    )


def federated_compensation_provider_plan_binding_fingerprint(
    **values: Any,
) -> str:
    return _fingerprint(
        FederatedProjectionCompensationProviderPlanBinding.schema_id,
        values,
        "plan_binding_sha256",
    )


def federated_compensation_provider_plan_set_fingerprint(**values: Any) -> str:
    return _fingerprint(
        FederatedProjectionCompensationProviderPlanSet.schema_id,
        values,
        "plan_set_sha256",
    )


class FederatedProjectionCompensationProviderPlanBinding(_FrozenModel):
    """One source-plan identity mapped to a deployment operation contract."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-plan-binding.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    dispatch_intent_sha256: Sha256
    adapter_resolution_sha256: Sha256
    source_plan_sha256: Sha256
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    candidate_action: CompensationProposalAction
    adapter_id: ShortName
    adapter_semantic_version: str = Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
    )
    adapter_sha256: Sha256
    implementation_artifact_sha256: Sha256
    provider_action: Literal["checkpoint", "rebuild", "delete"]
    operation_contract_sha256: Sha256
    receipt_schema_id: NonEmptyText
    provider_idempotency_key: Sha256
    execution_material_state: Literal["deployment_payload_not_materialized"] = (
        "deployment_payload_not_materialized"
    )
    provider_dispatch_performed: Literal[False] = False
    execution_allowed: Literal[False] = False
    plan_binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_binding(
        self,
    ) -> FederatedProjectionCompensationProviderPlanBinding:
        FederatedProjectionCompensationProviderReceiptContract(
            target_engine=self.target_engine,
            receipt_schema_id=self.receipt_schema_id,
        )
        values = self.model_dump(
            mode="json",
            exclude={"provider_idempotency_key", "plan_binding_sha256"},
        )
        expected_key = federated_compensation_provider_plan_idempotency_key(
            **values
        )
        if self.provider_idempotency_key != expected_key:
            raise ValueError("provider plan idempotency key is invalid")
        expected = federated_compensation_provider_plan_binding_fingerprint(
            **self.model_dump(mode="json", exclude={"plan_binding_sha256"})
        )
        if self.plan_binding_sha256 != expected:
            raise ValueError("provider plan binding fingerprint is invalid")
        return self


class FederatedProjectionCompensationProviderPlanSet(_FrozenModel):
    """Complete non-dispatching handoff evidence for one adapter resolution."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-plan-set.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    dispatch_intent_sha256: Sha256
    adapter_resolution_sha256: Sha256
    adapter_id: ShortName
    adapter_semantic_version: str = Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
    )
    adapter_sha256: Sha256
    implementation_artifact_sha256: Sha256
    candidate_action: CompensationProposalAction
    plan_bindings: tuple[
        FederatedProjectionCompensationProviderPlanBinding, ...
    ] = Field(min_length=1, max_length=32)
    execution_material_state: Literal["deployment_payload_not_materialized"] = (
        "deployment_payload_not_materialized"
    )
    provider_dispatch_performed: Literal[False] = False
    execution_allowed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    plan_set_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_set(self) -> FederatedProjectionCompensationProviderPlanSet:
        positions = tuple(binding.position for binding in self.plan_bindings)
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("provider plan positions must be unique and ordered")
        source_plans = tuple(
            binding.source_plan_sha256 for binding in self.plan_bindings
        )
        if len(set(source_plans)) != len(source_plans):
            raise ValueError("provider plan source identities must be unique")
        idempotency_keys = tuple(
            binding.provider_idempotency_key for binding in self.plan_bindings
        )
        if len(set(idempotency_keys)) != len(idempotency_keys):
            raise ValueError("provider plan idempotency keys must be unique")
        for binding in self.plan_bindings:
            if (
                binding.tenant_id != self.tenant_id
                or binding.run_id != self.run_id
                or binding.dispatch_intent_sha256 != self.dispatch_intent_sha256
                or binding.adapter_resolution_sha256
                != self.adapter_resolution_sha256
                or binding.adapter_id != self.adapter_id
                or binding.adapter_semantic_version
                != self.adapter_semantic_version
                or binding.adapter_sha256 != self.adapter_sha256
                or binding.implementation_artifact_sha256
                != self.implementation_artifact_sha256
                or binding.candidate_action is not self.candidate_action
            ):
                raise ValueError("provider plan binding differs from plan set")
        expected = federated_compensation_provider_plan_set_fingerprint(
            **self.model_dump(mode="json", exclude={"plan_set_sha256"})
        )
        if self.plan_set_sha256 != expected:
            raise ValueError("provider plan set fingerprint is invalid")
        return self


def _validated_inputs(
    intent: FederatedProjectionCompensationDispatchIntent,
    resolution: FederatedProjectionCompensationProviderAdapterResolution,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderAdapterResolution,
]:
    try:
        return (
            FederatedProjectionCompensationDispatchIntent.model_validate(
                intent.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderAdapterResolution.model_validate(
                resolution.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationProviderPlanError(
            "provider plan input violates its sealed contract"
        ) from exc


def build_federated_compensation_provider_plan_set(
    intent: FederatedProjectionCompensationDispatchIntent,
    resolution: FederatedProjectionCompensationProviderAdapterResolution,
) -> FederatedProjectionCompensationProviderPlanSet:
    """Map sealed source plans to deployment contracts without Provider dispatch."""

    intent, resolution = _validated_inputs(intent, resolution)
    if (
        resolution.tenant_id != intent.tenant_id
        or resolution.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or resolution.candidate_action is not intent.candidate_action
        or resolution.provider_dispatch_performed
        or resolution.execution_allowed
    ):
        raise FederatedProjectionCompensationProviderPlanError(
            "adapter resolution differs from dispatch intent"
        )

    targets = {target.identity for target in resolution.targets}
    receipt_by_engine = {
        contract.target_engine: contract for contract in resolution.receipt_contracts
    }
    mutation_by_engine = {
        contract.target_engine: contract for contract in resolution.mutation_contracts
    }
    bindings: list[FederatedProjectionCompensationProviderPlanBinding] = []
    for source in intent.plan_bindings:
        try:
            engine = ProjectionEngine(source.target_engine)
            receipt = receipt_by_engine[engine]
            mutation = mutation_by_engine[engine]
        except (ValueError, KeyError) as exc:
            raise FederatedProjectionCompensationProviderPlanError(
                "dispatch target lacks a deployment operation or receipt contract"
            ) from exc
        if (engine.value, source.target_ref) not in targets:
            raise FederatedProjectionCompensationProviderPlanError(
                "dispatch target is not present in adapter resolution"
            )
        values = {
            "tenant_id": intent.tenant_id,
            "run_id": intent.run_id,
            "position": source.position,
            "dispatch_intent_sha256": intent.dispatch_intent_sha256,
            "adapter_resolution_sha256": resolution.resolution_sha256,
            "source_plan_sha256": source.plan_sha256,
            "source_resource_version_ref": source.source_resource_version_ref,
            "source_content_sha256": source.source_content_sha256,
            "target_engine": engine,
            "target_ref": source.target_ref,
            "candidate_action": intent.candidate_action,
            "adapter_id": resolution.adapter_id,
            "adapter_semantic_version": resolution.adapter_semantic_version,
            "adapter_sha256": resolution.adapter_sha256,
            "implementation_artifact_sha256": (
                resolution.implementation_artifact_sha256
            ),
            "provider_action": mutation.provider_action,
            "operation_contract_sha256": mutation.operation_contract_sha256,
            "receipt_schema_id": receipt.receipt_schema_id,
            "execution_material_state": "deployment_payload_not_materialized",
            "provider_dispatch_performed": False,
            "execution_allowed": False,
        }
        normalized = (
            FederatedProjectionCompensationProviderPlanBinding.model_construct(
                **values,
                provider_idempotency_key="0" * 64,
                plan_binding_sha256="0" * 64,
            ).model_dump(
                mode="json",
                exclude={"provider_idempotency_key", "plan_binding_sha256"},
            )
        )
        idempotency_key = federated_compensation_provider_plan_idempotency_key(
            **normalized
        )
        binding_values = {
            **values,
            "provider_idempotency_key": idempotency_key,
        }
        normalized_binding = (
            FederatedProjectionCompensationProviderPlanBinding.model_construct(
                **binding_values,
                plan_binding_sha256="0" * 64,
            ).model_dump(mode="json", exclude={"plan_binding_sha256"})
        )
        bindings.append(
            FederatedProjectionCompensationProviderPlanBinding(
                **binding_values,
                plan_binding_sha256=(
                    federated_compensation_provider_plan_binding_fingerprint(
                        **normalized_binding
                    )
                ),
            )
        )

    values = {
        "tenant_id": intent.tenant_id,
        "run_id": intent.run_id,
        "dispatch_intent_sha256": intent.dispatch_intent_sha256,
        "adapter_resolution_sha256": resolution.resolution_sha256,
        "adapter_id": resolution.adapter_id,
        "adapter_semantic_version": resolution.adapter_semantic_version,
        "adapter_sha256": resolution.adapter_sha256,
        "implementation_artifact_sha256": (
            resolution.implementation_artifact_sha256
        ),
        "candidate_action": intent.candidate_action,
        "plan_bindings": tuple(bindings),
        "execution_material_state": "deployment_payload_not_materialized",
        "provider_dispatch_performed": False,
        "execution_allowed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized_set = FederatedProjectionCompensationProviderPlanSet.model_construct(
        **values,
        plan_set_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"plan_set_sha256"})
    return FederatedProjectionCompensationProviderPlanSet(
        **values,
        plan_set_sha256=federated_compensation_provider_plan_set_fingerprint(
            **normalized_set
        ),
    )


__all__ = [
    "FederatedProjectionCompensationProviderPlanError",
    "FederatedProjectionCompensationProviderPlanBinding",
    "FederatedProjectionCompensationProviderPlanSet",
    "build_federated_compensation_provider_plan_set",
    "federated_compensation_provider_plan_binding_fingerprint",
    "federated_compensation_provider_plan_idempotency_key",
    "federated_compensation_provider_plan_set_fingerprint",
]
