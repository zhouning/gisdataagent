"""Append-only business observations projected from governed metric query runs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from uuid import UUID, uuid5

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
from .platform_contracts import (
    ResourceURNText,
    Sha256,
    TenantId,
    parse_resource_urn,
)

_TENANT_ADAPTER = TypeAdapter(TenantId)
_OBSERVATION_NAMESPACE = UUID("8d31f09d-5a74-4f42-a0e3-2f7dc3c19457")
OBSERVATION_PROJECTOR_SUBJECT = "workload:metric-observation-projector"
_DIMENSION_NAME = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_DECIMAL_TEXT = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_SUBJECT_REF = re.compile(r"^(?:human|workload|service|agent):[^\s]{1,256}$")

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricObservationProjectionSpec(_FrozenContract):
    """Caller-supplied business dimensions for one successful query result."""

    value: Decimal
    dimensions: dict[str, Any] = Field(default_factory=dict)
    window_start: datetime | None = None
    window_end: datetime | None = None
    spatial_ref: ResourceURNText | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _finite_decimal(cls, value: Any) -> Decimal:
        try:
            parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("metric observation value must be a decimal") from exc
        if not parsed.is_finite():
            raise ValueError("metric observation value must be finite")
        return parsed

    @field_validator("dimensions")
    @classmethod
    def _scalar_dimensions(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 100:
            raise ValueError("metric observation dimensions are too large")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if _DIMENSION_NAME.fullmatch(key) is None:
                raise ValueError("metric observation dimension names are invalid")
            if item is not None and not isinstance(item, (bool, int, str)):
                raise ValueError("metric observation dimensions must be scalar JSON values")
            normalized[key] = item
        return dict(sorted(normalized.items()))

    @field_validator("window_start", "window_end")
    @classmethod
    def _utc_window(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric observation window timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("spatial_ref")
    @classmethod
    def _spatial_resource(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if parse_resource_urn(value)["resource_kind"] not in {
            "feature",
            "grid",
            "administrative_unit",
            "catchment",
        }:
            raise ValueError("spatial_ref must identify a governed spatial resource")
        return value

    @model_validator(mode="after")
    def _ordered_window(self) -> MetricObservationProjectionSpec:
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_end < self.window_start
        ):
            raise ValueError("metric observation window_end cannot precede window_start")
        return self


class MetricObservationResultProjection(_FrozenContract):
    """Scalar observation evidence derived from exact metric result bytes."""

    schema_id: Literal["gda.metric_observation_result_projection.v1"] = (
        "gda.metric_observation_result_projection.v1"
    )
    result_sha256: Sha256
    result_row_index: Literal[0] = 0
    result_rows: Literal[1] = 1
    result_columns: tuple[Literal["metric_value"], ...] = ("metric_value",)
    # ``0`` is retained for manifests produced before grouped projection was
    # introduced. New provider manifests always carry the actual row hash.
    result_row_fingerprint: Sha256 = "0" * 64
    projection: MetricObservationProjectionSpec

    @model_validator(mode="after")
    def _scalar_result_shape(self) -> MetricObservationResultProjection:
        if self.result_columns != ("metric_value",):
            raise ValueError(
                "metric observation result projection requires one metric_value column"
            )
        return self


class MetricObservationRowProjection(_FrozenContract):
    """One immutable row of a bounded grouped metric result."""

    result_row_index: int = Field(ge=0, le=1_000_000)
    result_row_fingerprint: Sha256
    projection: MetricObservationProjectionSpec


class MetricObservationBatchProjection(_FrozenContract):
    """Complete grouped-result evidence; rows are committed atomically."""

    schema_id: Literal["gda.metric_observation_batch_projection.v1"] = (
        "gda.metric_observation_batch_projection.v1"
    )
    result_sha256: Sha256
    result_rows: int = Field(ge=1, le=10_000)
    result_columns: tuple[str, ...] = Field(min_length=2, max_length=101)
    projections: tuple[MetricObservationRowProjection, ...] = Field(
        min_length=1, max_length=10_000
    )

    @model_validator(mode="after")
    def _complete_ordered_batch(self) -> MetricObservationBatchProjection:
        if self.result_columns[-1] != "metric_value" or len(
            set(self.result_columns)
        ) != len(self.result_columns):
            raise ValueError("grouped result columns must end with metric_value")
        if self.result_rows != len(self.projections):
            raise ValueError("grouped result row count does not match projections")
        indexes = tuple(item.result_row_index for item in self.projections)
        if indexes != tuple(range(self.result_rows)):
            raise ValueError("grouped observation rows must be contiguous and ordered")
        return self


class MetricObservation(_FrozenContract):
    schema_id: Literal["gda.metric_observation.v1"] = "gda.metric_observation.v1"
    tenant_id: TenantId
    observation_id: UUID
    run_id: UUID
    query_observation_id: UUID
    result_artifact_id: UUID
    result_row_ordinal: int = Field(default=0, ge=0, le=1_000_000)
    result_row_fingerprint: Sha256 = "0" * 64
    metric_version_ref: ResourceURNText
    metric_fingerprint: Sha256
    projection_version_ref: ResourceURNText
    projection_fingerprint: Sha256
    output_resource_version_id: UUID
    value: Decimal
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    dimensions: dict[str, Any] = Field(default_factory=dict)
    window_start: datetime | None = None
    window_end: datetime | None = None
    spatial_ref: ResourceURNText | None = None
    observed_at: datetime
    recorded_by: str = Field(pattern=r"^workload:[^\s]{1,128}$")
    observation_fingerprint: Sha256

    @field_validator("observed_at", "window_start", "window_end")
    @classmethod
    def _utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric observation timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("value", mode="before")
    @classmethod
    def _finite_value(cls, value: Any) -> Decimal:
        try:
            parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("metric observation value must be a decimal") from exc
        if not parsed.is_finite():
            raise ValueError("metric observation value must be finite")
        return parsed

    @field_validator("dimensions")
    @classmethod
    def _dimensions(cls, value: dict[str, Any]) -> dict[str, Any]:
        return MetricObservationProjectionSpec.model_validate(
            {"value": "0", "dimensions": value}
        ).dimensions

    @model_validator(mode="after")
    def _identity_and_fingerprint(self) -> MetricObservation:
        metric_identity = parse_resource_urn(self.metric_version_ref)
        projection_identity = parse_resource_urn(self.projection_version_ref)
        for ref, kind in (
            (self.metric_version_ref, "metric_definition"),
            (self.projection_version_ref, "metric_projection"),
        ):
            if parse_resource_urn(ref)["resource_kind"] != kind or ".v" not in ref:
                raise ValueError("metric observation must bind immutable metric versions")
        if metric_identity["tenant_id"] != self.tenant_id or projection_identity[
            "tenant_id"
        ] != self.tenant_id:
            raise ValueError("metric observation versions must share the observation tenant")
        if self.recorded_by != OBSERVATION_PROJECTOR_SUBJECT:
            raise ValueError("metric observation must use the platform projector identity")
        if self.spatial_ref is not None:
            if parse_resource_urn(self.spatial_ref)["resource_kind"] not in {
                "feature",
                "grid",
                "administrative_unit",
                "catchment",
            }:
                raise ValueError("spatial_ref must identify a governed spatial resource")
        if self.window_start is not None and self.window_end is not None:
            if self.window_end < self.window_start:
                raise ValueError("metric observation window_end cannot precede window_start")
        payload = self._fingerprint_payload()
        if self.observation_fingerprint != metric_observation_fingerprint(payload):
            raise ValueError("observation_fingerprint does not match immutable observation")
        return self

    @staticmethod
    def canonical_value(value: Decimal) -> str:
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        if rendered in {"", "-0"}:
            return "0"
        return rendered

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "tenant_id": self.tenant_id,
            "observation_id": str(self.observation_id),
            "run_id": str(self.run_id),
            "query_observation_id": str(self.query_observation_id),
            "result_artifact_id": str(self.result_artifact_id),
            "metric_version_ref": self.metric_version_ref,
            "metric_fingerprint": self.metric_fingerprint,
            "projection_version_ref": self.projection_version_ref,
            "projection_fingerprint": self.projection_fingerprint,
            "output_resource_version_id": str(self.output_resource_version_id),
            "value": self.canonical_value(self.value),
            "unit": self.unit,
            "dimensions": self.dimensions,
            "window_start": self._timestamp_text(self.window_start),
            "window_end": self._timestamp_text(self.window_end),
            "spatial_ref": self.spatial_ref,
            "observed_at": self._timestamp_text(self.observed_at),
            "recorded_by": self.recorded_by,
        }

    @staticmethod
    def _timestamp_text(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class MetricObservationQuery(_FrozenContract):
    """Bounded filters for consuming immutable metric observations."""

    metric_version_ref: ResourceURNText
    projection_version_ref: ResourceURNText | None = None
    output_resource_version_id: UUID | None = None
    dimensions: dict[str, Any] = Field(default_factory=dict)
    spatial_ref: ResourceURNText | None = None
    observed_after: datetime | None = None
    observed_before: datetime | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10_000)

    @field_validator("metric_version_ref")
    @classmethod
    def _metric_version(cls, value: str) -> str:
        identity = parse_resource_urn(value)
        if identity["resource_kind"] != "metric_definition" or ".v" not in value:
            raise ValueError("metric_version_ref must identify an immutable metric definition")
        return value

    @field_validator("projection_version_ref")
    @classmethod
    def _projection_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        identity = parse_resource_urn(value)
        if identity["resource_kind"] != "metric_projection" or ".v" not in value:
            raise ValueError(
                "projection_version_ref must identify an immutable metric projection"
            )
        return value

    @field_validator("dimensions")
    @classmethod
    def _dimension_subset(cls, value: dict[str, Any]) -> dict[str, Any]:
        return MetricObservationProjectionSpec.model_validate(
            {"value": "0", "dimensions": value}
        ).dimensions

    @field_validator("spatial_ref")
    @classmethod
    def _spatial_resource(cls, value: str | None) -> str | None:
        return MetricObservationProjectionSpec.model_validate(
            {"value": "0", "spatial_ref": value}
        ).spatial_ref

    @field_validator("observed_after", "observed_before")
    @classmethod
    def _utc_observed_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric observation query timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_scope(self) -> MetricObservationQuery:
        metric_tenant = parse_resource_urn(self.metric_version_ref)["tenant_id"]
        if self.projection_version_ref is not None:
            projection_tenant = parse_resource_urn(self.projection_version_ref)["tenant_id"]
            if projection_tenant != metric_tenant:
                raise ValueError("metric and projection query refs must share a tenant")
        if (
            self.observed_after is not None
            and self.observed_before is not None
            and self.observed_before < self.observed_after
        ):
            raise ValueError("observed_before cannot precede observed_after")
        return self


class MetricObservationPage(_FrozenContract):
    schema_id: Literal["gda.metric_observation_page.v1"] = (
        "gda.metric_observation_page.v1"
    )
    items: tuple[MetricObservation, ...]
    count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool

    @model_validator(mode="after")
    def _count_matches_items(self) -> MetricObservationPage:
        if self.count != len(self.items):
            raise ValueError("metric observation page count must match its items")
        return self


class MetricObservationError(RuntimeError):
    code = "metric_observation_error"


class MetricObservationConflictError(MetricObservationError):
    code = "metric_observation_conflict"


class MetricObservationNotFoundError(MetricObservationError):
    code = "metric_observation_not_found"


class MetricObservationForbiddenError(MetricObservationError):
    code = "metric_observation_forbidden"


class MetricObservationNotReadyError(MetricObservationError):
    code = "metric_observation_not_ready"


class MetricObservationValidationError(MetricObservationError):
    code = "metric_observation_validation_error"


class MetricObservationConfigurationError(MetricObservationError):
    code = "metric_observation_unavailable"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _postgres_jsonb_text(value: Any) -> str:
    """Render the scalar/object subset exactly like PostgreSQL jsonb::text."""
    if isinstance(value, dict):
        items = sorted(
            value.items(),
            key=lambda item: (len(item[0].encode("utf-8")), item[0].encode("utf-8")),
        )
        body = ", ".join(
            f"{json.dumps(key, ensure_ascii=False)}: {_postgres_jsonb_text(item)}"
            for key, item in items
        )
        return f"{{{body}}}"
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError("metric observation fingerprint only accepts JSON scalar objects")


def metric_observation_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_postgres_jsonb_text(payload).encode("utf-8")).hexdigest()


def metric_observation_row_fingerprint(row: dict[str, Any]) -> str:
    """Fingerprint one row in the canonical metric-result JSON encoding."""
    return hashlib.sha256(_json(row).encode("utf-8")).hexdigest()


def metric_observation_id(
    run_id: UUID,
    *,
    result_row_ordinal: int = 0,
    result_row_fingerprint: str | None = None,
) -> UUID:
    """Return the legacy scalar ID or the stable grouped-row identity."""
    if result_row_fingerprint is None:
        if result_row_ordinal != 0:
            raise ValueError("scalar metric observation row ordinal must be zero")
        return uuid5(run_id, "metric-observation:v1")
    if result_row_ordinal < 0 or re.fullmatch(r"[0-9a-f]{64}", result_row_fingerprint) is None:
        raise ValueError("grouped metric observation row identity is invalid")
    return uuid5(
        run_id,
        f"metric-observation:v2:{result_row_ordinal}:{result_row_fingerprint}",
    )


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class MetricObservationAuthority:
    """PostgreSQL authority for append-only metric observations."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise MetricObservationConfigurationError(
                "metric observation authority requires PostgreSQL"
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
                        raise MetricObservationConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except MetricObservationError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise MetricObservationConflictError(
                    "metric observation evidence conflicts with an existing projection"
                ) from exc
            if state == "P0002":
                raise MetricObservationNotFoundError("metric query run was not found") from exc
            if state == "55000":
                raise MetricObservationNotReadyError(
                    "metric query run does not have successful result evidence"
                ) from exc
            if state == "42501":
                raise MetricObservationForbiddenError(
                    "metric observation tenant access was denied"
                ) from exc
            if state in {"22023", "22P02", "23503", "23514"}:
                raise MetricObservationValidationError(
                    "metric observation contract was rejected"
                ) from exc
            raise MetricObservationError("metric observation database operation failed") from exc
        except SQLAlchemyError as exc:
            raise MetricObservationError("metric observation database operation failed") from exc

    @staticmethod
    def _from_row(row: Any) -> MetricObservation:
        value = dict(row)
        value["dimensions"] = _json_value(value["dimensions"])
        value["value"] = Decimal(value.pop("value_canonical"))
        return MetricObservation.model_validate(value)

    @classmethod
    def _load(cls, connection: Any, tenant_id: str, run_id: UUID) -> MetricObservation | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, observation_id, run_id, query_observation_id,
                           result_artifact_id, result_row_ordinal,
                           result_row_fingerprint, metric_version_ref, metric_fingerprint,
                           projection_version_ref, projection_fingerprint,
                           output_resource_version_id, value_canonical, unit,
                           dimensions, window_start, window_end, spatial_ref,
                           observed_at, recorded_by, observation_fingerprint
                    FROM gda_control.metric_observation
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                      AND result_row_ordinal = 0
                    """
                ),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._from_row(row) if row is not None else None

    @classmethod
    def _load_all(
        cls, connection: Any, tenant_id: str, run_id: UUID
    ) -> tuple[MetricObservation, ...]:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, observation_id, run_id, query_observation_id,
                           result_artifact_id, result_row_ordinal,
                           result_row_fingerprint, metric_version_ref,
                           metric_fingerprint, projection_version_ref,
                           projection_fingerprint, output_resource_version_id,
                           value_canonical, unit, dimensions, window_start,
                           window_end, spatial_ref, observed_at, recorded_by,
                           observation_fingerprint
                    FROM gda_control.metric_observation
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    ORDER BY result_row_ordinal
                    """
                ),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
            .mappings()
            .all()
        )
        return tuple(cls._from_row(row) for row in rows)

    @classmethod
    def _load_by_id(
        cls, connection: Any, tenant_id: str, observation_id: UUID
    ) -> MetricObservation | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, observation_id, run_id, query_observation_id,
                           result_artifact_id, result_row_ordinal,
                           result_row_fingerprint, metric_version_ref, metric_fingerprint,
                           projection_version_ref, projection_fingerprint,
                           output_resource_version_id, value_canonical, unit,
                           dimensions, window_start, window_end, spatial_ref,
                           observed_at, recorded_by, observation_fingerprint
                    FROM gda_control.metric_observation
                    WHERE tenant_id = :tenant_id AND observation_id = :observation_id
                    """
                ),
                {"tenant_id": tenant_id, "observation_id": observation_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._from_row(row) if row is not None else None

    def project(
        self,
        tenant_id: str,
        run_id: UUID,
        spec: MetricObservationProjectionSpec,
        *,
        actor_subject: str,
        role: str,
    ) -> MetricObservation:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            source = connection.execute(
                text(
                    """
                    SELECT a.admitted_by, a.metric_version_ref, a.metric_fingerprint,
                           a.projection_version_ref, a.projection_fingerprint,
                           a.output_resource_version_id, a.run_id,
                           q.query_observation_id, q.result_artifact_id,
                           q.outcome, q.result_sha256, q.observed_at,
                           m.definition_document->>'unit' AS unit
                    FROM gda_control.metric_query_execution_admission AS a
                    JOIN gda_control.metric_query_execution_observation AS q
                      ON q.tenant_id = a.tenant_id AND q.run_id = a.run_id
                    JOIN gda_control.platform_run AS r
                      ON r.tenant_id = a.tenant_id AND r.run_id = a.run_id
                    JOIN gda_control.metric_definition_version AS m
                      ON m.tenant_id = a.tenant_id
                     AND m.metric_version_ref = a.metric_version_ref
                     AND m.definition_fingerprint = a.metric_fingerprint
                    WHERE a.tenant_id = :tenant_id AND a.run_id = :run_id
                    """
                ),
                {"tenant_id": tenant, "run_id": run_id},
            ).mappings().one_or_none()
            if source is None:
                raise MetricObservationNotFoundError("metric query run was not found")
            if source["admitted_by"] != actor_subject and role not in {
                "admin",
                "platform_operator",
            }:
                raise MetricObservationForbiddenError(
                    "metric observation projection requires the run submitter or an operator"
                )
            if source["outcome"] != "succeeded":
                raise MetricObservationNotReadyError(
                    "metric query run does not have successful result evidence"
                )
            if source["result_artifact_id"] is None or source["result_sha256"] is None:
                raise MetricObservationNotReadyError(
                    "metric query run does not have a result Artifact"
                )
            if not source["unit"]:
                raise MetricObservationValidationError(
                    "metric definition does not provide an observation unit"
                )
            observation_id = metric_observation_id(run_id)
            stored = self._load(connection, tenant, run_id)
            candidate = MetricObservation.model_construct(
                tenant_id=tenant,
                observation_id=observation_id,
                run_id=run_id,
                query_observation_id=source["query_observation_id"],
                result_artifact_id=source["result_artifact_id"],
                metric_version_ref=source["metric_version_ref"],
                metric_fingerprint=source["metric_fingerprint"],
                projection_version_ref=source["projection_version_ref"],
                projection_fingerprint=source["projection_fingerprint"],
                output_resource_version_id=source["output_resource_version_id"],
                value=spec.value,
                unit=source["unit"],
                dimensions=spec.dimensions,
                window_start=spec.window_start,
                window_end=spec.window_end,
                spatial_ref=spec.spatial_ref,
                observed_at=source["observed_at"],
                recorded_by=OBSERVATION_PROJECTOR_SUBJECT,
                observation_fingerprint="0" * 64,
            )
            candidate = candidate.model_copy(
                update={
                    "observation_fingerprint": metric_observation_fingerprint(
                        candidate._fingerprint_payload()
                    )
                }
            )
            if stored is not None:
                if stored != candidate:
                    raise MetricObservationConflictError(
                        "metric query run already has a different observation projection"
                    )
                return stored
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_metric_observation(
                        :tenant_id, :run_id, :observation_id, :value_canonical,
                        CAST(:dimensions AS jsonb), :window_start, :window_end,
                        :spatial_ref, :recorded_by
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "run_id": run_id,
                    "observation_id": observation_id,
                    "value_canonical": candidate.canonical_value(candidate.value),
                    "dimensions": _json(candidate.dimensions),
                    "window_start": candidate.window_start,
                    "window_end": candidate.window_end,
                    "spatial_ref": candidate.spatial_ref,
                    "recorded_by": candidate.recorded_by,
                },
            ).scalar_one()
            stored = self._load(connection, tenant, run_id)
            if stored is None:
                raise MetricObservationNotFoundError(
                    "metric observation was not visible after projection"
                )
            if stored != candidate:
                raise MetricObservationConflictError(
                    "metric observation evidence changed during projection"
                )
            return stored

    def get(self, tenant_id: str, observation_id: UUID) -> MetricObservation:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            observation = self._load_by_id(connection, tenant, observation_id)
        if observation is None:
            raise MetricObservationNotFoundError("metric observation was not found")
        return observation

    def project_batch(
        self,
        tenant_id: str,
        run_id: UUID,
        batch: MetricObservationBatchProjection,
        *,
        actor_subject: str,
        role: str,
    ) -> tuple[MetricObservation, ...]:
        """Project a complete grouped result in one database transaction."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            source = connection.execute(
                text(
                    """
                    SELECT a.admitted_by, a.metric_version_ref, a.metric_fingerprint,
                           a.projection_version_ref, a.projection_fingerprint,
                           a.output_resource_version_id, q.query_observation_id,
                           q.result_artifact_id, q.outcome, q.result_sha256,
                           q.observed_at, m.definition_document->>'unit' AS unit
                    FROM gda_control.metric_query_execution_admission AS a
                    JOIN gda_control.metric_query_execution_observation AS q
                      ON q.tenant_id = a.tenant_id AND q.run_id = a.run_id
                    JOIN gda_control.metric_definition_version AS m
                      ON m.tenant_id = a.tenant_id
                     AND m.metric_version_ref = a.metric_version_ref
                     AND m.definition_fingerprint = a.metric_fingerprint
                    WHERE a.tenant_id = :tenant_id AND a.run_id = :run_id
                    """
                ),
                {"tenant_id": tenant, "run_id": run_id},
            ).mappings().one_or_none()
            if source is None:
                raise MetricObservationNotFoundError("metric query run was not found")
            if source["admitted_by"] != actor_subject and role not in {
                "admin",
                "platform_operator",
            }:
                raise MetricObservationForbiddenError(
                    "metric observation projection requires the run submitter or an operator"
                )
            if (
                source["outcome"] != "succeeded"
                or source["result_artifact_id"] is None
                or source["result_sha256"] != batch.result_sha256
            ):
                raise MetricObservationNotReadyError(
                    "grouped metric result is not bound to successful result evidence"
                )
            if not source["unit"]:
                raise MetricObservationValidationError(
                    "metric definition does not provide an observation unit"
                )

            candidates: list[MetricObservation] = []
            rows_payload: list[dict[str, Any]] = []
            for item in batch.projections:
                observation_id = metric_observation_id(
                    run_id,
                    result_row_ordinal=item.result_row_index,
                    result_row_fingerprint=item.result_row_fingerprint,
                )
                spec = item.projection
                candidate = MetricObservation.model_construct(
                    tenant_id=tenant,
                    observation_id=observation_id,
                    run_id=run_id,
                    query_observation_id=source["query_observation_id"],
                    result_artifact_id=source["result_artifact_id"],
                    result_row_ordinal=item.result_row_index,
                    result_row_fingerprint=item.result_row_fingerprint,
                    metric_version_ref=source["metric_version_ref"],
                    metric_fingerprint=source["metric_fingerprint"],
                    projection_version_ref=source["projection_version_ref"],
                    projection_fingerprint=source["projection_fingerprint"],
                    output_resource_version_id=source["output_resource_version_id"],
                    value=spec.value,
                    unit=source["unit"],
                    dimensions=spec.dimensions,
                    window_start=spec.window_start,
                    window_end=spec.window_end,
                    spatial_ref=spec.spatial_ref,
                    observed_at=source["observed_at"],
                    recorded_by=OBSERVATION_PROJECTOR_SUBJECT,
                    observation_fingerprint="0" * 64,
                )
                candidate = candidate.model_copy(
                    update={
                        "observation_fingerprint": metric_observation_fingerprint(
                            candidate._fingerprint_payload()
                        )
                    }
                )
                candidates.append(candidate)
                rows_payload.append(
                    {
                        "observation_id": str(observation_id),
                        "result_row_ordinal": item.result_row_index,
                        "result_row_fingerprint": item.result_row_fingerprint,
                        "value_canonical": candidate.canonical_value(candidate.value),
                        "dimensions": candidate.dimensions,
                        "window_start": MetricObservation._timestamp_text(
                            candidate.window_start
                        ),
                        "window_end": MetricObservation._timestamp_text(
                            candidate.window_end
                        ),
                        "spatial_ref": candidate.spatial_ref,
                    }
                )
            expected = tuple(candidates)
            stored = self._load_all(connection, tenant, run_id)
            if stored:
                if stored != expected:
                    raise MetricObservationConflictError(
                        "metric query run already has a different observation batch"
                    )
                return stored
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_metric_observation_batch(
                        :tenant_id, :run_id, CAST(:rows AS jsonb), :recorded_by
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "run_id": run_id,
                    "rows": _json(rows_payload),
                    "recorded_by": OBSERVATION_PROJECTOR_SUBJECT,
                },
            ).scalar_one()
            stored = self._load_all(connection, tenant, run_id)
            if stored != expected:
                raise MetricObservationConflictError(
                    "metric observation batch changed during projection"
                )
            return stored

    def search(
        self,
        tenant_id: str,
        query: MetricObservationQuery,
        *,
        actor_subject: str,
        role: str,
    ) -> MetricObservationPage:
        """List an actor's observations, or the tenant view for platform operators."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if parse_resource_urn(query.metric_version_ref)["tenant_id"] != tenant:
            raise MetricObservationForbiddenError(
                "metric observation query tenant access was denied"
            )
        if _SUBJECT_REF.fullmatch(actor_subject) is None:
            raise MetricObservationValidationError(
                "metric observation query actor is invalid"
            )

        conditions = [
            "o.tenant_id = :tenant_id",
            "o.metric_version_ref = :metric_version_ref",
        ]
        parameters: dict[str, Any] = {
            "tenant_id": tenant,
            "metric_version_ref": query.metric_version_ref,
            "fetch_limit": query.limit + 1,
            "offset": query.offset,
        }
        if role not in {"admin", "platform_operator"}:
            conditions.append("a.admitted_by = :actor_subject")
            parameters["actor_subject"] = actor_subject
        if query.projection_version_ref is not None:
            conditions.append("o.projection_version_ref = :projection_version_ref")
            parameters["projection_version_ref"] = query.projection_version_ref
        if query.output_resource_version_id is not None:
            conditions.append(
                "o.output_resource_version_id = :output_resource_version_id"
            )
            parameters["output_resource_version_id"] = query.output_resource_version_id
        if query.dimensions:
            conditions.append("o.dimensions @> CAST(:dimensions AS jsonb)")
            parameters["dimensions"] = _json(query.dimensions)
        if query.spatial_ref is not None:
            conditions.append("o.spatial_ref = :spatial_ref")
            parameters["spatial_ref"] = query.spatial_ref
        if query.observed_after is not None:
            conditions.append("o.observed_at >= :observed_after")
            parameters["observed_after"] = query.observed_after
        if query.observed_before is not None:
            conditions.append("o.observed_at <= :observed_before")
            parameters["observed_before"] = query.observed_before

        statement = text(
            f"""
            SELECT o.tenant_id, o.observation_id, o.run_id,
                   o.query_observation_id, o.result_artifact_id,
                   o.result_row_ordinal, o.result_row_fingerprint,
                   o.metric_version_ref, o.metric_fingerprint,
                   o.projection_version_ref, o.projection_fingerprint,
                   o.output_resource_version_id, o.value_canonical, o.unit,
                   o.dimensions, o.window_start, o.window_end, o.spatial_ref,
                   o.observed_at, o.recorded_by, o.observation_fingerprint
            FROM gda_control.metric_observation AS o
            JOIN gda_control.metric_query_execution_admission AS a
              ON a.tenant_id = o.tenant_id AND a.run_id = o.run_id
            WHERE {' AND '.join(conditions)}
            ORDER BY o.observed_at DESC, o.observation_id DESC
            LIMIT :fetch_limit OFFSET :offset
            """
        )
        with self._transaction(tenant) as connection:
            rows = connection.execute(statement, parameters).mappings().all()
        items = tuple(self._from_row(row) for row in rows[: query.limit])
        return MetricObservationPage(
            items=items,
            count=len(items),
            offset=query.offset,
            limit=query.limit,
            has_more=len(rows) > query.limit,
        )


__all__ = [
    "MetricObservation",
    "MetricObservationAuthority",
    "MetricObservationConfigurationError",
    "MetricObservationConflictError",
    "MetricObservationError",
    "MetricObservationForbiddenError",
    "MetricObservationNotFoundError",
    "MetricObservationNotReadyError",
    "MetricObservationPage",
    "MetricObservationProjectionSpec",
    "MetricObservationBatchProjection",
    "MetricObservationRowProjection",
    "MetricObservationQuery",
    "MetricObservationResultProjection",
    "MetricObservationValidationError",
    "OBSERVATION_PROJECTOR_SUBJECT",
    "metric_observation_fingerprint",
    "metric_observation_id",
    "metric_observation_row_fingerprint",
]
