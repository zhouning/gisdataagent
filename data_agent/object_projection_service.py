"""Configured service boundary for plan-bound S3 object projection repair."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import create_engine

from .cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
    ProjectionCheckpointAuthorityConfigurationError,
    ProjectionCheckpointAuthorityError,
    ProjectionCheckpointAuthorityForbiddenError,
    ProjectionCheckpointAuthorityValidationError,
)
from .cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionCheckpointConflictError,
    ProjectionConsistencyError,
    ProjectionEngine,
    ProjectionRepairPlan,
    ProjectionTargetObservation,
    build_projection_checkpoint_from_repair,
)
from .object_projection_executor import (
    ObjectProjectionConfigurationError,
    ObjectProjectionExecutionError,
    ObjectProjectionRepairExecutor,
    ObjectProjectionRepairReceipt,
    ObjectProjectionTarget,
    ObjectProjectionTargetRegistry,
    ObjectProjectionValidationError,
    object_projection_receipt_fingerprint,
)
from .platform_contracts import NonEmptyText


class ObjectProjectionServiceError(RuntimeError):
    code = "object_projection_service_error"


class ObjectProjectionServiceConfigurationError(ObjectProjectionServiceError):
    code = "object_projection_service_unavailable"


class ObjectProjectionServiceValidationError(ObjectProjectionServiceError):
    code = "object_projection_repair_invalid"


class ObjectProjectionServiceConflictError(ObjectProjectionServiceError):
    code = "object_projection_repair_conflict"


class ObjectProjectionServiceForbiddenError(ObjectProjectionServiceError):
    code = "object_projection_repair_forbidden"


class ObjectProjectionRepairRequest(BaseModel):
    """Canonical request accepting only a sealed plan and checkpoint identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    plan: ProjectionRepairPlan
    checkpointed_by: NonEmptyText = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")

    @model_validator(mode="after")
    def _plan(self) -> ObjectProjectionRepairRequest:
        if self.plan.target_engine is not ProjectionEngine.OBJECT_STORE:
            raise ValueError("object repair service only accepts object_store plans")
        if self.plan.action == "fail_closed":
            raise ValueError("fail-closed repair plans cannot be submitted")
        return self


