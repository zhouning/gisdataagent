"""Validate Provider-native receipt candidates without admitting authority state.

The validator reuses the five existing Provider receipt models and fingerprint
functions.  A successful result proves structural and cryptographic binding to
one materialized plan only; it does not write a checkpoint, mark execution
complete, or make a production decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationBinding,
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_consistency import ProjectionEngine
from .lakehouse_projection_executor import (
    LakehouseProjectionRepairReceipt,
    lakehouse_projection_receipt_fingerprint,
)
from .object_projection_executor import (
    ObjectProjectionRepairReceipt,
    object_projection_receipt_fingerprint,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)
from .postgis_projection_executor import (
    PostGISProjectionRepairReceipt,
    postgis_projection_receipt_fingerprint,
)
from .rdf_projection_executor import (
    RDFProjectionRepairReceipt,
    rdf_projection_receipt_fingerprint,
)
from .vector_projection_executor import (
    VectorProjectionRepairReceipt,
    vector_projection_receipt_fingerprint,
)


class FederatedProjectionCompensationProviderReceiptValidationError(ValueError):
    """A Provider receipt candidate is invalid or differs from materialization."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_RECEIPT_MODEL_BY_ENGINE: dict[ProjectionEngine, type[BaseModel]] = {
    ProjectionEngine.POSTGIS: PostGISProjectionRepairReceipt,
    ProjectionEngine.VECTOR: VectorProjectionRepairReceipt,
    ProjectionEngine.RDF: RDFProjectionRepairReceipt,
    ProjectionEngine.OBJECT_STORE: ObjectProjectionRepairReceipt,
    ProjectionEngine.LAKEHOUSE: LakehouseProjectionRepairReceipt,
}


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


class FederatedProjectionCompensationProviderReceiptCandidate(_FrozenModel):
    """Unadmitted native receipt document returned by a deployment adapter."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-provider-receipt-candidate.v1"
    tenant_id: TenantId
    materialization_set_sha256: Sha256
    materialization_binding_sha256: Sha256
    plan_binding_sha256: Sha256
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    receipt_schema_id: NonEmptyText
    receipt_document: dict[str, Any] = Field(min_length=1)
    receipt_candidate_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_candidate(
        self,
    ) -> FederatedProjectionCompensationProviderReceiptCandidate:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"receipt_candidate_sha256"}),
            "receipt_candidate_sha256",
        )
        if self.receipt_candidate_sha256 != expected:
            raise ValueError("provider receipt candidate fingerprint is invalid")
        return self


class FederatedProjectionCompensationProviderReceiptValidation(_FrozenModel):
    """Validated receipt evidence that remains outside checkpoint authority."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-receipt-validation.v1"
    )
    tenant_id: TenantId
    materialization_set_sha256: Sha256
    materialization_binding_sha256: Sha256
    plan_binding_sha256: Sha256
    receipt_candidate_sha256: Sha256
    target_engine: ProjectionEngine
    projection_id: NonEmptyText
    target_ref: NonEmptyText
    provider_action: Literal["checkpoint", "rebuild", "delete"]
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    receipt_schema_id: NonEmptyText
    provider_receipt_sha256: Sha256
    receipt_status: Literal["completed", "replayed", "checkpointed", "deleted"]
    target_exists: bool
    target_content_sha256: Sha256 | None = None
    target_row_count: int = Field(ge=0)
    observed_at: datetime
    validation_state: Literal["validated_not_authority_admitted"] = (
        "validated_not_authority_admitted"
    )
    authority_write_allowed: Literal[False] = False
    provider_execution_performed: Literal[False] = False
    receipt_is_authority_record: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    validation_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_validation(
        self,
    ) -> FederatedProjectionCompensationProviderReceiptValidation:
        if self.target_exists != (self.target_content_sha256 is not None):
            raise ValueError("validated receipt target content differs from existence")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"validation_sha256"}),
            "validation_sha256",
        )
        if self.validation_sha256 != expected:
            raise ValueError("provider receipt validation fingerprint is invalid")
        return self


