"""Governed admission and provider receipts for metric query executions."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .db_engine import get_engine
from .metric_authority import GATEWAY_DATABASE_ROLE
from .metric_query import (
    MetricQueryPlan,
    MetricQuerySecurityContext,
)
from .platform_contracts import (
    Artifact,
    OrchestrationClass,
    PlatformDefinitionVersion,
    PlatformRun,
    PortabilityClass,
    Resource,
    ResourceVersion,
    Sha256,
    SubjectContext,
    SubjectType,
    TenantId,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
)
from .platform_gateway import (
    DefinitionRegistration,
    GatewayConfigurationError,
    GatewayConflictError,
    GatewayForbiddenError,
    GatewayNotFoundError,
    GatewayUnavailableError,
    GatewayValidationError,
    PlatformGateway,
)

_TENANT_ADAPTER = TypeAdapter(TenantId)
_EXECUTOR_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/contracts/metric-query-executor/v1",
)
_RUN_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/contracts/metric-query-run/v1",
)
_EXECUTOR_RELEASED_AT = datetime(2026, 8, 5, tzinfo=UTC)
_EXECUTOR_ACTOR = "workload:metric-query-control-plane"
_ALLOWED_RESULT_SCHEMES = frozenset(
    {"file", "gs", "https", "iceberg", "obs", "postgresql", "s3", "stac"}
)

ClientRequestId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$",
    ),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricQueryOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MetricQueryCacheStatus(StrEnum):
    HIT = "hit"
    MISS = "miss"
    BYPASS = "bypass"


class MetricQueryExecutionAdmission(_FrozenContract):
    tenant_id: TenantId
    run_id: UUID
    client_request_id: ClientRequestId
    definition_version_id: UUID
    plan_artifact_id: UUID
    plan: MetricQueryPlan
    plan_fingerprint: Sha256
    cache_key: Sha256
    engine: Literal["postgis", "duckdb", "iceberg_spark"]
    execution_mode: Literal["synchronous", "asynchronous"]
    admitted_by: str = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")
    admitted_at: datetime

    @field_validator("admitted_at")
    @classmethod
    def _utc_admitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric query admission time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _exact_plan_binding(self) -> MetricQueryExecutionAdmission:
        if (
            self.plan.tenant_id != self.tenant_id
            or self.plan.cache_key != self.cache_key
            or self.plan.engine != self.engine
            or self.plan.execution_mode != self.execution_mode
        ):
            raise ValueError("metric query admission must bind the exact plan")
        return self


class MetricQueryExecutionObservation(_FrozenContract):
    tenant_id: TenantId
    query_observation_id: UUID
    run_id: UUID
    attempt_no: int = Field(ge=1, le=100)
    start_observation_id: UUID
    terminal_observation_id: UUID
    result_artifact_id: UUID | None = None
    outcome: MetricQueryOutcome
    cache_status: MetricQueryCacheStatus
    rows_returned: int = Field(ge=0, le=10**15)
    rows_scanned: int = Field(ge=0, le=10**15)
    bytes_scanned: int = Field(ge=0, le=10**18)
    duration_ms: int = Field(ge=0, le=86_400_000)
    result_sha256: Sha256 | None = None
    error_code: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_]{0,127}$"
    )
    error_message: str | None = Field(default=None, min_length=1, max_length=2048)
    observed_at: datetime
    recorded_by: str = Field(pattern=r"^workload:[^\s]{1,128}$")

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric query observation time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_outcome(self) -> MetricQueryExecutionObservation:
        succeeded = self.outcome is MetricQueryOutcome.SUCCEEDED
        result_bound = self.result_artifact_id is not None and self.result_sha256 is not None
        error_bound = self.error_code is not None and self.error_message is not None
        if succeeded != result_bound or succeeded == error_bound:
            raise ValueError("query outcome must bind exactly one result or error")
        if self.cache_status is MetricQueryCacheStatus.HIT and not succeeded:
            raise ValueError("cache hit can only produce a successful query outcome")
        return self


class MetricQueryRunRecord(_FrozenContract):
    admission: MetricQueryExecutionAdmission
    run: PlatformRun
    plan_artifact: Artifact
    observation: MetricQueryExecutionObservation | None = None

    @model_validator(mode="after")
    def _consistent_record(self) -> MetricQueryRunRecord:
        admission = self.admission
        if (
            self.run.tenant_id != admission.tenant_id
            or self.run.run_id != admission.run_id
            or self.run.definition_version_id != admission.definition_version_id
            or self.plan_artifact.tenant_id != admission.tenant_id
            or self.plan_artifact.artifact_id != admission.plan_artifact_id
            or self.plan_artifact.run_id != admission.run_id
            or self.plan_artifact.content_sha256 != admission.plan_fingerprint
        ):
            raise ValueError("metric query run evidence is not exactly bound")
        if self.observation is not None and self.observation.run_id != admission.run_id:
            raise ValueError("metric query observation must belong to the run")
        return self


class MetricQueryStartSpec(_FrozenContract):
    attempt_no: int = Field(default=1, ge=1, le=100)
    external_namespace: NonEmptyText
    external_run_id: NonEmptyText
    external_attempt_id: NonEmptyText | None = None
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric query start time must be timezone-aware")
        return value.astimezone(UTC)


class MetricQueryCompletionSpec(_FrozenContract):
    attempt_no: int = Field(default=1, ge=1, le=100)
    start_observation_id: UUID
    outcome: MetricQueryOutcome
    cache_status: MetricQueryCacheStatus = MetricQueryCacheStatus.BYPASS
    rows_returned: int = Field(default=0, ge=0, le=10**15)
    rows_scanned: int = Field(default=0, ge=0, le=10**15)
    bytes_scanned: int = Field(default=0, ge=0, le=10**18)
    duration_ms: int = Field(ge=0, le=86_400_000)
    result_storage_uri: str | None = Field(default=None, min_length=1, max_length=512)
    result_media_type: str | None = Field(default=None, min_length=1, max_length=256)
    result_sha256: Sha256 | None = None
    result_size_bytes: int | None = Field(default=None, ge=0, le=10**18)
    result_manifest: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_]{0,127}$"
    )
    error_message: str | None = Field(default=None, min_length=1, max_length=2048)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric query completion time must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("result_storage_uri")
    @classmethod
    def _safe_result_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme not in _ALLOWED_RESULT_SCHEMES:
            raise ValueError("query result storage URI is unsupported")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("query result storage URI must be stable and credential-free")
        if parts.scheme == "file" and (parts.netloc or not parts.path.startswith("/")):
            raise ValueError("file result URI must use an absolute path")
        if parts.scheme != "file" and not parts.netloc:
            raise ValueError("query result storage URI must identify an authority")
        return value

    @model_validator(mode="after")
    def _consistent_completion(self) -> MetricQueryCompletionSpec:
        result_values = (
            self.result_storage_uri,
            self.result_media_type,
            self.result_sha256,
            self.result_size_bytes,
        )
        result_bound = all(value is not None for value in result_values)
        no_result = all(value is None for value in result_values)
        error_bound = self.error_code is not None and self.error_message is not None
        no_error = self.error_code is None and self.error_message is None
        if self.outcome is MetricQueryOutcome.SUCCEEDED:
            if not result_bound or not no_error:
                raise ValueError("successful query completion requires result evidence only")
        elif not no_result or not error_bound:
            raise ValueError("failed query completion requires error evidence only")
        if (
            self.cache_status is MetricQueryCacheStatus.HIT
            and self.outcome is not MetricQueryOutcome.SUCCEEDED
        ):
            raise ValueError("cache hit cannot be recorded for a failed query")
        if not isinstance(self.result_manifest, dict):
            raise ValueError("query result manifest must be an object")
        return self


class MetricQueryExecutionError(RuntimeError):
    code = "metric_query_execution_error"


class MetricQueryExecutionConflictError(MetricQueryExecutionError):
    code = "metric_query_execution_conflict"


class MetricQueryExecutionNotFoundError(MetricQueryExecutionError):
    code = "metric_query_execution_not_found"


class MetricQueryExecutionForbiddenError(MetricQueryExecutionError):
    code = "metric_query_execution_forbidden"


class MetricQueryExecutionValidationError(MetricQueryExecutionError):
    code = "metric_query_execution_validation_error"


class MetricQueryExecutionConfigurationError(MetricQueryExecutionError):
    code = "metric_query_execution_unavailable"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _execution_definition_registration(
    tenant_id: str, execution_mode: Literal["synchronous", "asynchronous"]
) -> DefinitionRegistration:
    orchestration = (
        OrchestrationClass.SYNCHRONOUS
        if execution_mode == "synchronous"
        else OrchestrationClass.DATAOPS
    )
    definition_id = uuid5(
        _EXECUTOR_NAMESPACE, f"{tenant_id}:{execution_mode}:v1"
    )
    suffix = "sync" if execution_mode == "synchronous" else "batch"
    definition_urn = f"gda://{tenant_id}/definition/metric-query-{suffix}"
    definition_document = {
        "schema": "gda.metric_query_executor_definition.v1",
        "version": 1,
        "execution_mode": execution_mode,
        "engines": (
            ["postgis", "duckdb"]
            if execution_mode == "synchronous"
            else ["iceberg_spark"]
        ),
        "planner_contract": "gda.metric_query_plan.v1",
    }
    input_contract = {
        "schema": "gda.metric_query_executor_input.v1",
        "required": ["execution_plan_artifact", "metric_source"],
    }
    output_contract = {
        "schema": "gda.metric_query_executor_output.v1",
        "required": ["framework_attempt", "query_observation"],
        "result_artifact_required_on_success": True,
    }
    definition_sha256 = platform_definition_fingerprint(
        orchestration_class=orchestration,
        capability_id="metric.query.execute",
        portability_class=PortabilityClass.ENGINE_FAMILY,
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    resource = Resource(
        tenant_id=tenant_id,
        resource_urn=definition_urn,
        resource_kind="definition",
        authority_system="gda",
        authority_locator=f"metric-query-executor/{execution_mode}/v1",
        owner_ref="team:data-platform",
        governance_ref={
            "contract": "gda.metric_query_executor_definition.v1",
            "execution_mode": execution_mode,
        },
        technical_refs=tuple(
            {"engine": engine} for engine in definition_document["engines"]
        ),
    )
    version = ResourceVersion(
        tenant_id=tenant_id,
        resource_urn=definition_urn,
        resource_version_id=definition_id,
        version_key="v1",
        content_sha256=definition_sha256,
        authority_version_ref={
            "schema": "gda.metric_query_executor_release.v1",
            "version": 1,
            "execution_mode": execution_mode,
        },
        created_by=_EXECUTOR_ACTOR,
        created_at=_EXECUTOR_RELEASED_AT,
    )
    definition = PlatformDefinitionVersion(
        tenant_id=tenant_id,
        definition_urn=definition_urn,
        definition_version_id=definition_id,
        orchestration_class=orchestration,
        capability_id="metric.query.execute",
        portability_class="engine_family",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=definition_sha256,
    )
    return DefinitionRegistration(
        resource=resource,
        resource_version=version,
        definition=definition,
    )


class MetricQueryExecutionAuthority:
    """Atomic metric query admission and terminal provider evidence authority."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise MetricQueryExecutionConfigurationError(
                "metric query execution authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise MetricQueryExecutionConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except MetricQueryExecutionError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise MetricQueryExecutionConflictError(
                    "metric query execution state conflict"
                ) from exc
            if state == "P0002":
                raise MetricQueryExecutionNotFoundError(
                    "metric query execution was not found"
                ) from exc
            if state == "42501":
                raise MetricQueryExecutionForbiddenError(
                    "metric query execution access was denied"
                ) from exc
            if state in {"22023", "22P02", "23502", "23503", "23514", "55000"}:
                raise MetricQueryExecutionValidationError(
                    "metric query execution contract was rejected"
                ) from exc
            raise MetricQueryExecutionError(
                "metric query execution database operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise MetricQueryExecutionError(
                "metric query execution database operation failed"
            ) from exc

    def _ensure_definition(
        self, tenant_id: str, execution_mode: Literal["synchronous", "asynchronous"]
    ) -> DefinitionRegistration:
        registration = _execution_definition_registration(tenant_id, execution_mode)
        try:
            PlatformGateway(self._get_engine()).register_definition(registration)
        except GatewayConflictError as exc:
            raise MetricQueryExecutionConflictError(str(exc)) from exc
        except GatewayForbiddenError as exc:
            raise MetricQueryExecutionForbiddenError(str(exc)) from exc
        except (GatewayConfigurationError, GatewayUnavailableError) as exc:
            raise MetricQueryExecutionConfigurationError(str(exc)) from exc
        except (GatewayNotFoundError, GatewayValidationError) as exc:
            raise MetricQueryExecutionValidationError(str(exc)) from exc
        return registration

    @staticmethod
    def _admission_from_row(row: Any) -> MetricQueryExecutionAdmission:
        value = dict(row)
        value["plan"] = _json_value(value.pop("plan_document"))
        return MetricQueryExecutionAdmission.model_validate(value)

    @staticmethod
    def _observation_from_row(row: Any) -> MetricQueryExecutionObservation:
        return MetricQueryExecutionObservation.model_validate(dict(row))

    @classmethod
    def _load_admission(
        cls, connection: Any, tenant_id: str, run_id: UUID
    ) -> MetricQueryExecutionAdmission | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, run_id, client_request_id,
                           definition_version_id, plan_artifact_id,
                           plan_document, plan_fingerprint, cache_key,
                           engine, execution_mode, admitted_by, admitted_at
                    FROM gda_control.metric_query_execution_admission
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    """
                ),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._admission_from_row(row) if row is not None else None

    @classmethod
    def _load_observation(
        cls, connection: Any, tenant_id: str, run_id: UUID
    ) -> MetricQueryExecutionObservation | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, query_observation_id, run_id, attempt_no,
                           start_observation_id, terminal_observation_id,
                           result_artifact_id, outcome, cache_status,
                           rows_returned, rows_scanned, bytes_scanned, duration_ms,
                           result_sha256, error_code, error_message,
                           observed_at, recorded_by
                    FROM gda_control.metric_query_execution_observation
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    """
                ),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._observation_from_row(row) if row is not None else None

    def admit(
        self,
        plan: MetricQueryPlan,
        security: MetricQuerySecurityContext,
        client_request_id: str,
        *,
        admitted_at: datetime | None = None,
    ) -> MetricQueryRunRecord:
        request_id = TypeAdapter(ClientRequestId).validate_python(client_request_id)
        if plan.tenant_id != security.tenant_id:
            raise MetricQueryExecutionValidationError(
                "metric query plan and security tenant must match"
            )
        if plan.security_context_fingerprint != canonical_json_fingerprint(
            security.model_dump(mode="json")
        ):
            raise MetricQueryExecutionValidationError(
                "metric query plan does not bind this security context"
            )
        admitted = admitted_at or datetime.now(UTC)
        if admitted.tzinfo is None or admitted.utcoffset() is None:
            raise MetricQueryExecutionValidationError(
                "metric query admission time must be timezone-aware"
            )
        admitted = admitted.astimezone(UTC)
        registration = self._ensure_definition(
            security.tenant_id, plan.execution_mode
        )
        run_id = uuid5(_RUN_NAMESPACE, f"{security.tenant_id}:{request_id}")
        artifact_id = uuid5(run_id, "metric-query-plan")
        subject_type, subject_id = security.subject_ref.split(":", 1)
        subject_context = SubjectContext(
            tenant_id=security.tenant_id,
            subject_id=subject_id,
            subject_type=SubjectType(subject_type),
            roles=security.roles,
            purpose=security.purpose,
        )
        with self._transaction(security.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.admit_metric_query_execution(
                        :tenant_id, :run_id, :client_request_id,
                        :definition_version_id, :orchestration_class,
                        CAST(:subject_context AS jsonb), :idempotency_key,
                        :config_fingerprint, :output_resource_version_id,
                        :plan_artifact_id, CAST(:plan_document AS jsonb),
                        :admitted_by, :admitted_at
                    )
                    """
                ),
                {
                    "tenant_id": security.tenant_id,
                    "run_id": run_id,
                    "client_request_id": request_id,
                    "definition_version_id": (
                        registration.definition.definition_version_id
                    ),
                    "orchestration_class": (
                        registration.definition.orchestration_class.value
                    ),
                    "subject_context": _json(subject_context.model_dump(mode="json")),
                    "idempotency_key": f"metric-query:v1:{request_id}",
                    "config_fingerprint": plan.cache_key,
                    "output_resource_version_id": plan.output_resource_version_id,
                    "plan_artifact_id": artifact_id,
                    "plan_document": _json(plan.model_dump(mode="json")),
                    "admitted_by": security.subject_ref,
                    "admitted_at": admitted,
                },
            ).scalar_one()
        return self.get(security.tenant_id, run_id)

    def get(self, tenant_id: str, run_id: UUID) -> MetricQueryRunRecord:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            admission = self._load_admission(connection, tenant, run_id)
            observation = self._load_observation(connection, tenant, run_id)
        if admission is None:
            raise MetricQueryExecutionNotFoundError(
                "metric query execution was not found"
            )
        gateway = PlatformGateway(self._get_engine())
        try:
            run = gateway.get_run(tenant, run_id)
            artifact = gateway.get_artifact(tenant, admission.plan_artifact_id)
        except GatewayNotFoundError as exc:
            raise MetricQueryExecutionNotFoundError(str(exc)) from exc
        except GatewayForbiddenError as exc:
            raise MetricQueryExecutionForbiddenError(str(exc)) from exc
        except (GatewayConfigurationError, GatewayUnavailableError) as exc:
            raise MetricQueryExecutionConfigurationError(str(exc)) from exc
        return MetricQueryRunRecord(
            admission=admission,
            run=run,
            plan_artifact=artifact,
            observation=observation,
        )

    def start(
        self,
        tenant_id: str,
        run_id: UUID,
        spec: MetricQueryStartSpec,
        *,
        actor_subject: str,
        expected_state_version: int = 0,
    ) -> MetricQueryRunRecord:
        start_observation_id = uuid5(
            run_id,
            f"metric-query-start:{spec.attempt_no}:{spec.external_namespace}:{spec.external_run_id}",
        )
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.start_metric_query_execution(
                        :tenant_id, :run_id, :expected_state_version,
                        :start_observation_id, :attempt_no,
                        :external_namespace, :external_run_id,
                        :external_attempt_id, :actor_subject, :observed_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "expected_state_version": expected_state_version,
                    "start_observation_id": start_observation_id,
                    "attempt_no": spec.attempt_no,
                    "external_namespace": spec.external_namespace,
                    "external_run_id": spec.external_run_id,
                    "external_attempt_id": spec.external_attempt_id,
                    "actor_subject": actor_subject,
                    "observed_at": spec.observed_at,
                },
            ).scalar_one()
        return self.get(tenant_id, run_id)

    def complete(
        self,
        tenant_id: str,
        run_id: UUID,
        spec: MetricQueryCompletionSpec,
        *,
        actor_subject: str,
        expected_state_version: int = 2,
    ) -> MetricQueryRunRecord:
        identity = (
            spec.result_sha256
            if spec.result_sha256 is not None
            else f"{spec.error_code}:{spec.error_message}"
        )
        query_observation_id = uuid5(
            run_id, f"metric-query-observation:{spec.attempt_no}:{identity}"
        )
        terminal_observation_id = uuid5(
            run_id, f"metric-query-terminal:{spec.attempt_no}:{identity}"
        )
        result_artifact_id = (
            uuid5(run_id, f"metric-query-result:{spec.result_sha256}")
            if spec.result_sha256 is not None
            else None
        )
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.complete_metric_query_execution(
                        :tenant_id, :run_id, :expected_state_version,
                        :query_observation_id, :start_observation_id,
                        :terminal_observation_id, :result_artifact_id,
                        :attempt_no, :outcome, :cache_status,
                        :rows_returned, :rows_scanned, :bytes_scanned,
                        :duration_ms, :result_storage_uri, :result_media_type,
                        :result_sha256, :result_size_bytes,
                        CAST(:result_manifest AS jsonb), :error_code,
                        :error_message, :actor_subject, :observed_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "expected_state_version": expected_state_version,
                    "query_observation_id": query_observation_id,
                    "start_observation_id": spec.start_observation_id,
                    "terminal_observation_id": terminal_observation_id,
                    "result_artifact_id": result_artifact_id,
                    "attempt_no": spec.attempt_no,
                    "outcome": spec.outcome.value,
                    "cache_status": spec.cache_status.value,
                    "rows_returned": spec.rows_returned,
                    "rows_scanned": spec.rows_scanned,
                    "bytes_scanned": spec.bytes_scanned,
                    "duration_ms": spec.duration_ms,
                    "result_storage_uri": spec.result_storage_uri,
                    "result_media_type": spec.result_media_type,
                    "result_sha256": spec.result_sha256,
                    "result_size_bytes": spec.result_size_bytes,
                    "result_manifest": _json(spec.result_manifest),
                    "error_code": spec.error_code,
                    "error_message": spec.error_message,
                    "actor_subject": actor_subject,
                    "observed_at": spec.observed_at,
                },
            ).scalar_one()
        return self.get(tenant_id, run_id)
