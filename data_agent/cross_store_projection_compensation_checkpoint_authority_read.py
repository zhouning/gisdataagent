"""Read-only authority predecessor verification for compensation admission.

The compensation admission preview proves that the sealed repair plans agree
with deployment-supplied predecessor summaries.  This module adds the next
boundary: read the current predecessor from the checkpoint authority and
compare it with that preview.  It intentionally has no ``record`` call and
never constructs a writable ``ProjectionCheckpoint``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
    ProjectionCheckpointAuthorityError,
)
from .cross_store_projection_compensation_checkpoint_admission import (
    FederatedProjectionCompensationCheckpointAdmissionError,
    FederatedProjectionCompensationCheckpointAdmissionRequest,
    preview_federated_compensation_checkpoint_admission,
)
from .cross_store_projection_consistency import ProjectionCheckpoint, ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class FederatedProjectionCompensationCheckpointAuthorityReadError(ValueError):
    """The live authority predecessor cannot be safely admitted."""


class ProjectionCheckpointCurrentReader(Protocol):
    """Minimal read-only authority port used by the admission verifier."""

    def current(
        self,
        *,
        tenant_id: str,
        projection_id: str,
        target_engine: ProjectionEngine | str,
        target_ref: str,
    ) -> ProjectionCheckpoint | None: ...


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


class FederatedProjectionCompensationCheckpointAuthorityPredecessorSnapshot(_FrozenModel):
    """One current checkpoint identity read from the authority."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-checkpoint-authority-predecessor-snapshot.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    current_checkpoint_sha256: Sha256 | None
    current_checkpoint_version: int = Field(ge=0)
    authority_current_state: Literal[
        "candidate_predecessor",
        "requested_checkpoint_replay",
    ] = "candidate_predecessor"
    predecessor_matches_candidate: Literal[True] = True
    authority_read_state: Literal["read_from_authority_current"] = "read_from_authority_current"
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_snapshot(
        self,
    ) -> FederatedProjectionCompensationCheckpointAuthorityPredecessorSnapshot:
        if self.current_checkpoint_sha256 is None and self.current_checkpoint_version != 0:
            raise ValueError("missing authority checkpoint must use version zero")
        if self.current_checkpoint_sha256 is not None and self.current_checkpoint_version < 1:
            raise ValueError("existing authority checkpoint must use a positive version")
        if (
            self.authority_current_state == "requested_checkpoint_replay"
            and self.current_checkpoint_sha256 is None
        ):
            raise ValueError("checkpoint replay requires an existing authority current")
        if not self.predecessor_matches_candidate:
            raise ValueError("authority predecessor snapshot must be matched")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"snapshot_sha256"}),
            "snapshot_sha256",
        )
        if self.snapshot_sha256 != expected:
            raise ValueError("authority predecessor snapshot fingerprint is invalid")
        return self