def build_federated_compensation_provider_receipt_candidate(
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    binding: FederatedProjectionCompensationProviderMaterializationBinding,
    receipt_document: dict[str, Any],
) -> FederatedProjectionCompensationProviderReceiptCandidate:
    """Seal an untrusted Provider document before model-specific validation."""

    try:
        materialization = FederatedProjectionCompensationProviderMaterializationSet.model_validate(
            materialization.model_dump(mode="python")
        )
        binding = FederatedProjectionCompensationProviderMaterializationBinding.model_validate(
            binding.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider receipt materialization evidence is invalid"
        ) from exc
    if binding not in materialization.bindings:
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider receipt binding is not part of materialization set"
        )
    values = {
        "tenant_id": binding.tenant_id,
        "materialization_set_sha256": materialization.materialization_set_sha256,
        "materialization_binding_sha256": binding.materialization_binding_sha256,
        "plan_binding_sha256": binding.plan_binding_sha256,
        "target_engine": binding.target_engine,
        "target_ref": binding.target_ref,
        "receipt_schema_id": binding.receipt_schema_id,
        "receipt_document": receipt_document,
    }
    normalized = FederatedProjectionCompensationProviderReceiptCandidate.model_construct(
        **values,
        receipt_candidate_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"receipt_candidate_sha256"})
    return FederatedProjectionCompensationProviderReceiptCandidate(
        **values,
        receipt_candidate_sha256=_fingerprint(
            FederatedProjectionCompensationProviderReceiptCandidate.schema_id,
            normalized,
            "receipt_candidate_sha256",
        ),
    )


def _expected_receipt_sha256(
    engine: ProjectionEngine,
    receipt: Any,
) -> str:
    common = {
        "tenant_id": receipt.tenant_id,
        "projection_id": receipt.projection_id,
        "target_ref": receipt.target_ref,
        "action": receipt.action,
        "plan_sha256": receipt.plan_sha256,
        "idempotency_key": receipt.idempotency_key,
        "provider_commit_ref": receipt.provider_commit_ref,
        "target_exists": receipt.target_exists,
        "target_content_sha256": receipt.target_content_sha256,
        "target_row_count": receipt.target_row_count,
    }
    if engine is ProjectionEngine.POSTGIS:
        return postgis_projection_receipt_fingerprint(**common)
    if engine is ProjectionEngine.VECTOR:
        return vector_projection_receipt_fingerprint(**common)
    if engine is ProjectionEngine.RDF:
        return rdf_projection_receipt_fingerprint(**common)
    if engine is ProjectionEngine.OBJECT_STORE:
        return object_projection_receipt_fingerprint(
            **common,
            target_size_bytes=receipt.target_size_bytes,
        )
    if engine is ProjectionEngine.LAKEHOUSE:
        return lakehouse_projection_receipt_fingerprint(**common)
    raise FederatedProjectionCompensationProviderReceiptValidationError(
        "provider receipt target engine is unsupported"
    )


