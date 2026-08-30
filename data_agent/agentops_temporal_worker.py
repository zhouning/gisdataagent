"""Typed worker registration boundary for the optional Temporal AgentOps runtime.

The module contains no Temporal SDK import at module load time. It freezes the worker
identity/task-queue/deployment binding and provides a lazy SDK factory that can be exercised
with a fake Worker class until a pinned temporalio dependency is available.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from pydantic import Field, model_validator

from .agentops_temporal_contracts import temporal_contract_fingerprint
from .agentops_temporalio_provider import TemporalAdapterError
from .platform_contracts import FrozenContract, NonEmptyText, Sha256, TenantId

TEMPORAL_WORKER_REGISTRATION_SCHEMA = "gda.temporal_worker_registration.v1"
TEMPORAL_WORKER_CONFIG_SCHEMA = "gda.temporal_worker_config.v1"


class TemporalWorkerRegistration(FrozenContract):
    """Immutable binding between one AgentOps deployment and a Temporal worker."""

    schema_id: ClassVar[str] = TEMPORAL_WORKER_REGISTRATION_SCHEMA
    tenant_id: TenantId
    namespace_ref: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,62}$")
    task_queue_ref: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,62}$")
    worker_identity_ref: NonEmptyText
    workflow_type: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    activity_types: tuple[str, ...] = Field(min_length=1)
    agent_spec_sha256: Sha256
    deployment_revision_sha256: Sha256
    max_concurrent_activities: int = Field(default=10, ge=1, le=1_000)
    max_concurrent_workflow_tasks: int = Field(default=10, ge=1, le=1_000)
    registration_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_registration(self) -> TemporalWorkerRegistration:
        if any(
            not isinstance(activity_type, str)
            or not activity_type
            or not activity_type[0].islower()
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
                for character in activity_type
            )
            for activity_type in self.activity_types
        ):
            raise ValueError("activity_types must contain lower-case provider names")
        if self.activity_types != tuple(sorted(set(self.activity_types))):
            raise ValueError("activity_types must be sorted and unique")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "registration_sha256"
        )
        if self.registration_sha256 != expected:
            raise ValueError("registration_sha256 does not match worker registration")
        return self


class TemporalWorkerRuntimeConfig(FrozenContract):
    """Environment-bound configuration required before constructing a worker."""

    schema_id: ClassVar[str] = TEMPORAL_WORKER_CONFIG_SCHEMA
    tenant_id: TenantId
    namespace_ref: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,62}$")
    frontend_target: NonEmptyText
    task_queue_ref: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,62}$")
    worker_identity_ref: NonEmptyText
    workflow_type: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    activity_types: tuple[str, ...] = Field(min_length=1)
    agent_spec_sha256: Sha256
    deployment_revision_sha256: Sha256
    max_concurrent_activities: int = Field(default=10, ge=1, le=1_000)
    max_concurrent_workflow_tasks: int = Field(default=10, ge=1, le=1_000)

    @model_validator(mode="after")
    def _valid_frontend_target(self) -> TemporalWorkerRuntimeConfig:
        target = self.frontend_target.rsplit(":", 1)
        if len(target) != 2 or not target[0].strip():
            raise ValueError("frontend_target must be host:port")
        try:
            port = int(target[1])
        except ValueError as exc:
            raise ValueError("frontend_target port must be numeric") from exc
        if not 1 <= port <= 65_535:
            raise ValueError("frontend_target port must be between 1 and 65535")
        if self.activity_types != tuple(sorted(set(self.activity_types))):
            raise ValueError("activity_types must be sorted and unique")
        return self

    @classmethod
    def from_env(
        cls, environ: dict[str, str] | None = None
    ) -> TemporalWorkerRuntimeConfig:
        """Load required worker settings without reading secrets or inventing hashes."""

        values = environ if environ is not None else os.environ

        def required(name: str) -> str:
            value = values.get(name, "").strip()
            if not value:
                raise TemporalAdapterError(f"missing required Temporal worker setting: {name}")
            return value

        activity_types = tuple(
            sorted(
                {
                    item.strip()
                    for item in required("GDA_AGENTOPS_TEMPORAL_ACTIVITY_TYPES").split(",")
                    if item.strip()
                }
            )
        )
        if not activity_types:
            raise TemporalAdapterError(
                "GDA_AGENTOPS_TEMPORAL_ACTIVITY_TYPES must contain at least one activity"
            )
        try:
            config = cls(
                tenant_id=required("GDA_AGENTOPS_TEMPORAL_TENANT_ID"),
                namespace_ref=required("GDA_AGENTOPS_TEMPORAL_NAMESPACE"),
                frontend_target=required("GDA_AGENTOPS_TEMPORAL_FRONTEND"),
                task_queue_ref=required("GDA_AGENTOPS_TEMPORAL_TASK_QUEUE"),
                worker_identity_ref=required("GDA_AGENTOPS_TEMPORAL_WORKER_ID"),
                workflow_type=required("GDA_AGENTOPS_TEMPORAL_WORKFLOW_TYPE"),
                activity_types=activity_types,
                agent_spec_sha256=required("GDA_AGENTOPS_AGENT_SPEC_SHA256"),
                deployment_revision_sha256=required(
                    "GDA_AGENTOPS_DEPLOYMENT_REVISION_SHA256"
                ),
                max_concurrent_activities=int(
                    values.get("GDA_AGENTOPS_TEMPORAL_MAX_CONCURRENT_ACTIVITIES", "10")
                ),
                max_concurrent_workflow_tasks=int(
                    values.get(
                        "GDA_AGENTOPS_TEMPORAL_MAX_CONCURRENT_WORKFLOW_TASKS", "10"
                    )
                ),
            )
            config.registration()
            return config
        except (TypeError, ValueError) as exc:
            if isinstance(exc, TemporalAdapterError):
                raise
            raise TemporalAdapterError(
                "invalid Temporal worker runtime configuration"
            ) from exc

    def registration(self) -> TemporalWorkerRegistration:
        return build_worker_registration(
            tenant_id=self.tenant_id,
            namespace_ref=self.namespace_ref,
            task_queue_ref=self.task_queue_ref,
            worker_identity_ref=self.worker_identity_ref,
            workflow_type=self.workflow_type,
            activity_types=self.activity_types,
            agent_spec_sha256=self.agent_spec_sha256,
            deployment_revision_sha256=self.deployment_revision_sha256,
            max_concurrent_activities=self.max_concurrent_activities,
            max_concurrent_workflow_tasks=self.max_concurrent_workflow_tasks,
        )


class TemporalWorkerLike(Protocol):
    """Minimal worker object returned by a Temporal SDK implementation."""

    async def run(self) -> None: ...

    def shutdown(self) -> None: ...


TemporalWorkerClass = Callable[..., TemporalWorkerLike]


@dataclass(frozen=True)
class TemporalWorkerDefinition:
    """Explicit Temporal provider name bound to one Python handler."""

    name: str
    handler: Callable[..., Any]

    def __post_init__(self) -> None:
        if not self.name or not self.name[0].islower() or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in self.name
        ):
            raise ValueError("Temporal definition name must be a lower-case provider name")
        if not callable(self.handler):
            raise TypeError("Temporal definition handler must be callable")


class TemporalioWorkerFactory:
    """Build a Temporal SDK Worker only after registration checks pass."""

    def __init__(
        self,
        client: Any,
        registration: TemporalWorkerRegistration,
        *,
        workflows: Sequence[TemporalWorkerDefinition],
        activities: Sequence[TemporalWorkerDefinition],
        worker_class: TemporalWorkerClass | None = None,
    ) -> None:
        self._client = client
        self._registration = registration
        self._workflows = tuple(workflows)
        self._activities = tuple(activities)
        self._worker_class = worker_class

    def build(self) -> TemporalWorkerLike:
        self._validate_bindings()
        worker_class = self._worker_class or self._load_worker_class()
        try:
            return worker_class(
                self._client,
                task_queue=self._registration.task_queue_ref,
                workflows=[definition.handler for definition in self._workflows],
                activities=[definition.handler for definition in self._activities],
                max_concurrent_activities=self._registration.max_concurrent_activities,
                max_concurrent_workflow_tasks=self._registration.max_concurrent_workflow_tasks,
            )
        except (TypeError, ValueError) as exc:
            raise TemporalAdapterError(
                "Temporal Worker construction failed for the registered bindings"
            ) from exc

    def _validate_bindings(self) -> None:
        if not self._workflows:
            raise TemporalAdapterError("Temporal worker requires at least one workflow")
        if not self._activities:
            raise TemporalAdapterError("Temporal worker requires at least one activity")
        namespace = getattr(self._client, "namespace", None)
        if namespace is not None and namespace != self._registration.namespace_ref:
            raise TemporalAdapterError(
                "Temporal client namespace differs from worker registration"
            )
        workflow_names = {definition.name for definition in self._workflows}
        if len(workflow_names) != len(self._workflows):
            raise TemporalAdapterError("Temporal workflow definition names must be unique")
        if self._registration.workflow_type not in workflow_names:
            raise TemporalAdapterError(
                "registered workflow_type is not present in worker definitions"
            )
        activity_names = {definition.name for definition in self._activities}
        if len(activity_names) != len(self._activities):
            raise TemporalAdapterError("Temporal activity definition names must be unique")
        missing = set(self._registration.activity_types) - activity_names
        if missing:
            raise TemporalAdapterError(
                f"registered activity types are missing from worker definitions: {sorted(missing)}"
            )

    @staticmethod
    def _load_worker_class() -> TemporalWorkerClass:
        try:
            from temporalio.worker import Worker
        except ImportError as exc:
            raise TemporalAdapterError(
                "Temporal worker requires optional dependency temporalio"
            ) from exc
        return Worker


def build_worker_registration(
    *,
    tenant_id: TenantId,
    namespace_ref: str,
    task_queue_ref: str,
    worker_identity_ref: NonEmptyText,
    workflow_type: str,
    activity_types: tuple[str, ...],
    agent_spec_sha256: Sha256,
    deployment_revision_sha256: Sha256,
    max_concurrent_activities: int = 10,
    max_concurrent_workflow_tasks: int = 10,
) -> TemporalWorkerRegistration:
    """Create a hash-bound registration with canonical activity ordering."""

    values = {
        "tenant_id": tenant_id,
        "namespace_ref": namespace_ref,
        "task_queue_ref": task_queue_ref,
        "worker_identity_ref": worker_identity_ref,
        "workflow_type": workflow_type,
        "activity_types": tuple(sorted(set(activity_types))),
        "agent_spec_sha256": agent_spec_sha256,
        "deployment_revision_sha256": deployment_revision_sha256,
        "max_concurrent_activities": max_concurrent_activities,
        "max_concurrent_workflow_tasks": max_concurrent_workflow_tasks,
    }
    values["registration_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKER_REGISTRATION_SCHEMA, values, "registration_sha256"
    )
    return TemporalWorkerRegistration(**values)


__all__ = [
    "TEMPORAL_WORKER_CONFIG_SCHEMA",
    "TEMPORAL_WORKER_REGISTRATION_SCHEMA",
    "TemporalWorkerClass",
    "TemporalWorkerDefinition",
    "TemporalWorkerLike",
    "TemporalWorkerRegistration",
    "TemporalWorkerRuntimeConfig",
    "TemporalioWorkerFactory",
    "build_worker_registration",
]
