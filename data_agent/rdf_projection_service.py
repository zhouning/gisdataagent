"""Configured service boundary for plan-bound RDF projection repair."""

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
from .platform_contracts import NonEmptyText
from .rdf_projection_executor import (
    RDFProjectionConfigurationError,
    RDFProjectionExecutionError,
    RDFProjectionRepairExecutor,
    RDFProjectionRepairReceipt,
    RDFProjectionTarget,
    RDFProjectionTargetRegistry,
    RDFProjectionValidationError,
)


class RDFProjectionServiceError(RuntimeError):
    code = "rdf_projection_service_error"


class RDFProjectionServiceConfigurationError(RDFProjectionServiceError):
    code = "rdf_projection_service_unavailable"


class RDFProjectionServiceValidationError(RDFProjectionServiceError):
    code = "rdf_projection_repair_invalid"


class RDFProjectionServiceConflictError(RDFProjectionServiceError):
    code = "rdf_projection_repair_conflict"


class RDFProjectionServiceForbiddenError(RDFProjectionServiceError):
    code = "rdf_projection_repair_forbidden"


class RDFProjectionRepairRequest(BaseModel):
    """Canonical REST/MCP request with no endpoint, credentials, or RDF body."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    plan: ProjectionRepairPlan
    checkpointed_by: NonEmptyText = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")

    @model_validator(mode="after")
    def _plan(self) -> RDFProjectionRepairRequest:
        if self.plan.target_engine is not ProjectionEngine.RDF:
            raise ValueError("RDF repair service only accepts RDF plans")
        if self.plan.action == "fail_closed":
            raise ValueError("fail-closed repair plans cannot be submitted")
        return self


class RDFProjectionRepairResult(BaseModel):
    """Provider receipt and durable checkpoint produced by one RDF repair."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str = Field(pattern=r"^(completed|replayed)$")
    receipt: RDFProjectionRepairReceipt
    checkpoint: ProjectionCheckpoint
    checkpoint_created: bool
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"


