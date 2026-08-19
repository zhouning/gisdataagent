"""Durable, version-bound execution contracts for governed GIS analysis."""

from __future__ import annotations

import hashlib
import json
import re
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
from .gis_algorithm_registry import (
    DEFAULT_GIS_ALGORITHM_REGISTRY,
    GISAlgorithmRegistryError,
    GISAnalysisOperation,
)
from .nl2sql_source_authority import (
    NL2SQLSourceAdmissionError,
    NL2SQLSourceAuthority,
    NL2SQLSourceBinding,
)
from .platform_contracts import (
    Artifact,
    IncidentSeverity,
    OrchestrationClass,
    PlatformCommand,
    PlatformDefinitionVersion,
    PlatformRun,
    PortabilityClass,
    Resource,
    ResourceVersion,
    Sha256,
    SubjectContext,
    TenantId,
    canonical_json_fingerprint,
    data_incident_fingerprint,
    platform_definition_fingerprint,
)
from .platform_gateway import (
    GATEWAY_DATABASE_ROLE,
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
_RUN_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/contracts/gis-analysis-run/v1",
)
_DEFINITION_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/contracts/gis-analysis-executor/v1",
)
_RELEASED_AT = datetime(2026, 8, 13, tzinfo=UTC)
_CONTROL_ACTOR = "workload:gis-analysis-control-plane"
GIS_POSTGIS_WORKLOAD = "workload:gis-analysis-postgis"
GIS_POSTGIS_CANCELLER_WORKLOAD = "workload:gis-analysis-postgis-canceller"
GIS_POSTGIS_RECONCILER_WORKLOAD = "workload:gis-analysis-postgis-reconciler"
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_ALLOWED_RESULT_SCHEMES = frozenset(
    {"file", "gs", "https", "obs", "postgresql", "s3"}
)


def gis_analysis_stable_uuid(dedupe_key: str) -> UUID:
    value = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
    return UUID(
        f"{value[:8]}-{value[8:12]}-5{value[13:16]}-"
        f"8{value[17:20]}-{value[20:32]}"
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


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GISAnalysisRequest(_FrozenContract):
    operation: GISAnalysisOperation
    algorithm_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.-]{2,127}$",
    )
    algorithm_version: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.-]{2,127}$",
    )
    input_source_name: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$",
    )
    overlay_source_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$",
    )
    distance_meters: float | None = Field(default=None, gt=0, le=1_000_000)
    output_crs: str = Field(pattern=r"^EPSG:[1-9][0-9]{2,5}$")

    @model_validator(mode="after")
    def _operation_inputs(self) -> GISAnalysisRequest:
        if (self.algorithm_id is None) != (self.algorithm_version is None):
            raise ValueError("GIS algorithm id and version must be selected together")
        if self.operation is GISAnalysisOperation.BUFFER:
            if self.overlay_source_name is not None or self.distance_meters is None:
                raise ValueError("buffer requires distance_meters and one input source")
        elif self.overlay_source_name is None or self.distance_meters is not None:
            raise ValueError(
                "clip and intersection require an overlay source and no distance"
            )
        if self.overlay_source_name == self.input_source_name:
            raise ValueError("GIS analysis inputs must be distinct")
        return self


class GISAnalysisBudget(_FrozenContract):
    max_features: int = Field(ge=1, le=100_000)
    max_output_bytes: int = Field(ge=1_024, le=10_000_000_000)
    max_duration_ms: int = Field(ge=100, le=1_795_000)


class GISAnalysisSource(_FrozenContract):
    role: Literal["input", "overlay"]
    semantic_source_name: str
    binding_id: UUID
    resource_version_id: UUID
    resource_urn: str
    version_key: str
    content_sha256: Sha256
    authority_version_sha256: Sha256
    physical_binding_sha256: Sha256
    physical_relation: str = Field(
        pattern=r"^[a-z_][a-z0-9_]{0,62}(?:\.[a-z_][a-z0-9_]{0,62})?$"
    )
    geometry_column: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    source_srid: int = Field(ge=1, le=999_999)


class GISAnalysisPlan(_FrozenContract):
    schema_id: Literal["gda.gis_analysis_plan.v1"] = "gda.gis_analysis_plan.v1"
    tenant_id: TenantId
    operation: GISAnalysisOperation
    algorithm_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    algorithm_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    algorithm_spec_fingerprint: Sha256
    engine: Literal["postgis"] = "postgis"
    execution_mode: Literal["asynchronous"] = "asynchronous"
    sources: tuple[GISAnalysisSource, ...]
    distance_meters: float | None = None
    output_srid: int = Field(ge=1, le=999_999)
    budget: GISAnalysisBudget
    security_context_fingerprint: Sha256
    cache_key: Sha256

    @model_validator(mode="after")
    def _exact_contract(self) -> GISAnalysisPlan:
        try:
            algorithm = DEFAULT_GIS_ALGORITHM_REGISTRY.require_plan_binding(
                operation=self.operation,
                algorithm_id=self.algorithm_id,
                algorithm_version=self.algorithm_version,
                spec_fingerprint=self.algorithm_spec_fingerprint,
                engine=self.engine,
            )
        except GISAlgorithmRegistryError as exc:
            raise ValueError(str(exc)) from exc
        roles = tuple(source.role for source in self.sources)
        if roles != algorithm.input_roles:
            raise ValueError("GIS plan sources do not match its operation")
        required_parameters = set(algorithm.required_parameter_names)
        present_parameters = (
            {"distance_meters"} if self.distance_meters is not None else set()
        )
        if present_parameters != required_parameters:
            raise ValueError("GIS plan parameters do not match its algorithm release")
        ceiling = algorithm.budget_ceiling
        if (
            self.budget.max_features > ceiling.max_features
            or self.budget.max_output_bytes > ceiling.max_output_bytes
            or self.budget.max_duration_ms > ceiling.max_duration_ms
        ):
            raise ValueError("GIS plan budget exceeds its algorithm release ceiling")
        expected_cache_key = canonical_json_fingerprint(
            self.model_dump(mode="json", exclude={"cache_key"})
        )
        if self.cache_key != expected_cache_key:
            raise ValueError("GIS plan cache key does not match its contract")
        return self

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        operation: GISAnalysisOperation,
        sources: tuple[GISAnalysisSource, ...],
        distance_meters: float | None,
        output_srid: int,
        budget: GISAnalysisBudget,
        security_context_fingerprint: str,
        algorithm_id: str | None = None,
        algorithm_version: str | None = None,
    ) -> GISAnalysisPlan:
        normalized_sources = tuple(
            source
            if isinstance(source, GISAnalysisSource)
            else GISAnalysisSource.model_validate(source)
            for source in sources
        )
        try:
            algorithm = DEFAULT_GIS_ALGORITHM_REGISTRY.resolve(
                operation,
                algorithm_id=algorithm_id,
                algorithm_version=algorithm_version,
            )
        except GISAlgorithmRegistryError as exc:
            raise ValueError(str(exc)) from exc
        values: dict[str, Any] = {
            "tenant_id": tenant_id,
            "operation": operation,
            "algorithm_id": algorithm.algorithm_id,
            "algorithm_version": algorithm.algorithm_version,
            "algorithm_spec_fingerprint": algorithm.spec_fingerprint,
            "engine": algorithm.engine,
            "sources": normalized_sources,
            "distance_meters": distance_meters,
            "output_srid": output_srid,
            "budget": budget,
            "security_context_fingerprint": security_context_fingerprint,
        }
        if distance_meters is not None:
            values["distance_meters"] = float(distance_meters)
        provisional = cls.model_construct(**values, cache_key="0" * 64)
        document = provisional.model_dump(mode="json", exclude={"cache_key"})
        return cls(**values, cache_key=canonical_json_fingerprint(document))


class GISAnalysisOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GISAnalysisExecutionAdmission(_FrozenContract):
    tenant_id: TenantId
    run_id: UUID
    client_request_id: ClientRequestId
    definition_version_id: UUID
    plan_artifact_id: UUID
    plan: GISAnalysisPlan
    plan_fingerprint: Sha256
    cache_key: Sha256
    admitted_by: str = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")
    admitted_at: datetime

    @field_validator("admitted_at")
    @classmethod
    def _utc_admitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GIS admission time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _exact_plan(self) -> GISAnalysisExecutionAdmission:
        if self.plan.tenant_id != self.tenant_id or self.plan.cache_key != self.cache_key:
            raise ValueError("GIS admission must bind the exact plan")
        return self


class GISAnalysisExecutionObservation(_FrozenContract):
    tenant_id: TenantId
    analysis_observation_id: UUID
    run_id: UUID
    attempt_no: int = Field(ge=1, le=100)
    start_observation_id: UUID
    terminal_observation_id: UUID
    result_artifact_id: UUID | None = None
    outcome: GISAnalysisOutcome
    features_returned: int = Field(ge=0, le=10**15)
    bytes_scanned: int = Field(ge=0, le=10**18)
    duration_ms: int = Field(ge=0, le=1_795_000)
    result_sha256: Sha256 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,127}$")
    error_message: str | None = Field(default=None, min_length=1, max_length=2048)
    observed_at: datetime
    recorded_by: str = Field(pattern=r"^workload:[^\s]{1,128}$")

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GIS observation time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _result_or_error(self) -> GISAnalysisExecutionObservation:
        succeeded = self.outcome is GISAnalysisOutcome.SUCCEEDED
        result = self.result_artifact_id is not None and self.result_sha256 is not None
        error = self.error_code is not None and self.error_message is not None
        if succeeded != result or succeeded == error:
            raise ValueError("GIS outcome must bind exactly one result or error")
        return self


class GISAnalysisCancelOutcome(StrEnum):
    SIGNALLED = "signalled"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


class GISAnalysisReconciliationObservation(_FrozenContract):
    tenant_id: TenantId
    run_id: UUID
    reconciliation_observation_id: UUID
    reconcile_command_id: UUID
    reconcile_attempt_no: int = Field(ge=1, le=100)
    cancel_command_id: UUID
    cancel_observation_id: UUID
    outcome: GISAnalysisCancelOutcome
    backend_binding_fingerprint: Sha256
    observed_at: datetime
    recorded_by: str = Field(pattern=r"^workload:[^\s]{1,128}$")

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GIS reconciliation time must be timezone-aware")
        return value.astimezone(UTC)


class GISAnalysisRunRecord(_FrozenContract):
    admission: GISAnalysisExecutionAdmission
    run: PlatformRun
    plan_artifact: Artifact
    observation: GISAnalysisExecutionObservation | None = None
    cancel_admission: GISAnalysisCancelAdmission | None = None
    cancel_receipt: GISAnalysisCancelReceipt | None = None
    reconciliation_observations: tuple[
        GISAnalysisReconciliationObservation, ...
    ] = ()

    @model_validator(mode="after")
    def _exact_binding(self) -> GISAnalysisRunRecord:
        admission = self.admission
        if (
            self.run.tenant_id != admission.tenant_id
            or self.run.run_id != admission.run_id
            or self.run.definition_version_id != admission.definition_version_id
            or self.plan_artifact.artifact_id != admission.plan_artifact_id
            or self.plan_artifact.run_id != admission.run_id
            or self.plan_artifact.content_sha256 != admission.plan_fingerprint
        ):
            raise ValueError("GIS run evidence is not exactly bound")
        if self.observation is not None and self.observation.run_id != admission.run_id:
            raise ValueError("GIS observation must belong to the run")
        if self.cancel_admission is not None and (
            self.cancel_admission.run_id != admission.run_id
            or self.cancel_admission.tenant_id != admission.tenant_id
        ):
            raise ValueError("GIS cancellation must belong to the run")
        if self.cancel_receipt is not None and (
            self.cancel_admission is None
            or self.cancel_receipt.run_id != admission.run_id
            or self.cancel_receipt.cancel_command_id
            != self.cancel_admission.cancel_command_id
        ):
            raise ValueError("GIS cancellation receipt must bind its admission")
        for reconciliation in self.reconciliation_observations:
            if (
                reconciliation.tenant_id != admission.tenant_id
                or reconciliation.run_id != admission.run_id
                or self.cancel_admission is None
                or self.cancel_receipt is None
                or reconciliation.cancel_command_id
                != self.cancel_admission.cancel_command_id
                or reconciliation.cancel_observation_id
                != self.cancel_receipt.cancel_observation_id
                or reconciliation.backend_binding_fingerprint
                != self.cancel_admission.backend.binding_fingerprint
                or reconciliation.recorded_by
                != GIS_POSTGIS_RECONCILER_WORKLOAD
            ):
                raise ValueError("GIS reconciliation has a foreign evidence binding")
        return self


