"""Configured service boundary for plan-bound PostGIS projection repair."""

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
from .postgis_projection_executor import (
    PostGISProjectionConfigurationError,
    PostGISProjectionExecutionError,
    PostGISProjectionRepairExecutor,
    PostGISProjectionRepairReceipt,
    PostGISProjectionTarget,
    PostGISProjectionTargetRegistry,
    PostGISProjectionValidationError,
)


class PostGISProjectionServiceError(RuntimeError):
    code = "postgis_projection_service_error"


class PostGISProjectionServiceConfigurationError(PostGISProjectionServiceError):
    code = "postgis_projection_service_unavailable"


class PostGISProjectionServiceValidationError(PostGISProjectionServiceError):
    code = "postgis_projection_repair_invalid"


class PostGISProjectionServiceConflictError(PostGISProjectionServiceError):
    code = "postgis_projection_repair_conflict"


class PostGISProjectionServiceForbiddenError(PostGISProjectionServiceError):
    code = "postgis_projection_repair_forbidden"


class PostGISProjectionRepairRequest(BaseModel):
    """Canonical REST/MCP request without writable target-registration fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    plan: ProjectionRepairPlan
    rows: tuple[dict[str, Any], ...] = Field(default=(), max_length=100_000)
    checkpointed_by: NonEmptyText = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")

    @model_validator(mode="after")
    def _action_rows(self) -> PostGISProjectionRepairRequest:
        if self.plan.target_engine is not ProjectionEngine.POSTGIS:
            raise ValueError("PostGIS repair service only accepts postgis plans")
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


class PostGISProjectionRepairResult(BaseModel):
    """Provider receipt and durable checkpoint produced by one repair request."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str = Field(pattern=r"^(completed|replayed)$")
    receipt: PostGISProjectionRepairReceipt
    checkpoint: ProjectionCheckpoint
    checkpoint_created: bool
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"


