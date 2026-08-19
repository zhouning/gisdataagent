"""Configured service boundary for plan-bound Iceberg projection repair."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

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
from .lakehouse_projection_executor import (
    LakehouseProjectionConfigurationError,
    LakehouseProjectionExecutionError,
    LakehouseProjectionRepairExecutor,
    LakehouseProjectionRepairReceipt,
    LakehouseProjectionTarget,
    LakehouseProjectionTargetRegistry,
    LakehouseProjectionValidationError,
)
from .lakehouse_projection_spark_provider import DockerSparkIcebergProjectionProvider
from .platform_contracts import NonEmptyText


class LakehouseProjectionServiceError(RuntimeError):
    code = "lakehouse_projection_service_error"


class LakehouseProjectionServiceConfigurationError(LakehouseProjectionServiceError):
    code = "lakehouse_projection_service_unavailable"


class LakehouseProjectionServiceValidationError(LakehouseProjectionServiceError):
    code = "lakehouse_projection_repair_invalid"


class LakehouseProjectionServiceConflictError(LakehouseProjectionServiceError):
    code = "lakehouse_projection_repair_conflict"


class LakehouseProjectionServiceForbiddenError(LakehouseProjectionServiceError):
    code = "lakehouse_projection_repair_forbidden"


class LakehouseProjectionRepairRequest(BaseModel):
    """Canonical request accepting only a sealed plan and checkpoint identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    plan: ProjectionRepairPlan
    checkpointed_by: NonEmptyText = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")

    @model_validator(mode="after")
    def _plan(self) -> LakehouseProjectionRepairRequest:
        if self.plan.target_engine is not ProjectionEngine.LAKEHOUSE:
            raise ValueError("lakehouse repair service only accepts lakehouse plans")
        if self.plan.action == "fail_closed":
            raise ValueError("fail-closed repair plans cannot be submitted")
        return self


