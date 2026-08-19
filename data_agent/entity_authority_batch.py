"""Typed batch contract and executor for the entity authority boundary.

The HTTP layer authenticates the principal and checks tenant/actor ownership;
this module only validates the canonical payload and calls the existing
authority methods in bounded, deterministic chunks.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import ceil
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .entity_link_authority import (
    EntityLinkAuthority,
    EntitySourceBindingDraft,
    InstanceLinkAssertionDraft,
    InstanceLinkTypeDraft,
)
from .platform_contracts import (
    FrozenContract,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)
from .temporal_entity_authority import (
    TemporalEntityAssertionDraft,
    TemporalEntityAuthority,
)

AuthorityBatchType = Literal[
    "temporal_entity_assertions",
    "source_identity_bindings",
    "link_types",
    "link_assertions",
]


class EntityAuthorityBatchRequest(FrozenContract):
    """One typed authority operation, optionally split into bounded chunks."""

    schema_id: Literal["gda.entity-authority-batch-request.v1"] = (
        "gda.entity-authority-batch-request.v1"
    )
    batch_type: AuthorityBatchType
    tenant_id: TenantId
    idempotency_key: Annotated[
        str,
        Field(
            min_length=3,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$",
        ),
    ]
    batch_size: int = Field(default=250, ge=1, le=500)
    items: tuple[
        Annotated[
            TemporalEntityAssertionDraft
            | EntitySourceBindingDraft
            | InstanceLinkTypeDraft
            | InstanceLinkAssertionDraft,
            Field(discriminator="schema_id"),
        ],
        ...,
    ] = Field(min_length=1, max_length=5_000)

    @model_validator(mode="after")
    def _coherent_batch(self) -> EntityAuthorityBatchRequest:
        expected_schema = {
            "temporal_entity_assertions": "gda.temporal-entity-assertion.v1",
            "source_identity_bindings": "gda.entity-source-binding.v1",
            "link_types": "gda.instance-link-type.v1",
            "link_assertions": "gda.instance-link-assertion.v1",
        }[self.batch_type]
        if any(item.schema_id != expected_schema for item in self.items):
            raise ValueError("items must match batch_type")
        item_tenants = {item.tenant_id for item in self.items}
        if item_tenants != {self.tenant_id}:
            raise ValueError("batch tenant_id must match every item tenant_id")
        return self

    @property
    def logical_operation_count(self) -> int:
        return len(self.items)

    @property
    def batch_count(self) -> int:
        return ceil(len(self.items) / self.batch_size)

    @property
    def request_sha256(self) -> Sha256:
        return canonical_json_fingerprint(self.model_dump(mode="json"))


class EntityAuthorityBatchResponse(FrozenContract):
    schema_id: Literal["gda.entity-authority-batch-response.v1"] = (
        "gda.entity-authority-batch-response.v1"
    )
    tenant_id: TenantId
    batch_type: AuthorityBatchType
    idempotency_key: str
    request_sha256: Sha256
    state_fingerprint: Sha256
    logical_operation_count: int = Field(ge=1)
    batch_count: int = Field(ge=1)
    entity_count: int = Field(ge=0)
    binding_count: int = Field(ge=0)
    link_type_count: int = Field(ge=0)
    link_assertion_count: int = Field(ge=0)
    idempotency_status: Literal["authority_idempotency_enforced"] = (
        "authority_idempotency_enforced"
    )
    technical_baseline_status: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    decision_status: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )


AuthorityBatchItem = (
    TemporalEntityAssertionDraft
    | EntitySourceBindingDraft
    | InstanceLinkTypeDraft
    | InstanceLinkAssertionDraft
)


def _state_fingerprint(items: Sequence[object]) -> Sha256:
    return canonical_json_fingerprint(
        [item.model_dump(mode="json") for item in items]  # type: ignore[attr-defined]
    )


def execute_entity_authority_batch(
    request: EntityAuthorityBatchRequest,
    *,
    temporal_authority: TemporalEntityAuthority | None = None,
    link_authority: EntityLinkAuthority | None = None,
) -> EntityAuthorityBatchResponse:
    """Execute one request as bounded authority batches.

    Each chunk is atomic inside its authority. Cross-chunk continuation is
    intentionally idempotent rather than pretending to be one database
    transaction; the response exposes the exact chunk count.
    """

    temporal = temporal_authority or TemporalEntityAuthority()
    links = link_authority or EntityLinkAuthority()
    results: list[object] = []
    for offset in range(0, len(request.items), request.batch_size):
        chunk = request.items[offset : offset + request.batch_size]
        if request.batch_type == "temporal_entity_assertions":
            results.extend(temporal.record_batch(chunk))  # type: ignore[arg-type]
        elif request.batch_type == "source_identity_bindings":
            results.extend(links.bind_sources_batch(chunk))  # type: ignore[arg-type]
        elif request.batch_type == "link_types":
            results.extend(links.register_link_types_batch(chunk))  # type: ignore[arg-type]
        else:
            results.extend(links.record_links_batch(chunk))  # type: ignore[arg-type]

    counts = {
        "entity_count": len(results) if request.batch_type == "temporal_entity_assertions" else 0,
        "binding_count": len(results) if request.batch_type == "source_identity_bindings" else 0,
        "link_type_count": len(results) if request.batch_type == "link_types" else 0,
        "link_assertion_count": len(results) if request.batch_type == "link_assertions" else 0,
    }
    return EntityAuthorityBatchResponse(
        tenant_id=request.tenant_id,
        batch_type=request.batch_type,
        idempotency_key=request.idempotency_key,
        request_sha256=request.request_sha256,
        state_fingerprint=_state_fingerprint(results),
        logical_operation_count=request.logical_operation_count,
        batch_count=request.batch_count,
        **counts,
    )


__all__ = [
    "AuthorityBatchItem",
    "AuthorityBatchType",
    "EntityAuthorityBatchRequest",
    "EntityAuthorityBatchResponse",
    "execute_entity_authority_batch",
]
