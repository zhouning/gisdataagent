"""Cohort planning and current-state admission for cross-store projections.

This module composes the existing single-target consistency contract and the
federated recovery coordinator. It does not introduce another checkpoint or
recovery authority. A cohort is admitted only after every plan is proven to
share one immutable source snapshot and every target checkpoint is re-read.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionConsistencyAssessment,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionRepairPlan,
    ProjectionTargetObservation,
    assess_projection_consistency,
    build_projection_repair_plan,
)
from .cross_store_projection_federated_recovery import (
    FederatedProjectionItemState,
    FederatedProjectionRecoveryCoordinator,
    FederatedProjectionRecoverySnapshot,
    FederatedProjectionRecoveryState,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class ProjectionCohortError(ValueError):
    """A projection cohort cannot be planned without guessing."""


class ProjectionCohortAdmissionError(ProjectionCohortError):
    """Current source or checkpoint evidence differs from the sealed cohort."""


class ProjectionCohortStatus(StrEnum):
    ALIGNED = "aligned"
    READY = "ready"
    BLOCKED = "blocked"


class ProjectionCohortExecutionState(StrEnum):
    COMPLETED = "completed"
    RECONCILING = "reconciling"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("projection cohort timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return _utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint(_json_ready({"schema": schema, "data": payload}))


def _target_identity(
    *,
    tenant_id: str,
    projection_id: str,
    target_engine: ProjectionEngine,
    target_ref: str,
) -> tuple[str, str, str, str]:
    return tenant_id, projection_id, target_engine.value, target_ref


class ProjectionCohortTargetInput(_FrozenModel):
    """Desired, observed, and last committed state for one target."""

    desired_state: ProjectionDesiredState
    observation: ProjectionTargetObservation
    checkpoint: ProjectionCheckpoint | None = None

    @model_validator(mode="after")
    def _same_target(self) -> ProjectionCohortTargetInput:
        desired_identity = _target_identity(
            tenant_id=self.desired_state.tenant_id,
            projection_id=self.desired_state.projection_id,
            target_engine=self.desired_state.target_engine,
            target_ref=self.desired_state.target_ref,
        )
        observed_identity = _target_identity(
            tenant_id=self.observation.tenant_id,
            projection_id=self.observation.projection_id,
            target_engine=self.observation.target_engine,
            target_ref=self.observation.target_ref,
        )
        if desired_identity != observed_identity:
            raise ValueError("cohort desired state and observation target differ")
        if self.checkpoint is not None:
            checkpoint_identity = _target_identity(
                tenant_id=self.checkpoint.tenant_id,
                projection_id=self.checkpoint.projection_id,
                target_engine=self.checkpoint.target_engine,
                target_ref=self.checkpoint.target_ref,
            )
            if checkpoint_identity != desired_identity:
                raise ValueError("cohort checkpoint target differs")
        return self


class ProjectionCohortPlanningRequest(_FrozenModel):
    """One immutable source snapshot projected to an ordered target cohort."""

    schema_id: ClassVar[str] = "gda.projection-cohort-planning-request.v1"
    tenant_id: TenantId
    cohort_id: NonEmptyText
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    targets: tuple[ProjectionCohortTargetInput, ...] = Field(min_length=2, max_length=32)
    max_provider_mutations: int = Field(ge=0, le=32)
    requested_by: NonEmptyText
    requested_at: datetime
    request_sha256: Sha256

    @field_validator("requested_at")
    @classmethod
    def _requested_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _sealed_request(self) -> ProjectionCohortPlanningRequest:
        if not self.requested_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("projection cohort requester must be a typed subject")
        identities: set[tuple[str, str, str, str]] = set()
        for target in self.targets:
            desired = target.desired_state
            if (
                desired.tenant_id != self.tenant_id
                or desired.source_resource_version_ref != self.source_resource_version_ref
                or desired.source_content_sha256 != self.source_content_sha256
            ):
                raise ValueError(
                    "projection cohort targets must share one immutable source snapshot"
                )
            identity = _target_identity(
                tenant_id=desired.tenant_id,
                projection_id=desired.projection_id,
                target_engine=desired.target_engine,
                target_ref=desired.target_ref,
            )
            if identity in identities:
                raise ValueError("projection cohort targets must be unique")
            identities.add(identity)
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("projection cohort request fingerprint is invalid")
        return self


def projection_cohort_request_fingerprint(**values: Any) -> str:
    return _fingerprint(
        ProjectionCohortPlanningRequest.schema_id,
        values,
        "request_sha256",
    )


def build_projection_cohort_request(
    *,
    tenant_id: str,
    cohort_id: str,
    source_resource_version_ref: str,
    source_content_sha256: str,
    targets: Sequence[ProjectionCohortTargetInput],
    max_provider_mutations: int,
    requested_by: str,
    requested_at: datetime,
) -> ProjectionCohortPlanningRequest:
    values = {
        "tenant_id": tenant_id,
        "cohort_id": cohort_id,
        "source_resource_version_ref": source_resource_version_ref,
        "source_content_sha256": source_content_sha256,
        "targets": tuple(targets),
        "max_provider_mutations": max_provider_mutations,
        "requested_by": requested_by,
        "requested_at": _utc(requested_at),
    }
    return ProjectionCohortPlanningRequest(
        **values,
        request_sha256=projection_cohort_request_fingerprint(**values),
    )


class ProjectionCohortTargetAssessment(_FrozenModel):
    """Read-only assessment for one cohort position."""

    schema_id: ClassVar[str] = "gda.projection-cohort-target-assessment.v1"
    position: int = Field(ge=0, le=31)
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    assessment: ProjectionConsistencyAssessment
    target_assessment_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_assessment(self) -> ProjectionCohortTargetAssessment:
        if (
            self.projection_id != self.assessment.projection_id
            or self.target_engine is not self.assessment.target_engine
            or self.target_ref != self.assessment.target_ref
        ):
            raise ValueError("cohort target assessment identity differs")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"target_assessment_sha256"}),
            "target_assessment_sha256",
        )
        if self.target_assessment_sha256 != expected:
            raise ValueError("cohort target assessment fingerprint is invalid")
        return self


def _target_assessment(
    position: int,
    assessment: ProjectionConsistencyAssessment,
) -> ProjectionCohortTargetAssessment:
    values = {
        "position": position,
        "projection_id": assessment.projection_id,
        "target_engine": assessment.target_engine,
        "target_ref": assessment.target_ref,
        "assessment": assessment,
    }
    return ProjectionCohortTargetAssessment(
        **values,
        target_assessment_sha256=_fingerprint(
            ProjectionCohortTargetAssessment.schema_id,
            values,
            "target_assessment_sha256",
        ),
    )


def _blocked_reason_codes(
    assessments: Sequence[ProjectionCohortTargetAssessment],
    *,
    provider_mutation_count: int,
    max_provider_mutations: int,
) -> tuple[str, ...]:
    reasons = {
        f"target[{item.position}]:{reason}"
        for item in assessments
        if item.assessment.action == "fail_closed"
        for reason in item.assessment.reason_codes
    }
    if provider_mutation_count > max_provider_mutations:
        reasons.add("provider_mutation_budget_exceeded")
    return tuple(sorted(reasons))


def projection_cohort_plan_set_fingerprint(
    request_sha256: str,
    plan_sha256s: Sequence[str],
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": "gda.projection-cohort-plan-set.v1",
            "request_sha256": request_sha256,
            "plan_sha256s": list(plan_sha256s),
        }
    )


class ProjectionCohortPlan(_FrozenModel):
    """All-target preflight result with write payloads exposed only when ready."""

    schema_id: ClassVar[str] = "gda.projection-cohort-plan.v1"
    request: ProjectionCohortPlanningRequest
    status: ProjectionCohortStatus
    target_assessments: tuple[ProjectionCohortTargetAssessment, ...] = Field(
        min_length=2, max_length=32
    )
    executable_plans: tuple[ProjectionRepairPlan, ...] = ()
    provider_mutation_count: int = Field(ge=0, le=32)
    checkpoint_only_count: int = Field(ge=0, le=32)
    blocked_reason_codes: tuple[NonEmptyText, ...] = ()
    cross_target_atomic: Literal[False] = False
    plan_set_sha256: Sha256
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_plan(self) -> ProjectionCohortPlan:
        if tuple(item.position for item in self.target_assessments) != tuple(
            range(len(self.request.targets))
        ):
            raise ValueError("projection cohort assessment positions are not contiguous")
        expected_assessments: list[ProjectionCohortTargetAssessment] = []
        candidate_plans: list[ProjectionRepairPlan] = []
        for position, target in enumerate(self.request.targets):
            assessment = assess_projection_consistency(
                target.desired_state,
                target.observation,
                target.checkpoint,
            )
            expected_assessments.append(_target_assessment(position, assessment))
            if assessment.action not in {"noop", "fail_closed"}:
                candidate_plans.append(
                    build_projection_repair_plan(
                        target.desired_state,
                        target.observation,
                        target.checkpoint,
                    )
                )
        if tuple(expected_assessments) != self.target_assessments:
            raise ValueError("projection cohort target assessments are not canonical")

        provider_mutations = sum(
            item.assessment.action in {"rebuild", "delete"} for item in self.target_assessments
        )
        checkpoint_only = sum(
            item.assessment.action == "checkpoint" for item in self.target_assessments
        )
        if (
            self.provider_mutation_count != provider_mutations
            or self.checkpoint_only_count != checkpoint_only
        ):
            raise ValueError("projection cohort action counts are invalid")
        blocked_reasons = _blocked_reason_codes(
            self.target_assessments,
            provider_mutation_count=provider_mutations,
            max_provider_mutations=self.request.max_provider_mutations,
        )
        expected_status = (
            ProjectionCohortStatus.BLOCKED
            if blocked_reasons
            else (
                ProjectionCohortStatus.ALIGNED
                if not candidate_plans
                else ProjectionCohortStatus.READY
            )
        )
        if self.status is not expected_status:
            raise ValueError("projection cohort status is not canonical")
        if self.blocked_reason_codes != blocked_reasons:
            raise ValueError("projection cohort blocked reasons are not canonical")
        expected_executable = (
            tuple(candidate_plans) if expected_status is ProjectionCohortStatus.READY else ()
        )
        if self.executable_plans != expected_executable:
            raise ValueError("projection cohort executable plans must be hidden unless fully ready")
        expected_set = projection_cohort_plan_set_fingerprint(
            self.request.request_sha256,
            tuple(item.plan_sha256 for item in self.executable_plans),
        )
        if self.plan_set_sha256 != expected_set:
            raise ValueError("projection cohort plan set fingerprint is invalid")
        expected_plan = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"plan_sha256"}),
            "plan_sha256",
        )
        if self.plan_sha256 != expected_plan:
            raise ValueError("projection cohort plan fingerprint is invalid")
        return self


def build_projection_cohort_plan(
    request: ProjectionCohortPlanningRequest,
) -> ProjectionCohortPlan:
    request = ProjectionCohortPlanningRequest.model_validate(request.model_dump(mode="json"))
    assessments = tuple(
        _target_assessment(
            position,
            assess_projection_consistency(
                target.desired_state,
                target.observation,
                target.checkpoint,
            ),
        )
        for position, target in enumerate(request.targets)
    )
    provider_mutations = sum(
        item.assessment.action in {"rebuild", "delete"} for item in assessments
    )
    checkpoint_only = sum(item.assessment.action == "checkpoint" for item in assessments)
    blocked_reasons = _blocked_reason_codes(
        assessments,
        provider_mutation_count=provider_mutations,
        max_provider_mutations=request.max_provider_mutations,
    )
    candidate_plans = tuple(
        build_projection_repair_plan(
            target.desired_state,
            target.observation,
            target.checkpoint,
        )
        for target, assessment in zip(request.targets, assessments, strict=True)
        if assessment.assessment.action not in {"noop", "fail_closed"}
    )
    status = (
        ProjectionCohortStatus.BLOCKED
        if blocked_reasons
        else (
            ProjectionCohortStatus.ALIGNED if not candidate_plans else ProjectionCohortStatus.READY
        )
    )
    executable = candidate_plans if status is ProjectionCohortStatus.READY else ()
    values = {
        "request": request,
        "status": status,
        "target_assessments": assessments,
        "executable_plans": executable,
        "provider_mutation_count": provider_mutations,
        "checkpoint_only_count": checkpoint_only,
        "blocked_reason_codes": blocked_reasons,
        "cross_target_atomic": False,
        "plan_set_sha256": projection_cohort_plan_set_fingerprint(
            request.request_sha256,
            tuple(item.plan_sha256 for item in executable),
        ),
    }
    return ProjectionCohortPlan(
        **values,
        plan_sha256=_fingerprint(
            ProjectionCohortPlan.schema_id,
            values,
            "plan_sha256",
        ),
    )


class ProjectionSourceSnapshotEvidence(_FrozenModel):
    """Current read proving that the pinned immutable source still matches."""

    schema_id: ClassVar[str] = "gda.projection-source-snapshot-evidence.v1"
    tenant_id: TenantId
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    observed_by: NonEmptyText
    observed_at: datetime
    evidence_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _observed_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _sealed_evidence(self) -> ProjectionSourceSnapshotEvidence:
        if not self.observed_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("source snapshot observer must be a typed subject")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"evidence_sha256"}),
            "evidence_sha256",
        )
        if self.evidence_sha256 != expected:
            raise ValueError("source snapshot evidence fingerprint is invalid")
        return self


def build_projection_source_snapshot_evidence(
    *,
    tenant_id: str,
    source_resource_version_ref: str,
    source_content_sha256: str,
    observed_by: str,
    observed_at: datetime,
) -> ProjectionSourceSnapshotEvidence:
    values = {
        "tenant_id": tenant_id,
        "source_resource_version_ref": source_resource_version_ref,
        "source_content_sha256": source_content_sha256,
        "observed_by": observed_by,
        "observed_at": _utc(observed_at),
    }
    return ProjectionSourceSnapshotEvidence(
        **values,
        evidence_sha256=_fingerprint(
            ProjectionSourceSnapshotEvidence.schema_id,
            values,
            "evidence_sha256",
        ),
    )


class ProjectionSourceSnapshotReader(Protocol):
    def read(
        self,
        *,
        tenant_id: str,
        source_resource_version_ref: str,
    ) -> ProjectionSourceSnapshotEvidence: ...


class ProjectionCheckpointCurrentReader(Protocol):
    def current(
        self,
        *,
        tenant_id: str,
        projection_id: str,
        target_engine: ProjectionEngine | str,
        target_ref: str,
    ) -> ProjectionCheckpoint | None: ...


class ProjectionCohortCheckpointAdmission(_FrozenModel):
    schema_id: ClassVar[str] = "gda.projection-cohort-checkpoint-admission.v1"
    position: int = Field(ge=0, le=31)
    plan_sha256: Sha256
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    expected_checkpoint_sha256: Sha256 | None
    current_checkpoint_sha256: Sha256 | None
    current_checkpoint_version: int = Field(ge=0)
    authority_state: Literal["predecessor_confirmed", "committed_confirmed"]
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_checkpoint_admission(self) -> ProjectionCohortCheckpointAdmission:
        if self.expected_checkpoint_sha256 != self.current_checkpoint_sha256:
            raise ValueError("cohort checkpoint current differs from expected state")
        if self.current_checkpoint_sha256 is None and self.current_checkpoint_version != 0:
            raise ValueError("missing cohort checkpoint must use version zero")
        if self.current_checkpoint_sha256 is not None and self.current_checkpoint_version < 1:
            raise ValueError("existing cohort checkpoint must use a positive version")
        if self.authority_state == "committed_confirmed" and self.current_checkpoint_sha256 is None:
            raise ValueError("committed cohort item requires a current checkpoint")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"evidence_sha256"}),
            "evidence_sha256",
        )
        if self.evidence_sha256 != expected:
            raise ValueError("cohort checkpoint admission fingerprint is invalid")
        return self


class ProjectionCohortExecutionAdmission(_FrozenModel):
    """All-target current-read proof created before federated recovery advances."""

    schema_id: ClassVar[str] = "gda.projection-cohort-execution-admission.v1"
    tenant_id: TenantId
    cohort_plan_sha256: Sha256
    plan_sha256s: tuple[Sha256, ...] = Field(min_length=2, max_length=32)
    federated_snapshot_sha256: Sha256
    source_evidence: ProjectionSourceSnapshotEvidence
    checkpoints: tuple[ProjectionCohortCheckpointAdmission, ...] = Field(
        min_length=2, max_length=32
    )
    admitted_by: NonEmptyText
    admitted_at: datetime
    source_snapshot_read_performed: Literal[True] = True
    all_checkpoint_currents_verified: Literal[True] = True
    provider_access_allowed: Literal[True] = True
    checkpoint_write_performed: Literal[False] = False
    cross_target_atomic: Literal[False] = False
    admission_sha256: Sha256

    @field_validator("admitted_at")
    @classmethod
    def _admitted_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _sealed_admission(self) -> ProjectionCohortExecutionAdmission:
        if not self.admitted_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("projection cohort admission actor must be typed")
        if self.source_evidence.tenant_id != self.tenant_id:
            raise ValueError("projection cohort source evidence tenant differs")
        if tuple(item.position for item in self.checkpoints) != tuple(range(len(self.checkpoints))):
            raise ValueError("projection cohort checkpoint admissions are not contiguous")
        if tuple(item.plan_sha256 for item in self.checkpoints) != self.plan_sha256s:
            raise ValueError("projection cohort checkpoint plan bindings differ")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"admission_sha256"}),
            "admission_sha256",
        )
        if self.admission_sha256 != expected:
            raise ValueError("projection cohort execution admission fingerprint is invalid")
        return self


def _read_source_snapshot(
    plan: ProjectionCohortPlan,
    reader: ProjectionSourceSnapshotReader,
) -> ProjectionSourceSnapshotEvidence:
    try:
        evidence = reader.read(
            tenant_id=plan.request.tenant_id,
            source_resource_version_ref=plan.request.source_resource_version_ref,
        )
    except Exception as exc:
        raise ProjectionCohortAdmissionError(
            "projection cohort source snapshot read failed"
        ) from exc
    if not isinstance(evidence, ProjectionSourceSnapshotEvidence):
        raise ProjectionCohortAdmissionError(
            "projection cohort source reader returned invalid evidence"
        )
    if (
        evidence.tenant_id != plan.request.tenant_id
        or evidence.source_resource_version_ref != plan.request.source_resource_version_ref
        or evidence.source_content_sha256 != plan.request.source_content_sha256
    ):
        raise ProjectionCohortAdmissionError(
            "projection cohort source snapshot differs from the sealed request"
        )
    return evidence


def _read_checkpoint(
    *,
    position: int,
    repair_plan: ProjectionRepairPlan,
    item_state: FederatedProjectionItemState,
    item_checkpoint_sha256: str | None,
    reader: ProjectionCheckpointCurrentReader,
) -> ProjectionCohortCheckpointAdmission:
    if item_state is FederatedProjectionItemState.AUTHORITY_COMMITTED:
        expected_sha = item_checkpoint_sha256
        expected_version = repair_plan.next_checkpoint_version
        authority_state: Literal["predecessor_confirmed", "committed_confirmed"] = (
            "committed_confirmed"
        )
    else:
        expected_sha = repair_plan.previous_checkpoint_sha256
        expected_version = repair_plan.next_checkpoint_version - 1
        authority_state = "predecessor_confirmed"
    try:
        current = reader.current(
            tenant_id=repair_plan.tenant_id,
            projection_id=repair_plan.projection_id,
            target_engine=repair_plan.target_engine,
            target_ref=repair_plan.target_ref,
        )
    except Exception as exc:
        raise ProjectionCohortAdmissionError(
            "projection cohort checkpoint current read failed"
        ) from exc
    if current is not None and not isinstance(current, ProjectionCheckpoint):
        raise ProjectionCohortAdmissionError(
            "projection cohort checkpoint reader returned invalid evidence"
        )
    current_sha = current.checkpoint_sha256 if current is not None else None
    current_version = current.checkpoint_version if current is not None else 0
    if current is not None:
        current_identity = _target_identity(
            tenant_id=current.tenant_id,
            projection_id=current.projection_id,
            target_engine=current.target_engine,
            target_ref=current.target_ref,
        )
        plan_identity = _target_identity(
            tenant_id=repair_plan.tenant_id,
            projection_id=repair_plan.projection_id,
            target_engine=repair_plan.target_engine,
            target_ref=repair_plan.target_ref,
        )
        if current_identity != plan_identity:
            raise ProjectionCohortAdmissionError(
                "projection cohort checkpoint target identity differs"
            )
    if current_sha != expected_sha or current_version != expected_version:
        raise ProjectionCohortAdmissionError(
            "projection cohort checkpoint current differs from the recovery cursor"
        )
    values = {
        "position": position,
        "plan_sha256": repair_plan.plan_sha256,
        "target_engine": repair_plan.target_engine,
        "target_ref": repair_plan.target_ref,
        "expected_checkpoint_sha256": expected_sha,
        "current_checkpoint_sha256": current_sha,
        "current_checkpoint_version": current_version,
        "authority_state": authority_state,
    }
    return ProjectionCohortCheckpointAdmission(
        **values,
        evidence_sha256=_fingerprint(
            ProjectionCohortCheckpointAdmission.schema_id,
            values,
            "evidence_sha256",
        ),
    )


def admit_projection_cohort_execution(
    plan: ProjectionCohortPlan,
    federated_snapshot: FederatedProjectionRecoverySnapshot,
    *,
    source_reader: ProjectionSourceSnapshotReader,
    checkpoint_reader: ProjectionCheckpointCurrentReader,
    admitted_by: str,
    admitted_at: datetime,
) -> ProjectionCohortExecutionAdmission:
    """Re-read all current evidence before a federated run or resume advances."""

    if plan.status is not ProjectionCohortStatus.READY:
        raise ProjectionCohortAdmissionError("only a ready projection cohort can be admitted")
    if len(plan.executable_plans) < 2:
        raise ProjectionCohortAdmissionError(
            "federated cohort admission requires at least two executable plans"
        )
    expected_plan_sha256s = tuple(item.plan_sha256 for item in plan.executable_plans)
    if (
        federated_snapshot.tenant_id != plan.request.tenant_id
        or federated_snapshot.plan_sha256s != expected_plan_sha256s
    ):
        raise ProjectionCohortAdmissionError(
            "federated recovery snapshot differs from the cohort plan"
        )
    source_evidence = _read_source_snapshot(plan, source_reader)
    checkpoints = tuple(
        _read_checkpoint(
            position=position,
            repair_plan=repair_plan,
            item_state=item.state,
            item_checkpoint_sha256=item.checkpoint_sha256,
            reader=checkpoint_reader,
        )
        for position, (repair_plan, item) in enumerate(
            zip(
                plan.executable_plans,
                federated_snapshot.items,
                strict=True,
            )
        )
    )
    values = {
        "tenant_id": plan.request.tenant_id,
        "cohort_plan_sha256": plan.plan_sha256,
        "plan_sha256s": expected_plan_sha256s,
        "federated_snapshot_sha256": federated_snapshot.snapshot_sha256,
        "source_evidence": source_evidence,
        "checkpoints": checkpoints,
        "admitted_by": admitted_by,
        "admitted_at": _utc(admitted_at),
        "source_snapshot_read_performed": True,
        "all_checkpoint_currents_verified": True,
        "provider_access_allowed": True,
        "checkpoint_write_performed": False,
        "cross_target_atomic": False,
    }
    return ProjectionCohortExecutionAdmission(
        **values,
        admission_sha256=_fingerprint(
            ProjectionCohortExecutionAdmission.schema_id,
            values,
            "admission_sha256",
        ),
    )


class ProjectionCohortExecutionResult(_FrozenModel):
    """Outcome of one admitted advance, preserving partial recovery evidence."""

    schema_id: ClassVar[str] = "gda.projection-cohort-execution-result.v1"
    cohort_plan: ProjectionCohortPlan
    admission: ProjectionCohortExecutionAdmission
    state: ProjectionCohortExecutionState
    federated_snapshot: FederatedProjectionRecoverySnapshot
    committed_plan_sha256s: tuple[Sha256, ...]
    pending_plan_sha256s: tuple[Sha256, ...]
    coordinator_advance_invoked: Literal[True] = True
    cross_target_atomic: Literal[False] = False
    error_type: NonEmptyText | None = None
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_result(self) -> ProjectionCohortExecutionResult:
        plan_sha256s = tuple(item.plan_sha256 for item in self.cohort_plan.executable_plans)
        if (
            self.cohort_plan.status is not ProjectionCohortStatus.READY
            or self.admission.cohort_plan_sha256 != self.cohort_plan.plan_sha256
            or self.admission.plan_sha256s != plan_sha256s
            or self.federated_snapshot.plan_sha256s != plan_sha256s
        ):
            raise ValueError("projection cohort result bindings differ")
        if self.committed_plan_sha256s != self.federated_snapshot.committed_plan_sha256s:
            raise ValueError("projection cohort committed evidence differs")
        expected_pending = tuple(
            item for item in plan_sha256s if item not in self.committed_plan_sha256s
        )
        if self.pending_plan_sha256s != expected_pending:
            raise ValueError("projection cohort pending evidence differs")
        if self.state is ProjectionCohortExecutionState.COMPLETED:
            if (
                self.federated_snapshot.state is not FederatedProjectionRecoveryState.COMPLETED
                or self.pending_plan_sha256s
                or self.error_type is not None
            ):
                raise ValueError("completed projection cohort has incomplete evidence")
        elif self.federated_snapshot.state is FederatedProjectionRecoveryState.COMPLETED:
            raise ValueError("completed federated snapshot cannot remain reconciling")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("projection cohort execution result fingerprint is invalid")
        return self


def execute_federated_projection_cohort(
    plan: ProjectionCohortPlan,
    coordinator: FederatedProjectionRecoveryCoordinator,
    *,
    source_reader: ProjectionSourceSnapshotReader,
    checkpoint_reader: ProjectionCheckpointCurrentReader,
    admitted_by: str,
    admitted_at: datetime,
    max_steps_per_item: int = 8,
) -> ProjectionCohortExecutionResult:
    """Admit then advance an existing generic federated recovery coordinator."""

    if max_steps_per_item < 1 or max_steps_per_item > 100:
        raise ProjectionCohortAdmissionError(
            "projection cohort step budget must be between 1 and 100"
        )
    expected_plans = tuple(item.plan_sha256 for item in plan.executable_plans)
    coordinator_plans = tuple(item.plan_sha256 for item in coordinator.plans)
    if expected_plans != coordinator_plans:
        raise ProjectionCohortAdmissionError(
            "projection cohort coordinator plans differ from the sealed cohort"
        )
    admission = admit_projection_cohort_execution(
        plan,
        coordinator.snapshot,
        source_reader=source_reader,
        checkpoint_reader=checkpoint_reader,
        admitted_by=admitted_by,
        admitted_at=admitted_at,
    )
    error_type: str | None = None
    try:
        snapshot = coordinator.advance(max_steps_per_item=max_steps_per_item)
    except Exception as exc:
        snapshot = coordinator.snapshot
        error_type = type(exc).__name__
    state = (
        ProjectionCohortExecutionState.COMPLETED
        if snapshot.state is FederatedProjectionRecoveryState.COMPLETED
        else ProjectionCohortExecutionState.RECONCILING
    )
    plan_sha256s = tuple(item.plan_sha256 for item in plan.executable_plans)
    values = {
        "cohort_plan": plan,
        "admission": admission,
        "state": state,
        "federated_snapshot": snapshot,
        "committed_plan_sha256s": snapshot.committed_plan_sha256s,
        "pending_plan_sha256s": tuple(
            item for item in plan_sha256s if item not in snapshot.committed_plan_sha256s
        ),
        "coordinator_advance_invoked": True,
        "cross_target_atomic": False,
        "error_type": error_type,
    }
    return ProjectionCohortExecutionResult(
        **values,
        result_sha256=_fingerprint(
            ProjectionCohortExecutionResult.schema_id,
            values,
            "result_sha256",
        ),
    )


__all__ = [
    "ProjectionCheckpointCurrentReader",
    "ProjectionCohortAdmissionError",
    "ProjectionCohortCheckpointAdmission",
    "ProjectionCohortError",
    "ProjectionCohortExecutionAdmission",
    "ProjectionCohortExecutionResult",
    "ProjectionCohortExecutionState",
    "ProjectionCohortPlan",
    "ProjectionCohortPlanningRequest",
    "ProjectionCohortStatus",
    "ProjectionCohortTargetAssessment",
    "ProjectionCohortTargetInput",
    "ProjectionSourceSnapshotEvidence",
    "ProjectionSourceSnapshotReader",
    "admit_projection_cohort_execution",
    "build_projection_cohort_plan",
    "build_projection_cohort_request",
    "build_projection_source_snapshot_evidence",
    "execute_federated_projection_cohort",
    "projection_cohort_plan_set_fingerprint",
    "projection_cohort_request_fingerprint",
]
