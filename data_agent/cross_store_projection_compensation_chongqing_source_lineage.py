"""Seal per-position Chongqing customer-source lineage for compensation runs.

The customer catalog records the available supplied Chongqing sources, while a
deployment binding records the sealed Provider operations.  This module joins
those two pieces of evidence explicitly: each Provider position must name the
customer source roles it is allowed to use.  It carries only role names and
content fingerprints; customer paths, records, geometries, SQL, endpoints,
credentials, and materialized payloads are intentionally excluded.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_chongqing_deployment import (
    ChongqingCustomerSourceRecord,
    ChongqingFederatedCompensationDeploymentBinding,
    ChongqingFederatedCompensationSourceCatalog,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class ChongqingFederatedCompensationSourceLineageError(ValueError):
    """Customer source lineage cannot be safely joined to a deployment run."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


class ChongqingFederatedCompensationLineageSource(_FrozenModel):
    """Hash-only evidence for one selected Chongqing customer source role."""

    schema_id: ClassVar[str] = "gda.chongqing-federated-compensation-lineage-source.v1"
    source_role: NonEmptyText
    source_content_sha256: Sha256
    source_record_sha256: Sha256
    lineage_source_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationLineageSource:
        if "/" in self.source_role or "\\" in self.source_role:
            raise ValueError("customer source lineage role must not expose a source path")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"lineage_source_sha256"}),
            "lineage_source_sha256",
        )
        if self.lineage_source_sha256 != expected:
            raise ValueError("customer source lineage fingerprint is invalid")
        return self


class ChongqingFederatedCompensationSourceLineageItem(_FrozenModel):
    """One deployment position and its explicit customer-source selection."""

    schema_id: ClassVar[str] = "gda.chongqing-federated-compensation-source-lineage-item.v1"
    position: int = Field(ge=0, le=31)
    deployment_item_sha256: Sha256
    source_plan_sha256: Sha256
    source_content_sha256: Sha256
    customer_sources: tuple[ChongqingFederatedCompensationLineageSource, ...] = Field(
        min_length=1,
        max_length=32,
    )
    lineage_item_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationSourceLineageItem:
        roles = tuple(item.source_role for item in self.customer_sources)
        if roles != tuple(sorted(set(roles))):
            raise ValueError("customer source lineage roles must be unique and sorted")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"lineage_item_sha256"}),
            "lineage_item_sha256",
        )
        if self.lineage_item_sha256 != expected:
            raise ValueError("customer source lineage item fingerprint is invalid")
        return self


class ChongqingFederatedCompensationSourceLineageSet(_FrozenModel):
    """Read-only source lineage pinned to one Chongqing deployment binding."""

    schema_id: ClassVar[str] = "gda.chongqing-federated-compensation-source-lineage-set.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    deployment_binding_sha256: Sha256
    source_catalog_sha256: Sha256
    field_mapping_set_sha256: Sha256
    items: tuple[ChongqingFederatedCompensationSourceLineageItem, ...] = Field(
        min_length=1,
        max_length=32,
    )
    lineage_state: Literal["customer_source_lineage_bound_pending_provider_execution"] = (
        "customer_source_lineage_bound_pending_provider_execution"
    )
    provider_dispatch_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    source_lineage_set_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationSourceLineageSet:
        positions = tuple(item.position for item in self.items)
        if positions != tuple(range(len(self.items))):
            raise ValueError("customer source lineage positions must be contiguous and ordered")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"source_lineage_set_sha256"}),
            "source_lineage_set_sha256",
        )
        if self.source_lineage_set_sha256 != expected:
            raise ValueError("customer source lineage set fingerprint is invalid")
        return self