class FederatedProjectionCompensationCheckpointAuthorityReadPreview(_FrozenModel):
    """Read-only proof that authority current state matches all candidates."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-checkpoint-authority-read-preview.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    admission_request_sha256: Sha256
    admission_preview_sha256: Sha256
    snapshots: tuple[FederatedProjectionCompensationCheckpointAuthorityPredecessorSnapshot, ...] = (
        Field(min_length=1, max_length=32)
    )
    authority_current_read_performed: Literal[True] = True
    all_predecessors_match: Literal[True] = True
    admission_state: Literal["authority_predecessors_verified_pending_write"] = (
        "authority_predecessors_verified_pending_write"
    )
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    preview_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_preview(
        self,
    ) -> FederatedProjectionCompensationCheckpointAuthorityReadPreview:
        positions = tuple(snapshot.position for snapshot in self.snapshots)
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("authority read snapshot positions must be unique and ordered")
        if not self.authority_current_read_performed or not self.all_predecessors_match:
            raise ValueError("authority read preview must contain successful reads")
        for snapshot in self.snapshots:
            if (
                snapshot.tenant_id != self.tenant_id
                or snapshot.run_id != self.run_id
                or not snapshot.predecessor_matches_candidate
            ):
                raise ValueError("authority read snapshot differs from preview")
        if (
            self.authority_admission_performed
            or self.authority_write_allowed
            or self.checkpoint_write_allowed
            or self.compensation_completion_allowed
        ):
            raise ValueError("authority read preview cannot authorize writes")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"preview_sha256"}),
            "preview_sha256",
        )
        if self.preview_sha256 != expected:
            raise ValueError("authority read preview fingerprint is invalid")
        return self


def _validated_request(
    request: FederatedProjectionCompensationCheckpointAdmissionRequest,
) -> FederatedProjectionCompensationCheckpointAdmissionRequest:
    try:
        return FederatedProjectionCompensationCheckpointAdmissionRequest.model_validate(
            request.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationCheckpointAuthorityReadError(
            "authority predecessor read request violates its sealed contract"
        ) from exc


def _assert_current_matches_candidate(
    *,
    candidate: Any,
    admission_item: Any,
    current: ProjectionCheckpoint | None,
) -> tuple[Sha256 | None, int, Literal["candidate_predecessor", "requested_checkpoint_replay"]]:
    if current is None:
        if (
            candidate.previous_checkpoint_sha256 is not None
            or candidate.next_checkpoint_version != 1
        ):
            raise FederatedProjectionCompensationCheckpointAuthorityReadError(
                "authority current checkpoint is missing but candidate expects a successor"
            )
        return None, 0, "candidate_predecessor"
    if (
        current.tenant_id != candidate.tenant_id
        or current.projection_id != candidate.projection_id
        or current.target_engine is not candidate.target_engine
        or current.target_ref != candidate.target_ref
    ):
        raise FederatedProjectionCompensationCheckpointAuthorityReadError(
            "authority current checkpoint differs from candidate predecessor or version"
        )
    if (
        candidate.previous_checkpoint_sha256 == current.checkpoint_sha256
        and candidate.next_checkpoint_version == current.checkpoint_version + 1
    ):
        return current.checkpoint_sha256, current.checkpoint_version, "candidate_predecessor"

    replay_commit_ref = {
        "provider": candidate.target_engine.value,
        "provider_action": candidate.provider_action,
        "plan_sha256": admission_item.plan_sha256,
        "idempotency_key": admission_item.plan_idempotency_key,
        "provider_plan_sha256": candidate.provider_plan_sha256,
        "provider_idempotency_key": candidate.provider_idempotency_key,
        "provider_receipt_sha256": candidate.provider_receipt_sha256,
    }
    if (
        candidate.next_checkpoint_version == current.checkpoint_version
        and current.source_resource_version_ref == candidate.source_resource_version_ref
        and current.source_content_sha256 == candidate.source_content_sha256
        and current.target_exists == candidate.target_exists
        and current.target_content_sha256 == candidate.target_content_sha256
        and current.target_row_count == candidate.target_row_count
        and current.target_commit_ref == replay_commit_ref
    ):
        return current.checkpoint_sha256, current.checkpoint_version, (
            "requested_checkpoint_replay"
        )
    raise FederatedProjectionCompensationCheckpointAuthorityReadError(
        "authority current checkpoint differs from candidate predecessor or version"
    )


def build_federated_compensation_checkpoint_authority_read_preview(
    request: FederatedProjectionCompensationCheckpointAdmissionRequest,
    authority: ProjectionCheckpointCurrentReader | PostgresProjectionCheckpointAuthority,
) -> FederatedProjectionCompensationCheckpointAuthorityReadPreview:
    """Read authority current state and return a non-writing match preview."""

    request = _validated_request(request)
    try:
        admission_preview = preview_federated_compensation_checkpoint_admission(request)
    except FederatedProjectionCompensationCheckpointAdmissionError as exc:
        raise FederatedProjectionCompensationCheckpointAuthorityReadError(
            "authority predecessor read requires a valid admission request"
        ) from exc

    snapshots: list[FederatedProjectionCompensationCheckpointAuthorityPredecessorSnapshot] = []
    admission_items = {item.position: item for item in admission_preview.items}
    for candidate in request.candidate_set.candidates:
        try:
            current = authority.current(
                tenant_id=candidate.tenant_id,
                projection_id=candidate.projection_id,
                target_engine=candidate.target_engine,
                target_ref=candidate.target_ref,
            )
        except ProjectionCheckpointAuthorityError as exc:
            raise FederatedProjectionCompensationCheckpointAuthorityReadError(
                "authority current checkpoint read failed"
            ) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise FederatedProjectionCompensationCheckpointAuthorityReadError(
                "authority current checkpoint reader returned an invalid result"
            ) from exc
        current_sha, current_version, current_state = _assert_current_matches_candidate(
            candidate=candidate,
            admission_item=admission_items[candidate.position],
            current=current,
        )
        values = {
            "tenant_id": request.tenant_id,
            "run_id": request.run_id,
            "position": candidate.position,
            "projection_id": candidate.projection_id,
            "target_engine": candidate.target_engine,
            "target_ref": candidate.target_ref,
            "current_checkpoint_sha256": current_sha,
            "current_checkpoint_version": current_version,
            "authority_current_state": current_state,
            "predecessor_matches_candidate": True,
            "authority_read_state": "read_from_authority_current",
        }
        snapshots.append(
            FederatedProjectionCompensationCheckpointAuthorityPredecessorSnapshot(
                **values,
                snapshot_sha256=_fingerprint(
                    FederatedProjectionCompensationCheckpointAuthorityPredecessorSnapshot.schema_id,
                    values,
                    "snapshot_sha256",
                ),
            )
        )

    values = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "admission_request_sha256": request.request_sha256,
        "admission_preview_sha256": admission_preview.preview_sha256,
        "snapshots": tuple(snapshots),
        "authority_current_read_performed": True,
        "all_predecessors_match": True,
        "admission_state": "authority_predecessors_verified_pending_write",
        "authority_admission_performed": False,
        "authority_write_allowed": False,
        "checkpoint_write_allowed": False,
        "compensation_completion_allowed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationCheckpointAuthorityReadPreview.model_construct(
        **values,
        preview_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"preview_sha256"})
    return FederatedProjectionCompensationCheckpointAuthorityReadPreview(
        **values,
        preview_sha256=_fingerprint(
            FederatedProjectionCompensationCheckpointAuthorityReadPreview.schema_id,
            normalized,
            "preview_sha256",
        ),
    )


__all__ = [
    "FederatedProjectionCompensationCheckpointAuthorityReadError",
    "ProjectionCheckpointCurrentReader",
    "FederatedProjectionCompensationCheckpointAuthorityPredecessorSnapshot",
    "FederatedProjectionCompensationCheckpointAuthorityReadPreview",
    "build_federated_compensation_checkpoint_authority_read_preview",
]
