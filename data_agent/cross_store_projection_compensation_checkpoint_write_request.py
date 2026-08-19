"""Build sealed checkpoint write requests from final target observations.

This module turns a validated, non-writing checkpoint intent into an exact
``ProjectionCheckpoint`` request.  It binds the final target observation,
the original repair plan, the live authority predecessor read and provider
receipt evidence, but deliberately has no authority ``record`` dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_checkpoint_admission import (
    FederatedProjectionCompensationCheckpointAdmissionRequest,
)
from .cross_store_projection_compensation_checkpoint_authority_read import (
    FederatedProjectionCompensationCheckpointAuthorityReadPreview,
)
from .cross_store_projection_compensation_checkpoint_write_intent import (
    FederatedProjectionCompensationCheckpointWriteIntentError,
    FederatedProjectionCompensationCheckpointWriteIntentSet,
    build_federated_compensation_checkpoint_write_intent_set,
)
from .cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionConsistencyError,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_checkpoint_from_repair,
    projection_checkpoint_fingerprint,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class FederatedProjectionCompensationCheckpointWriteRequestError(ValueError):
    """Final target evidence cannot safely become a checkpoint write request."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("checkpoint write request timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _target_key(
    *,
    tenant_id: str,
    projection_id: str,
    target_engine: ProjectionEngine,
    target_ref: str,
) -> tuple[str, str, str, str]:
    return tenant_id, projection_id, target_engine.value, target_ref


def _checkpoint_fingerprint(checkpoint: ProjectionCheckpoint) -> str:
    return projection_checkpoint_fingerprint(
        **checkpoint.model_dump(mode="python", exclude={"checkpoint_sha256"})
    )


class FederatedProjectionCompensationCheckpointWriteRequest(_FrozenModel):
    """One exact checkpoint request that still cannot invoke authority record."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-checkpoint-write-request.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    admission_request_sha256: Sha256
    authority_read_preview_sha256: Sha256
    authority_predecessor_snapshot_sha256: Sha256
    write_intent_set_sha256: Sha256
    write_intent_sha256: Sha256
    plan_sha256: Sha256
    plan_idempotency_key: Sha256
    previous_checkpoint_sha256: Sha256 | None
    previous_checkpoint_version: int = Field(ge=0)
    final_observation: ProjectionTargetObservation
    checkpoint: ProjectionCheckpoint
    authority_current_read_performed: Literal[True] = True
    final_target_observation_verified: Literal[True] = True
    write_state: Literal["checkpoint_write_request_pending_authority_record"] = (
        "checkpoint_write_request_pending_authority_record"
    )
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    request_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_request(
        self,
    ) -> FederatedProjectionCompensationCheckpointWriteRequest:
        observation = self.final_observation
        checkpoint = self.checkpoint
        request_key = _target_key(
            tenant_id=self.tenant_id,
            projection_id=checkpoint.projection_id,
            target_engine=checkpoint.target_engine,
            target_ref=checkpoint.target_ref,
        )
        observation_key = _target_key(
            tenant_id=observation.tenant_id,
            projection_id=observation.projection_id,
            target_engine=observation.target_engine,
            target_ref=observation.target_ref,
        )
        if request_key != observation_key:
            raise ValueError("checkpoint write request target identity differs")
        if (
            checkpoint.target_exists != observation.target_exists
            or checkpoint.target_content_sha256 != observation.observed_content_sha256
            or checkpoint.target_row_count != observation.observed_row_count
        ):
            raise ValueError("checkpoint write request target state differs")
        if observation.observed_at > checkpoint.updated_at:
            raise ValueError("checkpoint write request predates final observation")
        if not checkpoint.updated_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("checkpoint write request actor must use a typed subject")
        if (
            checkpoint.target_commit_ref.get("plan_sha256") != self.plan_sha256
            or checkpoint.target_commit_ref.get("idempotency_key") != self.plan_idempotency_key
        ):
            raise ValueError("checkpoint write request is not bound to its repair plan")
        if self.previous_checkpoint_sha256 is None:
            if self.previous_checkpoint_version != 0 or checkpoint.checkpoint_version != 1:
                raise ValueError("initial checkpoint write request must advance zero to one")
        elif (
            self.previous_checkpoint_version < 1
            or checkpoint.checkpoint_version != self.previous_checkpoint_version + 1
        ):
            raise ValueError("successor checkpoint write request must advance one version")
        if checkpoint.checkpoint_sha256 != _checkpoint_fingerprint(checkpoint):
            raise ValueError("checkpoint write request contains an invalid checkpoint")
        if not self.authority_current_read_performed or not self.final_target_observation_verified:
            raise ValueError("checkpoint write request requires predecessor and target checks")
        if (
            self.authority_admission_performed
            or self.authority_write_allowed
            or self.checkpoint_write_allowed
            or self.compensation_completion_allowed
        ):
            raise ValueError("checkpoint write request cannot authorize writes")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("checkpoint write request fingerprint is invalid")
        return self


class FederatedProjectionCompensationCheckpointWriteRequestSet(_FrozenModel):
    """Complete, sealed set of checkpoint requests pending authority record."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-checkpoint-write-request-set.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    admission_request_sha256: Sha256
    authority_read_preview_sha256: Sha256
    write_intent_set_sha256: Sha256
    updated_by: NonEmptyText
    updated_at: datetime
    requests: tuple[FederatedProjectionCompensationCheckpointWriteRequest, ...] = Field(
        min_length=1, max_length=32
    )
    write_state: Literal["checkpoint_write_requests_pending_authority_record"] = (
        "checkpoint_write_requests_pending_authority_record"
    )
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    request_set_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_set(
        self,
    ) -> FederatedProjectionCompensationCheckpointWriteRequestSet:
        positions = tuple(request.position for request in self.requests)
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("checkpoint write request positions must be unique and ordered")
        target_keys: set[tuple[str, str, str, str]] = set()
        for request in self.requests:
            checkpoint = request.checkpoint
            target_key = _target_key(
                tenant_id=request.tenant_id,
                projection_id=checkpoint.projection_id,
                target_engine=checkpoint.target_engine,
                target_ref=checkpoint.target_ref,
            )
            if target_key in target_keys:
                raise ValueError("checkpoint write request targets must be unique")
            target_keys.add(target_key)
            if (
                request.tenant_id != self.tenant_id
                or request.run_id != self.run_id
                or request.admission_request_sha256 != self.admission_request_sha256
                or request.authority_read_preview_sha256 != self.authority_read_preview_sha256
                or request.write_intent_set_sha256 != self.write_intent_set_sha256
                or checkpoint.updated_by != self.updated_by
                or checkpoint.updated_at != self.updated_at
                or request.authority_admission_performed
                or request.authority_write_allowed
                or request.checkpoint_write_allowed
                or request.compensation_completion_allowed
            ):
                raise ValueError("checkpoint write request differs from its set")
        if not self.updated_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("checkpoint write request actor must use a typed subject")
        if (
            self.authority_admission_performed
            or self.authority_write_allowed
            or self.checkpoint_write_allowed
            or self.compensation_completion_allowed
        ):
            raise ValueError("checkpoint write request set cannot authorize writes")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_set_sha256"}),
            "request_set_sha256",
        )
        if self.request_set_sha256 != expected:
            raise ValueError("checkpoint write request set fingerprint is invalid")
        return self