def _validated_inputs(
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
) -> tuple[
    ChongqingFederatedCompensationSourceCatalog,
    ChongqingFederatedCompensationDeploymentBinding,
]:
    try:
        return (
            ChongqingFederatedCompensationSourceCatalog.model_validate(
                source_catalog.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationDeploymentBinding.model_validate(
                deployment_binding.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationSourceLineageError(
            "Chongqing source lineage input violates a sealed contract"
        ) from exc


def _selected_sources(
    source_by_role: Mapping[str, ChongqingCustomerSourceRecord],
    source_roles: tuple[str, ...],
) -> tuple[ChongqingFederatedCompensationLineageSource, ...]:
    if not source_roles:
        raise ChongqingFederatedCompensationSourceLineageError(
            "every deployment position must select at least one customer source role"
        )
    if source_roles != tuple(sorted(set(source_roles))):
        raise ChongqingFederatedCompensationSourceLineageError(
            "customer source roles must be unique and sorted per deployment position"
        )
    selected: list[ChongqingFederatedCompensationLineageSource] = []
    for source_role in source_roles:
        source = source_by_role.get(source_role)
        if source is None:
            raise ChongqingFederatedCompensationSourceLineageError(
                "selected customer source role is absent from the Chongqing catalog"
            )
        values = {
            "source_role": source.source_role,
            "source_content_sha256": source.source_content_sha256,
            "source_record_sha256": source.source_record_sha256,
        }
        selected.append(
            ChongqingFederatedCompensationLineageSource(
                **values,
                lineage_source_sha256=_fingerprint(
                    ChongqingFederatedCompensationLineageSource.schema_id,
                    values,
                    "lineage_source_sha256",
                ),
            )
        )
    return tuple(selected)


def build_chongqing_federated_compensation_source_lineage_set(
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    source_roles_by_position: Mapping[int, tuple[str, ...]],
) -> ChongqingFederatedCompensationSourceLineageSet:
    """Bind each sealed Provider position to explicit supplied customer source roles."""

    source_catalog, deployment_binding = _validated_inputs(
        source_catalog,
        deployment_binding,
    )
    if (
        deployment_binding.source_catalog_sha256 != source_catalog.source_catalog_sha256
        or deployment_binding.field_mapping_set_sha256
        != source_catalog.field_mapping_set_sha256
    ):
        raise ChongqingFederatedCompensationSourceLineageError(
            "Chongqing deployment binding differs from the customer source catalog"
        )
    if not isinstance(source_roles_by_position, Mapping):
        raise ChongqingFederatedCompensationSourceLineageError(
            "customer source lineage selections must be a position mapping"
        )
    expected_positions = tuple(item.position for item in deployment_binding.items)
    actual_positions = tuple(source_roles_by_position)
    if (
        any(
            not isinstance(position, int) or isinstance(position, bool)
            for position in actual_positions
        )
        or set(actual_positions) != set(expected_positions)
        or len(actual_positions) != len(expected_positions)
    ):
        raise ChongqingFederatedCompensationSourceLineageError(
            "customer source lineage selections must cover every deployment position exactly once"
        )
    source_by_role = {item.source_role: item for item in source_catalog.sources}
    items: list[ChongqingFederatedCompensationSourceLineageItem] = []
    for deployment_item in deployment_binding.items:
        source_roles = source_roles_by_position[deployment_item.position]
        if not isinstance(source_roles, tuple) or any(
            not isinstance(source_role, str) for source_role in source_roles
        ):
            raise ChongqingFederatedCompensationSourceLineageError(
                "customer source roles must be a tuple of text values"
            )
        selected = _selected_sources(source_by_role, source_roles)
        values = {
            "position": deployment_item.position,
            "deployment_item_sha256": deployment_item.item_sha256,
            "source_plan_sha256": deployment_item.source_plan_sha256,
            "source_content_sha256": deployment_item.source_content_sha256,
            "customer_sources": selected,
        }
        items.append(
            ChongqingFederatedCompensationSourceLineageItem(
                **values,
                lineage_item_sha256=_fingerprint(
                    ChongqingFederatedCompensationSourceLineageItem.schema_id,
                    values,
                    "lineage_item_sha256",
                ),
            )
        )
    values = {
        "tenant_id": deployment_binding.tenant_id,
        "run_id": deployment_binding.run_id,
        "deployment_binding_sha256": deployment_binding.deployment_binding_sha256,
        "source_catalog_sha256": source_catalog.source_catalog_sha256,
        "field_mapping_set_sha256": source_catalog.field_mapping_set_sha256,
        "items": tuple(items),
        "lineage_state": "customer_source_lineage_bound_pending_provider_execution",
        "provider_dispatch_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationSourceLineageSet(
        **values,
        source_lineage_set_sha256=_fingerprint(
            ChongqingFederatedCompensationSourceLineageSet.schema_id,
            values,
            "source_lineage_set_sha256",
        ),
    )


__all__ = [
    "ChongqingFederatedCompensationLineageSource",
    "ChongqingFederatedCompensationSourceLineageError",
    "ChongqingFederatedCompensationSourceLineageItem",
    "ChongqingFederatedCompensationSourceLineageSet",
    "build_chongqing_federated_compensation_source_lineage_set",
]
