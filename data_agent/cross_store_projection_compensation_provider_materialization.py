"""Deployment-owned execution materialization references.

Materialization records only opaque hashes and governed resource references.
They do not carry Provider payloads, credentials, SQL, or endpoints.  The
deployment adapter may use the hashes to locate private execution material,
but this module never invokes that adapter.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    ResourceURNText,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
)


class FederatedProjectionCompensationProviderMaterializationError(ValueError):
    """Execution material cannot be safely bound to a sealed plan set."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


class FederatedProjectionCompensationProviderMaterializationInput(_FrozenModel):
    """Private adapter output digest for one source-plan position."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-materialization-input.v1"
    )
    position: int = Field(ge=0, le=31)
    projection_id: NonEmptyText
    payload_sha256: Sha256
    expected_target_exists: bool
    expected_target_content_sha256: Sha256 | None
    expected_target_row_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _expected_target_state(
        self,
    ) -> FederatedProjectionCompensationProviderMaterializationInput:
        if self.expected_target_exists != (self.expected_target_content_sha256 is not None):
            raise ValueError("materialization expected target state is incomplete")
        if not self.expected_target_exists and self.expected_target_row_count != 0:
            raise ValueError("missing materialization target must have zero rows")
        return self


class FederatedProjectionCompensationProviderMaterializationBinding(_FrozenModel):
    """Opaque materialized operation identity for one Provider target."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-materialization-binding.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    plan_set_sha256: Sha256
    plan_binding_sha256: Sha256
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    provider_action: Literal["checkpoint", "rebuild", "delete"]
    receipt_schema_id: NonEmptyText
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    payload_sha256: Sha256
    expected_target_exists: bool
    expected_target_content_sha256: Sha256 | None
    expected_target_row_count: int = Field(ge=0)
    materialization_ref: ResourceURNText
    materialized_by: NonEmptyText
    materialization_state: Literal["deployment_payload_materialized_pending_provider_dispatch"] = (
        "deployment_payload_materialized_pending_provider_dispatch"
    )
    provider_dispatch_performed: Literal[False] = False
    execution_allowed: Literal[False] = False
    materialization_binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_binding(
        self,
    ) -> FederatedProjectionCompensationProviderMaterializationBinding:
        identity = parse_resource_urn(self.materialization_ref)
        if (
            identity["tenant_id"] != self.tenant_id
            or identity["resource_kind"] != "provider_materialization"
        ):
            raise ValueError("provider materialization reference is not tenant-bound")
        if not self.materialized_by.startswith("workload:"):
            raise ValueError("provider materialization must use a workload identity")
        if self.expected_target_exists != (self.expected_target_content_sha256 is not None):
            raise ValueError("materialization expected target state is incomplete")
        if not self.expected_target_exists and self.expected_target_row_count != 0:
            raise ValueError("missing materialization target must have zero rows")
        if self.provider_action == "rebuild" and not self.expected_target_exists:
            raise ValueError("rebuild materialization must expect an existing target")
        if self.provider_action == "delete" and self.expected_target_exists:
            raise ValueError("delete materialization must expect a missing target")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"materialization_binding_sha256"}),
            "materialization_binding_sha256",
        )
        if self.materialization_binding_sha256 != expected:
            raise ValueError("provider materialization binding fingerprint is invalid")
        return self