class GISAnalysisStartSpec(_FrozenContract):
    attempt_no: int = Field(default=1, ge=1, le=100)
    external_namespace: str = Field(min_length=1, max_length=512)
    external_run_id: str = Field(min_length=1, max_length=512)
    external_attempt_id: str | None = Field(default=None, min_length=1, max_length=512)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GIS start time must be timezone-aware")
        return value.astimezone(UTC)


class GISAnalysisBackendBinding(_FrozenContract):
    schema_id: Literal["gda.gis_analysis_backend_binding.v1"] = (
        "gda.gis_analysis_backend_binding.v1"
    )
    backend_pid: int = Field(ge=1, le=2_147_483_647)
    backend_start: datetime
    database_oid: int = Field(ge=1, le=4_294_967_295)
    user_oid: int = Field(ge=1, le=4_294_967_295)
    application_name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^gda-gis-analysis/[0-9a-f-]{36}$",
    )
    binding_fingerprint: Sha256

    @field_validator("backend_start")
    @classmethod
    def _utc_backend_start(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("PostGIS backend start time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _exact_backend(self) -> GISAnalysisBackendBinding:
        expected = canonical_json_fingerprint(
            self.model_dump(mode="json", exclude={"binding_fingerprint"})
        )
        if self.binding_fingerprint != expected:
            raise ValueError("PostGIS backend binding fingerprint is invalid")
        return self

    @classmethod
    def create(
        cls,
        *,
        backend_pid: int,
        backend_start: datetime,
        database_oid: int,
        user_oid: int,
        application_name: str,
    ) -> GISAnalysisBackendBinding:
        values = {
            "backend_pid": backend_pid,
            "backend_start": backend_start,
            "database_oid": database_oid,
            "user_oid": user_oid,
            "application_name": application_name,
        }
        provisional = cls.model_construct(**values, binding_fingerprint="0" * 64)
        fingerprint = canonical_json_fingerprint(
            provisional.model_dump(mode="json", exclude={"binding_fingerprint"})
        )
        return cls(**values, binding_fingerprint=fingerprint)


class GISAnalysisProviderStartSpec(GISAnalysisStartSpec):
    backend: GISAnalysisBackendBinding


class GISAnalysisCancelAdmission(_FrozenContract):
    tenant_id: TenantId
    run_id: UUID
    cancel_request_id: ClientRequestId
    cancel_command_id: UUID
    start_observation_id: UUID
    requested_by: str = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")
    reason: str = Field(min_length=1, max_length=512)
    backend: GISAnalysisBackendBinding
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def _utc_requested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GIS cancellation request time must be timezone-aware")
        return value.astimezone(UTC)


class GISAnalysisCancelReceipt(_FrozenContract):
    tenant_id: TenantId
    run_id: UUID
    cancel_command_id: UUID
    cancel_observation_id: UUID
    outcome: GISAnalysisCancelOutcome
    backend: GISAnalysisBackendBinding
    observed_at: datetime
    recorded_by: str = Field(pattern=r"^workload:[^\s]{1,128}$")

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GIS cancellation receipt time must be timezone-aware")
        return value.astimezone(UTC)


class GISAnalysisCompletionSpec(_FrozenContract):
    attempt_no: int = Field(default=1, ge=1, le=100)
    start_observation_id: UUID
    outcome: GISAnalysisOutcome
    features_returned: int = Field(default=0, ge=0, le=10**15)
    bytes_scanned: int = Field(default=0, ge=0, le=10**18)
    duration_ms: int = Field(ge=0, le=1_795_000)
    result_storage_uri: str | None = Field(default=None, min_length=1, max_length=2048)
    result_media_type: str | None = Field(default=None, min_length=1, max_length=256)
    result_sha256: Sha256 | None = None
    result_size_bytes: int | None = Field(default=None, ge=0, le=10**18)
    result_manifest: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,127}$")
    error_message: str | None = Field(default=None, min_length=1, max_length=2048)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GIS completion time must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("result_storage_uri")
    @classmethod
    def _safe_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if (
            parts.scheme not in _ALLOWED_RESULT_SCHEMES
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or (parts.scheme == "file" and (parts.netloc or not parts.path.startswith("/")))
            or (parts.scheme != "file" and not parts.netloc)
        ):
            raise ValueError("GIS result storage URI is unsupported or unstable")
        return value

    @model_validator(mode="after")
    def _result_or_error(self) -> GISAnalysisCompletionSpec:
        result_fields = (
            self.result_storage_uri,
            self.result_media_type,
            self.result_sha256,
            self.result_size_bytes,
        )
        if self.outcome is GISAnalysisOutcome.SUCCEEDED:
            if (
                any(value is None for value in result_fields)
                or self.error_code
                or self.error_message
            ):
                raise ValueError("successful GIS analysis requires result evidence only")
        elif any(value is not None for value in result_fields) or not (
            self.error_code and self.error_message
        ):
            raise ValueError("failed GIS analysis requires error evidence only")
        return self


class GISAnalysisRunAdmissionRequest(_FrozenContract):
    client_request_id: ClientRequestId
    analysis: GISAnalysisRequest
    budget: GISAnalysisBudget


class GISAnalysisRunCancelRequest(_FrozenContract):
    cancel_request_id: ClientRequestId
    expected_state_version: int = Field(default=0, ge=0)
    reason: str = Field(min_length=1, max_length=512)


class GISAnalysisExecutionError(RuntimeError):
    code = "gis_analysis_execution_error"


class GISAnalysisExecutionConflictError(GISAnalysisExecutionError):
    code = "gis_analysis_execution_conflict"


class GISAnalysisExecutionNotFoundError(GISAnalysisExecutionError):
    code = "gis_analysis_execution_not_found"


class GISAnalysisExecutionForbiddenError(GISAnalysisExecutionError):
    code = "gis_analysis_execution_forbidden"


class GISAnalysisExecutionValidationError(GISAnalysisExecutionError):
    code = "gis_analysis_execution_validation_error"


class GISAnalysisExecutionConfigurationError(GISAnalysisExecutionError):
    code = "gis_analysis_execution_unavailable"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _normalized_relation(value: str) -> str:
    candidate = re.sub(r"^postgis://", "", str(value).strip(), flags=re.IGNORECASE)
    parts = candidate.casefold().split(".")
    if not 1 <= len(parts) <= 2 or any(_IDENTIFIER.fullmatch(part) is None for part in parts):
        raise GISAnalysisExecutionValidationError(
            "GIS physical relation must be a governed PostgreSQL identifier"
        )
    return ".".join(parts)


def _authority_scalar(document: Any, names: set[str]) -> Any:
    if isinstance(document, dict):
        for key, value in document.items():
            if str(key) in names and not isinstance(value, (dict, list, tuple)):
                return value
        for value in document.values():
            found = _authority_scalar(value, names)
            if found is not None:
                return found
    elif isinstance(document, (list, tuple)):
        for value in document:
            found = _authority_scalar(value, names)
            if found is not None:
                return found
    return None


def _source_from_binding(
    binding: NL2SQLSourceBinding,
    version: ResourceVersion,
    role: Literal["input", "overlay"],
) -> GISAnalysisSource:
    if binding.source_mode != "immutable_snapshot":
        raise GISAnalysisExecutionValidationError("GIS input is not an immutable snapshot")
    if (
        version.tenant_id != binding.tenant_id
        or version.resource_version_id != binding.resource_version_id
        or version.resource_urn != binding.resource_urn
        or version.version_key != binding.version_key
        or version.content_sha256 != binding.content_sha256
        or canonical_json_fingerprint(version.authority_version_ref)
        != binding.authority_version_sha256
    ):
        raise GISAnalysisExecutionValidationError(
            "GIS input binding no longer matches its ResourceVersion"
        )
    if binding.physical_binding_sha256 != canonical_json_fingerprint(
        binding.fingerprint_document(binding.model_dump(mode="python"))
    ):
        raise GISAnalysisExecutionValidationError(
            "GIS input binding physical fingerprint is invalid"
        )
    geometry_column = str(
        _authority_scalar(
            version.authority_version_ref,
            {"geometry_column", "postgis_geometry_column"},
        )
        or ""
    ).casefold()
    raw_srid = _authority_scalar(version.authority_version_ref, {"srid", "epsg"})
    if _IDENTIFIER.fullmatch(geometry_column) is None:
        raise GISAnalysisExecutionValidationError(
            "GIS ResourceVersion lacks an authoritative geometry column"
        )
    try:
        source_srid = int(str(raw_srid).removeprefix("EPSG:").removeprefix("epsg:"))
    except (TypeError, ValueError) as exc:
        raise GISAnalysisExecutionValidationError(
            "GIS ResourceVersion lacks an authoritative SRID"
        ) from exc
    return GISAnalysisSource(
        role=role,
        semantic_source_name=binding.semantic_source_name,
        binding_id=binding.binding_id,
        resource_version_id=binding.resource_version_id,
        resource_urn=binding.resource_urn,
        version_key=binding.version_key,
        content_sha256=binding.content_sha256,
        authority_version_sha256=binding.authority_version_sha256,
        physical_binding_sha256=binding.physical_binding_sha256,
        physical_relation=_normalized_relation(binding.physical_locator),
        geometry_column=geometry_column,
        source_srid=source_srid,
    )


class GISAnalysisPlanner:
    """Resolve a typed operation only against immutable active source versions."""

    def __init__(
        self,
        source_authority: NL2SQLSourceAuthority | None = None,
        gateway: PlatformGateway | None = None,
    ):
        self.source_authority = source_authority or NL2SQLSourceAuthority()
        self.gateway = gateway or PlatformGateway()

    def plan(
        self,
        request: GISAnalysisRequest,
        subject_context: SubjectContext,
        budget: GISAnalysisBudget,
    ) -> GISAnalysisPlan:
        names: list[tuple[Literal["input", "overlay"], str]] = [
            ("input", request.input_source_name)
        ]
        if request.overlay_source_name is not None:
            names.append(("overlay", request.overlay_source_name))
        sources: list[GISAnalysisSource] = []
        for role, name in names:
            sources.append(self.resolve_source(name, subject_context, role=role))
        output_srid = int(request.output_crs.split(":", 1)[1])
        try:
            return GISAnalysisPlan.create(
                tenant_id=subject_context.tenant_id,
                operation=request.operation,
                sources=tuple(sources),
                distance_meters=request.distance_meters,
                output_srid=output_srid,
                budget=budget,
                security_context_fingerprint=canonical_json_fingerprint(
                    subject_context.model_dump(mode="json")
                ),
                algorithm_id=request.algorithm_id,
                algorithm_version=request.algorithm_version,
            )
        except (GISAlgorithmRegistryError, ValueError) as exc:
            raise GISAnalysisExecutionValidationError(str(exc)) from exc

    def resolve_source(
        self,
        semantic_source_name: str,
        subject_context: SubjectContext,
        *,
        role: Literal["input", "overlay"] = "input",
    ) -> GISAnalysisSource:
        """Resolve one governed semantic source to its immutable GIS binding."""
        try:
            binding = self.source_authority.resolve(
                subject_context.tenant_id,
                semantic_source_name,
                "postgis",
            )
            version = self.gateway.get_resource_version(
                subject_context.tenant_id,
                binding.resource_version_id,
            )
        except (NL2SQLSourceAdmissionError, GatewayNotFoundError) as exc:
            raise GISAnalysisExecutionValidationError(str(exc)) from exc
        return _source_from_binding(binding, version, role)


def _definition_registration(tenant_id: str) -> DefinitionRegistration:
    definition_id = uuid5(_DEFINITION_NAMESPACE, f"{tenant_id}:postgis:v2")
    definition_urn = f"gda://{tenant_id}/definition/gis-analysis-postgis"
    definition_document = {
        "schema": "gda.gis_analysis_executor_definition.v1",
        "version": 2,
        "engine": "postgis",
        "execution_mode": "asynchronous",
        "operations": ["buffer", "clip", "intersection"],
        "planner_contract": "gda.gis_analysis_plan.v1",
        "algorithm_registry_schema": "gda.gis_algorithm_catalog.v1",
        "algorithm_registry_fingerprint": DEFAULT_GIS_ALGORITHM_REGISTRY.fingerprint,
        "algorithm_releases": [
            {
                "algorithm_id": spec.algorithm_id,
                "algorithm_version": spec.algorithm_version,
                "spec_fingerprint": spec.spec_fingerprint,
            }
            for spec in DEFAULT_GIS_ALGORITHM_REGISTRY.catalog().algorithms
        ],
    }
    input_contract = {
        "schema": "gda.gis_analysis_executor_input.v1",
        "required": ["execution_plan_artifact", "immutable_source_versions"],
    }
    output_contract = {
        "schema": "gda.gis_analysis_executor_output.v1",
        "required": ["framework_attempt", "analysis_observation"],
        "result_artifact_required_on_success": True,
    }
    digest = platform_definition_fingerprint(
        orchestration_class=OrchestrationClass.DATAOPS,
        capability_id="gis.analysis.execute",
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
        authority_locator="gis-analysis/postgis/v1",
        owner_ref="team:data-platform",
        governance_ref={"contract": "gda.gis_analysis_executor_definition.v1"},
        technical_refs=({"engine": "postgis"},),
    )
    version = ResourceVersion(
        tenant_id=tenant_id,
        resource_urn=definition_urn,
        resource_version_id=definition_id,
        version_key="v2",
        content_sha256=digest,
        authority_version_ref={
            "schema": "gda.gis_analysis_executor_release.v1",
            "version": 2,
        },
        created_by=_CONTROL_ACTOR,
        created_at=_RELEASED_AT,
    )
    definition = PlatformDefinitionVersion(
        tenant_id=tenant_id,
        definition_urn=definition_urn,
        definition_version_id=definition_id,
        orchestration_class=OrchestrationClass.DATAOPS,
        capability_id="gis.analysis.execute",
        portability_class=PortabilityClass.ENGINE_FAMILY,
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=digest,
    )
    return DefinitionRegistration(
        resource=resource, resource_version=version, definition=definition
    )


class GISAnalysisExecutionAuthority:
    """Atomic admission, provider receipt and pre-start cancellation authority."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise GISAnalysisExecutionConfigurationError(
                "GIS analysis execution authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql(f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except GISAnalysisExecutionError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise GISAnalysisExecutionConflictError(
                    "GIS analysis execution state conflict"
                ) from exc
            if state == "P0002":
                raise GISAnalysisExecutionNotFoundError(
                    "GIS analysis execution was not found"
                ) from exc
            if state == "42501":
                raise GISAnalysisExecutionForbiddenError(
                    "GIS analysis execution access was denied"
                ) from exc
            if state in {"22023", "22P02", "23502", "23503", "23514", "55000"}:
                raise GISAnalysisExecutionValidationError(
                    "GIS analysis execution contract was rejected"
                ) from exc
            raise GISAnalysisExecutionError(
                "GIS analysis execution database operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise GISAnalysisExecutionError(
                "GIS analysis execution database operation failed"
            ) from exc

    def _ensure_definition(self, tenant_id: str) -> DefinitionRegistration:
        registration = _definition_registration(tenant_id)
        try:
            PlatformGateway(self._get_engine()).register_definition(registration)
        except GatewayConflictError as exc:
            raise GISAnalysisExecutionConflictError(str(exc)) from exc
        except GatewayForbiddenError as exc:
            raise GISAnalysisExecutionForbiddenError(str(exc)) from exc
        except (GatewayConfigurationError, GatewayUnavailableError) as exc:
            raise GISAnalysisExecutionConfigurationError(str(exc)) from exc
        except (GatewayNotFoundError, GatewayValidationError) as exc:
            raise GISAnalysisExecutionValidationError(str(exc)) from exc
        return registration

    @staticmethod
    def _admission_from_row(row: Any) -> GISAnalysisExecutionAdmission:
        value = dict(row)
        value["plan"] = _json_value(value.pop("plan_document"))
        return GISAnalysisExecutionAdmission.model_validate(value)

    @staticmethod
    def _observation_from_row(row: Any) -> GISAnalysisExecutionObservation:
        return GISAnalysisExecutionObservation.model_validate(dict(row))

    @staticmethod
    def _cancel_admission_from_row(row: Any) -> GISAnalysisCancelAdmission:
        value = dict(row)
        value["backend"] = {
            "backend_pid": value.pop("backend_pid"),
            "backend_start": value.pop("backend_start"),
            "database_oid": value.pop("database_oid"),
            "user_oid": value.pop("user_oid"),
            "application_name": value.pop("application_name"),
            "binding_fingerprint": value.pop("backend_binding_fingerprint"),
        }
        return GISAnalysisCancelAdmission.model_validate(value)

    @staticmethod
    def _cancel_receipt_from_row(
        row: Any,
        backend: GISAnalysisBackendBinding,
    ) -> GISAnalysisCancelReceipt:
        value = dict(row)
        value.pop("backend_binding_fingerprint")
        value["backend"] = backend
        return GISAnalysisCancelReceipt.model_validate(value)

    @staticmethod
    def _reconciliation_from_row(
        row: Any,
    ) -> GISAnalysisReconciliationObservation:
        return GISAnalysisReconciliationObservation.model_validate(dict(row))

    @classmethod
    def _load_admission(cls, connection, tenant_id: str, run_id: UUID):
        row = connection.execute(
            text(
                """
                SELECT tenant_id, run_id, client_request_id,
                       definition_version_id, plan_artifact_id, plan_document,
                       plan_fingerprint, cache_key, admitted_by, admitted_at
                FROM gda_control.gis_analysis_execution_admission
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).mappings().one_or_none()
        return cls._admission_from_row(row) if row is not None else None

    @classmethod
    def _load_observation(cls, connection, tenant_id: str, run_id: UUID):
        row = connection.execute(
            text(
                """
                SELECT tenant_id, analysis_observation_id, run_id, attempt_no,
                       start_observation_id, terminal_observation_id,
                       result_artifact_id, outcome, features_returned,
                       bytes_scanned, duration_ms, result_sha256, error_code,
                       error_message, observed_at, recorded_by
                FROM gda_control.gis_analysis_execution_observation
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).mappings().one_or_none()
        return cls._observation_from_row(row) if row is not None else None

    @classmethod
    def _load_cancel_admission(cls, connection, tenant_id: str, run_id: UUID):
        row = connection.execute(
            text(
                """
                SELECT tenant_id, run_id, cancel_request_id, cancel_command_id,
                       start_observation_id, requested_by, reason, backend_pid,
                       backend_start, database_oid, user_oid, application_name,
                       backend_binding_fingerprint, requested_at
                FROM gda_control.gis_analysis_cancel_admission
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).mappings().one_or_none()
        return cls._cancel_admission_from_row(row) if row is not None else None

    @classmethod
    def _load_cancel_receipt(
        cls,
        connection,
        tenant_id: str,
        run_id: UUID,
        admission: GISAnalysisCancelAdmission | None,
    ):
        if admission is None:
            return None
        row = connection.execute(
            text(
                """
                SELECT tenant_id, run_id, cancel_command_id,
                       cancel_observation_id, outcome,
                       backend_binding_fingerprint, observed_at, recorded_by
                FROM gda_control.gis_analysis_cancel_receipt
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).mappings().one_or_none()
        return (
            cls._cancel_receipt_from_row(row, admission.backend)
            if row is not None
            else None
        )

    @classmethod
    def _load_reconciliations(cls, connection, tenant_id: str, run_id: UUID):
        rows = connection.execute(
            text(
                """
                SELECT tenant_id, reconciliation_observation_id, run_id,
                       reconcile_command_id, reconcile_attempt_no,
                       cancel_command_id, cancel_observation_id, outcome,
                       backend_binding_fingerprint, observed_at, recorded_by
                FROM gda_control.gis_analysis_reconciliation_observation
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                ORDER BY reconcile_attempt_no, reconciliation_observation_id
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).mappings().all()
        return tuple(cls._reconciliation_from_row(row) for row in rows)

    def admit(
        self,
        plan: GISAnalysisPlan,
        subject_context: SubjectContext,
        client_request_id: str,
        *,
        admitted_at: datetime | None = None,
    ) -> GISAnalysisRunRecord:
        request_id = TypeAdapter(ClientRequestId).validate_python(client_request_id)
        if plan.tenant_id != subject_context.tenant_id:
            raise GISAnalysisExecutionValidationError(
                "GIS plan and subject tenant must match"
            )
        if plan.security_context_fingerprint != canonical_json_fingerprint(
            subject_context.model_dump(mode="json")
        ):
            raise GISAnalysisExecutionValidationError(
                "GIS plan does not bind this subject context"
            )
        at = admitted_at or datetime.now(UTC)
        if at.tzinfo is None or at.utcoffset() is None:
            raise GISAnalysisExecutionValidationError(
                "GIS admission time must be timezone-aware"
            )
        at = at.astimezone(UTC)
        registration = self._ensure_definition(subject_context.tenant_id)
        run_id = uuid5(_RUN_NAMESPACE, f"{subject_context.tenant_id}:{request_id}")
        plan_artifact_id = uuid5(run_id, "gis-analysis-plan")
        actor = f"{subject_context.subject_type.value}:{subject_context.subject_id}"
        with self._transaction(subject_context.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.admit_gis_analysis_execution(
                        :tenant_id, :run_id, :client_request_id,
                        :definition_version_id, CAST(:subject_context AS jsonb),
                        :idempotency_key, :cache_key, :plan_artifact_id,
                        CAST(:plan_document AS jsonb), :admitted_by, :admitted_at,
                        :provider_subject
                    )
                    """
                ),
                {
                    "tenant_id": subject_context.tenant_id,
                    "run_id": run_id,
                    "client_request_id": request_id,
                    "definition_version_id": registration.definition.definition_version_id,
                    "subject_context": _json(subject_context.model_dump(mode="json")),
                    "idempotency_key": f"gis-analysis:v1:{request_id}",
                    "cache_key": plan.cache_key,
                    "plan_artifact_id": plan_artifact_id,
                    "plan_document": _json(plan.model_dump(mode="json")),
                    "admitted_by": actor,
                    "admitted_at": at,
                    "provider_subject": GIS_POSTGIS_WORKLOAD,
                },
            ).scalar_one()
        return self.get(subject_context.tenant_id, run_id)

    def get(self, tenant_id: str, run_id: UUID) -> GISAnalysisRunRecord:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            admission = self._load_admission(connection, tenant, run_id)
            observation = self._load_observation(connection, tenant, run_id)
            cancel_admission = self._load_cancel_admission(connection, tenant, run_id)
            cancel_receipt = self._load_cancel_receipt(
                connection, tenant, run_id, cancel_admission
            )
            reconciliations = self._load_reconciliations(
                connection, tenant, run_id
            )
        if admission is None:
            raise GISAnalysisExecutionNotFoundError(
                "GIS analysis execution was not found"
            )
        gateway = PlatformGateway(self._get_engine())
        try:
            run = gateway.get_run(tenant, run_id)
            artifact = gateway.get_artifact(tenant, admission.plan_artifact_id)
        except GatewayNotFoundError as exc:
            raise GISAnalysisExecutionNotFoundError(str(exc)) from exc
        except GatewayForbiddenError as exc:
            raise GISAnalysisExecutionForbiddenError(str(exc)) from exc
        except (GatewayConfigurationError, GatewayUnavailableError) as exc:
            raise GISAnalysisExecutionConfigurationError(str(exc)) from exc
        return GISAnalysisRunRecord(
            admission=admission,
            run=run,
            plan_artifact=artifact,
            observation=observation,
            cancel_admission=cancel_admission,
            cancel_receipt=cancel_receipt,
            reconciliation_observations=reconciliations,
        )

    def start(
        self,
        tenant_id: str,
        run_id: UUID,
        spec: GISAnalysisProviderStartSpec,
        *,
        actor_subject: str,
        expected_state_version: int = 0,
    ) -> GISAnalysisRunRecord:
        observation_id = uuid5(
            run_id,
            f"gis-analysis-start:{spec.attempt_no}:{spec.external_namespace}:{spec.external_run_id}",
        )
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.start_gis_analysis_execution(
                        :tenant_id, :run_id, :expected_state_version,
                        :observation_id, :attempt_no, :external_namespace,
                        :external_run_id, :external_attempt_id,
                        :backend_pid, :backend_start, :database_oid, :user_oid,
                        :application_name, :backend_binding_fingerprint,
                        :actor_subject, :observed_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "expected_state_version": expected_state_version,
                    "observation_id": observation_id,
                    "attempt_no": spec.attempt_no,
                    "external_namespace": spec.external_namespace,
                    "external_run_id": spec.external_run_id,
                    "external_attempt_id": spec.external_attempt_id,
                    "backend_pid": spec.backend.backend_pid,
                    "backend_start": spec.backend.backend_start,
                    "database_oid": spec.backend.database_oid,
                    "user_oid": spec.backend.user_oid,
                    "application_name": spec.backend.application_name,
                    "backend_binding_fingerprint": spec.backend.binding_fingerprint,
                    "actor_subject": actor_subject,
                    "observed_at": spec.observed_at,
                },
            ).scalar_one()
        return self.get(tenant_id, run_id)

    def complete(
        self,
        tenant_id: str,
        run_id: UUID,
        spec: GISAnalysisCompletionSpec,
        *,
        actor_subject: str,
        expected_state_version: int = 2,
    ) -> GISAnalysisRunRecord:
        identity = spec.result_sha256 or f"{spec.error_code}:{spec.error_message}"
        observation_id = uuid5(
            run_id, f"gis-analysis-observation:{spec.attempt_no}:{identity}"
        )
        terminal_id = uuid5(
            run_id, f"gis-analysis-terminal:{spec.attempt_no}:{identity}"
        )
        artifact_id = (
            uuid5(run_id, f"gis-analysis-result:{spec.result_sha256}")
            if spec.result_sha256
            else None
        )
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.complete_gis_analysis_execution(
                        :tenant_id, :run_id, :expected_state_version,
                        :observation_id, :start_observation_id, :terminal_id,
                        :artifact_id, :attempt_no, :outcome, :features_returned,
                        :bytes_scanned, :duration_ms, :result_storage_uri,
                        :result_media_type, :result_sha256, :result_size_bytes,
                        CAST(:result_manifest AS jsonb), :error_code,
                        :error_message, :actor_subject, :observed_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "expected_state_version": expected_state_version,
                    "observation_id": observation_id,
                    "start_observation_id": spec.start_observation_id,
                    "terminal_id": terminal_id,
                    "artifact_id": artifact_id,
                    "attempt_no": spec.attempt_no,
                    "outcome": spec.outcome.value,
                    "features_returned": spec.features_returned,
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

    def cancel_pending(
        self,
        tenant_id: str,
        run_id: UUID,
        *,
        actor_subject: str,
        roles: tuple[str, ...],
        reason: str,
        expected_state_version: int = 0,
    ) -> GISAnalysisRunRecord:
        record = self.get(tenant_id, run_id)
        if actor_subject != record.admission.admitted_by and not set(roles) & {
            "admin",
            "platform_operator",
        }:
            raise GISAnalysisExecutionForbiddenError(
                "GIS cancellation requires the submitter or a platform operator"
            )
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.cancel_pending_gis_analysis_execution(
                        :tenant_id, :run_id, :expected_state_version,
                        :actor_subject, :reason
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "expected_state_version": expected_state_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                },
            ).scalar_one()
        return self.get(tenant_id, run_id)

    def cancel(
        self,
        tenant_id: str,
        run_id: UUID,
        *,
        cancel_request_id: str,
        actor_subject: str,
        roles: tuple[str, ...],
        reason: str,
        expected_state_version: int,
        requested_at: datetime | None = None,
    ) -> GISAnalysisRunRecord:
        request_id = TypeAdapter(ClientRequestId).validate_python(cancel_request_id)
        record = self.get(tenant_id, run_id)
        if actor_subject != record.admission.admitted_by and not set(roles) & {
            "admin",
            "platform_operator",
        }:
            raise GISAnalysisExecutionForbiddenError(
                "GIS cancellation requires the submitter or a platform operator"
            )
        if record.run.status.value == "accepted":
            return self.cancel_pending(
                tenant_id,
                run_id,
                actor_subject=actor_subject,
                roles=roles,
                reason=reason,
                expected_state_version=expected_state_version,
            )
        at = requested_at or datetime.now(UTC)
        if at.tzinfo is None or at.utcoffset() is None:
            raise GISAnalysisExecutionValidationError(
                "GIS cancellation request time must be timezone-aware"
            )
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.admit_running_gis_analysis_cancel(
                        :tenant_id, :run_id, :cancel_request_id,
                        :expected_state_version, :actor_subject, :reason,
                        :requested_at, :canceller_subject
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "cancel_request_id": request_id,
                    "expected_state_version": expected_state_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "requested_at": at.astimezone(UTC),
                    "canceller_subject": GIS_POSTGIS_CANCELLER_WORKLOAD,
                },
            ).scalar_one()
        return self.get(tenant_id, run_id)

    def record_cancel_signal(
        self,
        tenant_id: str,
        run_id: UUID,
        *,
        cancel_command_id: UUID,
        outcome: GISAnalysisCancelOutcome,
        backend_binding_fingerprint: str,
        actor_subject: str,
        observed_at: datetime | None = None,
    ) -> GISAnalysisRunRecord:
        at = observed_at or datetime.now(UTC)
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_gis_analysis_cancel_signal(
                        :tenant_id, :run_id, :cancel_command_id, :outcome,
                        :backend_binding_fingerprint, :actor_subject, :observed_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "cancel_command_id": cancel_command_id,
                    "outcome": outcome.value,
                    "backend_binding_fingerprint": backend_binding_fingerprint,
                    "actor_subject": actor_subject,
                    "observed_at": at,
                },
            ).scalar_one()
        return self.get(tenant_id, run_id)

    def complete_cancelled(
        self,
        tenant_id: str,
        run_id: UUID,
        *,
        start_observation_id: UUID,
        backend_binding_fingerprint: str,
        actor_subject: str,
        observed_at: datetime | None = None,
    ) -> GISAnalysisRunRecord:
        at = observed_at or datetime.now(UTC)
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.complete_cancelled_gis_analysis_execution(
                        :tenant_id, :run_id, :start_observation_id,
                        :backend_binding_fingerprint, :actor_subject, :observed_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "start_observation_id": start_observation_id,
                    "backend_binding_fingerprint": backend_binding_fingerprint,
                    "actor_subject": actor_subject,
                    "observed_at": at,
                },
            ).scalar_one()
        return self.get(tenant_id, run_id)

    def settle_reconciliation(
        self,
        command: PlatformCommand,
        *,
        worker_id: str,
        outcome: GISAnalysisCancelOutcome,
        backend_binding_fingerprint: str,
        retry_delay_seconds: int,
        observed_at: datetime | None = None,
    ) -> PlatformCommand:
        at = observed_at or datetime.now(UTC)
        if at.tzinfo is None or at.utcoffset() is None:
            raise GISAnalysisExecutionValidationError(
                "GIS reconciliation time must be timezone-aware"
            )
        at = at.astimezone(UTC)
        incident_id: UUID | None = None
        incident_dedupe_key: str | None = None
        incident_details: dict[str, Any] | None = None
        incident_sha256: str | None = None
        raw_deadline = command.payload.get("reconciliation_deadline")
        raw_max_attempts = command.payload.get("max_reconciliation_attempts")
        try:
            deadline = datetime.fromisoformat(str(raw_deadline).replace("Z", "+00:00"))
            business_max = int(raw_max_attempts)
        except (TypeError, ValueError) as exc:
            raise GISAnalysisExecutionValidationError(
                "GIS reconciliation command policy is invalid"
            ) from exc
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            raise GISAnalysisExecutionValidationError(
                "GIS reconciliation deadline must be timezone-aware"
            )
        deadline = deadline.astimezone(UTC)
        if command.attempt_count >= business_max or at >= deadline:
            record = self.get(command.tenant_id, command.run_id)
            if record.cancel_admission is None or record.cancel_receipt is None:
                raise GISAnalysisExecutionValidationError(
                    "GIS reconciliation has no cancellation evidence"
                )
            receipt = record.cancel_receipt
            incident_id = gis_analysis_stable_uuid(
                "gis-analysis-reconciliation-incident:"
                f"{command.run_id}:{receipt.cancel_observation_id}"
            )
            incident_dedupe_key = f"gis-reconcile:{receipt.cancel_observation_id}"
            incident_details = {
                "schema": "gda.gis_analysis_reconciliation_timeout.v1",
                "reconcile_command_id": str(command.command_id),
                "reconcile_attempt_count": command.attempt_count,
                "cancel_command_id": str(receipt.cancel_command_id),
                "cancel_observation_id": str(receipt.cancel_observation_id),
                "initial_cancel_outcome": receipt.outcome.value,
                "last_reconciliation_outcome": outcome.value,
                "backend_binding_fingerprint": backend_binding_fingerprint,
                "reconciliation_deadline": deadline.isoformat().replace("+00:00", "Z"),
            }
            incident_sha256 = data_incident_fingerprint(
                tenant_id=command.tenant_id,
                run_id=command.run_id,
                dedupe_key=incident_dedupe_key,
                incident_type="gis_analysis_reconciliation_timeout",
                severity=IncidentSeverity.HIGH,
                summary="GIS analysis cancellation requires human resolution",
                trigger_observation_id=record.cancel_admission.start_observation_id,
                details=incident_details,
                detected_by=GIS_POSTGIS_RECONCILER_WORKLOAD,
                opened_at=at,
            )
        with self._transaction(command.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.settle_gis_analysis_reconciliation(
                        :tenant_id, :run_id, :command_id, :worker_id,
                        :outcome, :backend_binding_fingerprint, :actor_subject,
                        :observed_at, :retry_delay_seconds, :incident_id,
                        :incident_dedupe_key, CAST(:incident_details AS jsonb),
                        :incident_sha256
                    )
                    """
                ),
                {
                    "tenant_id": command.tenant_id,
                    "run_id": command.run_id,
                    "command_id": command.command_id,
                    "worker_id": worker_id,
                    "outcome": outcome.value,
                    "backend_binding_fingerprint": backend_binding_fingerprint,
                    "actor_subject": GIS_POSTGIS_RECONCILER_WORKLOAD,
                    "observed_at": at,
                    "retry_delay_seconds": retry_delay_seconds,
                    "incident_id": incident_id,
                    "incident_dedupe_key": incident_dedupe_key,
                    "incident_details": (
                        _json(incident_details) if incident_details is not None else None
                    ),
                    "incident_sha256": incident_sha256,
                },
            ).mappings().one()
        value = dict(row)
        value["payload"] = _json_value(value["payload"])
        return PlatformCommand.model_validate(value)

    def resolve_reconciliation(
        self,
        tenant_id: str,
        run_id: UUID,
        *,
        incident_id: UUID,
        expected_run_state_version: int,
        expected_incident_state_version: int,
        actor_subject: str,
        roles: tuple[str, ...],
        reason: str,
    ) -> GISAnalysisRunRecord:
        if not set(roles) & {"admin", "platform_operator"}:
            raise GISAnalysisExecutionForbiddenError(
                "GIS reconciliation resolution requires a platform operator"
            )
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.resolve_gis_analysis_reconciliation(
                        :tenant_id, :run_id, :incident_id,
                        :expected_run_state_version,
                        :expected_incident_state_version,
                        :actor_subject, :reason
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "incident_id": incident_id,
                    "expected_run_state_version": expected_run_state_version,
                    "expected_incident_state_version": expected_incident_state_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                },
            ).scalar_one()
        return self.get(tenant_id, run_id)