class LakehouseProjectionRepairResult(BaseModel):
    """Provider receipt and durable checkpoint produced by one Iceberg repair."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str = Field(pattern=r"^(completed|replayed)$")
    receipt: LakehouseProjectionRepairReceipt
    checkpoint: ProjectionCheckpoint
    checkpoint_created: bool
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"


def load_lakehouse_projection_registry(
    raw: str | None = None,
) -> LakehouseProjectionTargetRegistry:
    document = (
        raw if raw is not None else os.environ.get("GDA_LAKEHOUSE_PROJECTION_TARGETS_JSON", "")
    )
    if not document.strip():
        raise LakehouseProjectionServiceConfigurationError(
            "GDA_LAKEHOUSE_PROJECTION_TARGETS_JSON is not configured"
        )
    try:
        payload = json.loads(document)
        if not isinstance(payload, list) or not payload:
            raise ValueError("target registry must be a non-empty JSON array")
        targets = tuple(LakehouseProjectionTarget.model_validate(item) for item in payload)
        return LakehouseProjectionTargetRegistry(targets)
    except (TypeError, ValueError) as exc:
        raise LakehouseProjectionServiceConfigurationError(
            "lakehouse projection target registry is invalid"
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
        raise LakehouseProjectionServiceConflictError(
            "projection authority contains duplicate plan idempotency evidence"
        )
    if not matches:
        return None
    checkpoint = matches[0]
    if (
        checkpoint.target_commit_ref.get("provider") != "spark_iceberg"
        or checkpoint.target_commit_ref.get("plan_sha256") != plan.plan_sha256
    ):
        raise LakehouseProjectionServiceConflictError(
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
        raise LakehouseProjectionServiceConflictError(
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
        raise LakehouseProjectionServiceConflictError(
            "repair plan predecessor does not match the checkpoint authority"
        )


def _post_observation_from_receipt(
    plan: ProjectionRepairPlan,
    receipt: LakehouseProjectionRepairReceipt,
) -> ProjectionTargetObservation:
    return ProjectionTargetObservation(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=ProjectionEngine.LAKEHOUSE,
        target_ref=plan.target_ref,
        target_exists=receipt.target_exists,
        observed_content_sha256=receipt.target_content_sha256,
        observed_row_count=receipt.target_row_count,
        observed_by="workload:lakehouse-projection-executor",
        observed_at=receipt.observed_at,
    )


def _assert_receipt_bound_to_plan(
    plan: ProjectionRepairPlan,
    receipt: LakehouseProjectionRepairReceipt,
) -> None:
    if (
        receipt.tenant_id != plan.tenant_id
        or receipt.projection_id != plan.projection_id
        or receipt.target_ref != plan.target_ref
        or receipt.action != plan.action
        or receipt.plan_sha256 != plan.plan_sha256
        or receipt.idempotency_key != plan.plan_idempotency_key
        or receipt.provider_commit_ref.get("provider") != "spark_iceberg"
    ):
        raise LakehouseProjectionServiceConflictError(
            "lakehouse provider receipt is not bound to the submitted repair plan"
        )


def _receipt_from_checkpoint(
    plan: ProjectionRepairPlan,
    checkpoint: ProjectionCheckpoint,
) -> LakehouseProjectionRepairReceipt:
    commit = checkpoint.target_commit_ref
    return LakehouseProjectionRepairReceipt(
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
        snapshot_id=commit.get("snapshot_id"),
        deleted_snapshot_id=commit.get("deleted_snapshot_id"),
        drop_evidence_sha256=commit.get("drop_evidence_sha256"),
        observed_at=checkpoint.updated_at,
    )


def _assert_replayed_target(
    executor: LakehouseProjectionRepairExecutor,
    target: LakehouseProjectionTarget,
    plan: ProjectionRepairPlan,
    checkpoint: ProjectionCheckpoint,
) -> None:
    observation, evidence = executor.observe_versioned(target)
    desired = plan.desired_state
    commit = checkpoint.target_commit_ref
    content_matches = (
        observation.target_exists == desired.target_exists
        and observation.observed_content_sha256 == desired.expected_target_content_sha256
        and observation.observed_row_count == desired.expected_row_count
    )
    if desired.target_exists:
        identity_matches = evidence.snapshot_id == commit.get("snapshot_id")
    else:
        identity_matches = (
            not evidence.target_exists
            and evidence.deleted_snapshot_id == commit.get("deleted_snapshot_id")
            and evidence.drop_evidence_sha256 == commit.get("drop_evidence_sha256")
            and evidence.tombstone_plan_sha256 == commit.get("tombstone_plan_sha256")
            and evidence.tombstone_idempotency_key == commit.get("tombstone_idempotency_key")
        )
    if not content_matches or not identity_matches:
        raise LakehouseProjectionServiceConflictError(
            "stored checkpoint exists but the Iceberg target has drifted"
        )


def _default_executor(
    registry: LakehouseProjectionTargetRegistry,
) -> LakehouseProjectionRepairExecutor:
    try:
        timeout = float(os.environ.get("GDA_LAKEHOUSE_PROJECTION_TIMEOUT_SECONDS", "600"))
        root = Path(
            os.environ.get("GDA_LAKEHOUSE_PROJECTION_REPOSITORY_ROOT")
            or Path(__file__).resolve().parents[1]
        )
        provider = DockerSparkIcebergProjectionProvider(
            repository_root=root,
            image=os.environ.get(
                "GDA_LAKEHOUSE_PROJECTION_SPARK_IMAGE",
                "gisdataagent/mmfe-spark-runtime:local",
            ),
            docker_network=os.environ.get(
                "GDA_LAKEHOUSE_PROJECTION_DOCKER_NETWORK",
                "gisdataagent_agent-net",
            ),
            access_key_id=os.environ.get("GDA_LAKEHOUSE_PROJECTION_ACCESS_KEY_ID", ""),
            secret_access_key=os.environ.get("GDA_LAKEHOUSE_PROJECTION_SECRET_ACCESS_KEY", ""),
            session_token=os.environ.get("GDA_LAKEHOUSE_PROJECTION_SESSION_TOKEN") or None,
            java_home=os.environ.get(
                "GDA_LAKEHOUSE_PROJECTION_JAVA_HOME",
                "/usr/lib/jvm/java-17-openjdk-arm64",
            ),
            timeout_seconds=timeout,
        )
        return LakehouseProjectionRepairExecutor(registry, provider=provider)
    except (TypeError, ValueError) as exc:
        raise LakehouseProjectionServiceConfigurationError(
            "lakehouse projection provider configuration is invalid"
        ) from exc


def execute_lakehouse_projection_repair(
    request: LakehouseProjectionRepairRequest,
    *,
    database_url: str | None = None,
    registry: LakehouseProjectionTargetRegistry | None = None,
    executor: LakehouseProjectionRepairExecutor | None = None,
    authority: PostgresProjectionCheckpointAuthority | None = None,
) -> LakehouseProjectionRepairResult:
    url = (
        database_url
        or os.environ.get("GDA_CONTROL_DATABASE_URL", "")
        or os.environ.get("DATABASE_URL", "")
    )
    if not url and authority is None:
        raise LakehouseProjectionServiceConfigurationError("DATABASE_URL is not configured")
    targets = (
        registry or getattr(executor, "registry", None) or load_lakehouse_projection_registry()
    )
    engine = create_engine(url) if url and authority is None else None
    try:
        provider = executor or _default_executor(targets)
        checkpoint_authority = authority or PostgresProjectionCheckpointAuthority(engine)
        target = targets.resolve(
            tenant_id=request.plan.tenant_id,
            projection_id=request.plan.projection_id,
            target_ref=request.plan.target_ref,
        )
        existing = _checkpoint_for_plan(checkpoint_authority, request.plan)
        if existing is not None:
            _assert_replayed_target(provider, target, request.plan, existing)
            return LakehouseProjectionRepairResult(
                status="replayed",
                receipt=_receipt_from_checkpoint(request.plan, existing),
                checkpoint=existing,
                checkpoint_created=False,
            )
        _assert_authority_predecessor(checkpoint_authority, request.plan)
        receipt = provider.recover_receipt(request.plan)
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
            return LakehouseProjectionRepairResult(
                status="replayed",
                receipt=_receipt_from_checkpoint(request.plan, concurrent),
                checkpoint=concurrent,
                checkpoint_created=False,
            )
        return LakehouseProjectionRepairResult(
            status="completed" if written.created else "replayed",
            receipt=receipt,
            checkpoint=written.checkpoint,
            checkpoint_created=written.created,
        )
    except LakehouseProjectionValidationError as exc:
        raise LakehouseProjectionServiceValidationError(str(exc)) from exc
    except LakehouseProjectionConfigurationError as exc:
        raise LakehouseProjectionServiceConfigurationError(str(exc)) from exc
    except LakehouseProjectionExecutionError as exc:
        raise LakehouseProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityForbiddenError as exc:
        raise LakehouseProjectionServiceForbiddenError(str(exc)) from exc
    except ProjectionCheckpointAuthorityValidationError as exc:
        raise LakehouseProjectionServiceValidationError(str(exc)) from exc
    except ProjectionCheckpointConflictError as exc:
        raise LakehouseProjectionServiceConflictError(str(exc)) from exc
    except ProjectionConsistencyError as exc:
        raise LakehouseProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityConfigurationError as exc:
        raise LakehouseProjectionServiceConfigurationError(str(exc)) from exc
    except ProjectionCheckpointAuthorityError as exc:
        raise LakehouseProjectionServiceError(str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise LakehouseProjectionServiceConfigurationError(
            "lakehouse projection service configuration is invalid"
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()


__all__ = [
    "LakehouseProjectionRepairRequest",
    "LakehouseProjectionRepairResult",
    "LakehouseProjectionServiceConfigurationError",
    "LakehouseProjectionServiceConflictError",
    "LakehouseProjectionServiceError",
    "LakehouseProjectionServiceForbiddenError",
    "LakehouseProjectionServiceValidationError",
    "execute_lakehouse_projection_repair",
    "load_lakehouse_projection_registry",
]