def validate_federated_compensation_provider_receipt_candidate(
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    candidate: FederatedProjectionCompensationProviderReceiptCandidate,
) -> FederatedProjectionCompensationProviderReceiptValidation:
    """Validate one native receipt without writing or admitting authority state."""

    try:
        materialization = FederatedProjectionCompensationProviderMaterializationSet.model_validate(
            materialization.model_dump(mode="python")
        )
        candidate = FederatedProjectionCompensationProviderReceiptCandidate.model_validate(
            candidate.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider receipt validation input violates its sealed contract"
        ) from exc
    binding = next(
        (
            item
            for item in materialization.bindings
            if item.materialization_binding_sha256 == candidate.materialization_binding_sha256
        ),
        None,
    )
    if binding is None or (
        candidate.tenant_id != materialization.tenant_id
        or candidate.materialization_set_sha256 != materialization.materialization_set_sha256
        or candidate.plan_binding_sha256 != binding.plan_binding_sha256
        or candidate.target_engine is not binding.target_engine
        or candidate.target_ref != binding.target_ref
        or candidate.receipt_schema_id != binding.receipt_schema_id
    ):
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider receipt candidate differs from materialization"
        )
    model = _RECEIPT_MODEL_BY_ENGINE[binding.target_engine]
    if candidate.receipt_schema_id != model.schema_id:
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider receipt schema differs from target engine"
        )
    try:
        receipt = model.model_validate(candidate.receipt_document)
    except (TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider-native receipt document is invalid"
        ) from exc
    if (
        receipt.tenant_id != binding.tenant_id
        or receipt.projection_id != binding.projection_id
        or receipt.target_ref != binding.target_ref
        or receipt.action != binding.provider_action
        or receipt.plan_sha256 != binding.provider_plan_sha256
        or receipt.idempotency_key != binding.provider_idempotency_key
    ):
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider-native receipt differs from materialized plan"
        )
    allowed_statuses = {
        "checkpoint": {"checkpointed", "replayed"},
        "rebuild": {"completed", "replayed"},
        "delete": {"deleted", "replayed"},
    }
    if receipt.status not in allowed_statuses[receipt.action]:
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider-native receipt status differs from provider action"
        )
    if receipt.action == "delete" and receipt.target_exists:
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider-native delete receipt still reports an existing target"
        )
    if receipt.action == "rebuild" and not receipt.target_exists:
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider-native rebuild receipt reports a missing target"
        )
    if (
        receipt.target_exists != binding.expected_target_exists
        or receipt.target_content_sha256 != binding.expected_target_content_sha256
        or receipt.target_row_count != binding.expected_target_row_count
    ):
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider-native receipt outcome differs from materialized expectation"
        )
    provider_receipt_sha256 = receipt.provider_commit_ref.get("receipt_sha256")
    expected_receipt_sha256 = _expected_receipt_sha256(binding.target_engine, receipt)
    if provider_receipt_sha256 != expected_receipt_sha256:
        raise FederatedProjectionCompensationProviderReceiptValidationError(
            "provider-native receipt fingerprint is invalid"
        )
    values = {
        "tenant_id": binding.tenant_id,
        "materialization_set_sha256": materialization.materialization_set_sha256,
        "materialization_binding_sha256": binding.materialization_binding_sha256,
        "plan_binding_sha256": binding.plan_binding_sha256,
        "receipt_candidate_sha256": candidate.receipt_candidate_sha256,
        "target_engine": binding.target_engine,
        "projection_id": receipt.projection_id,
        "target_ref": receipt.target_ref,
        "provider_action": receipt.action,
        "provider_plan_sha256": receipt.plan_sha256,
        "provider_idempotency_key": receipt.idempotency_key,
        "receipt_schema_id": candidate.receipt_schema_id,
        "provider_receipt_sha256": provider_receipt_sha256,
        "receipt_status": receipt.status,
        "target_exists": receipt.target_exists,
        "target_content_sha256": receipt.target_content_sha256,
        "target_row_count": receipt.target_row_count,
        "observed_at": receipt.observed_at,
        "validation_state": "validated_not_authority_admitted",
        "authority_write_allowed": False,
        "provider_execution_performed": False,
        "receipt_is_authority_record": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationProviderReceiptValidation.model_construct(
        **values,
        validation_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"validation_sha256"})
    return FederatedProjectionCompensationProviderReceiptValidation(
        **values,
        validation_sha256=_fingerprint(
            FederatedProjectionCompensationProviderReceiptValidation.schema_id,
            normalized,
            "validation_sha256",
        ),
    )


__all__ = [
    "FederatedProjectionCompensationProviderReceiptValidationError",
    "FederatedProjectionCompensationProviderReceiptCandidate",
    "FederatedProjectionCompensationProviderReceiptValidation",
    "build_federated_compensation_provider_receipt_candidate",
    "validate_federated_compensation_provider_receipt_candidate",
]
