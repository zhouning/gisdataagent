"""Fail-closed consistency and repair contracts for governed projections.

The contract deliberately separates source truth, target observation, and the
checkpoint that records a completed target commit. It does not execute a
rebuild or silently adopt an untracked target; callers must apply the returned
repair plan and then record a new checkpoint.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class ProjectionConsistencyError(ValueError):
    """Raised when projection evidence cannot be reconciled safely."""


class ProjectionCheckpointConflictError(ProjectionConsistencyError):
    """Raised when a checkpoint write races or skips an expected predecessor."""


class ProjectionEngine(StrEnum):
    POSTGIS = "postgis"
    RDF = "rdf"
    VECTOR = "vector"
    OBJECT_STORE = "object_store"
    LAKEHOUSE = "lakehouse"


ProjectionId = str


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("projection timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _projection_key(
    tenant_id: str,
    projection_id: str,
    target_engine: ProjectionEngine,
    target_ref: str,
) -> tuple[str, str, str, str]:
    return tenant_id, projection_id, target_engine.value, target_ref


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return _utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


class ProjectionDesiredState(_FrozenModel):
    """The immutable source version and target content expected by a run."""

    schema_id: ClassVar[str] = (
        "gda.projection-desired-state.v1"
    )
    tenant_id: TenantId
    projection_id: ProjectionId = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    target_exists: bool = True
    expected_target_content_sha256: Sha256 | None = None
    expected_row_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _target_state_is_complete(self) -> ProjectionDesiredState:
        if self.target_exists and self.expected_target_content_sha256 is None:
            raise ValueError("existing target requires expected content fingerprint")
        if not self.target_exists and self.expected_target_content_sha256 is not None:
            raise ValueError("deleted target must not have content fingerprint")
        if not self.target_exists and self.expected_row_count != 0:
            raise ValueError("deleted target must have zero rows")
        return self


class ProjectionTargetObservation(_FrozenModel):
    """An independently observed target state, never inferred from a checkpoint."""

    schema_id: ClassVar[str] = (
        "gda.projection-target-observation.v1"
    )
    tenant_id: TenantId
    projection_id: ProjectionId = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    target_exists: bool
    observed_content_sha256: Sha256 | None = None
    observed_row_count: int = Field(ge=0)
    observed_by: NonEmptyText
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _observed_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _target_state_is_complete(self) -> ProjectionTargetObservation:
        if self.target_exists and self.observed_content_sha256 is None:
            raise ValueError("existing observation requires content fingerprint")
        if not self.target_exists and self.observed_content_sha256 is not None:
            raise ValueError("missing target must not have content fingerprint")
        if not self.target_exists and self.observed_row_count != 0:
            raise ValueError("missing target must have zero rows")
        return self


class ProjectionCheckpoint(_FrozenModel):
    """Evidence that one target commit completed for one source version."""

    schema_id: ClassVar[str] = "gda.projection-checkpoint.v1"
    tenant_id: TenantId
    projection_id: ProjectionId = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    target_exists: bool
    target_content_sha256: Sha256 | None = None
    target_row_count: int = Field(ge=0)
    checkpoint_version: int = Field(ge=1)
    target_commit_ref: dict[str, Any] = Field(default_factory=dict)
    updated_by: NonEmptyText
    updated_at: datetime
    checkpoint_sha256: Sha256

    @field_validator("updated_at")
    @classmethod
    def _updated_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _checkpoint_is_complete(self) -> ProjectionCheckpoint:
        if self.target_exists and self.target_content_sha256 is None:
            raise ValueError("existing checkpoint requires target fingerprint")
        if not self.target_exists and self.target_content_sha256 is not None:
            raise ValueError("deleted checkpoint must not have target fingerprint")
        if not self.target_exists and self.target_row_count != 0:
            raise ValueError("deleted checkpoint must have zero rows")
        if not self.target_commit_ref:
            raise ValueError("checkpoint requires target commit evidence")
        expected = projection_checkpoint_fingerprint(
            tenant_id=self.tenant_id,
            projection_id=self.projection_id,
            source_resource_version_ref=self.source_resource_version_ref,
            source_content_sha256=self.source_content_sha256,
            target_engine=self.target_engine,
            target_ref=self.target_ref,
            target_exists=self.target_exists,
            target_content_sha256=self.target_content_sha256,
            target_row_count=self.target_row_count,
            checkpoint_version=self.checkpoint_version,
            target_commit_ref=self.target_commit_ref,
            updated_by=self.updated_by,
            updated_at=self.updated_at,
        )
        if self.checkpoint_sha256 != expected:
            raise ValueError("projection checkpoint fingerprint does not match content")
        return self


class ProjectionConsistencyAssessment(_FrozenModel):
    """Deterministic decision before any projection side effect is attempted."""

    schema_id: ClassVar[str] = (
        "gda.projection-consistency-assessment.v1"
    )
    tenant_id: TenantId
    projection_id: ProjectionId = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    status: Literal[
        "aligned",
        "aligned_deleted",
        "checkpoint_missing",
        "source_advanced_same_target",
        "source_advanced",
        "target_missing",
        "delete_required",
        "target_drift",
        "checkpoint_state_drift",
        "desired_content_mismatch",
    ]
    action: Literal["noop", "checkpoint", "rebuild", "delete", "fail_closed"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    checkpoint_version: int = Field(ge=0)
    observed_content_sha256: Sha256 | None = None
    expected_content_sha256: Sha256 | None = None
    assessment_sha256: Sha256

    @model_validator(mode="after")
    def _assessment_is_canonical(self) -> ProjectionConsistencyAssessment:
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("assessment reason codes must be unique and sorted")
        expected = projection_assessment_fingerprint(
            tenant_id=self.tenant_id,
            projection_id=self.projection_id,
            target_engine=self.target_engine,
            target_ref=self.target_ref,
            status=self.status,
            action=self.action,
            reason_codes=self.reason_codes,
            checkpoint_version=self.checkpoint_version,
            observed_content_sha256=self.observed_content_sha256,
            expected_content_sha256=self.expected_content_sha256,
        )
        if self.assessment_sha256 != expected:
            raise ValueError("projection assessment fingerprint does not match content")
        return self


class ProjectionRepairPlan(_FrozenModel):
    """Sealed checkpoint/rebuild/delete plan; it never performs the action."""

    schema_id: ClassVar[str] = "gda.projection-repair-plan.v1"
    tenant_id: TenantId
    projection_id: ProjectionId = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    action: Literal["checkpoint", "rebuild", "delete", "fail_closed"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    desired_state: ProjectionDesiredState
    observation: ProjectionTargetObservation
    assessment: ProjectionConsistencyAssessment
    previous_checkpoint_sha256: Sha256 | None = None
    next_checkpoint_version: int = Field(ge=1)
    requires_operator: bool
    plan_idempotency_key: Sha256
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _plan_is_canonical(self) -> ProjectionRepairPlan:
        if self.assessment.action != self.action:
            raise ValueError("repair plan action must match assessment")
        if self.assessment.reason_codes != self.reason_codes:
            raise ValueError("repair plan reasons must match assessment")
        if self.action == "noop":
            raise ValueError("noop assessments do not produce repair plans")
        if self.requires_operator != (self.action == "fail_closed"):
            raise ValueError("operator requirement must match fail-closed action")
        expected_key = projection_repair_idempotency_key(
            desired_state=self.desired_state,
            observation=self.observation,
            assessment=self.assessment,
            previous_checkpoint_sha256=self.previous_checkpoint_sha256,
        )
        if self.plan_idempotency_key != expected_key:
            raise ValueError("repair plan idempotency key does not match content")
        expected_plan = projection_repair_plan_fingerprint(
            tenant_id=self.tenant_id,
            projection_id=self.projection_id,
            target_engine=self.target_engine,
            target_ref=self.target_ref,
            action=self.action,
            reason_codes=self.reason_codes,
            desired_state=self.desired_state,
            observation=self.observation,
            assessment=self.assessment,
            previous_checkpoint_sha256=self.previous_checkpoint_sha256,
            next_checkpoint_version=self.next_checkpoint_version,
            requires_operator=self.requires_operator,
            plan_idempotency_key=self.plan_idempotency_key,
        )
        if self.plan_sha256 != expected_plan:
            raise ValueError("repair plan fingerprint does not match content")
        return self


def projection_checkpoint_fingerprint(**values: Any) -> str:
    values.pop("checkpoint_sha256", None)
    return canonical_json_fingerprint(
        _json_ready({"schema": ProjectionCheckpoint.schema_id, "data": values})
    )


def projection_assessment_fingerprint(**values: Any) -> str:
    values.pop("assessment_sha256", None)
    return canonical_json_fingerprint(
        _json_ready(
            {"schema": ProjectionConsistencyAssessment.schema_id, "data": values}
        )
    )


def projection_repair_idempotency_key(
    *,
    desired_state: ProjectionDesiredState,
    observation: ProjectionTargetObservation,
    assessment: ProjectionConsistencyAssessment,
    previous_checkpoint_sha256: str | None,
) -> str:
    return canonical_json_fingerprint(
        _json_ready({
            "schema": "gda.projection-repair-idempotency.v1",
            "desired_state": desired_state.model_dump(mode="json"),
            "observation": observation.model_dump(mode="json"),
            "assessment": assessment.model_dump(mode="json"),
            "previous_checkpoint_sha256": previous_checkpoint_sha256,
        })
    )


def projection_repair_plan_fingerprint(**values: Any) -> str:
    values.pop("plan_sha256", None)
    return canonical_json_fingerprint(
        _json_ready({"schema": ProjectionRepairPlan.schema_id, "data": values})
    )


def _assessment(
    *,
    desired: ProjectionDesiredState,
    observation: ProjectionTargetObservation,
    status: str,
    action: str,
    reason_codes: tuple[str, ...],
    checkpoint: ProjectionCheckpoint | None,
) -> ProjectionConsistencyAssessment:
    reasons = tuple(sorted(set(reason_codes)))
    expected = desired.expected_target_content_sha256
    observed = observation.observed_content_sha256
    values = {
        "tenant_id": desired.tenant_id,
        "projection_id": desired.projection_id,
        "target_engine": desired.target_engine,
        "target_ref": desired.target_ref,
        "status": status,
        "action": action,
        "reason_codes": reasons,
        "checkpoint_version": checkpoint.checkpoint_version if checkpoint else 0,
        "observed_content_sha256": observed,
        "expected_content_sha256": expected,
    }
    return ProjectionConsistencyAssessment(
        **values,
        assessment_sha256=projection_assessment_fingerprint(**values),
    )


def assess_projection_consistency(
    desired: ProjectionDesiredState,
    observation: ProjectionTargetObservation,
    checkpoint: ProjectionCheckpoint | None,
) -> ProjectionConsistencyAssessment:
    """Compare source expectation, target observation, and last committed checkpoint."""

    expected_key = _projection_key(
        desired.tenant_id,
        desired.projection_id,
        desired.target_engine,
        desired.target_ref,
    )
    observed_key = _projection_key(
        observation.tenant_id,
        observation.projection_id,
        observation.target_engine,
        observation.target_ref,
    )
    if expected_key != observed_key:
        raise ProjectionConsistencyError("desired state and observation target identity differ")
    if checkpoint is not None:
        checkpoint_key = _projection_key(
            checkpoint.tenant_id,
            checkpoint.projection_id,
            checkpoint.target_engine,
            checkpoint.target_ref,
        )
        if checkpoint_key != expected_key:
            raise ProjectionConsistencyError("checkpoint target identity differs")

    if desired.target_exists != observation.target_exists:
        if desired.target_exists:
            return _assessment(
                desired=desired,
                observation=observation,
                status="target_missing",
                action="rebuild",
                reason_codes=("target_missing",),
                checkpoint=checkpoint,
            )
        return _assessment(
            desired=desired,
            observation=observation,
            status="delete_required",
            action="delete",
            reason_codes=("target_should_be_deleted",),
            checkpoint=checkpoint,
        )

    if checkpoint is None:
        return _assessment(
            desired=desired,
            observation=observation,
            status="checkpoint_missing",
            action="fail_closed",
            reason_codes=("checkpoint_missing",),
            checkpoint=None,
        )

    if checkpoint.target_exists != observation.target_exists:
        return _assessment(
            desired=desired,
            observation=observation,
            status="checkpoint_state_drift",
            action="fail_closed",
            reason_codes=("checkpoint_state_drift",),
            checkpoint=checkpoint,
        )

    if not observation.target_exists:
        if checkpoint.source_content_sha256 != desired.source_content_sha256:
            return _assessment(
                desired=desired,
                observation=observation,
                status="source_advanced_same_target",
                action="checkpoint",
                reason_codes=("source_version_advanced", "target_remains_deleted"),
                checkpoint=checkpoint,
            )
        return _assessment(
            desired=desired,
            observation=observation,
            status="aligned_deleted",
            action="noop",
            reason_codes=("target_absence_confirmed",),
            checkpoint=checkpoint,
        )

    if (
        checkpoint.target_content_sha256 != observation.observed_content_sha256
        or checkpoint.target_row_count != observation.observed_row_count
    ):
        return _assessment(
            desired=desired,
            observation=observation,
            status="target_drift",
            action="fail_closed",
            reason_codes=("target_checkpoint_mismatch",),
            checkpoint=checkpoint,
        )

    if checkpoint.source_content_sha256 != desired.source_content_sha256:
        if (
            checkpoint.target_content_sha256
            == desired.expected_target_content_sha256
            and checkpoint.target_row_count == desired.expected_row_count
        ):
            return _assessment(
                desired=desired,
                observation=observation,
                status="source_advanced_same_target",
                action="checkpoint",
                reason_codes=("source_version_advanced", "target_content_unchanged"),
                checkpoint=checkpoint,
            )
        return _assessment(
            desired=desired,
            observation=observation,
            status="source_advanced",
            action="rebuild",
            reason_codes=("source_version_advanced",),
            checkpoint=checkpoint,
        )

    if (
        observation.observed_content_sha256 != desired.expected_target_content_sha256
        or observation.observed_row_count != desired.expected_row_count
    ):
        return _assessment(
            desired=desired,
            observation=observation,
            status="desired_content_mismatch",
            action="fail_closed",
            reason_codes=("desired_target_mismatch",),
            checkpoint=checkpoint,
        )

    return _assessment(
        desired=desired,
        observation=observation,
        status="aligned",
        action="noop",
        reason_codes=("source_and_target_aligned",),
        checkpoint=checkpoint,
    )


def build_projection_repair_plan(
    desired: ProjectionDesiredState,
    observation: ProjectionTargetObservation,
    checkpoint: ProjectionCheckpoint | None,
) -> ProjectionRepairPlan:
    assessment = assess_projection_consistency(desired, observation, checkpoint)
    if assessment.action == "noop":
        raise ProjectionConsistencyError("aligned projection does not require a repair plan")
    previous_sha = checkpoint.checkpoint_sha256 if checkpoint else None
    next_version = (checkpoint.checkpoint_version + 1) if checkpoint else 1
    key = projection_repair_idempotency_key(
        desired_state=desired,
        observation=observation,
        assessment=assessment,
        previous_checkpoint_sha256=previous_sha,
    )
    values = {
        "tenant_id": desired.tenant_id,
        "projection_id": desired.projection_id,
        "target_engine": desired.target_engine,
        "target_ref": desired.target_ref,
        "action": assessment.action,
        "reason_codes": assessment.reason_codes,
        "desired_state": desired,
        "observation": observation,
        "assessment": assessment,
        "previous_checkpoint_sha256": previous_sha,
        "next_checkpoint_version": next_version,
        "requires_operator": assessment.action == "fail_closed",
        "plan_idempotency_key": key,
    }
    return ProjectionRepairPlan(
        **values,
        plan_sha256=projection_repair_plan_fingerprint(**values),
    )


def build_projection_checkpoint_from_repair(
    plan: ProjectionRepairPlan,
    post_observation: ProjectionTargetObservation,
    *,
    target_commit_ref: dict[str, Any],
    updated_by: str,
    updated_at: datetime,
) -> ProjectionCheckpoint:
    """Create the next checkpoint only from an exact, plan-bound repair receipt."""

    if plan.action == "fail_closed":
        raise ProjectionConsistencyError("fail-closed repair plan cannot advance checkpoint")
    expected_key = _projection_key(
        plan.tenant_id,
        plan.projection_id,
        plan.target_engine,
        plan.target_ref,
    )
    observed_key = _projection_key(
        post_observation.tenant_id,
        post_observation.projection_id,
        post_observation.target_engine,
        post_observation.target_ref,
    )
    if observed_key != expected_key:
        raise ProjectionConsistencyError("post-repair observation target identity differs")
    desired = plan.desired_state
    if (
        post_observation.target_exists != desired.target_exists
        or post_observation.observed_content_sha256
        != desired.expected_target_content_sha256
        or post_observation.observed_row_count != desired.expected_row_count
    ):
        raise ProjectionConsistencyError(
            "post-repair observation does not match desired target state"
        )
    if post_observation.observed_at > _utc(updated_at):
        raise ProjectionConsistencyError(
            "checkpoint time must not precede post-repair observation"
        )
    if not updated_by.startswith(("human:", "workload:", "agent:")):
        raise ProjectionConsistencyError(
            "checkpoint updater must use a typed subject identity"
        )
    if (
        target_commit_ref.get("plan_sha256") != plan.plan_sha256
        or target_commit_ref.get("idempotency_key") != plan.plan_idempotency_key
    ):
        raise ProjectionConsistencyError(
            "target commit evidence must bind repair plan and idempotency key"
        )
    values = {
        "tenant_id": plan.tenant_id,
        "projection_id": plan.projection_id,
        "source_resource_version_ref": desired.source_resource_version_ref,
        "source_content_sha256": desired.source_content_sha256,
        "target_engine": plan.target_engine,
        "target_ref": plan.target_ref,
        "target_exists": post_observation.target_exists,
        "target_content_sha256": post_observation.observed_content_sha256,
        "target_row_count": post_observation.observed_row_count,
        "checkpoint_version": plan.next_checkpoint_version,
        "target_commit_ref": target_commit_ref,
        "updated_by": updated_by,
        "updated_at": _utc(updated_at),
    }
    return ProjectionCheckpoint(
        **values,
        checkpoint_sha256=projection_checkpoint_fingerprint(**values),
    )


@dataclass(frozen=True)
class ProjectionCheckpointWriteResult:
    checkpoint: ProjectionCheckpoint
    created: bool


class InMemoryProjectionCheckpointLedger:
    """Small deterministic ledger used by tests and local rehearsal only."""

    def __init__(self) -> None:
        self._current: dict[tuple[str, str, str, str], ProjectionCheckpoint] = {}
        self._history: defaultdict[
            tuple[str, str, str, str], list[ProjectionCheckpoint]
        ] = defaultdict(list)

    def current(
        self,
        *,
        tenant_id: str,
        projection_id: str,
        target_engine: ProjectionEngine,
        target_ref: str,
    ) -> ProjectionCheckpoint | None:
        return self._current.get(
            _projection_key(tenant_id, projection_id, target_engine, target_ref)
        )

    def history(
        self,
        *,
        tenant_id: str,
        projection_id: str,
        target_engine: ProjectionEngine,
        target_ref: str,
    ) -> tuple[ProjectionCheckpoint, ...]:
        return tuple(
            self._history.get(
                _projection_key(tenant_id, projection_id, target_engine, target_ref),
                (),
            )
        )

    def record(
        self,
        checkpoint: ProjectionCheckpoint,
        *,
        previous_checkpoint_sha256: str | None = None,
    ) -> ProjectionCheckpointWriteResult:
        key = _projection_key(
            checkpoint.tenant_id,
            checkpoint.projection_id,
            checkpoint.target_engine,
            checkpoint.target_ref,
        )
        current = self._current.get(key)
        if current is not None and current.checkpoint_sha256 == checkpoint.checkpoint_sha256:
            return ProjectionCheckpointWriteResult(checkpoint=current, created=False)
        if current is None:
            if checkpoint.checkpoint_version != 1 or previous_checkpoint_sha256 is not None:
                raise ProjectionCheckpointConflictError(
                    "initial projection checkpoint must start at version 1"
                )
        else:
            if previous_checkpoint_sha256 != current.checkpoint_sha256:
                raise ProjectionCheckpointConflictError(
                    "projection checkpoint predecessor does not match current state"
                )
            if checkpoint.checkpoint_version != current.checkpoint_version + 1:
                raise ProjectionCheckpointConflictError(
                    "projection checkpoint version must advance exactly once"
                )
        self._current[key] = checkpoint
        self._history[key].append(checkpoint)
        return ProjectionCheckpointWriteResult(checkpoint=checkpoint, created=True)


__all__ = [
    "InMemoryProjectionCheckpointLedger",
    "ProjectionCheckpoint",
    "ProjectionCheckpointConflictError",
    "ProjectionCheckpointWriteResult",
    "ProjectionConsistencyAssessment",
    "ProjectionConsistencyError",
    "ProjectionDesiredState",
    "ProjectionEngine",
    "ProjectionRepairPlan",
    "ProjectionTargetObservation",
    "assess_projection_consistency",
    "build_projection_checkpoint_from_repair",
    "build_projection_repair_plan",
    "projection_assessment_fingerprint",
    "projection_checkpoint_fingerprint",
    "projection_repair_idempotency_key",
    "projection_repair_plan_fingerprint",
]
