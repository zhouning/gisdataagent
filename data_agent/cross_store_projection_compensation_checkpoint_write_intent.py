"""Prepare non-writing checkpoint write intents after authority read checks.

The write intent is the last immutable handoff before a future authority
``record`` call.  It contains exactly the source, target, provider receipt,
plan idempotency and predecessor evidence needed for that call, but this
module does not construct a ``ProjectionCheckpoint`` or perform a write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_checkpoint_admission import (
    FederatedProjectionCompensationCheckpointAdmissionError,
    FederatedProjectionCompensationCheckpointAdmissionRequest,
    preview_federated_compensation_checkpoint_admission,
)
from .cross_store_projection_compensation_checkpoint_authority_read import (
    FederatedProjectionCompensationCheckpointAuthorityReadPreview,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class FederatedProjectionCompensationCheckpointWriteIntentError(ValueError):
    """Checkpoint write evidence is incomplete or differs from authority read state."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("checkpoint write intent timestamp must be timezone-aware")
    return value.astimezone(UTC)


class FederatedProjectionCompensationCheckpointWriteIntent(_FrozenModel):
    """One exact, still non-writing authority record handoff."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-checkpoint-write-intent.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    candidate_sha256: Sha256
    admission_request_sha256: Sha256
    authority_read_preview_sha256: Sha256
    plan_sha256: Sha256
    plan_idempotency_key: Sha256
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    provider_action: Literal["checkpoint", "rebuild", "delete"]
    target_exists: bool
    target_content_sha256: Sha256 | None
    target_row_count: int = Field(ge=0)
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    provider_receipt_sha256: Sha256
    previous_checkpoint_sha256: Sha256 | None
    checkpoint_version: int = Field(ge=1)
    target_commit_ref: dict[str, Any]
    prepared_by: NonEmptyText
    prepared_at: datetime
    write_state: Literal["checkpoint_write_intent_pending_authority_record"] = (
        "checkpoint_write_intent_pending_authority_record"
    )
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    intent_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_intent(
        self,
    ) -> FederatedProjectionCompensationCheckpointWriteIntent:
        if self.target_exists != (self.target_content_sha256 is not None):
            raise ValueError("checkpoint write intent target state is incomplete")
        if not self.target_exists and self.target_row_count != 0:
            raise ValueError("deleted checkpoint write intent must have zero rows")
        if self.previous_checkpoint_sha256 is None and self.checkpoint_version != 1:
            raise ValueError("initial checkpoint write intent must use version 1")
        if self.previous_checkpoint_sha256 is not None and self.checkpoint_version < 2:
            raise ValueError("successor checkpoint write intent must advance the version")
        if not self.prepared_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("checkpoint write intent actor must use a typed subject")
        expected_ref = {
            "provider": self.target_engine.value,
            "provider_action": self.provider_action,
            "plan_sha256": self.plan_sha256,
            "idempotency_key": self.plan_idempotency_key,
            "provider_plan_sha256": self.provider_plan_sha256,
            "provider_idempotency_key": self.provider_idempotency_key,
            "provider_receipt_sha256": self.provider_receipt_sha256,
        }
        if self.target_commit_ref != expected_ref:
            raise ValueError("checkpoint write intent commit evidence is not canonical")
        if (
            self.authority_admission_performed
            or self.authority_write_allowed
            or self.checkpoint_write_allowed
            or self.compensation_completion_allowed
        ):
            raise ValueError("checkpoint write intent cannot authorize writes")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"intent_sha256"}),
            "intent_sha256",
        )
        if self.intent_sha256 != expected:
            raise ValueError("checkpoint write intent fingerprint is invalid")
        return self


class FederatedProjectionCompensationCheckpointWriteIntentSet(_FrozenModel):
    """Complete, non-writing set of authority record intents."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-checkpoint-write-intent-set.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    admission_request_sha256: Sha256
    authority_read_preview_sha256: Sha256
    intents: tuple[FederatedProjectionCompensationCheckpointWriteIntent, ...] = Field(
        min_length=1, max_length=32
    )
    write_state: Literal["checkpoint_write_intents_pending_authority_record"] = (
        "checkpoint_write_intents_pending_authority_record"
    )
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    intent_set_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_set(
        self,
    ) -> FederatedProjectionCompensationCheckpointWriteIntentSet:
        positions = tuple(intent.position for intent in self.intents)
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("checkpoint write intent positions must be unique and ordered")
        for intent in self.intents:
            if (
                intent.tenant_id != self.tenant_id
                or intent.run_id != self.run_id
                or intent.admission_request_sha256 != self.admission_request_sha256
                or intent.authority_read_preview_sha256 != self.authority_read_preview_sha256
                or intent.authority_admission_performed
                or intent.authority_write_allowed
                or intent.checkpoint_write_allowed
                or intent.compensation_completion_allowed
            ):
                raise ValueError("checkpoint write intent differs from its set")
        if (
            self.authority_admission_performed
            or self.authority_write_allowed
            or self.checkpoint_write_allowed
            or self.compensation_completion_allowed
        ):
            raise ValueError("checkpoint write intent set cannot authorize writes")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"intent_set_sha256"}),
            "intent_set_sha256",
        )
        if self.intent_set_sha256 != expected:
            raise ValueError("checkpoint write intent set fingerprint is invalid")
        return self