def load_rdf_projection_registry(raw: str | None = None) -> RDFProjectionTargetRegistry:
    document = raw if raw is not None else os.environ.get("GDA_RDF_PROJECTION_TARGETS_JSON", "")
    if not document.strip():
        raise RDFProjectionServiceConfigurationError(
            "GDA_RDF_PROJECTION_TARGETS_JSON is not configured"
        )
    try:
        payload = json.loads(document)
        if not isinstance(payload, list) or not payload:
            raise ValueError("target registry must be a non-empty JSON array")
        targets = tuple(RDFProjectionTarget.model_validate(item) for item in payload)
        return RDFProjectionTargetRegistry(targets)
    except (TypeError, ValueError) as exc:
        raise RDFProjectionServiceConfigurationError(
            "RDF projection target registry is invalid"
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
        raise RDFProjectionServiceConflictError(
            "projection authority contains duplicate plan idempotency evidence"
        )
    if not matches:
        return None
    checkpoint = matches[0]
    if (
        checkpoint.target_commit_ref.get("provider") != "rdf_fuseki"
        or checkpoint.target_commit_ref.get("plan_sha256") != plan.plan_sha256
    ):
        raise RDFProjectionServiceConflictError(
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
        raise RDFProjectionServiceConflictError(
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
        raise RDFProjectionServiceConflictError(
            "repair plan predecessor does not match the checkpoint authority"
        )


def _post_observation_from_receipt(
    plan: ProjectionRepairPlan,
    receipt: RDFProjectionRepairReceipt,
) -> ProjectionTargetObservation:
    return ProjectionTargetObservation(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=ProjectionEngine.RDF,
        target_ref=plan.target_ref,
        target_exists=receipt.target_exists,
        observed_content_sha256=receipt.target_content_sha256,
        observed_row_count=receipt.target_row_count,
        observed_by="workload:rdf-projection-executor",
        observed_at=receipt.observed_at,
    )


def _assert_receipt_bound_to_plan(
    plan: ProjectionRepairPlan,
    receipt: RDFProjectionRepairReceipt,
) -> None:
    if (
        receipt.tenant_id != plan.tenant_id
        or receipt.projection_id != plan.projection_id
        or receipt.target_ref != plan.target_ref
        or receipt.action != plan.action
        or receipt.plan_sha256 != plan.plan_sha256
        or receipt.idempotency_key != plan.plan_idempotency_key
        or receipt.provider_commit_ref.get("provider") != "rdf_fuseki"
    ):
        raise RDFProjectionServiceConflictError(
            "RDF provider receipt is not bound to the submitted repair plan"
        )


def _receipt_from_checkpoint(
    plan: ProjectionRepairPlan,
    checkpoint: ProjectionCheckpoint,
) -> RDFProjectionRepairReceipt:
    return RDFProjectionRepairReceipt(
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
    executor: RDFProjectionRepairExecutor,
    target: RDFProjectionTarget,
    plan: ProjectionRepairPlan,
) -> None:
    observation = executor.observe(target)
    desired = plan.desired_state
    if (
        observation.target_exists != desired.target_exists
        or observation.observed_content_sha256 != desired.expected_target_content_sha256
        or observation.observed_row_count != desired.expected_row_count
    ):
        raise RDFProjectionServiceConflictError(
            "stored checkpoint exists but the RDF target has drifted"
        )


def execute_rdf_projection_repair(
    request: RDFProjectionRepairRequest,
    *,
    database_url: str | None = None,
    registry: RDFProjectionTargetRegistry | None = None,
    executor: RDFProjectionRepairExecutor | None = None,
    authority: PostgresProjectionCheckpointAuthority | None = None,
) -> RDFProjectionRepairResult:
    url = (
        database_url
        or os.environ.get("GDA_CONTROL_DATABASE_URL", "")
        or os.environ.get("DATABASE_URL", "")
    )
    if not url and authority is None:
        raise RDFProjectionServiceConfigurationError("DATABASE_URL is not configured")
    targets = registry or getattr(executor, "registry", None) or load_rdf_projection_registry()
    engine = create_engine(url) if url and authority is None else None
    try:
        provider = executor or RDFProjectionRepairExecutor(
            targets,
            username=os.environ.get("GDA_RDF_PROJECTION_USERNAME") or None,
            password=os.environ.get("GDA_RDF_PROJECTION_PASSWORD") or None,
            timeout_seconds=float(os.environ.get("GDA_RDF_PROJECTION_TIMEOUT_SECONDS", "120")),
        )
        checkpoint_authority = authority or PostgresProjectionCheckpointAuthority(engine)
        target = targets.resolve(
            tenant_id=request.plan.tenant_id,
            projection_id=request.plan.projection_id,
            target_ref=request.plan.target_ref,
        )
        existing = _checkpoint_for_plan(checkpoint_authority, request.plan)
        if existing is not None:
            _assert_replayed_target(provider, target, request.plan)
            return RDFProjectionRepairResult(
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
            _assert_replayed_target(provider, target, request.plan)
            return RDFProjectionRepairResult(
                status="replayed",
                receipt=_receipt_from_checkpoint(request.plan, concurrent),
                checkpoint=concurrent,
                checkpoint_created=False,
            )
        return RDFProjectionRepairResult(
            status="completed" if written.created else "replayed",
            receipt=receipt,
            checkpoint=written.checkpoint,
            checkpoint_created=written.created,
        )
    except RDFProjectionValidationError as exc:
        raise RDFProjectionServiceValidationError(str(exc)) from exc
    except RDFProjectionConfigurationError as exc:
        raise RDFProjectionServiceConfigurationError(str(exc)) from exc
    except RDFProjectionExecutionError as exc:
        raise RDFProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityForbiddenError as exc:
        raise RDFProjectionServiceForbiddenError(str(exc)) from exc
    except ProjectionCheckpointAuthorityValidationError as exc:
        raise RDFProjectionServiceValidationError(str(exc)) from exc
    except ProjectionCheckpointConflictError as exc:
        raise RDFProjectionServiceConflictError(str(exc)) from exc
    except ProjectionConsistencyError as exc:
        raise RDFProjectionServiceConflictError(str(exc)) from exc
    except ProjectionCheckpointAuthorityConfigurationError as exc:
        raise RDFProjectionServiceConfigurationError(str(exc)) from exc
    except ProjectionCheckpointAuthorityError as exc:
        raise RDFProjectionServiceError(str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise RDFProjectionServiceConfigurationError(
            "RDF projection service configuration is invalid"
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()


__all__ = [
    "RDFProjectionRepairRequest",
    "RDFProjectionRepairResult",
    "RDFProjectionServiceConfigurationError",
    "RDFProjectionServiceConflictError",
    "RDFProjectionServiceError",
    "RDFProjectionServiceForbiddenError",
    "RDFProjectionServiceValidationError",
    "execute_rdf_projection_repair",
    "load_rdf_projection_registry",
]
