"""Deployment-side provider resolver for durable projection recovery jobs.

The queue stores only sealed repair plans. This module resolves every provider
from server-owned registry and credential configuration; it never accepts an
endpoint, credential, target, or row payload from a recovery job. PostGIS and
pgvector rebuilds additionally require a plan-bound row bundle on local
worker storage because a repair plan intentionally contains hashes, not data.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from .cross_store_projection_consistency import ProjectionEngine, ProjectionRepairPlan
from .cross_store_projection_recovery_controller import (
    StaticProjectionRecoveryControllerBinding,
)
from .cross_store_projection_recovery_worker import (
    ProjectionRecoveryProvider,
    RegisteredExecutorProjectionProvider,
)
from .lakehouse_projection_service import _default_executor as _default_lakehouse_executor
from .lakehouse_projection_service import load_lakehouse_projection_registry
from .object_projection_executor import ObjectProjectionRepairExecutor
from .object_projection_service import load_object_projection_registry
from .platform_contracts import canonical_json_fingerprint
from .platform_runtime.cross_store_recovery_admission import (
    CrossStoreRecoveryAdmission,
)
from .platform_runtime.cross_store_recovery_admission_bundle import (
    ProjectionRecoveryAdmissionBundleError,
    load_projection_recovery_admission_bundle,
)
from .platform_runtime.cross_store_recovery_controller import (
    CrossStoreRecoveryController,
)
from .platform_runtime.cross_store_recovery_controller_authority import (
    PostgresCrossStoreRecoveryControllerLedger,
)
from .postgis_projection_executor import PostGISProjectionRepairExecutor
from .postgis_projection_service import load_postgis_projection_registry
from .rdf_projection_executor import RDFProjectionRepairExecutor
from .rdf_projection_service import load_rdf_projection_registry
from .vector_projection_executor import VectorProjectionRepairExecutor
from .vector_projection_service import load_vector_projection_registry

_ROW_BUNDLE_SCHEMA = "gda.projection-recovery-rows.v1"
_MAX_ROW_BUNDLE_BYTES = 500_000_000
_MAX_CONTROLLER_ADMISSION_BUNDLE_BYTES = 10_000_000


class ProjectionRecoveryRuntimeConfigurationError(RuntimeError):
    """Raised when deployment-owned recovery provider configuration is unsafe."""

    code = "projection_recovery_runtime_configuration_error"


class ProjectionRecoveryControllerAdmissionBundleResolver:
    """Load plan-bound cross-store admission evidence from worker storage."""

    def __init__(self, path: str | Path):
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_file():
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery controller admission bundle is unavailable"
            )
        self._path = candidate

    def __call__(self, job: Any) -> CrossStoreRecoveryAdmission:
        try:
            admission = load_projection_recovery_admission_bundle(
                self._path, max_bytes=_MAX_CONTROLLER_ADMISSION_BUNDLE_BYTES
            ).for_plan(job.plan_sha256)
        except ProjectionRecoveryAdmissionBundleError as exc:
            raise ProjectionRecoveryRuntimeConfigurationError(
                str(exc)
            ) from exc
        if job.tenant_id not in admission.binding.tenant_ids:
            raise ProjectionRecoveryRuntimeConfigurationError(
                "controller admission does not cover the projection tenant"
            )
        desired = getattr(job.plan, "desired_state", None)
        if desired is None or (
            admission.binding.source_resource_version_ref
            != desired.source_resource_version_ref
            or admission.binding.source_content_sha256 != desired.source_content_sha256
        ):
            raise ProjectionRecoveryRuntimeConfigurationError(
                "controller admission source identity differs from the sealed plan"
            )
        return admission


class ProjectionRecoveryControllerBindingResolver:
    """Resolve one durable controller ledger for each projection recovery job."""

    def __init__(self, engine: Engine, admission_bundle_path: str | Path):
        self._engine = engine
        self._admission = ProjectionRecoveryControllerAdmissionBundleResolver(
            admission_bundle_path
        )

    @classmethod
    def from_environment(
        cls, engine: Engine
    ) -> ProjectionRecoveryControllerBindingResolver | None:
        path = os.environ.get("GDA_PROJECTION_RECOVERY_CONTROLLER_ADMISSION_FILE", "")
        if not path.strip():
            return None
        return cls(engine, path)

    def __call__(self, job: Any) -> StaticProjectionRecoveryControllerBinding:
        admission = self._admission(job)
        ledger = PostgresCrossStoreRecoveryControllerLedger(
            admission.binding.tenant_ids,
            self._engine,
        )
        controller = CrossStoreRecoveryController(
            f"projection-recovery:{job.job_id}",
            ledger=ledger,
        )
        return StaticProjectionRecoveryControllerBinding(controller, admission)


@dataclass(frozen=True)
class ProjectionRecoveryProviderBinding:
    """An executor and its immutable deployment-side target registry."""

    executor: Any
    registry: Any


ProjectionRowsResolver = Callable[[ProjectionRepairPlan], tuple[dict[str, Any], ...]]
ProjectionProviderFactory = Callable[[], ProjectionRecoveryProviderBinding]


class SealedProjectionRowsFileResolver:
    """Load a server-owned row bundle bound to one sealed repair plan."""

    def __init__(self, directory: str | Path) -> None:
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery rows directory is unavailable"
            )
        self._directory = root

    def __call__(self, plan: ProjectionRepairPlan) -> tuple[dict[str, Any], ...]:
        candidate = (self._directory / f"{plan.plan_sha256}.json").resolve()
        try:
            candidate.relative_to(self._directory)
        except ValueError as exc:
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery row bundle escapes its configured directory"
            ) from exc
        if not candidate.is_file():
            raise ProjectionRecoveryRuntimeConfigurationError(
                "no server-side row bundle is registered for the sealed repair plan"
            )
        try:
            raw = candidate.read_bytes()
        except OSError as exc:
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery row bundle could not be read"
            ) from exc
        if not raw or len(raw) > _MAX_ROW_BUNDLE_BYTES:
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery row bundle exceeds its byte budget"
            )
        try:
            document = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery row bundle is not valid JSON"
            ) from exc
        if not isinstance(document, dict) or document.get("schema_id") != _ROW_BUNDLE_SCHEMA:
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery row bundle schema is invalid"
            )
        expected = {
            "tenant_id": plan.tenant_id,
            "projection_id": plan.projection_id,
            "target_engine": plan.target_engine.value,
            "target_ref": plan.target_ref,
            "plan_sha256": plan.plan_sha256,
            "plan_idempotency_key": plan.plan_idempotency_key,
        }
        if any(document.get(key) != value for key, value in expected.items()):
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery row bundle identity differs from the sealed plan"
            )
        rows = document.get("rows")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery row bundle rows are invalid"
            )
        if len(rows) != plan.desired_state.expected_row_count:
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery row bundle count differs from the sealed plan"
            )
        if document.get("rows_sha256") != canonical_json_fingerprint(rows):
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery row bundle fingerprint is invalid"
            )
        return tuple(rows)


class ProjectionRecoveryProviderResolver:
    """Resolve only registered provider executors for a sealed repair plan."""

    def __init__(
        self,
        *,
        bindings: Mapping[ProjectionEngine, ProjectionRecoveryProviderBinding] | None = None,
        factories: Mapping[ProjectionEngine, ProjectionProviderFactory] | None = None,
        rows_resolver: ProjectionRowsResolver | None = None,
    ) -> None:
        self._bindings = dict(bindings or {})
        self._factories = dict(factories or {})
        self._rows_resolver = rows_resolver

    @classmethod
    def from_environment(
        cls,
        engine: Engine,
        *,
        rows_resolver: ProjectionRowsResolver | None = None,
    ) -> ProjectionRecoveryProviderResolver:
        if engine is None or engine.dialect.name != "postgresql":
            raise ProjectionRecoveryRuntimeConfigurationError(
                "projection recovery provider resolver requires PostgreSQL"
            )

        def postgis() -> ProjectionRecoveryProviderBinding:
            registry = load_postgis_projection_registry()
            return ProjectionRecoveryProviderBinding(
                executor=PostGISProjectionRepairExecutor(engine, registry),
                registry=registry,
            )

        def vector() -> ProjectionRecoveryProviderBinding:
            registry = load_vector_projection_registry()
            return ProjectionRecoveryProviderBinding(
                executor=VectorProjectionRepairExecutor(engine, registry),
                registry=registry,
            )

        def rdf() -> ProjectionRecoveryProviderBinding:
            registry = load_rdf_projection_registry()
            return ProjectionRecoveryProviderBinding(
                executor=RDFProjectionRepairExecutor(
                    registry,
                    username=os.environ.get("GDA_RDF_PROJECTION_USERNAME") or None,
                    password=os.environ.get("GDA_RDF_PROJECTION_PASSWORD") or None,
                    timeout_seconds=float(
                        os.environ.get("GDA_RDF_PROJECTION_TIMEOUT_SECONDS", "120")
                    ),
                ),
                registry=registry,
            )

        def object_store() -> ProjectionRecoveryProviderBinding:
            registry = load_object_projection_registry()
            return ProjectionRecoveryProviderBinding(
                executor=ObjectProjectionRepairExecutor(
                    registry,
                    access_key_id=os.environ.get("GDA_OBJECT_PROJECTION_ACCESS_KEY_ID")
                    or None,
                    secret_access_key=os.environ.get("GDA_OBJECT_PROJECTION_SECRET_ACCESS_KEY")
                    or None,
                    session_token=os.environ.get("GDA_OBJECT_PROJECTION_SESSION_TOKEN")
                    or None,
                    timeout_seconds=float(
                        os.environ.get("GDA_OBJECT_PROJECTION_TIMEOUT_SECONDS", "120")
                    ),
                ),
                registry=registry,
            )

        def lakehouse() -> ProjectionRecoveryProviderBinding:
            registry = load_lakehouse_projection_registry()
            return ProjectionRecoveryProviderBinding(
                executor=_default_lakehouse_executor(registry),
                registry=registry,
            )

        return cls(
            factories={
                ProjectionEngine.POSTGIS: postgis,
                ProjectionEngine.VECTOR: vector,
                ProjectionEngine.RDF: rdf,
                ProjectionEngine.OBJECT_STORE: object_store,
                ProjectionEngine.LAKEHOUSE: lakehouse,
            },
            rows_resolver=rows_resolver,
        )

    def _binding(self, engine: ProjectionEngine) -> ProjectionRecoveryProviderBinding:
        existing = self._bindings.get(engine)
        if existing is not None:
            return existing
        factory = self._factories.get(engine)
        if factory is None:
            raise ProjectionRecoveryRuntimeConfigurationError(
                f"no deployment provider is configured for {engine.value}"
            )
        try:
            binding = factory()
        except ProjectionRecoveryRuntimeConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface only a safe deployment error
            raise ProjectionRecoveryRuntimeConfigurationError(
                f"{engine.value} recovery provider configuration is unavailable"
            ) from exc
        self._bindings[engine] = binding
        return binding

    def __call__(self, plan: ProjectionRepairPlan) -> ProjectionRecoveryProvider:
        binding = self._binding(plan.target_engine)
        rows: tuple[dict[str, Any], ...] = ()
        if plan.target_engine in {ProjectionEngine.POSTGIS, ProjectionEngine.VECTOR}:
            if plan.action == "rebuild":
                if self._rows_resolver is None:
                    raise ProjectionRecoveryRuntimeConfigurationError(
                        "PostGIS/pgvector recovery rebuild requires a server-side row bundle"
                    )
                rows = self._rows_resolver(plan)
        return RegisteredExecutorProjectionProvider(
            executor=binding.executor,
            registry=binding.registry,
            rows=rows,
        )


__all__ = [
    "ProjectionRecoveryControllerAdmissionBundleResolver",
    "ProjectionRecoveryControllerBindingResolver",
    "ProjectionRecoveryProviderBinding",
    "ProjectionRecoveryProviderResolver",
    "ProjectionRecoveryRuntimeConfigurationError",
    "SealedProjectionRowsFileResolver",
]