def build_federated_compensation_checkpoint_write_intent_set(
    request: FederatedProjectionCompensationCheckpointAdmissionRequest,
    authority_read_preview: FederatedProjectionCompensationCheckpointAuthorityReadPreview,
    *,
    prepared_by: str,
    prepared_at: datetime,
) -> FederatedProjectionCompensationCheckpointWriteIntentSet:
    """Build record-ready evidence without constructing or writing a checkpoint."""

    try:
        request = FederatedProjectionCompensationCheckpointAdmissionRequest.model_validate(
            request.model_dump(mode="python")
        )
        authority_read_preview = (
            FederatedProjectionCompensationCheckpointAuthorityReadPreview.model_validate(
                authority_read_preview.model_dump(mode="python")
            )
        )
        prepared_at = _utc(prepared_at)
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationCheckpointWriteIntentError(
            "checkpoint write intent input violates a sealed contract"
        ) from exc

    try:
        admission_preview = preview_federated_compensation_checkpoint_admission(request)
    except FederatedProjectionCompensationCheckpointAdmissionError as exc:
        raise FederatedProjectionCompensationCheckpointWriteIntentError(
            "checkpoint write intent requires a valid admission preview"
        ) from exc
    if (
        authority_read_preview.admission_request_sha256 != request.request_sha256
        or authority_read_preview.admission_preview_sha256 != admission_preview.preview_sha256
        or authority_read_preview.tenant_id != request.tenant_id
        or authority_read_preview.run_id != request.run_id
    ):
        raise FederatedProjectionCompensationCheckpointWriteIntentError(
            "authority read preview differs from admission request"
        )

    candidate_by_position = {
        candidate.position: candidate for candidate in request.candidate_set.candidates
    }
    item_by_position = {item.position: item for item in admission_preview.items}
    snapshot_positions = {snapshot.position for snapshot in authority_read_preview.snapshots}
    if (
        set(candidate_by_position) != set(item_by_position)
        or set(candidate_by_position) != snapshot_positions
    ):
        raise FederatedProjectionCompensationCheckpointWriteIntentError(
            "checkpoint write intent inputs do not cover every target exactly once"
        )

    intents: list[FederatedProjectionCompensationCheckpointWriteIntent] = []
    for position in sorted(candidate_by_position):
        candidate = candidate_by_position[position]
        item = item_by_position[position]
        commit_ref = {
            "provider": candidate.target_engine.value,
            "provider_action": candidate.provider_action,
            "plan_sha256": item.plan_sha256,
            "idempotency_key": item.plan_idempotency_key,
            "provider_plan_sha256": candidate.provider_plan_sha256,
            "provider_idempotency_key": candidate.provider_idempotency_key,
            "provider_receipt_sha256": candidate.provider_receipt_sha256,
        }
        values = {
            "tenant_id": request.tenant_id,
            "run_id": request.run_id,
            "position": position,
            "candidate_sha256": candidate.candidate_sha256,
            "admission_request_sha256": request.request_sha256,
            "authority_read_preview_sha256": authority_read_preview.preview_sha256,
            "plan_sha256": item.plan_sha256,
            "plan_idempotency_key": item.plan_idempotency_key,
            "source_resource_version_ref": item.source_resource_version_ref,
            "source_content_sha256": item.source_content_sha256,
            "projection_id": item.projection_id,
            "target_engine": item.target_engine,
            "target_ref": item.target_ref,
            "provider_action": candidate.provider_action,
            "target_exists": item.target_exists,
            "target_content_sha256": item.target_content_sha256,
            "target_row_count": item.target_row_count,
            "provider_plan_sha256": candidate.provider_plan_sha256,
            "provider_idempotency_key": candidate.provider_idempotency_key,
            "provider_receipt_sha256": candidate.provider_receipt_sha256,
            "previous_checkpoint_sha256": item.previous_checkpoint_sha256,
            "checkpoint_version": item.next_checkpoint_version,
            "target_commit_ref": commit_ref,
            "prepared_by": prepared_by,
            "prepared_at": prepared_at,
            "write_state": "checkpoint_write_intent_pending_authority_record",
            "authority_admission_performed": False,
            "authority_write_allowed": False,
            "checkpoint_write_allowed": False,
            "compensation_completion_allowed": False,
        }
        intents.append(
            FederatedProjectionCompensationCheckpointWriteIntent(
                **values,
                intent_sha256=_fingerprint(
                    FederatedProjectionCompensationCheckpointWriteIntent.schema_id,
                    FederatedProjectionCompensationCheckpointWriteIntent.model_construct(
                        **values,
                        intent_sha256="0" * 64,
                    ).model_dump(mode="json", exclude={"intent_sha256"}),
                    "intent_sha256",
                ),
            )
        )

    values = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "admission_request_sha256": request.request_sha256,
        "authority_read_preview_sha256": authority_read_preview.preview_sha256,
        "intents": tuple(intents),
        "write_state": "checkpoint_write_intents_pending_authority_record",
        "authority_admission_performed": False,
        "authority_write_allowed": False,
        "checkpoint_write_allowed": False,
        "compensation_completion_allowed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationCheckpointWriteIntentSet.model_construct(
        **values,
        intent_set_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"intent_set_sha256"})
    return FederatedProjectionCompensationCheckpointWriteIntentSet(
        **values,
        intent_set_sha256=_fingerprint(
            FederatedProjectionCompensationCheckpointWriteIntentSet.schema_id,
            normalized,
            "intent_set_sha256",
        ),
    )


__all__ = [
    "FederatedProjectionCompensationCheckpointWriteIntentError",
    "FederatedProjectionCompensationCheckpointWriteIntent",
    "FederatedProjectionCompensationCheckpointWriteIntentSet",
    "build_federated_compensation_checkpoint_write_intent_set",
]