class FederatedProjectionCompensationProviderMaterializationSet(_FrozenModel):
    """All opaque materialization bindings for one sealed plan set."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-materialization-set.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    plan_set_sha256: Sha256
    adapter_id: NonEmptyText
    adapter_semantic_version: str
    adapter_sha256: Sha256
    implementation_artifact_sha256: Sha256
    materialized_by: NonEmptyText
    materialization_ref: ResourceURNText
    bindings: tuple[FederatedProjectionCompensationProviderMaterializationBinding, ...] = Field(
        min_length=1, max_length=32
    )
    materialization_state: Literal["deployment_payload_materialized_pending_provider_dispatch"] = (
        "deployment_payload_materialized_pending_provider_dispatch"
    )
    provider_dispatch_performed: Literal[False] = False
    execution_allowed: Literal[False] = False
    materialization_set_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_set(
        self,
    ) -> FederatedProjectionCompensationProviderMaterializationSet:
        identity = parse_resource_urn(self.materialization_ref)
        if (
            identity["tenant_id"] != self.tenant_id
            or identity["resource_kind"] != "provider_materialization"
        ):
            raise ValueError("provider materialization set reference is not tenant-bound")
        positions = tuple(binding.position for binding in self.bindings)
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("provider materialization positions must be unique and ordered")
        for binding in self.bindings:
            if (
                binding.tenant_id != self.tenant_id
                or binding.run_id != self.run_id
                or binding.plan_set_sha256 != self.plan_set_sha256
                or binding.materialized_by != self.materialized_by
                or binding.provider_dispatch_performed
                or binding.execution_allowed
            ):
                raise ValueError("provider materialization binding differs from its set")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"materialization_set_sha256"}),
            "materialization_set_sha256",
        )
        if self.materialization_set_sha256 != expected:
            raise ValueError("provider materialization set fingerprint is invalid")
        return self


def _validated_plan_set(
    plan_set: FederatedProjectionCompensationProviderPlanSet,
) -> FederatedProjectionCompensationProviderPlanSet:
    try:
        return FederatedProjectionCompensationProviderPlanSet.model_validate(
            plan_set.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationProviderMaterializationError(
            "provider materialization plan set violates its sealed contract"
        ) from exc


def _provider_plan_sha256(
    *,
    plan_binding_sha256: str,
    projection_id: str,
    provider_action: str,
    payload_sha256: str,
    expected_target_exists: bool,
    expected_target_content_sha256: str | None,
    expected_target_row_count: int,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": "gda.federated-projection-compensation-provider-plan.v1",
            "plan_binding_sha256": plan_binding_sha256,
            "projection_id": projection_id,
            "provider_action": provider_action,
            "payload_sha256": payload_sha256,
            "expected_target_exists": expected_target_exists,
            "expected_target_content_sha256": expected_target_content_sha256,
            "expected_target_row_count": expected_target_row_count,
        }
    )


def build_federated_compensation_provider_materialization_set(
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    inputs: tuple[FederatedProjectionCompensationProviderMaterializationInput, ...],
    *,
    materialized_by: str,
) -> FederatedProjectionCompensationProviderMaterializationSet:
    """Seal opaque adapter materialization references without dispatching."""

    plan_set = _validated_plan_set(plan_set)
    try:
        normalized_inputs = tuple(
            FederatedProjectionCompensationProviderMaterializationInput.model_validate(
                item.model_dump(mode="python")
            )
            for item in inputs
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationProviderMaterializationError(
            "provider materialization input violates its sealed contract"
        ) from exc
    if not materialized_by.startswith("workload:"):
        raise FederatedProjectionCompensationProviderMaterializationError(
            "provider materialization must use a workload identity"
        )
    by_position = {item.position: item for item in normalized_inputs}
    positions = tuple(binding.position for binding in plan_set.plan_bindings)
    if set(by_position) != set(positions) or len(by_position) != len(normalized_inputs):
        raise FederatedProjectionCompensationProviderMaterializationError(
            "provider materialization inputs must cover every plan position exactly once"
        )
    set_ref = build_resource_urn(
        plan_set.tenant_id,
        "provider_materialization",
        plan_set.plan_set_sha256,
    )
    bindings: list[FederatedProjectionCompensationProviderMaterializationBinding] = []
    for plan_binding in plan_set.plan_bindings:
        item = by_position[plan_binding.position]
        materialization_ref = build_resource_urn(
            plan_set.tenant_id,
            "provider_materialization",
            f"{plan_set.plan_set_sha256[:48]}-{plan_binding.position}",
        )
        provider_plan_sha256 = _provider_plan_sha256(
            plan_binding_sha256=plan_binding.plan_binding_sha256,
            projection_id=item.projection_id,
            provider_action=plan_binding.provider_action,
            payload_sha256=item.payload_sha256,
            expected_target_exists=item.expected_target_exists,
            expected_target_content_sha256=item.expected_target_content_sha256,
            expected_target_row_count=item.expected_target_row_count,
        )
        values = {
            "tenant_id": plan_set.tenant_id,
            "run_id": plan_set.run_id,
            "position": plan_binding.position,
            "plan_set_sha256": plan_set.plan_set_sha256,
            "plan_binding_sha256": plan_binding.plan_binding_sha256,
            "projection_id": item.projection_id,
            "target_engine": plan_binding.target_engine,
            "target_ref": plan_binding.target_ref,
            "provider_action": plan_binding.provider_action,
            "receipt_schema_id": plan_binding.receipt_schema_id,
            "provider_plan_sha256": provider_plan_sha256,
            "provider_idempotency_key": plan_binding.provider_idempotency_key,
            "payload_sha256": item.payload_sha256,
            "expected_target_exists": item.expected_target_exists,
            "expected_target_content_sha256": item.expected_target_content_sha256,
            "expected_target_row_count": item.expected_target_row_count,
            "materialization_ref": materialization_ref,
            "materialized_by": materialized_by,
            "materialization_state": ("deployment_payload_materialized_pending_provider_dispatch"),
            "provider_dispatch_performed": False,
            "execution_allowed": False,
        }
        binding = FederatedProjectionCompensationProviderMaterializationBinding(
            **values,
            materialization_binding_sha256=_fingerprint(
                FederatedProjectionCompensationProviderMaterializationBinding.schema_id,
                values,
                "materialization_binding_sha256",
            ),
        )
        bindings.append(binding)

    values = {
        "tenant_id": plan_set.tenant_id,
        "run_id": plan_set.run_id,
        "plan_set_sha256": plan_set.plan_set_sha256,
        "adapter_id": plan_set.adapter_id,
        "adapter_semantic_version": plan_set.adapter_semantic_version,
        "adapter_sha256": plan_set.adapter_sha256,
        "implementation_artifact_sha256": plan_set.implementation_artifact_sha256,
        "materialized_by": materialized_by,
        "materialization_ref": set_ref,
        "bindings": tuple(bindings),
        "materialization_state": ("deployment_payload_materialized_pending_provider_dispatch"),
        "provider_dispatch_performed": False,
        "execution_allowed": False,
    }
    normalized = FederatedProjectionCompensationProviderMaterializationSet.model_construct(
        **values,
        materialization_set_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"materialization_set_sha256"})
    return FederatedProjectionCompensationProviderMaterializationSet(
        **values,
        materialization_set_sha256=_fingerprint(
            FederatedProjectionCompensationProviderMaterializationSet.schema_id,
            normalized,
            "materialization_set_sha256",
        ),
    )


__all__ = [
    "FederatedProjectionCompensationProviderMaterializationError",
    "FederatedProjectionCompensationProviderMaterializationInput",
    "FederatedProjectionCompensationProviderMaterializationBinding",
    "FederatedProjectionCompensationProviderMaterializationSet",
    "build_federated_compensation_provider_materialization_set",
]