def _validated_inputs(
    request: FederatedProjectionCompensationCheckpointAdmissionRequest,
    authority_read_preview: FederatedProjectionCompensationCheckpointAuthorityReadPreview,
    write_intent_set: FederatedProjectionCompensationCheckpointWriteIntentSet,
    final_observations: tuple[ProjectionTargetObservation, ...],
    updated_at: datetime,
) -> tuple[
    FederatedProjectionCompensationCheckpointAdmissionRequest,
    FederatedProjectionCompensationCheckpointAuthorityReadPreview,
    FederatedProjectionCompensationCheckpointWriteIntentSet,
    tuple[ProjectionTargetObservation, ...],
    datetime,
]:
    try:
        return (
            FederatedProjectionCompensationCheckpointAdmissionRequest.model_validate(
                request.model_dump(mode="python")
            ),
            FederatedProjectionCompensationCheckpointAuthorityReadPreview.model_validate(
                authority_read_preview.model_dump(mode="python")
            ),
            FederatedProjectionCompensationCheckpointWriteIntentSet.model_validate(
                write_intent_set.model_dump(mode="python")
            ),
            tuple(
                ProjectionTargetObservation.model_validate(observation.model_dump(mode="python"))
                for observation in final_observations
            ),
            _utc(updated_at),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationCheckpointWriteRequestError(
            "checkpoint write request input violates a sealed contract"
        ) from exc


def build_federated_compensation_checkpoint_write_request_set(
    request: FederatedProjectionCompensationCheckpointAdmissionRequest,
    authority_read_preview: FederatedProjectionCompensationCheckpointAuthorityReadPreview,
    write_intent_set: FederatedProjectionCompensationCheckpointWriteIntentSet,
    final_observations: tuple[ProjectionTargetObservation, ...],
    *,
    updated_by: str,
    updated_at: datetime,
) -> FederatedProjectionCompensationCheckpointWriteRequestSet:
    """Build exact checkpoint requests without invoking authority ``record``."""

    (
        request,
        authority_read_preview,
        write_intent_set,
        final_observations,
        updated_at,
    ) = _validated_inputs(
        request,
        authority_read_preview,
        write_intent_set,
        final_observations,
        updated_at,
    )

    try:
        expected_intent_set = build_federated_compensation_checkpoint_write_intent_set(
            request,
            authority_read_preview,
            prepared_by=write_intent_set.intents[0].prepared_by,
            prepared_at=write_intent_set.intents[0].prepared_at,
        )
    except (IndexError, FederatedProjectionCompensationCheckpointWriteIntentError) as exc:
        raise FederatedProjectionCompensationCheckpointWriteRequestError(
            "checkpoint write request requires a valid write intent set"
        ) from exc
    if expected_intent_set.intent_set_sha256 != write_intent_set.intent_set_sha256:
        raise FederatedProjectionCompensationCheckpointWriteRequestError(
            "checkpoint write intent set differs from admission and authority evidence"
        )

    intent_by_position = {intent.position: intent for intent in write_intent_set.intents}
    candidate_by_position = {
        candidate.position: candidate for candidate in request.candidate_set.candidates
    }
    snapshot_by_position = {
        snapshot.position: snapshot for snapshot in authority_read_preview.snapshots
    }
    if (
        len(intent_by_position) != len(write_intent_set.intents)
        or len(snapshot_by_position) != len(authority_read_preview.snapshots)
        or set(intent_by_position) != set(candidate_by_position)
        or set(intent_by_position) != set(snapshot_by_position)
    ):
        raise FederatedProjectionCompensationCheckpointWriteRequestError(
            "checkpoint write request evidence does not cover every target exactly once"
        )

    plan_by_hash = {plan.plan_sha256: plan for plan in request.repair_plans}
    if len(plan_by_hash) != len(request.repair_plans):
        raise FederatedProjectionCompensationCheckpointWriteRequestError(
            "checkpoint write request repair plans must be unique"
        )

    observations_by_target: dict[tuple[str, str, str, str], ProjectionTargetObservation] = {}
    for observation in final_observations:
        key = _target_key(
            tenant_id=observation.tenant_id,
            projection_id=observation.projection_id,
            target_engine=observation.target_engine,
            target_ref=observation.target_ref,
        )
        if key in observations_by_target:
            raise FederatedProjectionCompensationCheckpointWriteRequestError(
                "final target observations must be unique"
            )
        observations_by_target[key] = observation

    expected_target_keys = {
        _target_key(
            tenant_id=intent.tenant_id,
            projection_id=intent.projection_id,
            target_engine=intent.target_engine,
            target_ref=intent.target_ref,
        )
        for intent in write_intent_set.intents
    }
    if set(observations_by_target) != expected_target_keys:
        raise FederatedProjectionCompensationCheckpointWriteRequestError(
            "final target observations must cover every intent target exactly once"
        )

    write_requests: list[FederatedProjectionCompensationCheckpointWriteRequest] = []
    for position in sorted(intent_by_position):
        intent = intent_by_position[position]
        candidate = candidate_by_position[position]
        snapshot = snapshot_by_position[position]
        plan = plan_by_hash.get(intent.plan_sha256)
        observation_key = _target_key(
            tenant_id=intent.tenant_id,
            projection_id=intent.projection_id,
            target_engine=intent.target_engine,
            target_ref=intent.target_ref,
        )
        observation = observations_by_target[observation_key]
        if plan is None:
            raise FederatedProjectionCompensationCheckpointWriteRequestError(
                "checkpoint write intent repair plan is missing"
            )
        if (
            plan.plan_idempotency_key != intent.plan_idempotency_key
            or plan.previous_checkpoint_sha256 != intent.previous_checkpoint_sha256
            or plan.next_checkpoint_version != intent.checkpoint_version
            or candidate.candidate_sha256 != intent.candidate_sha256
            or candidate.previous_checkpoint_sha256 != intent.previous_checkpoint_sha256
            or candidate.next_checkpoint_version != intent.checkpoint_version
        ):
            raise FederatedProjectionCompensationCheckpointWriteRequestError(
                "checkpoint plan, intent or authority predecessor evidence differs"
            )
        if (
            observation.target_exists != intent.target_exists
            or observation.observed_content_sha256 != intent.target_content_sha256
            or observation.observed_row_count != intent.target_row_count
        ):
            raise FederatedProjectionCompensationCheckpointWriteRequestError(
                "final target observation differs from checkpoint write intent"
            )
        try:
            checkpoint = build_projection_checkpoint_from_repair(
                plan,
                observation,
                target_commit_ref=intent.target_commit_ref,
                updated_by=updated_by,
                updated_at=updated_at,
            )
        except (ProjectionConsistencyError, TypeError, ValueError, ValidationError) as exc:
            raise FederatedProjectionCompensationCheckpointWriteRequestError(
                "final target observation cannot produce a checkpoint write request"
            ) from exc
        if (
            checkpoint.checkpoint_sha256 != _checkpoint_fingerprint(checkpoint)
            or checkpoint.source_resource_version_ref != intent.source_resource_version_ref
            or checkpoint.source_content_sha256 != intent.source_content_sha256
            or checkpoint.checkpoint_version != intent.checkpoint_version
            or checkpoint.target_commit_ref != intent.target_commit_ref
        ):
            raise FederatedProjectionCompensationCheckpointWriteRequestError(
                "constructed checkpoint differs from its sealed write intent"
            )
        predecessor_current = (
            snapshot.authority_current_state == "candidate_predecessor"
            and snapshot.current_checkpoint_sha256 == intent.previous_checkpoint_sha256
            and snapshot.current_checkpoint_version == intent.checkpoint_version - 1
        )
        replay_current = (
            snapshot.authority_current_state == "requested_checkpoint_replay"
            and snapshot.current_checkpoint_sha256 == checkpoint.checkpoint_sha256
            and snapshot.current_checkpoint_version == checkpoint.checkpoint_version
        )
        if not predecessor_current and not replay_current:
            raise FederatedProjectionCompensationCheckpointWriteRequestError(
                "authority current does not match the predecessor or replay checkpoint"
            )

        values = {
            "tenant_id": request.tenant_id,
            "run_id": request.run_id,
            "position": position,
            "admission_request_sha256": request.request_sha256,
            "authority_read_preview_sha256": authority_read_preview.preview_sha256,
            "authority_predecessor_snapshot_sha256": snapshot.snapshot_sha256,
            "write_intent_set_sha256": write_intent_set.intent_set_sha256,
            "write_intent_sha256": intent.intent_sha256,
            "plan_sha256": plan.plan_sha256,
            "plan_idempotency_key": plan.plan_idempotency_key,
            "previous_checkpoint_sha256": plan.previous_checkpoint_sha256,
            "previous_checkpoint_version": plan.next_checkpoint_version - 1,
            "final_observation": observation,
            "checkpoint": checkpoint,
            "authority_current_read_performed": True,
            "final_target_observation_verified": True,
            "write_state": "checkpoint_write_request_pending_authority_record",
            "authority_admission_performed": False,
            "authority_write_allowed": False,
            "checkpoint_write_allowed": False,
            "compensation_completion_allowed": False,
        }
        normalized = FederatedProjectionCompensationCheckpointWriteRequest.model_construct(
            **values,
            request_sha256="0" * 64,
        ).model_dump(mode="json", exclude={"request_sha256"})
        write_requests.append(
            FederatedProjectionCompensationCheckpointWriteRequest(
                **values,
                request_sha256=_fingerprint(
                    FederatedProjectionCompensationCheckpointWriteRequest.schema_id,
                    normalized,
                    "request_sha256",
                ),
            )
        )

    values = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "admission_request_sha256": request.request_sha256,
        "authority_read_preview_sha256": authority_read_preview.preview_sha256,
        "write_intent_set_sha256": write_intent_set.intent_set_sha256,
        "updated_by": updated_by,
        "updated_at": updated_at,
        "requests": tuple(write_requests),
        "write_state": "checkpoint_write_requests_pending_authority_record",
        "authority_admission_performed": False,
        "authority_write_allowed": False,
        "checkpoint_write_allowed": False,
        "compensation_completion_allowed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationCheckpointWriteRequestSet.model_construct(
        **values,
        request_set_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"request_set_sha256"})
    return FederatedProjectionCompensationCheckpointWriteRequestSet(
        **values,
        request_set_sha256=_fingerprint(
            FederatedProjectionCompensationCheckpointWriteRequestSet.schema_id,
            normalized,
            "request_set_sha256",
        ),
    )


__all__ = [
    "FederatedProjectionCompensationCheckpointWriteRequestError",
    "FederatedProjectionCompensationCheckpointWriteRequest",
    "FederatedProjectionCompensationCheckpointWriteRequestSet",
    "build_federated_compensation_checkpoint_write_request_set",
]
