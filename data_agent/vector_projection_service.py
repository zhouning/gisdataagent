"""Configured service boundary for plan-bound pgvector projection repair."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

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
from .platform_contracts import NonEmptyText
from .vector_projection_executor import (
    VectorProjectionConfigurationError,
    VectorProjectionExecutionError,
    VectorProjectionRepairExecutor,
    VectorProjectionRepairReceipt,
    VectorProjectionTarget,
    VectorProjectionTargetRegistry,
    VectorProjectionValidationError,
)


class VectorProjectionServiceError(RuntimeError):
    code = "vector_projection_service_error"


class VectorProjectionServiceConfigurationError(VectorProjectionServiceError):
    code = "vector_projection_service_unavailable"


class VectorProjectionServiceValidationError(VectorProjectionServiceError):
    code = "vector_projection_repair_invalid"


class VectorProjectionServiceConflictError(VectorProjectionServiceError):
    code = "vector_projection_repair_conflict"


class VectorProjectionServiceForbiddenError(VectorProjectionServiceError):
    code = "vector_projection_repair_forbidden"


class VectorProjectionRepairRequest(BaseModel):
    """Canonical REST/MCP request without writable target-registration fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    plan: ProjectionRepairPlan
    rows: tuple[dict[str, Any], ...] = Field(default=(), max_length=100_000)
    checkpointed_by: NonEmptyText = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")

    @model_validator(mode="after")
    def _action_rows(self) -> VectorProjectionRepairRequest:
        if self.plan.target_engine is not ProjectionEngine.VECTOR:
            raise ValueError("vector repair service only accepts vector plans")
        if self.plan.action == "fail_closed":
            raise ValueError("fail-closed repair plans cannot be submitted")
        if self.plan.action in {"checkpoint", "delete"} and self.rows:
            raise ValueError(f"{self.plan.action} plans must not carry rows")
        if (
            self.plan.action == "rebuild"
            and len(self.rows) != self.plan.desired_state.expected_row_count
        ):
            raise ValueError("rebuild row count must match desired target state")
        return self