class ObjectProjectionRepairResult(BaseModel):
    """Provider receipt and durable checkpoint produced by one object repair."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str = Field(pattern=r"^(completed|replayed)$")
    receipt: ObjectProjectionRepairReceipt
    checkpoint: ProjectionCheckpoint
    checkpoint_created: bool
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"


def load_object_projection_registry(
    raw: str | None = None,
) -> ObjectProjectionTargetRegistry:
    document = raw if raw is not None else os.environ.get("GDA_OBJECT_PROJECTION_TARGETS_JSON", "")
    if not document.strip():
        raise ObjectProjectionServiceConfigurationError(
            "GDA_OBJECT_PROJECTION_TARGETS_JSON is not configured"
        )
    try:
        payload = json.loads(document)
        if not isinstance(payload, list) or not payload:
            raise ValueError("target registry must be a non-empty JSON array")
        targets = tuple(ObjectProjectionTarget.model_validate(item) for item in payload)
        return ObjectProjectionTargetRegistry(targets)
    except (TypeError, ValueError) as exc:
        raise ObjectProjectionServiceConfigurationError(
            "object projection target registry is invalid"
        ) from exc


def _checkpoint_for_plan(authority, plan: ProjectionRepairPlan) -> ProjectionCheckpoint | None:
    history = authority.history(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=plan.target_engine,
        target_ref=plan.target_ref,
    )
    matches = tuple(
        checkpoint
        for checkpoint in history
        if checkpoint.target_commit_ref.get("idempotency_key") == plan.plan_idempotency_key
    )
    if len(matches) > 1:
        raise ObjectProjectionServiceConflictError(
            "projection authority contains duplicate plan idempotency evidence"
        )
    if not matches:
        return None
    checkpoint = matches[0]
    if (
        checkpoint.target_commit_ref.get("provider") != "s3_object_store"
        or checkpoint.target_commit_ref.get("plan_sha256") != plan.plan_sha256
    ):
        raise ObjectProjectionServiceConflictError(
            "stored checkpoint plan evidence differs from the submitted plan"
        )
    desired = plan.desired_state
    if (
        checkpoint.checkpoint_version != plan.next_checkpoint_version
        or checkpoint.source_resource_version_ref != desired.source_resource_version_ref
        or checkpoint.source_content_sha256 != desired.source_content_sha256
        or checkpoint.target_exists != desired.target_exists
        or checkpoint.target_content_sha256 != desired.expected_target_content_sha256
        or checkpoint.target_row_count != desired.expected_row_count
    ):
        raise ObjectProjectionServiceConflictError(
            "stored checkpoint evidence differs from the submitted repair plan"
        )
    return checkpoint


def _assert_authority_predecessor(authority, plan: ProjectionRepairPlan) -> None:
    current = authority.current(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=plan.target_engine,
        target_ref=plan.target_ref,
    )
    if plan.previous_checkpoint_sha256 is None:
        valid = current is None and plan.next_checkpoint_version == 1
    else:
        valid = (
            current is not None
            and current.checkpoint_sha256 == plan.previous_checkpoint_sha256
            and plan.next_checkpoint_version == current.checkpoint_version + 1
        )
    if not valid:
        raise ObjectProjectionServiceConflictError(
            "repair plan predecessor does not match the checkpoint authority"
        )


def _post_observation_from_receipt(
    plan: ProjectionRepairPlan,
    receipt: ObjectProjectionRepairReceipt,
) -> ProjectionTargetObservation:
    return ProjectionTargetObservation(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=ProjectionEngine.OBJECT_STORE,
        target_ref=plan.target_ref,
        target_exists=receipt.target_exists,
        observed_content_sha256=receipt.target_content_sha256,
        observed_row_count=receipt.target_row_count,
        observed_by="workload:object-projection-executor",
        observed_at=receipt.observed_at,
    )


def _assert_receipt_bound_to_plan(
    plan: ProjectionRepairPlan,
    receipt: ObjectProjectionRepairReceipt,
) -> None:
    expected_receipt_sha256 = object_projection_receipt_fingerprint(
        tenant_id=receipt.tenant_id,
        projection_id=receipt.projection_id,
        target_ref=receipt.target_ref,
        action=receipt.action,
        plan_sha256=receipt.plan_sha256,
        idempotency_key=receipt.idempotency_key,
        provider_commit_ref=receipt.provider_commit_ref,
        target_exists=receipt.target_exists,
        target_content_sha256=receipt.target_content_sha256,
        target_row_count=receipt.target_row_count,
        target_size_bytes=receipt.target_size_bytes,
    )
    if (
        receipt.tenant_id != plan.tenant_id
        or receipt.projection_id != plan.projection_id
        or receipt.target_ref != plan.target_ref
        or receipt.action != plan.action
        or receipt.plan_sha256 != plan.plan_sha256
        or receipt.idempotency_key != plan.plan_idempotency_key
        or receipt.provider_commit_ref.get("provider") != "s3_object_store"
        or not isinstance(receipt.provider_commit_ref.get("receipt_sha256"), str)
        or len(receipt.provider_commit_ref.get("receipt_sha256", "")) != 64
        or receipt.provider_commit_ref.get("receipt_sha256") != expected_receipt_sha256
    ):
        raise ObjectProjectionServiceConflictError(
            "object provider receipt is not bound to the submitted repair plan"
        )


def _receipt_from_checkpoint(
    plan: ProjectionRepairPlan,
    checkpoint: ProjectionCheckpoint,
) -> ObjectProjectionRepairReceipt:
    commit = checkpoint.target_commit_ref
    return ObjectProjectionRepairReceipt(
        status="replayed",
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_ref=plan.target_ref,
        action=plan.action,
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=commit,
        target_exists=checkpoint.target_exists,
        target_content_sha256=checkpoint.target_content_sha256,
        target_row_count=checkpoint.target_row_count,
        target_size_bytes=(
            int(commit.get("artifact_size_bytes", 0)) if checkpoint.target_exists else 0
        ),
        object_version_id=commit.get("version_id"),
        object_etag=commit.get("etag"),
        delete_marker_version_id=commit.get("delete_marker_version_id"),
        observed_at=checkpoint.updated_at,
    )


def _assert_replayed_target(
    executor: ObjectProjectionRepairExecutor,
    target: ObjectProjectionTarget,
    plan: ProjectionRepairPlan,
    checkpoint: ProjectionCheckpoint,
) -> None:
    observation, evidence, size = executor.observe_versioned(target)
    desired = plan.desired_state
    commit = checkpoint.target_commit_ref
    content_matches = (
        observation.target_exists == desired.target_exists
        and observation.observed_content_sha256 == desired.expected_target_content_sha256
        and observation.observed_row_count == desired.expected_row_count
    )
    if desired.target_exists:
        identity_matches = (
            evidence.version_id == commit.get("version_id")
            and evidence.etag == commit.get("etag")
            and size == int(commit.get("artifact_size_bytes", -1))
        )
    else:
        identity_matches = evidence.delete_marker_version_id == commit.get(
            "delete_marker_version_id"
        )
    if not content_matches or not identity_matches:
        raise ObjectProjectionServiceConflictError(
            "stored checkpoint exists but the object target has drifted"
        )


def execute_object_projection_repair(
    request: ObjectProjectionRepairRequest,
    *,
    database_url: str | None = None,
    registry: ObjectProjectionTargetRegistry | None = None,
    executor: ObjectProjectionRepairExecutor | None = None,
    authority: PostgresProjectionCheckpointAuthority | None = None,
) -> ObjectProjectionRepairResult:
    url = (
        database_url
        or os.environ.get("GDA_CONTROL_DATABASE_URL", "")
        or os.environ.get("DATABASE_URL", "")
    )
    if not url and authority is None:
        raise ObjectProjectionServiceConfigurationError("DATABASE_URL is not configured")
    targets = registry or getattr(executor, "registry", None) or load_object_projection_registry()
    engine = create_engine(url) if url and authority is None else None
    try:
        provider = executor or ObjectProjectionRepairExecutor(
            targets,
            access_key_id=os.environ.get("GDA_OBJECT_PROJECTION_ACCESS_KEY_ID") or None,
            secret_access_key=os.environ.get("GDA_OBJECT_PROJECTION_SECRET_ACCESS_KEY") or None,
            session_token=os.environ.get("GDA_OBJECT_PROJECTION_SESSION_TOKEN") or None,
            timeout_seconds=float(os.environ.get("GDA_OBJECT_PROJECTION_TIMEOUT_SECONDS", "120")),
        )
        checkpoint_authority = authority or PostgresProjectionCheckpointAuthority(engine)
        target = targets.resolve(
            tenant_id=request.plan.tenant_id,
            projection_id=request.plan.projection_id,
            target_ref=request.plan.target_ref,
        )
        existing = _checkpoint_for_plan(checkpoint_authority, request.plan)
        if existing is not None:
            _assert_replayed_target(provider, target, request.plan, existing)
            return ObjectProjectionRepairResult(
                status="replayed",
                receipt=_receipt_from_checkpoint(request.plan, existing),
                checkpoint=existing,
                checkpoint_created=False,
            )
        _assert_authority_predecessor(checkpoint_authority, request.plan)
        recover_receipt = getattr(provider, "recover_receipt", None)
        receipt = recover_receipt(request.plan) if callable(recover_receipt) else None
        if receipt is None:
            receipt = provider.execute(request.plan)
        _assert_receipt_bound_to_plan(request.plan, receipt)
        checkpoint = build_projection_checkpoint_from_repair(
            request.plan,
            _post_observation_from_receipt(request.plan, receipt),
            target_commit_ref=receipt.provider_commit_ref,
            updated_by=request.checkpointed_by,
            updated_at=max(datetime.now(UTC), receipt.observed_at),
        )
        try:
            written = checkpoint_authority.record(
                checkpoint,
                previous_checkpoint_sha256=request.plan.previous_checkpoint_sha256,
            )
        except ProjectionCheckpointConflictError:
            concurrent = _checkpoint_for_plan(checkpoint_authority, request.plan)
            if concurrent is None:
                raise
            _assert_replayed_target(provider, target, request.plan, concurrent)
            return ObjectProjectionRepairResult(
                status="replayed",
                receipt=_receipt_from_checkpoint(request.plan, concurrent),
                checkpoint=concurrent,
                checkpoint_created=False,
            )
        return ObjectProjectionRepairResult(
            status="completed" if written.created else "replayed",
            receipt=receipt,
            checkpoint=written.checkpoint,
            checkpoint_created=written.created,
        )
    except ObjectProjectionValidationError as exc:
        raise ObjectProjectionServiceValidationError(str(exc)) from exc
    except ObjectProjectionConfigurationError as exc:
        raise ObjectProjectionServiceConfigurationError(str(exc)) from exc
    except ObjectProjectionExecutionError as exc:
        raise ObjectProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityForbiddenError as exc:
        raise ObjectProjectionServiceForbiddenError(str(exc)) from exc
    except ProjectionCheckpointAuthorityValidationError as exc:
        raise ObjectProjectionServiceValidationError(str(exc)) from exc
    except ProjectionCheckpointConflictError as exc:
        raise ObjectProjectionServiceConflictError(str(exc)) from exc
    except ProjectionConsistencyError as exc:
        raise ObjectProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityConfigurationError as exc:
        raise ObjectProjectionServiceConfigurationError(str(exc)) from exc
    except ProjectionCheckpointAuthorityError as exc:
        raise ObjectProjectionServiceError(str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise ObjectProjectionServiceConfigurationError(
            "object projection service configuration is invalid"
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()


__all__ = [
    "ObjectProjectionRepairRequest",
    "ObjectProjectionRepairResult",
    "ObjectProjectionServiceConfigurationError",
    "ObjectProjectionServiceConflictError",
    "ObjectProjectionServiceError",
    "ObjectProjectionServiceForbiddenError",
    "ObjectProjectionServiceValidationError",
    "execute_object_projection_repair",
    "load_object_projection_registry",
]