def load_postgis_projection_registry(
    raw: str | None = None,
) -> PostGISProjectionTargetRegistry:
    document = raw if raw is not None else os.environ.get("GDA_POSTGIS_PROJECTION_TARGETS_JSON", "")
    if not document.strip():
        raise PostGISProjectionServiceConfigurationError(
            "GDA_POSTGIS_PROJECTION_TARGETS_JSON is not configured"
        )
    try:
        payload = json.loads(document)
        if not isinstance(payload, list) or not payload:
            raise ValueError("target registry must be a non-empty JSON array")
        targets = tuple(PostGISProjectionTarget.model_validate(item) for item in payload)
        return PostGISProjectionTargetRegistry(targets)
    except (TypeError, ValueError) as exc:
        raise PostGISProjectionServiceConfigurationError(
            "PostGIS projection target registry is invalid"
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
        raise PostGISProjectionServiceConflictError(
            "projection authority contains duplicate plan idempotency evidence"
        )
    if not matches:
        return None
    checkpoint = matches[0]
    if (
        checkpoint.target_commit_ref.get("provider") != "postgis"
        or checkpoint.target_commit_ref.get("plan_sha256") != plan.plan_sha256
    ):
        raise PostGISProjectionServiceConflictError(
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
        raise PostGISProjectionServiceConflictError(
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
        raise PostGISProjectionServiceConflictError(
            "repair plan predecessor does not match the checkpoint authority"
        )


def _post_observation_from_receipt(
    plan: ProjectionRepairPlan,
    receipt: PostGISProjectionRepairReceipt,
) -> ProjectionTargetObservation:
    return ProjectionTargetObservation(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=plan.target_ref,
        target_exists=receipt.target_exists,
        observed_content_sha256=receipt.target_content_sha256,
        observed_row_count=receipt.target_row_count,
        observed_by="workload:postgis-projection-executor",
        observed_at=receipt.observed_at,
    )


def _assert_receipt_bound_to_plan(
    plan: ProjectionRepairPlan,
    receipt: PostGISProjectionRepairReceipt,
) -> None:
    if (
        receipt.tenant_id != plan.tenant_id
        or receipt.projection_id != plan.projection_id
        or receipt.target_ref != plan.target_ref
        or receipt.action != plan.action
        or receipt.plan_sha256 != plan.plan_sha256
        or receipt.idempotency_key != plan.plan_idempotency_key
        or receipt.provider_commit_ref.get("provider") != "postgis"
    ):
        raise PostGISProjectionServiceConflictError(
            "PostGIS provider receipt is not bound to the submitted repair plan"
        )


def _receipt_from_checkpoint(
    plan: ProjectionRepairPlan,
    checkpoint: ProjectionCheckpoint,
) -> PostGISProjectionRepairReceipt:
    return PostGISProjectionRepairReceipt(
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
    executor: PostGISProjectionRepairExecutor,
    target: PostGISProjectionTarget,
    plan: ProjectionRepairPlan,
) -> None:
    observation = executor.observe(target)
    desired = plan.desired_state
    if (
        observation.target_exists != desired.target_exists
        or observation.observed_content_sha256 != desired.expected_target_content_sha256
        or observation.observed_row_count != desired.expected_row_count
    ):
        raise PostGISProjectionServiceConflictError(
            "stored checkpoint exists but the PostGIS target has drifted"
        )


def execute_postgis_projection_repair(
    request: PostGISProjectionRepairRequest,
    *,
    database_url: str | None = None,
    registry: PostGISProjectionTargetRegistry | None = None,
    executor: PostGISProjectionRepairExecutor | None = None,
    authority: PostgresProjectionCheckpointAuthority | None = None,
) -> PostGISProjectionRepairResult:
    url = (
        database_url
        or os.environ.get("GDA_CONTROL_DATABASE_URL", "")
        or os.environ.get("DATABASE_URL", "")
    )
    if not url and (executor is None or authority is None):
        raise PostGISProjectionServiceConfigurationError("DATABASE_URL is not configured")
    targets = registry or getattr(executor, "registry", None) or load_postgis_projection_registry()
    engine = create_engine(url) if url and (executor is None or authority is None) else None
    try:
        provider = executor or PostGISProjectionRepairExecutor(engine, targets)
        checkpoint_authority = authority or PostgresProjectionCheckpointAuthority(engine)
        target = targets.resolve(
            tenant_id=request.plan.tenant_id,
            projection_id=request.plan.projection_id,
            target_ref=request.plan.target_ref,
        )
        existing = _checkpoint_for_plan(checkpoint_authority, request.plan)
        if existing is not None:
            _assert_replayed_target(provider, target, request.plan)
            return PostGISProjectionRepairResult(
                status="replayed",
                receipt=_receipt_from_checkpoint(request.plan, existing),
                checkpoint=existing,
                checkpoint_created=False,
            )
        _assert_authority_predecessor(checkpoint_authority, request.plan)
        recover_receipt = getattr(provider, "recover_receipt", None)
        receipt = (
            recover_receipt(request.plan) if callable(recover_receipt) else None
        )
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
            return PostGISProjectionRepairResult(
                status="replayed",
                receipt=_receipt_from_checkpoint(request.plan, concurrent),
                checkpoint=concurrent,
                checkpoint_created=False,
            )
        return PostGISProjectionRepairResult(
            status="completed" if written.created else "replayed",
            receipt=receipt,
            checkpoint=written.checkpoint,
            checkpoint_created=written.created,
        )
    except PostGISProjectionValidationError as exc:
        raise PostGISProjectionServiceValidationError(str(exc)) from exc
    except PostGISProjectionConfigurationError as exc:
        raise PostGISProjectionServiceConfigurationError(str(exc)) from exc
    except PostGISProjectionExecutionError as exc:
        raise PostGISProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityForbiddenError as exc:
        raise PostGISProjectionServiceForbiddenError(str(exc)) from exc
    except ProjectionCheckpointAuthorityValidationError as exc:
        raise PostGISProjectionServiceValidationError(str(exc)) from exc
    except ProjectionCheckpointConflictError as exc:
        raise PostGISProjectionServiceConflictError(str(exc)) from exc
    except ProjectionConsistencyError as exc:
        raise PostGISProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityConfigurationError as exc:
        raise PostGISProjectionServiceConfigurationError(str(exc)) from exc
    except ProjectionCheckpointAuthorityError as exc:
        raise PostGISProjectionServiceError(str(exc)) from exc
    finally:
        if engine is not None:
            engine.dispose()


__all__ = [
    "PostGISProjectionRepairRequest",
    "PostGISProjectionRepairResult",
    "PostGISProjectionServiceConfigurationError",
    "PostGISProjectionServiceConflictError",
    "PostGISProjectionServiceError",
    "PostGISProjectionServiceForbiddenError",
    "PostGISProjectionServiceValidationError",
    "execute_postgis_projection_repair",
    "load_postgis_projection_registry",
]