class VectorProjectionRepairResult(BaseModel):
    """Provider receipt and durable checkpoint produced by one repair request."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str = Field(pattern=r"^(completed|replayed)$")
    receipt: VectorProjectionRepairReceipt
    checkpoint: ProjectionCheckpoint
    checkpoint_created: bool
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"


def load_vector_projection_registry(
    raw: str | None = None,
) -> VectorProjectionTargetRegistry:
    document = raw if raw is not None else os.environ.get("GDA_VECTOR_PROJECTION_TARGETS_JSON", "")
    if not document.strip():
        raise VectorProjectionServiceConfigurationError(
            "GDA_VECTOR_PROJECTION_TARGETS_JSON is not configured"
        )
    try:
        payload = json.loads(document)
        if not isinstance(payload, list) or not payload:
            raise ValueError("target registry must be a non-empty JSON array")
        targets = tuple(VectorProjectionTarget.model_validate(item) for item in payload)
        return VectorProjectionTargetRegistry(targets)
    except (TypeError, ValueError) as exc:
        raise VectorProjectionServiceConfigurationError(
            "vector projection target registry is invalid"
        ) from exc


def _checkpoint_for_plan(
    authority: PostgresProjectionCheckpointAuthority,
    plan: ProjectionRepairPlan,
) -> ProjectionCheckpoint | None:
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
        raise VectorProjectionServiceConflictError(
            "projection authority contains duplicate plan idempotency evidence"
        )
    if not matches:
        return None
    checkpoint = matches[0]
    if (
        checkpoint.target_commit_ref.get("provider") != "pgvector"
        or checkpoint.target_commit_ref.get("plan_sha256") != plan.plan_sha256
    ):
        raise VectorProjectionServiceConflictError(
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
        raise VectorProjectionServiceConflictError(
            "stored checkpoint evidence differs from the submitted repair plan"
        )
    return checkpoint


def _assert_authority_predecessor(
    authority: PostgresProjectionCheckpointAuthority,
    plan: ProjectionRepairPlan,
) -> None:
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
        raise VectorProjectionServiceConflictError(
            "repair plan predecessor does not match the checkpoint authority"
        )


def _post_observation_from_receipt(
    plan: ProjectionRepairPlan,
    receipt: VectorProjectionRepairReceipt,
) -> ProjectionTargetObservation:
    return ProjectionTargetObservation(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=ProjectionEngine.VECTOR,
        target_ref=plan.target_ref,
        target_exists=receipt.target_exists,
        observed_content_sha256=receipt.target_content_sha256,
        observed_row_count=receipt.target_row_count,
        observed_by="workload:vector-projection-executor",
        observed_at=receipt.observed_at,
    )


def _assert_receipt_bound_to_plan(
    plan: ProjectionRepairPlan,
    receipt: VectorProjectionRepairReceipt,
) -> None:
    if (
        receipt.tenant_id != plan.tenant_id
        or receipt.projection_id != plan.projection_id
        or receipt.target_ref != plan.target_ref
        or receipt.action != plan.action
        or receipt.plan_sha256 != plan.plan_sha256
        or receipt.idempotency_key != plan.plan_idempotency_key
        or receipt.provider_commit_ref.get("provider") != "pgvector"
    ):
        raise VectorProjectionServiceConflictError(
            "pgvector provider receipt is not bound to the submitted repair plan"
        )


def _receipt_from_checkpoint(
    plan: ProjectionRepairPlan,
    checkpoint: ProjectionCheckpoint,
) -> VectorProjectionRepairReceipt:
    return VectorProjectionRepairReceipt(
        status="replayed",
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_ref=plan.target_ref,
        action=plan.action,
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=checkpoint.target_commit_ref,
        target_exists=checkpoint.target_exists,
        target_content_sha256=checkpoint.target_content_sha256,
        target_row_count=checkpoint.target_row_count,
        observed_at=checkpoint.updated_at,
    )


def _assert_replayed_target(
    executor: VectorProjectionRepairExecutor,
    target: VectorProjectionTarget,
    plan: ProjectionRepairPlan,
) -> None:
    observation = executor.observe(target)
    desired = plan.desired_state
    if (
        observation.target_exists != desired.target_exists
        or observation.observed_content_sha256 != desired.expected_target_content_sha256
        or observation.observed_row_count != desired.expected_row_count
    ):
        raise VectorProjectionServiceConflictError(
            "stored checkpoint exists but the vector target has drifted"
        )


def execute_vector_projection_repair(
    request: VectorProjectionRepairRequest,
    *,
    database_url: str | None = None,
    registry: VectorProjectionTargetRegistry | None = None,
    executor: VectorProjectionRepairExecutor | None = None,
    authority: PostgresProjectionCheckpointAuthority | None = None,
) -> VectorProjectionRepairResult:
    url = (
        database_url
        or os.environ.get("GDA_CONTROL_DATABASE_URL", "")
        or os.environ.get("DATABASE_URL", "")
    )
    if not url and (executor is None or authority is None):
        raise VectorProjectionServiceConfigurationError("DATABASE_URL is not configured")
    targets = registry or getattr(executor, "registry", None) or load_vector_projection_registry()
    engine = create_engine(url) if url and (executor is None or authority is None) else None
    try:
        provider = executor or VectorProjectionRepairExecutor(engine, targets)
        checkpoint_authority = authority or PostgresProjectionCheckpointAuthority(engine)
        target = targets.resolve(
            tenant_id=request.plan.tenant_id,
            projection_id=request.plan.projection_id,
            target_ref=request.plan.target_ref,
        )
        existing = _checkpoint_for_plan(checkpoint_authority, request.plan)
        if existing is not None:
            _assert_replayed_target(provider, target, request.plan)
            return VectorProjectionRepairResult(
                status="replayed",
                receipt=_receipt_from_checkpoint(request.plan, existing),
                checkpoint=existing,
                checkpoint_created=False,
            )
        _assert_authority_predecessor(checkpoint_authority, request.plan)
        recover_receipt = getattr(provider, "recover_receipt", None)
        receipt = recover_receipt(request.plan) if callable(recover_receipt) else None
        if receipt is None:
            receipt = provider.execute(request.plan, rows=request.rows)
        _assert_receipt_bound_to_plan(request.plan, receipt)
        updated_at = max(datetime.now(UTC), receipt.observed_at)
        checkpoint = build_projection_checkpoint_from_repair(
            request.plan,
            _post_observation_from_receipt(request.plan, receipt),
            target_commit_ref=receipt.provider_commit_ref,
            updated_by=request.checkpointed_by,
            updated_at=updated_at,
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
            _assert_replayed_target(provider, target, request.plan)
            return VectorProjectionRepairResult(
                status="replayed",
                receipt=_receipt_from_checkpoint(request.plan, concurrent),
                checkpoint=concurrent,
                checkpoint_created=False,
            )
        return VectorProjectionRepairResult(
            status="completed" if written.created else "replayed",
            receipt=receipt,
            checkpoint=written.checkpoint,
            checkpoint_created=written.created,
        )
    except VectorProjectionValidationError as exc:
        raise VectorProjectionServiceValidationError(str(exc)) from exc
    except VectorProjectionConfigurationError as exc:
        raise VectorProjectionServiceConfigurationError(str(exc)) from exc
    except VectorProjectionExecutionError as exc:
        raise VectorProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityForbiddenError as exc:
        raise VectorProjectionServiceForbiddenError(str(exc)) from exc
    except ProjectionCheckpointAuthorityValidationError as exc:
        raise VectorProjectionServiceValidationError(str(exc)) from exc
    except ProjectionCheckpointConflictError as exc:
        raise VectorProjectionServiceConflictError(str(exc)) from exc
    except ProjectionConsistencyError as exc:
        raise VectorProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityConfigurationError as exc:
        raise VectorProjectionServiceConfigurationError(str(exc)) from exc
    except ProjectionCheckpointAuthorityError as exc:
        raise VectorProjectionServiceError(str(exc)) from exc
    finally:
        if engine is not None:
            engine.dispose()


__all__ = [
    "VectorProjectionRepairRequest",
    "VectorProjectionRepairResult",
    "VectorProjectionServiceConfigurationError",
    "VectorProjectionServiceConflictError",
    "VectorProjectionServiceError",
    "VectorProjectionServiceForbiddenError",
    "VectorProjectionServiceValidationError",
    "execute_vector_projection_repair",
    "load_vector_projection_registry",
]
