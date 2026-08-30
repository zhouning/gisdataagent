"""Managed Temporal history reconciler with PostgreSQL lease fencing."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import logging
import math
import os
import re
import signal
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from prometheus_client import start_http_server
from pydantic import Field, ValidationError, field_validator

from .agentops_specialist_providers import (
    SpecialistActivityReconciliation,
    SpecialistArtifactStore,
    SpecialistOperationAuthority,
    SpecialistProviderCancellationAdapter,
    SpecialistReconciliationVerdict,
)
from .agentops_temporal_adapter import (
    TemporalActivityAdapter,
    TemporalAdapterError,
    TemporalProviderWorkflowInputObservation,
)
from .agentops_temporal_checkpoint_authority import (
    AgentOpsTemporalCheckpointAuthorityConfigurationError,
    AgentOpsTemporalCheckpointAuthorityConflictError,
    AgentOpsTemporalCheckpointAuthorityError,
    AgentOpsTemporalReconcilerLease,
    PostgresAgentOpsTemporalCheckpointAuthority,
)
from .agentops_temporal_reconciliation import (
    TemporalCheckpointReconciliation,
    TemporalCheckpointReconciliationVerdict,
    TemporalProviderActivityHistoryStatus,
    TemporalProviderWorkflowHistoryObservation,
    reconcile_specialist_activity_history,
    reconcile_temporal_checkpoint,
)
from .agentops_temporal_start_target_authority import (
    PostgresAgentOpsTemporalStartTargetAuthority,
    TemporalStartTarget,
)
from .agentops_temporal_workflow import TemporalTaskGraphWorkflowCheckpoint
from .observability import (
    agentops_temporal_discovery_cycle_duration,
    agentops_temporal_discovery_last_success_timestamp,
    agentops_temporal_discovery_operations,
)
from .platform_contracts import FrozenContract, TenantId

LOGGER = logging.getLogger(__name__)

_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9._-]{1,62}$")
_WORKFLOW_RE = re.compile(r"^[a-z][a-z0-9._:-]{1,254}$")
_LEASE_OWNER_RE = re.compile(r"^(workload|agent):[^\s]{1,128}$")
DEFAULT_DISCOVERY_STATUS_FILE = Path(
    "/tmp/gda-agentops-temporal-discovery-status.json"
)
REQUIRED_TEMPORAL_SDK_VERSION = "1.32.0"
REQUIRED_RUNTIME_MIGRATIONS = (
    "240_agentops_temporal_checkpoint_authority",
    "241_agentops_temporal_reconciler_fencing",
    "242_agentops_temporal_start_target_authority",
    "246_agentops_specialist_operation_receipt_authority",
    "247_agentops_specialist_operation_uncertainty",
    "248_agentops_specialist_retry_budget_authority",
)


class AgentOpsTemporalReconcilerWorkerError(RuntimeError):
    """Base error for the managed Temporal reconciler worker."""


class AgentOpsTemporalReconcilerWorkerConfigurationError(
    AgentOpsTemporalReconcilerWorkerError
):
    """Worker configuration is missing or cannot preserve lease safety."""


class AgentOpsTemporalReconcilerLeaseLostError(
    AgentOpsTemporalReconcilerWorkerError
):
    """The worker stopped because its reconciler lease could not be renewed."""


class AgentOpsTemporalReconcilerObservationTimeoutError(
    AgentOpsTemporalReconcilerWorkerError
):
    """Temporal history observation exceeded the configured bound."""


def evaluate_runtime_image_contract() -> tuple[dict[str, Any], bool]:
    """Inspect dependencies shipped in the running discovery container."""

    from .migration_runner import catalog_fingerprint, discover_migrations

    errors: list[str] = []
    try:
        temporal_sdk_version = importlib.metadata.version("temporalio")
    except importlib.metadata.PackageNotFoundError:
        temporal_sdk_version = None
        errors.append("temporalio is not installed")

    try:
        migrations = discover_migrations()
        migration_names = {item.migration_id for item in migrations}
        missing_migrations = sorted(set(REQUIRED_RUNTIME_MIGRATIONS) - migration_names)
        migration_count = len(migrations)
        migration_fingerprint = catalog_fingerprint(migrations)
    except Exception as exc:
        missing_migrations = list(REQUIRED_RUNTIME_MIGRATIONS)
        migration_count = 0
        migration_fingerprint = None
        errors.append(f"migration catalog inspection failed: {type(exc).__name__}")

    if temporal_sdk_version != REQUIRED_TEMPORAL_SDK_VERSION:
        errors.append(
            "temporalio version mismatch: "
            f"observed={temporal_sdk_version!r}, required={REQUIRED_TEMPORAL_SDK_VERSION!r}"
        )
    if missing_migrations:
        errors.append(f"required migrations are absent: {missing_migrations!r}")

    passed = not errors
    report = {
        "schema": "gda.agentops-temporal-discovery-image-contract.v1",
        "passed": passed,
        "temporal_sdk_version": temporal_sdk_version,
        "required_temporal_sdk_version": REQUIRED_TEMPORAL_SDK_VERSION,
        "required_migrations": list(REQUIRED_RUNTIME_MIGRATIONS),
        "missing_migrations": missing_migrations,
        "migration_catalog_count": migration_count,
        "migration_catalog_fingerprint": migration_fingerprint,
        "errors": errors,
    }
    return report, passed


@dataclass(frozen=True)
class _SpecialistRuntimeDependencies:
    """Durable authorities shared by explicit and discovery worker entrypoints."""

    artifact_store: SpecialistArtifactStore
    operation_authority: SpecialistOperationAuthority
    checkpoint_authority: TemporalCheckpointAuthority
    start_target_authority: TemporalStartTargetAuthority


def _record_discovery_operation(outcome: str, count: int = 1) -> None:
    try:
        agentops_temporal_discovery_operations.labels(outcome=outcome).inc(count)
    except Exception:
        LOGGER.exception("Could not record AgentOps discovery metric")


def _observe_discovery_cycle(duration_seconds: float) -> None:
    try:
        agentops_temporal_discovery_cycle_duration.observe(duration_seconds)
    except Exception:
        LOGGER.exception("Could not record AgentOps discovery cycle duration")


def _record_discovery_success() -> None:
    try:
        agentops_temporal_discovery_last_success_timestamp.set_to_current_time()
    except Exception:
        LOGGER.exception("Could not record AgentOps discovery success timestamp")


class TemporalHistoryObserver(Protocol):
    async def observe_workflow_history(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        provider_run_id: str | None,
    ) -> TemporalProviderWorkflowHistoryObservation: ...


class TemporalCheckpointAuthority(Protocol):
    def acquire_reconciler_lease(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        lease_owner: str,
        lease_seconds: int = 60,
    ) -> AgentOpsTemporalReconcilerLease: ...

    def renew_reconciler_lease(
        self,
        lease: AgentOpsTemporalReconcilerLease,
        *,
        lease_seconds: int = 60,
    ) -> AgentOpsTemporalReconcilerLease: ...

    def release_reconciler_lease(
        self, lease: AgentOpsTemporalReconcilerLease
    ) -> AgentOpsTemporalReconcilerLease: ...

    def current_checkpoint(
        self, *, tenant_id: str, workflow_id: str
    ) -> TemporalTaskGraphWorkflowCheckpoint | None: ...

    def record_reconciliation(
        self,
        observation: TemporalProviderWorkflowHistoryObservation,
        reconciliation: TemporalCheckpointReconciliation,
        *,
        recorded_by: str,
        lease: AgentOpsTemporalReconcilerLease | None = None,
    ) -> Any: ...

    def resolve_reconciliation_write(
        self,
        observation: TemporalProviderWorkflowHistoryObservation,
        reconciliation: TemporalCheckpointReconciliation,
    ) -> Any | None: ...


class TemporalStartTargetAuthority(Protocol):
    def claim_due_targets(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        namespace_ref: str | None = None,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> tuple[TemporalStartTarget, ...]: ...

    def renew_target_claim(
        self, target: TemporalStartTarget, *, worker_id: str, lease_seconds: int = 60
    ) -> TemporalStartTarget: ...

    def attach_provider_run(
        self,
        target: TemporalStartTarget,
        observation: TemporalProviderWorkflowInputObservation,
        *,
        worker_id: str,
    ) -> TemporalStartTarget: ...

    def complete_target(
        self, target: TemporalStartTarget, *, worker_id: str
    ) -> TemporalStartTarget: ...

    def release_target_claim(
        self,
        target: TemporalStartTarget,
        *,
        worker_id: str,
        error: str,
        retry_after_seconds: float = 1.0,
    ) -> TemporalStartTarget: ...

    def fail_target(
        self, target: TemporalStartTarget, *, worker_id: str, error: str
    ) -> TemporalStartTarget: ...


def _required_runtime_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            f"{name} is required for specialist reconciliation"
        )
    return value


def _runtime_env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AgentOpsTemporalReconcilerWorkerConfigurationError(
        f"{name} must be a boolean"
    )


def _absolute_runtime_path(name: str) -> Path:
    value = Path(_required_runtime_env(name)).expanduser()
    if not value.is_absolute():
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            f"{name} must be an absolute path"
        )
    return value.resolve()


def _build_specialist_runtime_dependencies(
    tenant_id: str,
) -> _SpecialistRuntimeDependencies:
    """Build the durable specialist authorities used by live worker entrypoints.

    The worker deliberately does not fall back to an in-memory receipt authority or
    an unconfigured content backend.  A provider-bound activity must be reconciled
    against the same PostgreSQL Artifact and operation-receipt authorities used by
    execution, otherwise a restart could silently lose the provider operation
    identity.
    """

    from .agentops_specialist_operation_authority import (
        PostgresSpecialistOperationAuthority,
        SpecialistOperationAuthorityError,
    )
    from .agentops_specialist_providers import (
        FilesystemArtifactContentBackend,
        PostgresArtifactAuthoritySpecialistStore,
        S3ArtifactContentBackend,
        SpecialistProviderError,
    )
    from .agentops_temporal_start_target_authority import (
        PostgresAgentOpsTemporalStartTargetAuthority,
    )
    from .db_engine import get_engine
    from .platform_gateway import (
        GatewayNotFoundError,
        PlatformGateway,
        PlatformGatewayError,
    )

    try:
        engine = get_engine()
    except Exception as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist PostgreSQL engine could not be initialized"
        ) from exc
    if engine is None:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "DATABASE_URL is required for specialist Artifact and receipt authorities"
        )
    try:
        engine_dialect = getattr(getattr(engine, "dialect", None), "name", None)
    except Exception as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist PostgreSQL engine dialect could not be inspected"
        ) from exc
    if engine_dialect != "postgresql":
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist Artifact and receipt authorities require PostgreSQL"
        )

    backend_kind = _required_runtime_env(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND"
    ).lower()
    materialization_root = _absolute_runtime_path(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT"
    )
    try:
        if backend_kind == "filesystem":
            content_backend = FilesystemArtifactContentBackend(
                _absolute_runtime_path(
                    "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT"
                )
            )
        elif backend_kind in {"s3", "minio"}:
            bucket = _required_runtime_env(
                "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_BUCKET"
            )
            endpoint = os.environ.get(
                "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_ENDPOINT", ""
            ).strip()
            prefix = (
                os.environ.get(
                    "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_PREFIX",
                    "agentops-specialist/v1",
                ).strip()
                or "agentops-specialist/v1"
            )
            if not _runtime_env_bool(
                "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_VERSION_ID",
                default=True,
            ):
                raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                    "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_VERSION_ID must be true"
                )
            if not _runtime_env_bool(
                "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_OBJECT_LOCK_RETENTION",
                default=True,
            ):
                raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                    "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_OBJECT_LOCK_RETENTION "
                    "must be true"
                )
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                    "S3 specialist artifact backend requires boto3"
                ) from exc
            client_kwargs: dict[str, Any] = {
                "region_name": os.environ.get(
                    "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REGION", "us-east-1"
                ).strip()
                or "us-east-1"
            }
            if endpoint:
                client_kwargs["endpoint_url"] = endpoint
            access_key = os.environ.get(
                "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_ACCESS_KEY_ID", ""
            ).strip()
            secret_key = os.environ.get(
                "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_SECRET_ACCESS_KEY", ""
            ).strip()
            if bool(access_key) != bool(secret_key):
                raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                    "specialist S3 access key and secret key must be configured together"
                )
            if access_key:
                client_kwargs.update(
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                )
            addressing_style = os.environ.get(
                "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_ADDRESSING_STYLE",
                "path" if endpoint else "auto",
            ).strip().lower()
            if addressing_style not in {"auto", "path", "virtual"}:
                raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                    "specialist S3 addressing style must be auto, path, or virtual"
                )
            client_kwargs["config"] = Config(
                s3={"addressing_style": addressing_style}
            )
            content_backend = S3ArtifactContentBackend(
                boto3.client("s3", **client_kwargs),
                bucket=bucket,
                prefix=prefix,
                require_version_id=True,
                require_object_lock_retention=True,
            )
            try:
                content_backend.probe()
            except SpecialistProviderError as exc:
                raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                    str(exc)
                ) from exc
        else:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND must be filesystem or s3"
            )
    except AgentOpsTemporalReconcilerWorkerConfigurationError:
        raise
    except Exception as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist Artifact content backend could not be initialized"
        ) from exc

    try:
        gateway = PlatformGateway(engine)
    except Exception as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist Artifact authority configuration is invalid"
        ) from exc
    try:
        operation_authority = PostgresSpecialistOperationAuthority(
            tenant_id,
            engine,
            recorded_by=os.environ.get(
                "GDA_AGENTOPS_RECONCILER_SPECIALIST_RECORDED_BY",
                "workload:agentops-specialist-reconciler",
            ).strip()
            or "workload:agentops-specialist-reconciler",
        )
    except Exception as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist operation authority configuration is invalid"
        ) from exc
    # These read-only probes fail before Temporal polling when migration 246,
    # the gateway role, or the Artifact table is unavailable.
    try:
        operation_authority.observe("__agentops_reconciler_startup_probe__")
    except SpecialistOperationAuthorityError as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist operation receipt authority is unavailable; apply migration 246 "
            "and verify the gateway role"
        ) from exc
    except Exception as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist operation receipt authority probe failed"
        ) from exc
    try:
        gateway.get_artifact(tenant_id, UUID(int=0))
    except GatewayNotFoundError:
        pass
    except PlatformGatewayError as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist Artifact authority is unavailable; verify the gateway role and schema"
        ) from exc
    except Exception as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist Artifact authority probe failed"
        ) from exc

    try:
        artifact_store = PostgresArtifactAuthoritySpecialistStore(
            tenant_id,
            gateway=gateway,
            content_backend=content_backend,
            materialization_root=materialization_root,
        )
        checkpoint_authority = PostgresAgentOpsTemporalCheckpointAuthority(engine)
        start_target_authority = PostgresAgentOpsTemporalStartTargetAuthority(engine)
    except Exception as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "specialist durable authorities could not be initialized"
        ) from exc

    return _SpecialistRuntimeDependencies(
        artifact_store=artifact_store,
        operation_authority=operation_authority,
        checkpoint_authority=checkpoint_authority,
        start_target_authority=start_target_authority,
    )


@dataclass(frozen=True)
class AgentOpsTemporalReconcilerWorkerConfig:
    tenant_id: str
    namespace_ref: str
    frontend_target: str
    workflow_id: str
    provider_run_id: str
    lease_owner: str
    lease_seconds: int = 60
    heartbeat_interval_seconds: float = 15.0
    observation_timeout_seconds: float = 30.0
    poll_interval_seconds: float = 5.0

    @classmethod
    def from_env(
        cls, environ: dict[str, str] | None = None
    ) -> AgentOpsTemporalReconcilerWorkerConfig:
        values = os.environ if environ is None else environ

        def required(name: str) -> str:
            value = values.get(name, "").strip()
            if not value:
                raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                    f"{name} is required"
                )
            return value

        try:
            config = cls(
                tenant_id=required("GDA_AGENTOPS_RECONCILER_TENANT_ID"),
                namespace_ref=required("GDA_AGENTOPS_RECONCILER_NAMESPACE"),
                frontend_target=required("GDA_AGENTOPS_RECONCILER_FRONTEND"),
                workflow_id=required("GDA_AGENTOPS_RECONCILER_WORKFLOW_ID"),
                provider_run_id=required(
                    "GDA_AGENTOPS_RECONCILER_PROVIDER_RUN_ID"
                ),
                lease_owner=values.get(
                    "GDA_AGENTOPS_RECONCILER_WORKER_ID",
                    (
                        "workload:agentops-temporal-reconciler:"
                        f"{socket.gethostname()}:{os.getpid()}"
                    ),
                ).strip(),
                lease_seconds=int(
                    values.get("GDA_AGENTOPS_RECONCILER_LEASE_SECONDS", "60")
                ),
                heartbeat_interval_seconds=float(
                    values.get(
                        "GDA_AGENTOPS_RECONCILER_HEARTBEAT_SECONDS", "15"
                    )
                ),
                observation_timeout_seconds=float(
                    values.get(
                        "GDA_AGENTOPS_RECONCILER_OBSERVATION_TIMEOUT_SECONDS",
                        "30",
                    )
                ),
                poll_interval_seconds=float(
                    values.get("GDA_AGENTOPS_RECONCILER_POLL_SECONDS", "5")
                ),
            )
        except ValueError as exc:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler numeric configuration is invalid"
            ) from exc
        config.validate()
        return config

    def validate(self) -> None:
        if _TENANT_RE.fullmatch(self.tenant_id) is None:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler tenant_id is invalid"
            )
        if _NAMESPACE_RE.fullmatch(self.namespace_ref) is None:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler namespace_ref is invalid"
            )
        if _WORKFLOW_RE.fullmatch(self.workflow_id) is None:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler workflow_id is invalid"
            )
        if (
            not self.provider_run_id.strip()
            or len(self.provider_run_id.encode("utf-8")) > 512
        ):
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler provider_run_id is invalid"
            )
        if _LEASE_OWNER_RE.fullmatch(self.lease_owner) is None:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler worker identity must be a workload or agent"
            )
        host, separator, port_text = self.frontend_target.rpartition(":")
        if (
            not separator
            or not host
            or any(character.isspace() for character in host)
            or not port_text.isdigit()
            or not 1 <= int(port_text) <= 65_535
        ):
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler frontend target must be host:port"
            )
        if not 3 <= self.lease_seconds <= 3_600:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler lease must be 3..3600 seconds"
            )
        if not 0.1 <= self.heartbeat_interval_seconds < self.lease_seconds / 2:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler heartbeat must be shorter than half the lease"
            )
        if not 0.1 <= self.observation_timeout_seconds <= 3_600:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler observation timeout is invalid"
            )
        if not 0.1 <= self.poll_interval_seconds <= 300:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps reconciler poll interval is invalid"
            )


class AgentOpsTemporalReconcilerCycleStatus(StrEnum):
    RECORDED = "recorded"
    RECOVERED = "recovered"
    NO_CHECKPOINT = "no_checkpoint"


class AgentOpsTemporalSpecialistCycleStatus(StrEnum):
    """Summary of provider-bound activity receipt reconciliation in one cycle."""

    NO_ACTIVITY = "no_specialist_activity"
    AWAITING_TERMINAL = "awaiting_terminal"
    ALREADY_SETTLED = "already_settled"
    UNKNOWN_PENDING = "unknown_pending"
    MATCHED_SUCCEEDED = "matched_succeeded"
    DEFINITIVE_FAILED = "definitive_failed"
    MIXED = "mixed"


@dataclass(frozen=True)
class AgentOpsTemporalReconcilerCycle:
    tenant_id: str
    workflow_id: str
    provider_run_id: str
    lease_epoch: int
    status: AgentOpsTemporalReconcilerCycleStatus
    checkpoint_sha256: str | None = None
    history_sha256: str | None = None
    reconciliation_sha256: str | None = None
    verdict: TemporalCheckpointReconciliationVerdict | None = None
    created: bool = False
    specialist_status: AgentOpsTemporalSpecialistCycleStatus = (
        AgentOpsTemporalSpecialistCycleStatus.NO_ACTIVITY
    )
    specialist_activity_ids: tuple[str, ...] = ()
    specialist_terminal_activity_ids: tuple[str, ...] = ()
    specialist_unknown_pending_ids: tuple[str, ...] = ()
    specialist_matched_succeeded_ids: tuple[str, ...] = ()
    specialist_definitive_failed_ids: tuple[str, ...] = ()
    specialist_reconciliation_sha256: tuple[str, ...] = ()
    checkpoint_missing_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SpecialistReconciliationSummary:
    """In-memory join of specialist receipts and checkpoint evidence."""

    status: AgentOpsTemporalSpecialistCycleStatus
    activity_ids: tuple[str, ...] = ()
    terminal_activity_ids: tuple[str, ...] = ()
    unknown_pending_ids: tuple[str, ...] = ()
    matched_succeeded_ids: tuple[str, ...] = ()
    definitive_failed_ids: tuple[str, ...] = ()
    reconciliation_sha256: tuple[str, ...] = ()
    evidence_by_activity: dict[Any, Any] | None = None
    reconciliations: tuple[SpecialistActivityReconciliation, ...] = ()


@dataclass
class _LeaseSession:
    lease: AgentOpsTemporalReconcilerLease
    stop: asyncio.Event
    lost: asyncio.Event
    error: Exception | None = None


class AgentOpsTemporalReconcilerWorker:
    """Observe one workflow and persist reconciliation under a fenced lease."""

    def __init__(
        self,
        config: AgentOpsTemporalReconcilerWorkerConfig,
        *,
        provider: TemporalHistoryObserver,
        authority: TemporalCheckpointAuthority | None = None,
        artifact_store: SpecialistArtifactStore | None = None,
        operation_authority: SpecialistOperationAuthority | None = None,
        cancellation_adapters: Mapping[str, SpecialistProviderCancellationAdapter]
        | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.provider = provider
        self.authority = authority or PostgresAgentOpsTemporalCheckpointAuthority()
        if (artifact_store is None) != (operation_authority is None):
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "specialist artifact_store and operation_authority must be supplied together"
            )
        self.artifact_store = artifact_store
        self.operation_authority = operation_authority
        self.cancellation_adapters = dict(cancellation_adapters or {})

    async def _renew_loop(self, session: _LeaseSession) -> None:
        while not session.stop.is_set():
            try:
                await asyncio.wait_for(
                    session.stop.wait(),
                    timeout=self.config.heartbeat_interval_seconds,
                )
                return
            except TimeoutError:
                pass
            try:
                session.lease = await asyncio.to_thread(
                    self.authority.renew_reconciler_lease,
                    session.lease,
                    lease_seconds=self.config.lease_seconds,
                )
            except Exception as exc:
                session.error = exc
                session.lost.set()
                return

    async def _observe(
        self, session: _LeaseSession
    ) -> TemporalProviderWorkflowHistoryObservation:
        observation_task = asyncio.create_task(
            self.provider.observe_workflow_history(
                tenant_id=self.config.tenant_id,
                namespace_ref=self.config.namespace_ref,
                workflow_id=self.config.workflow_id,
                provider_run_id=self.config.provider_run_id,
            )
        )
        lost_task = asyncio.create_task(session.lost.wait())
        done, pending = await asyncio.wait(
            {observation_task, lost_task},
            timeout=self.config.observation_timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            observation_task.cancel()
            lost_task.cancel()
            await asyncio.gather(
                observation_task, lost_task, return_exceptions=True
            )
            raise AgentOpsTemporalReconcilerObservationTimeoutError(
                "Temporal history observation timed out"
            )
        if session.lost.is_set():
            observation_task.cancel()
            await asyncio.gather(observation_task, return_exceptions=True)
            raise AgentOpsTemporalReconcilerLeaseLostError(
                "AgentOps reconciler lease heartbeat failed"
            ) from session.error
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        observation = await observation_task
        if observation.provider_run_id != self.config.provider_run_id:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "Temporal observation provider run differs from worker target"
            )
        return observation

    @staticmethod
    def _specialist_status(
        verdicts: set[SpecialistReconciliationVerdict],
        *,
        has_terminal: bool,
    ) -> AgentOpsTemporalSpecialistCycleStatus:
        if not verdicts:
            return (
                AgentOpsTemporalSpecialistCycleStatus.AWAITING_TERMINAL
                if has_terminal is False
                else AgentOpsTemporalSpecialistCycleStatus.NO_ACTIVITY
            )
        if len(verdicts) > 1:
            return AgentOpsTemporalSpecialistCycleStatus.MIXED
        verdict = next(iter(verdicts))
        return {
            SpecialistReconciliationVerdict.UNKNOWN_PENDING: (
                AgentOpsTemporalSpecialistCycleStatus.UNKNOWN_PENDING
            ),
            SpecialistReconciliationVerdict.MATCHED_SUCCEEDED: (
                AgentOpsTemporalSpecialistCycleStatus.MATCHED_SUCCEEDED
            ),
            SpecialistReconciliationVerdict.DEFINITIVE_FAILED: (
                AgentOpsTemporalSpecialistCycleStatus.DEFINITIVE_FAILED
            ),
        }[verdict]

    async def _reconcile_specialists(
        self,
        session: _LeaseSession,
        observation: TemporalProviderWorkflowHistoryObservation,
    ) -> _SpecialistReconciliationSummary:
        specialist_activities = tuple(
            activity
            for activity in observation.activities
            if activity.request.provider_spec is not None
        )
        activity_ids = tuple(sorted(str(item.activity_id) for item in specialist_activities))
        terminal_statuses = {
            TemporalProviderActivityHistoryStatus.TIMED_OUT,
            TemporalProviderActivityHistoryStatus.FAILED,
            TemporalProviderActivityHistoryStatus.CANCELLED,
        }
        terminal_activities = tuple(
            activity
            for activity in specialist_activities
            if activity.status in terminal_statuses
        )
        terminal_ids = tuple(sorted(str(item.activity_id) for item in terminal_activities))
        if not specialist_activities:
            return _SpecialistReconciliationSummary(
                status=AgentOpsTemporalSpecialistCycleStatus.NO_ACTIVITY,
                evidence_by_activity={},
            )
        if not terminal_activities:
            if all(
                activity.status is TemporalProviderActivityHistoryStatus.SUCCEEDED
                for activity in specialist_activities
            ):
                return _SpecialistReconciliationSummary(
                    status=AgentOpsTemporalSpecialistCycleStatus.ALREADY_SETTLED,
                    activity_ids=activity_ids,
                    terminal_activity_ids=terminal_ids,
                    evidence_by_activity={},
                )
            return _SpecialistReconciliationSummary(
                status=AgentOpsTemporalSpecialistCycleStatus.AWAITING_TERMINAL,
                activity_ids=activity_ids,
                terminal_activity_ids=terminal_ids,
                evidence_by_activity={},
            )
        if self.artifact_store is None or self.operation_authority is None:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "provider-bound Temporal activity requires specialist artifact and "
                "operation authorities"
            )

        evidence_by_activity: dict[Any, Any] = {}
        reconciliations: list[SpecialistActivityReconciliation] = []
        unknown_pending: list[str] = []
        matched_succeeded: list[str] = []
        definitive_failed: list[str] = []
        reconciliation_hashes: list[str] = []
        verdicts: set[SpecialistReconciliationVerdict] = set()
        for activity in terminal_activities:
            if session.lost.is_set():
                raise AgentOpsTemporalReconcilerLeaseLostError(
                    "AgentOps reconciler lease was lost during specialist reconciliation"
                ) from session.error
            specialist, _specialist_join, settled = await asyncio.to_thread(
                reconcile_specialist_activity_history,
                activity,
                artifact_store=self.artifact_store,
                operation_authority=self.operation_authority,
                cancellation_adapter=self.cancellation_adapters.get(
                    activity.request.provider_spec.provider_ref
                    if activity.request.provider_spec is not None
                    else ""
                ),
            )
            reconciliations.append(specialist)
            reconciliation_hashes.append(specialist.reconciliation_sha256)
            verdicts.add(specialist.specialist_verdict)
            activity_id = str(activity.activity_id)
            if specialist.specialist_verdict is SpecialistReconciliationVerdict.UNKNOWN_PENDING:
                # Unknown is deliberately not converted to failure or success evidence.
                unknown_pending.append(activity_id)
                continue
            if specialist.specialist_verdict is SpecialistReconciliationVerdict.MATCHED_SUCCEEDED:
                matched_succeeded.append(activity_id)
            else:
                definitive_failed.append(activity_id)
            evidence_by_activity[activity.activity_id] = (
                TemporalActivityAdapter.evidence_from_result(activity.request, settled)
            )
        return _SpecialistReconciliationSummary(
            status=self._specialist_status(verdicts, has_terminal=True),
            activity_ids=activity_ids,
            terminal_activity_ids=terminal_ids,
            unknown_pending_ids=tuple(sorted(unknown_pending)),
            matched_succeeded_ids=tuple(sorted(matched_succeeded)),
            definitive_failed_ids=tuple(sorted(definitive_failed)),
            reconciliation_sha256=tuple(sorted(reconciliation_hashes)),
            evidence_by_activity=evidence_by_activity,
            reconciliations=tuple(reconciliations),
        )

    async def _reconcile_under_lease(
        self, session: _LeaseSession
    ) -> AgentOpsTemporalReconcilerCycle:
        checkpoint = await asyncio.to_thread(
            self.authority.current_checkpoint,
            tenant_id=self.config.tenant_id,
            workflow_id=self.config.workflow_id,
        )
        if checkpoint is None:
            return AgentOpsTemporalReconcilerCycle(
                tenant_id=self.config.tenant_id,
                workflow_id=self.config.workflow_id,
                provider_run_id=self.config.provider_run_id,
                lease_epoch=session.lease.lease_epoch,
                status=AgentOpsTemporalReconcilerCycleStatus.NO_CHECKPOINT,
            )
        identity = checkpoint.workflow_input.identity
        if identity.namespace.namespace_ref != self.config.namespace_ref:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "checkpoint namespace differs from worker target"
            )
        observation = await self._observe(session)
        if session.lost.is_set():
            raise AgentOpsTemporalReconcilerLeaseLostError(
                "AgentOps reconciler lease was lost before reconciliation"
            ) from session.error
        specialist = await self._reconcile_specialists(session, observation)
        reconciliation = reconcile_temporal_checkpoint(
            checkpoint,
            observation,
            specialist_evidence=specialist.evidence_by_activity,
        )
        recovered = await asyncio.to_thread(
            self.authority.resolve_reconciliation_write,
            observation,
            reconciliation,
        )
        if recovered is not None:
            return self._cycle(
                session,
                checkpoint,
                observation,
                reconciliation,
                status=AgentOpsTemporalReconcilerCycleStatus.RECOVERED,
                created=False,
                specialist=specialist,
            )
        try:
            write = await asyncio.to_thread(
                self.authority.record_reconciliation,
                observation,
                reconciliation,
                recorded_by=self.config.lease_owner,
                lease=session.lease,
            )
        except AgentOpsTemporalCheckpointAuthorityConfigurationError as exc:
            try:
                recovered = await asyncio.to_thread(
                    self.authority.resolve_reconciliation_write,
                    observation,
                    reconciliation,
                )
            except AgentOpsTemporalCheckpointAuthorityError as recovery_exc:
                raise exc from recovery_exc
            if recovered is None:
                raise
            return self._cycle(
                session,
                checkpoint,
                observation,
                reconciliation,
                status=AgentOpsTemporalReconcilerCycleStatus.RECOVERED,
                created=False,
                specialist=specialist,
            )
        created = bool(write.created)
        return self._cycle(
            session,
            checkpoint,
            observation,
            reconciliation,
            status=(
                AgentOpsTemporalReconcilerCycleStatus.RECORDED
                if created
                else AgentOpsTemporalReconcilerCycleStatus.RECOVERED
            ),
            created=created,
            specialist=specialist,
        )

    def _cycle(
        self,
        session: _LeaseSession,
        checkpoint: TemporalTaskGraphWorkflowCheckpoint,
        observation: TemporalProviderWorkflowHistoryObservation,
        reconciliation: TemporalCheckpointReconciliation,
        *,
        status: AgentOpsTemporalReconcilerCycleStatus,
        created: bool,
        specialist: _SpecialistReconciliationSummary | None = None,
    ) -> AgentOpsTemporalReconcilerCycle:
        specialist = specialist or _SpecialistReconciliationSummary(
            status=AgentOpsTemporalSpecialistCycleStatus.NO_ACTIVITY,
            evidence_by_activity={},
        )
        return AgentOpsTemporalReconcilerCycle(
            tenant_id=self.config.tenant_id,
            workflow_id=self.config.workflow_id,
            provider_run_id=self.config.provider_run_id,
            lease_epoch=session.lease.lease_epoch,
            status=status,
            checkpoint_sha256=checkpoint.checkpoint_sha256,
            history_sha256=observation.history_sha256,
            reconciliation_sha256=reconciliation.reconciliation_sha256,
            verdict=reconciliation.verdict,
            created=created,
            specialist_status=specialist.status,
            specialist_activity_ids=specialist.activity_ids,
            specialist_terminal_activity_ids=specialist.terminal_activity_ids,
            specialist_unknown_pending_ids=specialist.unknown_pending_ids,
            specialist_matched_succeeded_ids=specialist.matched_succeeded_ids,
            specialist_definitive_failed_ids=specialist.definitive_failed_ids,
            specialist_reconciliation_sha256=specialist.reconciliation_sha256,
            checkpoint_missing_evidence_ids=tuple(
                str(item) for item in reconciliation.checkpoint_missing_evidence_ids
            ),
        )

    async def run_once(self) -> AgentOpsTemporalReconcilerCycle:
        lease = await asyncio.to_thread(
            self.authority.acquire_reconciler_lease,
            tenant_id=self.config.tenant_id,
            workflow_id=self.config.workflow_id,
            lease_owner=self.config.lease_owner,
            lease_seconds=self.config.lease_seconds,
        )
        session = _LeaseSession(
            lease=lease,
            stop=asyncio.Event(),
            lost=asyncio.Event(),
        )
        heartbeat = asyncio.create_task(self._renew_loop(session))
        operation_error: BaseException | None = None
        try:
            return await self._reconcile_under_lease(session)
        except BaseException as exc:
            operation_error = exc
            raise
        finally:
            session.stop.set()
            await heartbeat
            if session.error is None:
                try:
                    await asyncio.to_thread(
                        self.authority.release_reconciler_lease,
                        session.lease,
                    )
                except Exception:
                    if operation_error is None:
                        raise
                    LOGGER.warning(
                        "AgentOps reconciler lease release failed after cycle error",
                        exc_info=True,
                    )

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                cycle = await self.run_once()
                LOGGER.info("AgentOps Temporal reconciliation cycle: %s", cycle)
            except AgentOpsTemporalCheckpointAuthorityConflictError:
                LOGGER.info(
                    "AgentOps Temporal reconciliation lease is held by another worker"
                )
            except AgentOpsTemporalReconcilerWorkerConfigurationError:
                raise
            except (
                AgentOpsTemporalCheckpointAuthorityError,
                AgentOpsTemporalReconcilerWorkerError,
                TemporalAdapterError,
            ):
                LOGGER.warning(
                    "AgentOps Temporal reconciliation cycle failed",
                    exc_info=True,
                )
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self.config.poll_interval_seconds
                )
            except TimeoutError:
                pass


@dataclass(frozen=True)
class AgentOpsTemporalReconcilerDiscoveryConfig:
    """Configuration for discovering registered start targets."""

    tenant_id: str
    namespace_ref: str
    worker_id: str
    lease_seconds: int = 60
    heartbeat_interval_seconds: float = 15.0
    observation_timeout_seconds: float = 30.0
    claim_limit: int = 10
    poll_interval_seconds: float = 5.0
    status_file: Path = DEFAULT_DISCOVERY_STATUS_FILE
    health_max_age_seconds: float = 180.0
    metrics_port: int = 0

    def validate(self) -> None:
        if _TENANT_RE.fullmatch(self.tenant_id) is None:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery tenant_id is invalid"
            )
        if _NAMESPACE_RE.fullmatch(self.namespace_ref) is None:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery namespace_ref is invalid"
            )
        if _LEASE_OWNER_RE.fullmatch(self.worker_id) is None:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery worker identity is invalid"
            )
        if not 5 <= self.lease_seconds <= 3_600:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery lease must be 5..3600 seconds"
            )
        if not 0.1 <= self.heartbeat_interval_seconds < self.lease_seconds / 2:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery heartbeat must be shorter than half the lease"
            )
        if not 0.1 <= self.observation_timeout_seconds <= 3_600:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery observation timeout is invalid"
            )
        if not 1 <= self.claim_limit <= 100:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery claim limit must be 1..100"
            )
        if not 0.1 <= self.poll_interval_seconds <= 300:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery poll interval is invalid"
            )
        if not self.status_file.is_absolute():
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery status file must be an absolute path"
            )
        if (
            not math.isfinite(self.health_max_age_seconds)
            or not 1 <= self.health_max_age_seconds <= 7_200
        ):
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery health max age is invalid"
            )
        if self.health_max_age_seconds < self.poll_interval_seconds * 2:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery health max age must cover two poll intervals"
            )
        if not 0 <= self.metrics_port <= 65_535:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery metrics port is invalid"
            )

    @classmethod
    def from_env(
        cls, environ: dict[str, str] | None = None
    ) -> AgentOpsTemporalReconcilerDiscoveryConfig:
        values = os.environ if environ is None else environ

        def required(name: str) -> str:
            value = values.get(name, "").strip()
            if not value:
                raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                    f"{name} is required"
                )
            return value

        try:
            config = cls(
                tenant_id=required("GDA_AGENTOPS_RECONCILER_TENANT_ID"),
                namespace_ref=required("GDA_AGENTOPS_RECONCILER_NAMESPACE"),
                worker_id=values.get(
                    "GDA_AGENTOPS_RECONCILER_WORKER_ID",
                    (
                        "workload:agentops-temporal-reconciler:"
                        f"{socket.gethostname()}:{os.getpid()}"
                    ),
                ).strip(),
                lease_seconds=int(
                    values.get("GDA_AGENTOPS_RECONCILER_LEASE_SECONDS", "60")
                ),
                heartbeat_interval_seconds=float(
                    values.get("GDA_AGENTOPS_RECONCILER_HEARTBEAT_SECONDS", "15")
                ),
                observation_timeout_seconds=float(
                    values.get(
                        "GDA_AGENTOPS_RECONCILER_OBSERVATION_TIMEOUT_SECONDS", "30"
                    )
                ),
                claim_limit=int(values.get("GDA_AGENTOPS_RECONCILER_CLAIM_LIMIT", "10")),
                poll_interval_seconds=float(
                    values.get("GDA_AGENTOPS_RECONCILER_POLL_SECONDS", "5")
                ),
                status_file=Path(
                    values.get(
                        "GDA_AGENTOPS_RECONCILER_STATUS_FILE",
                        DEFAULT_DISCOVERY_STATUS_FILE.as_posix(),
                    )
                ),
                health_max_age_seconds=float(
                    values.get(
                        "GDA_AGENTOPS_RECONCILER_HEALTH_MAX_AGE_SECONDS", "180"
                    )
                ),
                metrics_port=int(
                    values.get("GDA_AGENTOPS_RECONCILER_METRICS_PORT", "0")
                ),
            )
        except ValueError as exc:
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery numeric configuration is invalid"
            ) from exc
        config.validate()
        return config


class AgentOpsTemporalReconcilerDiscoveryStatus(FrozenContract):
    """Process-local lifecycle and dependency evidence for discovery probes."""

    schema_id = "gda.agentops_temporal_discovery_status.v1"
    state: Literal["starting", "ready", "degraded", "stopped"]
    tenant_id: TenantId
    worker_id: str = Field(pattern=r"^(workload|agent):[^\s]{1,128}$")
    started_at: datetime
    updated_at: datetime
    last_success_at: datetime | None = None
    frontend_reachable: bool = False
    cycles: int = Field(default=0, ge=0)
    claimed: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    claim_lost: int = Field(default=0, ge=0)
    observation_timeouts: int = Field(default=0, ge=0)
    consecutive_dependency_failures: int = Field(default=0, ge=0)
    last_error_code: str | None = None

    @field_validator("started_at", "updated_at", "last_success_at")
    @classmethod
    def _aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("AgentOps discovery status timestamps must include a timezone")
        return value.astimezone(UTC) if value is not None else None


class AgentOpsTemporalReconcilerDiscoveryStatusStore:
    """Atomic process-local status file used by Kubernetes exec probes."""

    def __init__(self, path: Path):
        self.path = path

    def write(self, status: AgentOpsTemporalReconcilerDiscoveryStatus) -> None:
        if not self.path.is_absolute():
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "AgentOps discovery status file must be an absolute path"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / f".{self.path.name}.{os.getpid()}.tmp"
        rendered = json.dumps(
            status.model_dump(mode="json"),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        try:
            temporary.write_text(rendered + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self) -> AgentOpsTemporalReconcilerDiscoveryStatus:
        return AgentOpsTemporalReconcilerDiscoveryStatus.model_validate(
            json.loads(self.path.read_text(encoding="utf-8"))
        )


def _valid_discovery_probe_window(max_age_seconds: float, now: datetime) -> bool:
    return (
        now.tzinfo is not None
        and now.utcoffset() is not None
        and math.isfinite(max_age_seconds)
        and max_age_seconds > 0
    )


def evaluate_discovery_health(
    status_store: AgentOpsTemporalReconcilerDiscoveryStatusStore,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    current = now or datetime.now(UTC)
    if not _valid_discovery_probe_window(max_age_seconds, current):
        return {"status": "unhealthy", "reason": "invalid_health_window"}, False
    try:
        status = status_store.read()
    except (OSError, ValueError, json.JSONDecodeError, ValidationError):
        return {"status": "unhealthy", "reason": "status_unavailable"}, False
    if status.state != "ready" or status.last_success_at is None:
        return {
            "status": "unhealthy",
            "reason": f"worker_{status.state}",
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    if not status.frontend_reachable:
        return {
            "status": "unhealthy",
            "reason": "temporal_frontend_unreachable",
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    age_seconds = (current - status.last_success_at).total_seconds()
    if age_seconds < -5:
        return {"status": "unhealthy", "reason": "clock_skew"}, False
    if age_seconds > max_age_seconds:
        return {
            "status": "unhealthy",
            "reason": "status_stale",
            "age_seconds": round(age_seconds, 3),
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    return {
        "status": "healthy",
        "age_seconds": round(max(0.0, age_seconds), 3),
        "tenant_id": status.tenant_id,
        "worker_id": status.worker_id,
        "cycles": status.cycles,
        "claimed": status.claimed,
        "completed": status.completed,
        "pending": status.pending,
        "failed": status.failed,
    }, True


def evaluate_discovery_liveness(
    status_store: AgentOpsTemporalReconcilerDiscoveryStatusStore,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    current = now or datetime.now(UTC)
    if not _valid_discovery_probe_window(max_age_seconds, current):
        return {"status": "unhealthy", "reason": "invalid_liveness_window"}, False
    try:
        status = status_store.read()
    except (OSError, ValueError, json.JSONDecodeError, ValidationError):
        return {"status": "unhealthy", "reason": "status_unavailable"}, False
    if status.state == "stopped":
        return {
            "status": "unhealthy",
            "reason": "worker_stopped",
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    age_seconds = (current - status.updated_at).total_seconds()
    if age_seconds < -5:
        return {"status": "unhealthy", "reason": "clock_skew"}, False
    if age_seconds > max_age_seconds:
        return {
            "status": "unhealthy",
            "reason": "status_stale",
            "age_seconds": round(age_seconds, 3),
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    return {
        "status": "healthy",
        "worker_state": status.state,
        "age_seconds": round(max(0.0, age_seconds), 3),
        "tenant_id": status.tenant_id,
        "worker_id": status.worker_id,
    }, True


@dataclass(frozen=True)
class AgentOpsTemporalReconcilerDiscoveryCycle:
    claimed_count: int
    completed_count: int
    pending_count: int
    failed_count: int


class AgentOpsTemporalReconcilerDiscoveryWorker:
    """Claim persisted start receipts and hand them to the fenced reconciler."""

    def __init__(
        self,
        config: AgentOpsTemporalReconcilerDiscoveryConfig,
        *,
        provider: TemporalHistoryObserver,
        target_authority: TemporalStartTargetAuthority | None = None,
        checkpoint_authority: TemporalCheckpointAuthority | None = None,
        status_store: AgentOpsTemporalReconcilerDiscoveryStatusStore | None = None,
        artifact_store: SpecialistArtifactStore | None = None,
        operation_authority: SpecialistOperationAuthority | None = None,
        cancellation_adapters: Mapping[str, SpecialistProviderCancellationAdapter]
        | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.provider = provider
        self.target_authority = target_authority or PostgresAgentOpsTemporalStartTargetAuthority()
        self.checkpoint_authority = checkpoint_authority
        if (artifact_store is None) != (operation_authority is None):
            raise AgentOpsTemporalReconcilerWorkerConfigurationError(
                "specialist artifact_store and operation_authority must be supplied together"
            )
        self.artifact_store = artifact_store
        self.operation_authority = operation_authority
        self.cancellation_adapters = dict(cancellation_adapters or {})
        self.status_store = status_store or AgentOpsTemporalReconcilerDiscoveryStatusStore(
            config.status_file
        )
        now = datetime.now(UTC)
        self.status = AgentOpsTemporalReconcilerDiscoveryStatus(
            state="starting",
            tenant_id=config.tenant_id,
            worker_id=config.worker_id,
            started_at=now,
            updated_at=now,
        )
        self.status_store.write(self.status)

    def _update_status(self, **updates: Any) -> None:
        self.status = self.status.model_copy(
            update={"updated_at": datetime.now(UTC), **updates}
        )
        self.status_store.write(self.status)

    def _record_failure(self, exc: Exception) -> None:
        code = re.sub(r"[^a-z0-9]+", "_", type(exc).__name__.lower()).strip("_")
        try:
            self._update_status(
                state="degraded",
                consecutive_dependency_failures=(
                    self.status.consecutive_dependency_failures + 1
                ),
                frontend_reachable=False,
                last_error_code=code or "discovery_cycle_error",
            )
        except Exception:
            LOGGER.exception("Could not persist AgentOps discovery degraded status")

    async def _check_frontend(self) -> None:
        checker = getattr(self.provider, "check_health", None)
        if not callable(checker):
            # Test doubles and non-Temporal observers may not expose health RPC;
            # the production TemporalioProviderClient does.
            return
        try:
            reachable = await asyncio.wait_for(
                checker(), timeout=self.config.observation_timeout_seconds
            )
        except TimeoutError as exc:
            raise AgentOpsTemporalReconcilerObservationTimeoutError(
                "Temporal frontend health check timed out"
            ) from exc
        if reachable is not True:
            raise TemporalAdapterError("Temporal frontend health check is not serving")

    async def _renew_target_loop(
        self, target: TemporalStartTarget, stop: asyncio.Event, lost: asyncio.Event
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=self.config.heartbeat_interval_seconds
                )
                return
            except TimeoutError:
                pass
            try:
                target = await asyncio.to_thread(
                    self.target_authority.renew_target_claim,
                    target,
                    worker_id=self.config.worker_id,
                    lease_seconds=self.config.lease_seconds,
                )
            except Exception:
                lost.set()
                return

    async def _observe_unknown(
        self, target: TemporalStartTarget, lost: asyncio.Event
    ) -> TemporalProviderWorkflowInputObservation:
        observer = getattr(self.provider, "observe_workflow_input", None)
        if not callable(observer):
            raise TemporalAdapterError(
                "registered unknown Temporal start requires workflow input observation"
            )
        observation_task = asyncio.create_task(
            observer(
                tenant_id=target.tenant_id,
                namespace_ref=target.namespace_ref,
                workflow_id=target.workflow_id,
                provider_run_id=None,
            )
        )
        lost_task = asyncio.create_task(lost.wait())
        done, pending = await asyncio.wait(
            {observation_task, lost_task},
            timeout=self.config.observation_timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            observation_task.cancel()
            lost_task.cancel()
            await asyncio.gather(observation_task, lost_task, return_exceptions=True)
            raise AgentOpsTemporalReconcilerObservationTimeoutError(
                "Temporal workflow input observation timed out"
            )
        if lost.is_set():
            observation_task.cancel()
            await asyncio.gather(observation_task, return_exceptions=True)
            raise AgentOpsTemporalReconcilerLeaseLostError(
                "AgentOps start target claim heartbeat failed"
            )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        observation = await observation_task
        if not isinstance(observation, TemporalProviderWorkflowInputObservation):
            raise TemporalAdapterError("Temporal workflow input observer returned invalid evidence")
        return observation

    async def _process_target(self, target: TemporalStartTarget) -> str:
        stop = asyncio.Event()
        lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._renew_target_loop(target, stop, lost))
        try:
            if target.provider_run_id is None:
                observation = await self._observe_unknown(target, lost)
                target = await asyncio.to_thread(
                    self.target_authority.attach_provider_run,
                    target,
                    observation,
                    worker_id=self.config.worker_id,
                )
            if lost.is_set():
                raise AgentOpsTemporalReconcilerLeaseLostError(
                    "AgentOps start target claim was lost before reconciliation"
                )
            explicit_config = AgentOpsTemporalReconcilerWorkerConfig(
                tenant_id=target.tenant_id,
                namespace_ref=target.namespace_ref,
                frontend_target="discovery-managed.invalid:7233",
                workflow_id=target.workflow_id,
                provider_run_id=target.provider_run_id or "",
                lease_owner=self.config.worker_id,
                lease_seconds=self.config.lease_seconds,
                heartbeat_interval_seconds=self.config.heartbeat_interval_seconds,
                observation_timeout_seconds=self.config.observation_timeout_seconds,
                poll_interval_seconds=self.config.poll_interval_seconds,
            )
            reconciler = AgentOpsTemporalReconcilerWorker(
                explicit_config,
                provider=self.provider,
                authority=self.checkpoint_authority,
                artifact_store=self.artifact_store,
                operation_authority=self.operation_authority,
                cancellation_adapters=self.cancellation_adapters,
            )
            cycle = await reconciler.run_once()
            if lost.is_set():
                raise AgentOpsTemporalReconcilerLeaseLostError(
                    "AgentOps start target claim was lost before settlement"
                )
            if cycle.status is AgentOpsTemporalReconcilerCycleStatus.NO_CHECKPOINT:
                await asyncio.to_thread(
                    self.target_authority.release_target_claim,
                    target,
                    worker_id=self.config.worker_id,
                    error="Temporal target has no GDA checkpoint yet",
                    retry_after_seconds=self.config.poll_interval_seconds,
                )
                return "pending"
            await asyncio.to_thread(
                self.target_authority.complete_target,
                target,
                worker_id=self.config.worker_id,
            )
            return "completed"
        except AgentOpsTemporalReconcilerWorkerConfigurationError as exc:
            await asyncio.to_thread(
                self.target_authority.fail_target,
                target,
                worker_id=self.config.worker_id,
                error=str(exc),
            )
            return "failed"
        except AgentOpsTemporalReconcilerObservationTimeoutError as exc:
            _record_discovery_operation("observation_timeout")
            self._update_status(
                observation_timeouts=self.status.observation_timeouts + 1
            )
            if not lost.is_set():
                await asyncio.to_thread(
                    self.target_authority.release_target_claim,
                    target,
                    worker_id=self.config.worker_id,
                    error=str(exc),
                    retry_after_seconds=self.config.poll_interval_seconds,
                )
            return "pending"
        except AgentOpsTemporalReconcilerLeaseLostError as exc:
            _record_discovery_operation("claim_lost")
            self._update_status(claim_lost=self.status.claim_lost + 1)
            if not lost.is_set():
                await asyncio.to_thread(
                    self.target_authority.release_target_claim,
                    target,
                    worker_id=self.config.worker_id,
                    error=str(exc),
                    retry_after_seconds=self.config.poll_interval_seconds,
                )
            return "pending"
        except TemporalAdapterError as exc:
            if not lost.is_set():
                await asyncio.to_thread(
                    self.target_authority.release_target_claim,
                    target,
                    worker_id=self.config.worker_id,
                    error=str(exc),
                    retry_after_seconds=self.config.poll_interval_seconds,
                )
            return "pending"
        except Exception as exc:
            if not lost.is_set():
                await asyncio.to_thread(
                    self.target_authority.release_target_claim,
                    target,
                    worker_id=self.config.worker_id,
                    error=f"transient discovery failure: {exc}",
                    retry_after_seconds=self.config.poll_interval_seconds,
                )
            return "pending"
        finally:
            stop.set()
            await heartbeat

    async def run_once(self) -> AgentOpsTemporalReconcilerDiscoveryCycle:
        started = time.monotonic()
        try:
            self._update_status(
                state="starting" if self.status.last_success_at is None else self.status.state
            )
            await self._check_frontend()
            targets = await asyncio.to_thread(
                self.target_authority.claim_due_targets,
                tenant_id=self.config.tenant_id,
                namespace_ref=self.config.namespace_ref,
                worker_id=self.config.worker_id,
                limit=self.config.claim_limit,
                lease_seconds=self.config.lease_seconds,
            )
            _record_discovery_operation("claimed", len(targets))
            completed = failed = pending = 0
            for target in targets:
                self._update_status()
                outcome = await self._process_target(target)
                self._update_status()
                if outcome == "completed":
                    completed += 1
                    _record_discovery_operation("completed")
                elif outcome == "failed":
                    failed += 1
                    _record_discovery_operation("failed")
                else:
                    pending += 1
                    _record_discovery_operation("pending")
            cycle = AgentOpsTemporalReconcilerDiscoveryCycle(
                claimed_count=len(targets),
                completed_count=completed,
                pending_count=pending,
                failed_count=failed,
            )
            self._update_status(
                state="ready",
                last_success_at=datetime.now(UTC),
                frontend_reachable=True,
                cycles=self.status.cycles + 1,
                claimed=self.status.claimed + cycle.claimed_count,
                completed=self.status.completed + cycle.completed_count,
                pending=self.status.pending + cycle.pending_count,
                failed=self.status.failed + cycle.failed_count,
                consecutive_dependency_failures=0,
                last_error_code=None,
            )
            _record_discovery_success()
            return cycle
        except Exception as exc:
            _record_discovery_operation("cycle_error")
            self._record_failure(exc)
            raise
        finally:
            _observe_discovery_cycle(time.monotonic() - started)

    async def run(self, stop_event: asyncio.Event) -> None:
        try:
            while not stop_event.is_set():
                try:
                    LOGGER.info(
                        "AgentOps Temporal discovery cycle: %s", await self.run_once()
                    )
                except AgentOpsTemporalReconcilerWorkerConfigurationError:
                    raise
                except Exception:
                    LOGGER.warning(
                        "AgentOps Temporal start-target discovery cycle failed",
                        exc_info=True,
                    )
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self.config.poll_interval_seconds
                    )
                except TimeoutError:
                    pass
        finally:
            try:
                self._update_status(state="stopped")
            except Exception:
                LOGGER.exception("Could not persist AgentOps discovery stopped status")


async def _run_from_config(
    config: AgentOpsTemporalReconcilerWorkerConfig, *, once: bool
) -> int:
    try:
        from temporalio.client import Client

        from .agentops_temporalio_provider import TemporalioProviderClient
    except ImportError as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "AgentOps reconciler requires the optional Temporal SDK"
        ) from exc
    dependencies = _build_specialist_runtime_dependencies(config.tenant_id)
    client = await Client.connect(
        config.frontend_target,
        namespace=config.namespace_ref,
        identity=config.lease_owner,
    )
    worker = AgentOpsTemporalReconcilerWorker(
        config,
        provider=TemporalioProviderClient(
            client, namespace_ref=config.namespace_ref
        ),
        authority=dependencies.checkpoint_authority,
        artifact_store=dependencies.artifact_store,
        operation_authority=dependencies.operation_authority,
    )
    if once:
        LOGGER.info("AgentOps Temporal reconciliation cycle: %s", await worker.run_once())
        return 0
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop_event.set)
    await worker.run(stop_event)
    return 0


async def _run_discovery_from_config(
    config: AgentOpsTemporalReconcilerDiscoveryConfig, *, once: bool
) -> int:
    try:
        from temporalio.client import Client

        from .agentops_temporalio_provider import TemporalioProviderClient
    except ImportError as exc:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "AgentOps discovery requires the optional Temporal SDK"
        ) from exc
    frontend_target = os.environ.get(
        "GDA_AGENTOPS_RECONCILER_FRONTEND", "temporal:7233"
    ).strip()
    if not frontend_target or ":" not in frontend_target:
        raise AgentOpsTemporalReconcilerWorkerConfigurationError(
            "GDA_AGENTOPS_RECONCILER_FRONTEND must be host:port"
        )
    dependencies = _build_specialist_runtime_dependencies(config.tenant_id)
    client = await Client.connect(
        frontend_target,
        namespace=config.namespace_ref,
        identity=config.worker_id,
    )
    worker = AgentOpsTemporalReconcilerDiscoveryWorker(
        config,
        provider=TemporalioProviderClient(
            client, namespace_ref=config.namespace_ref
        ),
        target_authority=dependencies.start_target_authority,
        checkpoint_authority=dependencies.checkpoint_authority,
        artifact_store=dependencies.artifact_store,
        operation_authority=dependencies.operation_authority,
    )
    if config.metrics_port:
        start_http_server(config.metrics_port)
        LOGGER.info(
            "AgentOps Temporal discovery metrics listening on port %s",
            config.metrics_port,
        )
    if once:
        LOGGER.info("AgentOps Temporal discovery cycle: %s", await worker.run_once())
        return 0
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop_event.set)
    await worker.run(stop_event)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the fenced AgentOps Temporal history reconciler"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="discover and reconcile persisted Temporal start targets",
    )
    parser.add_argument(
        "probe",
        nargs="?",
        choices=("health", "liveness", "image-contract"),
        help="run a local health probe or inspect the running image contract",
    )
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--max-age-seconds", type=float)
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    if args.probe == "image-contract":
        report, passed = evaluate_runtime_image_contract()
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if passed else 1
    if args.probe:
        status_file = args.status_file or Path(
            os.environ.get(
                "GDA_AGENTOPS_RECONCILER_STATUS_FILE",
                DEFAULT_DISCOVERY_STATUS_FILE.as_posix(),
            )
        )
        try:
            max_age = (
                args.max_age_seconds
                if args.max_age_seconds is not None
                else float(
                    os.environ.get(
                        "GDA_AGENTOPS_RECONCILER_HEALTH_MAX_AGE_SECONDS", "180"
                    )
                )
            )
        except ValueError:
            print(json.dumps({"status": "unhealthy", "reason": "invalid_max_age"}))
            return 1
        evaluator = (
            evaluate_discovery_health
            if args.probe == "health"
            else evaluate_discovery_liveness
        )
        report, healthy = evaluator(
            AgentOpsTemporalReconcilerDiscoveryStatusStore(status_file),
            max_age_seconds=max_age,
        )
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if healthy else 1
    if args.discover:
        config = AgentOpsTemporalReconcilerDiscoveryConfig.from_env()
        return asyncio.run(_run_discovery_from_config(config, once=args.once))
    config = AgentOpsTemporalReconcilerWorkerConfig.from_env()
    return asyncio.run(_run_from_config(config, once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AgentOpsTemporalReconcilerCycle",
    "AgentOpsTemporalReconcilerCycleStatus",
    "AgentOpsTemporalSpecialistCycleStatus",
    "AgentOpsTemporalReconcilerLeaseLostError",
    "AgentOpsTemporalReconcilerObservationTimeoutError",
    "AgentOpsTemporalReconcilerWorker",
    "AgentOpsTemporalReconcilerWorkerConfig",
    "AgentOpsTemporalReconcilerWorkerConfigurationError",
    "AgentOpsTemporalReconcilerWorkerError",
    "AgentOpsTemporalReconcilerDiscoveryConfig",
    "AgentOpsTemporalReconcilerDiscoveryCycle",
    "AgentOpsTemporalReconcilerDiscoveryStatus",
    "AgentOpsTemporalReconcilerDiscoveryStatusStore",
    "AgentOpsTemporalReconcilerDiscoveryWorker",
    "evaluate_discovery_health",
    "evaluate_discovery_liveness",
    "evaluate_runtime_image_contract",
    "TemporalStartTargetAuthority",
    "TemporalHistoryObserver",
]