__all__ = [
    "GIS_POSTGIS_CANCELLER_WORKLOAD",
    "GIS_POSTGIS_RECONCILER_WORKLOAD",
    "GIS_POSTGIS_WORKLOAD",
    "ClientRequestId",
    "GISAnalysisBudget",
    "GISAnalysisCompletionSpec",
    "GISAnalysisBackendBinding",
    "GISAnalysisCancelAdmission",
    "GISAnalysisCancelOutcome",
    "GISAnalysisCancelReceipt",
    "GISAnalysisReconciliationObservation",
    "GISAnalysisExecutionAdmission",
    "GISAnalysisExecutionAuthority",
    "GISAnalysisExecutionConfigurationError",
    "GISAnalysisExecutionConflictError",
    "GISAnalysisExecutionError",
    "GISAnalysisExecutionForbiddenError",
    "GISAnalysisExecutionNotFoundError",
    "GISAnalysisExecutionObservation",
    "GISAnalysisExecutionValidationError",
    "GISAnalysisOperation",
    "GISAnalysisOutcome",
    "GISAnalysisPlan",
    "GISAnalysisPlanner",
    "GISAnalysisProviderStartSpec",
    "GISAnalysisRequest",
    "GISAnalysisRunRecord",
    "GISAnalysisRunAdmissionRequest",
    "GISAnalysisRunCancelRequest",
    "GISAnalysisSource",
    "GISAnalysisStartSpec",
    "gis_analysis_stable_uuid",
    "_definition_registration",
]
