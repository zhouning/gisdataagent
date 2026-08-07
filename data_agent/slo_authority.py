"""Versioned, ApprovalCase-gated service-level objective authority."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

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
from .platform_contracts import ResourceURNText, Sha256, TenantId, parse_resource_urn

GATEWAY_DATABASE_ROLE = "gda_control_gateway"
SLO_ACTIVATION_ACTION = "slo_definition.activate"
_TENANT_ADAPTER = TypeAdapter(TenantId)
_METRIC_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_LABEL_VALUE_RE = re.compile(r"^[a-zA-Z0-9._:-]{1,128}$")
_OUTCOME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,63}$")

SLOName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
    ),
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SLOBurnSeverity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


class SLOEventRatioIndicator(_FrozenContract):
    kind: Literal["event_success_ratio"] = "event_success_ratio"
    metric_name: str
    good_outcomes: tuple[str, ...]
    bad_outcomes: tuple[str, ...]
    match_labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("metric_name")
    @classmethod
    def _valid_metric(cls, value: str) -> str:
        if _METRIC_RE.fullmatch(value) is None:
            raise ValueError("SLO indicator metric name is invalid")
        return value

    @field_validator("good_outcomes", "bad_outcomes")
    @classmethod
    def _valid_outcomes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or tuple(sorted(set(values))) != values:
            raise ValueError("SLO outcomes must be non-empty, unique and sorted")
        if any(_OUTCOME_RE.fullmatch(value) is None for value in values):
            raise ValueError("SLO outcome is invalid")
        return values

    @field_validator("match_labels")
    @classmethod
    def _valid_labels(cls, values: dict[str, str]) -> dict[str, str]:
        if "outcome" in values:
            raise ValueError("SLO match_labels cannot override outcome")
        if any(
            _LABEL_RE.fullmatch(name) is None
            or _LABEL_VALUE_RE.fullmatch(value) is None
            for name, value in values.items()
        ):
            raise ValueError("SLO match label is invalid")
        return dict(sorted(values.items()))

    @model_validator(mode="after")
    def _disjoint_outcomes(self) -> SLOEventRatioIndicator:
        if set(self.good_outcomes) & set(self.bad_outcomes):
            raise ValueError("SLO good and bad outcomes must be disjoint")
        return self


class SLOBurnRateWindow(_FrozenContract):
    name: SLOName
    short_window_seconds: Annotated[int, Field(ge=300)]
    long_window_seconds: Annotated[int, Field(ge=600)]
    burn_rate_milli: Annotated[int, Field(gt=0, le=1_000_000)]
    minimum_events: Annotated[int, Field(ge=1, le=1_000_000_000)]
    for_seconds: Annotated[int, Field(ge=0, le=86400)] = 0
    severity: SLOBurnSeverity

    @model_validator(mode="after")
    def _ordered_windows(self) -> SLOBurnRateWindow:
        if self.long_window_seconds <= self.short_window_seconds:
            raise ValueError("SLO burn-rate long window must exceed short window")
        return self


class SLODefinitionDraft(_FrozenContract):
    schema_id: Literal["gda.slo_definition_version.v1"] = (
        "gda.slo_definition_version.v1"
    )
    tenant_id: TenantId
    slo_definition_ref: ResourceURNText
    slo_version_ref: ResourceURNText
    version: Annotated[int, Field(ge=1, le=1_000_000)]
    service_resource_urn: ResourceURNText
    indicator: SLOEventRatioIndicator
    objective_basis_points: Annotated[int, Field(ge=1, le=9999)]
    objective_window_seconds: Annotated[
        int, Field(ge=3600, le=366 * 24 * 60 * 60)
    ]
    owner_subject: str
    oncall_ref: str
    burn_rate_windows: tuple[SLOBurnRateWindow, ...]
    created_by: str
    creation_reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
    ]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("SLO created_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("owner_subject")
    @classmethod
    def _valid_owner(cls, value: str) -> str:
        if re.fullmatch(r"^(human|team):[^\s]{1,128}$", value) is None:
            raise ValueError("SLO owner must be a human or team subject")
        return value

    @field_validator("oncall_ref")
    @classmethod
    def _valid_oncall(cls, value: str) -> str:
        if re.fullmatch(r"^oncall:[a-z0-9][a-z0-9._-]{0,127}$", value) is None:
            raise ValueError("SLO on-call reference is invalid")
        return value

    @field_validator("created_by")
    @classmethod
    def _valid_creator(cls, value: str) -> str:
        if re.fullmatch(r"^(human|workload|agent):[^\s]{1,128}$", value) is None:
            raise ValueError("SLO creator must use a typed subject")
        return value

    @model_validator(mode="after")
    def _consistent_identity_and_windows(self) -> SLODefinitionDraft:
        base = parse_resource_urn(self.slo_definition_ref)
        version = parse_resource_urn(self.slo_version_ref)
        service = parse_resource_urn(self.service_resource_urn)
        if base["tenant_id"] != self.tenant_id:
            raise ValueError("SLO definition tenant must match tenant_id")
        if version["tenant_id"] != self.tenant_id:
            raise ValueError("SLO version tenant must match tenant_id")
        if service["tenant_id"] != self.tenant_id:
            raise ValueError("SLO service tenant must match tenant_id")
        if base["resource_kind"] != "slo_definition":
            raise ValueError("SLO definition must use resource kind 'slo_definition'")
        if version["resource_kind"] != "slo_definition":
            raise ValueError("SLO version must use resource kind 'slo_definition'")
        if self.slo_version_ref != f"{self.slo_definition_ref}.v{self.version}":
            raise ValueError("SLO version reference must bind definition and version")
        if not 1 <= len(self.burn_rate_windows) <= 4:
            raise ValueError("SLO requires between one and four burn-rate windows")
        names = tuple(item.name for item in self.burn_rate_windows)
        if len(set(names)) != len(names):
            raise ValueError("SLO burn-rate window names must be unique")
        if any(
            item.long_window_seconds > self.objective_window_seconds
            for item in self.burn_rate_windows
        ):
            raise ValueError("SLO burn-rate windows cannot exceed objective window")
        return self


class SLODefinitionVersion(SLODefinitionDraft):
    definition_fingerprint: Sha256


class SLODefinitionActivation(_FrozenContract):
    tenant_id: TenantId
    slo_definition_ref: ResourceURNText
    active_version_ref: ResourceURNText
    active_fingerprint: Sha256
    approval_case_ref: ResourceURNText
    activation_version: Annotated[int, Field(ge=1)]
    activated_by: str
    activation_reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
    ]
    activated_at: datetime

    @field_validator("activated_at")
    @classmethod
    def _utc_activated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("SLO activated_at must be timezone-aware")
        return value.astimezone(UTC)


class SLODefinitionEvent(_FrozenContract):
    tenant_id: TenantId
    slo_event_id: UUID
    slo_definition_ref: ResourceURNText
    slo_version_ref: ResourceURNText
    definition_fingerprint: Sha256
    event_type: Literal["staged", "activated"]
    approval_case_ref: ResourceURNText | None = None
    actor_subject: str
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
    ]
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _utc_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("SLO event time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _approval_only_for_activation(self) -> SLODefinitionEvent:
        if (self.event_type == "activated") != (self.approval_case_ref is not None):
            raise ValueError("only an SLO activation event binds an ApprovalCase")
        return self


class SLOAuthorityError(RuntimeError):
    code = "slo_authority_error"


class SLOConflictError(SLOAuthorityError):
    code = "slo_conflict"


class SLONotFoundError(SLOAuthorityError):
    code = "slo_not_found"


class SLOForbiddenError(SLOAuthorityError):
    code = "slo_forbidden"


class SLOValidationError(SLOAuthorityError):
    code = "slo_validation_error"


class SLOConfigurationError(SLOAuthorityError):
    code = "slo_authority_unavailable"


class SLOCompilationError(ValueError):
    """An SLO cannot be compiled because no exact active authority exists."""


@dataclass(frozen=True)
class SLODefinitionVersionPage:
    items: tuple[SLODefinitionVersion, ...]
    offset: int
    limit: int
    has_more: bool


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class SLODefinitionAuthority:
    """PostgreSQL authority for immutable definitions and approved activation."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise SLOConfigurationError("SLO authority requires PostgreSQL")
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
                        raise SLOConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except SLOAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise SLOConflictError("SLO authority state conflict") from exc
            if state == "P0002":
                raise SLONotFoundError("SLO definition was not found") from exc
            if state == "42501":
                raise SLOForbiddenError("SLO tenant access was denied") from exc
            if state in {"22023", "22P02", "23502", "23503", "23514", "55000"}:
                raise SLOValidationError("SLO authority contract was rejected") from exc
            raise SLOAuthorityError("SLO database operation failed") from exc
        except SQLAlchemyError as exc:
            raise SLOAuthorityError("SLO database operation failed") from exc

    @staticmethod
    def _definition_from_row(row: Any) -> SLODefinitionVersion:
        value = dict(row)
        value["indicator"] = _json_value(value.pop("indicator_config"))
        value["burn_rate_windows"] = _json_value(value.pop("burn_rate_policy"))
        return SLODefinitionVersion.model_validate(value)

    @staticmethod
    def _activation_from_row(row: Any) -> SLODefinitionActivation:
        return SLODefinitionActivation.model_validate(dict(row))

    @staticmethod
    def _event_from_row(row: Any) -> SLODefinitionEvent:
        value = dict(row)
        value["details"] = _json_value(value["details"])
        return SLODefinitionEvent.model_validate(value)

    @classmethod
    def _load_definition(
        cls,
        connection: Any,
        tenant_id: str,
        slo_version_ref: str,
    ) -> SLODefinitionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, slo_definition_ref, slo_version_ref,
                           definition_version AS version, service_resource_urn,
                           indicator_config, objective_basis_points,
                           objective_window_seconds, owner_subject, oncall_ref,
                           burn_rate_policy, definition_fingerprint,
                           created_by, creation_reason, created_at
                    FROM gda_control.slo_definition_version
                    WHERE tenant_id = :tenant_id
                      AND slo_version_ref = :slo_version_ref
                    """
                ),
                {"tenant_id": tenant_id, "slo_version_ref": slo_version_ref},
            )
            .mappings()
            .one_or_none()
        )
        return cls._definition_from_row(row) if row is not None else None

    def stage(self, draft: SLODefinitionDraft) -> SLODefinitionVersion:
        with self._transaction(draft.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.stage_slo_definition_version(
                        :tenant_id, :slo_definition_ref, :slo_version_ref,
                        :definition_version, :service_resource_urn,
                        CAST(:indicator_config AS jsonb), :objective_basis_points,
                        :objective_window_seconds, :owner_subject, :oncall_ref,
                        CAST(:burn_rate_policy AS jsonb), :created_by,
                        :creation_reason, :created_at
                    )
                    """
                ),
                {
                    "tenant_id": draft.tenant_id,
                    "slo_definition_ref": draft.slo_definition_ref,
                    "slo_version_ref": draft.slo_version_ref,
                    "definition_version": draft.version,
                    "service_resource_urn": draft.service_resource_urn,
                    "indicator_config": _json(draft.indicator.model_dump(mode="json")),
                    "objective_basis_points": draft.objective_basis_points,
                    "objective_window_seconds": draft.objective_window_seconds,
                    "owner_subject": draft.owner_subject,
                    "oncall_ref": draft.oncall_ref,
                    "burn_rate_policy": _json(
                        [item.model_dump(mode="json") for item in draft.burn_rate_windows]
                    ),
                    "created_by": draft.created_by,
                    "creation_reason": draft.creation_reason,
                    "created_at": draft.created_at,
                },
            ).scalar_one()
            stored = self._load_definition(
                connection,
                draft.tenant_id,
                draft.slo_version_ref,
            )
            if stored is None:
                raise SLONotFoundError("staged SLO definition was not visible")
            comparable = stored.model_dump(
                exclude={"definition_fingerprint", "created_at"}
            )
            if comparable != draft.model_dump(exclude={"created_at"}):
                raise SLOConflictError("SLO version identity has different evidence")
            return stored

    def get(self, tenant_id: str, slo_version_ref: str) -> SLODefinitionVersion:
        with self._transaction(tenant_id) as connection:
            stored = self._load_definition(connection, tenant_id, slo_version_ref)
            if stored is None:
                raise SLONotFoundError("SLO definition was not found")
            return stored

    def list_versions(
        self,
        tenant_id: str,
        slo_definition_ref: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> SLODefinitionVersionPage:
        """Return one bounded definition-version page ordered newest first."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        identity = parse_resource_urn(slo_definition_ref)
        if (
            identity["tenant_id"] != tenant
            or identity["resource_kind"] != "slo_definition"
        ):
            raise ValueError("SLO definition identity does not match the tenant")
        if not 1 <= limit <= 100:
            raise ValueError("SLO version query limit must be between 1 and 100")
        if not 0 <= offset <= 10_000:
            raise ValueError("SLO version query offset must be between 0 and 10000")

        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, slo_definition_ref, slo_version_ref,
                               definition_version AS version, service_resource_urn,
                               indicator_config, objective_basis_points,
                               objective_window_seconds, owner_subject, oncall_ref,
                               burn_rate_policy, definition_fingerprint,
                               created_by, creation_reason, created_at
                        FROM gda_control.slo_definition_version
                        WHERE tenant_id = :tenant_id
                          AND slo_definition_ref = :slo_definition_ref
                        ORDER BY definition_version DESC, slo_version_ref DESC
                        LIMIT :row_limit OFFSET :offset
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "slo_definition_ref": slo_definition_ref,
                        "row_limit": limit + 1,
                        "offset": offset,
                    },
                )
                .mappings()
                .all()
            )
        return SLODefinitionVersionPage(
            items=tuple(self._definition_from_row(row) for row in rows[:limit]),
            offset=offset,
            limit=limit,
            has_more=len(rows) > limit,
        )

    def activate(
        self,
        *,
        tenant_id: str,
        slo_version_ref: str,
        definition_fingerprint: str,
        approval_case_ref: str,
        expected_activation_version: int,
        actor_subject: str,
        reason: str,
    ) -> SLODefinitionActivation:
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.activate_slo_definition_version(
                        :tenant_id, :slo_version_ref, :definition_fingerprint,
                        :approval_case_ref, :expected_activation_version,
                        :actor_subject, :reason
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "slo_version_ref": slo_version_ref,
                    "definition_fingerprint": definition_fingerprint,
                    "approval_case_ref": approval_case_ref,
                    "expected_activation_version": expected_activation_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                },
            ).scalar_one()
            definition = self._load_definition(connection, tenant_id, slo_version_ref)
            if definition is None:
                raise SLONotFoundError("activated SLO definition was not visible")
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, slo_definition_ref, active_version_ref,
                               active_fingerprint, approval_case_ref,
                               activation_version, activated_by,
                               activation_reason, activated_at
                        FROM gda_control.slo_definition_activation
                        WHERE tenant_id = :tenant_id
                          AND slo_definition_ref = :slo_definition_ref
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "slo_definition_ref": definition.slo_definition_ref,
                    },
                )
                .mappings()
                .one()
            )
            return self._activation_from_row(row)

    def active(
        self,
        tenant_id: str,
        slo_definition_ref: str,
    ) -> tuple[SLODefinitionVersion, SLODefinitionActivation]:
        with self._transaction(tenant_id) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, slo_definition_ref, active_version_ref,
                               active_fingerprint, approval_case_ref,
                               activation_version, activated_by,
                               activation_reason, activated_at
                        FROM gda_control.slo_definition_activation
                        WHERE tenant_id = :tenant_id
                          AND slo_definition_ref = :slo_definition_ref
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "slo_definition_ref": slo_definition_ref,
                    },
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise SLONotFoundError("active SLO definition was not found")
            activation = self._activation_from_row(row)
            definition = self._load_definition(
                connection,
                tenant_id,
                activation.active_version_ref,
            )
            if definition is None:
                raise SLONotFoundError("active SLO version was not found")
            return definition, activation

    def events(
        self,
        tenant_id: str,
        slo_definition_ref: str,
    ) -> tuple[SLODefinitionEvent, ...]:
        with self._transaction(tenant_id) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, slo_event_id, slo_definition_ref,
                               slo_version_ref, definition_fingerprint,
                               event_type, approval_case_ref, actor_subject,
                               reason, details, occurred_at
                        FROM gda_control.slo_definition_event
                        WHERE tenant_id = :tenant_id
                          AND slo_definition_ref = :slo_definition_ref
                        ORDER BY occurred_at, slo_event_id
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "slo_definition_ref": slo_definition_ref,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(self._event_from_row(row) for row in rows)


def _prometheus_selector(
    indicator: SLOEventRatioIndicator,
    outcomes: tuple[str, ...],
) -> str:
    matchers = [f'{name}="{value}"' for name, value in indicator.match_labels.items()]
    outcome_pattern = "|".join(outcomes)
    matchers.append(f'outcome=~"{outcome_pattern}"')
    return "{" + ",".join(matchers) + "}"


def _decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def compile_slo_prometheus_rules(
    definition: SLODefinitionVersion,
    activation: SLODefinitionActivation | None,
) -> dict[str, Any]:
    """Compile rules only when the exact immutable version is active."""

    if activation is None:
        raise SLOCompilationError("SLO definition is not active")
    if (
        activation.tenant_id != definition.tenant_id
        or activation.slo_definition_ref != definition.slo_definition_ref
        or activation.active_version_ref != definition.slo_version_ref
        or activation.active_fingerprint != definition.definition_fingerprint
    ):
        raise SLOCompilationError("SLO activation does not bind this exact definition")

    slo_id = parse_resource_urn(definition.slo_definition_ref)["resource_id"]
    service_id = parse_resource_urn(definition.service_resource_urn)["resource_id"]
    common_labels = {
        "service": service_id,
        "slo_id": slo_id,
        "slo_version": str(definition.version),
        "slo_fingerprint": definition.definition_fingerprint,
        "owner": definition.owner_subject,
        "oncall": definition.oncall_ref,
    }
    all_outcomes = tuple(
        sorted(definition.indicator.good_outcomes + definition.indicator.bad_outcomes)
    )
    bad_selector = _prometheus_selector(
        definition.indicator,
        definition.indicator.bad_outcomes,
    )
    all_selector = _prometheus_selector(definition.indicator, all_outcomes)
    windows = sorted(
        {
            seconds
            for policy in definition.burn_rate_windows
            for seconds in (policy.short_window_seconds, policy.long_window_seconds)
        }
    )
    rules: list[dict[str, Any]] = []
    for seconds in windows:
        window = f"{seconds}s"
        labels = {**common_labels, "window": window}
        rules.extend(
            [
                {
                    "record": "gda:slo_error_ratio",
                    "expr": (
                        f"(sum(rate({definition.indicator.metric_name}"
                        f"{bad_selector}[{window}])) or vector(0)) / "
                        f"clamp_min((sum(rate({definition.indicator.metric_name}"
                        f"{all_selector}[{window}])) or vector(0)), 1e-9)"
                    ),
                    "labels": labels,
                },
                {
                    "record": "gda:slo_events_total",
                    "expr": (
                        f"sum(increase({definition.indicator.metric_name}"
                        f"{all_selector}[{window}])) or vector(0)"
                    ),
                    "labels": labels,
                },
            ]
        )

    error_budget = Decimal(10_000 - definition.objective_basis_points) / Decimal(
        10_000
    )
    for policy in definition.burn_rate_windows:
        threshold = error_budget * Decimal(policy.burn_rate_milli) / Decimal(1_000)
        short_window = f"{policy.short_window_seconds}s"
        long_window = f"{policy.long_window_seconds}s"
        selector_prefix = (
            f'slo_id="{slo_id}",slo_version="{definition.version}"'
        )
        rules.append(
            {
                "alert": "GDASLOErrorBudgetBurn",
                "expr": (
                    f'gda:slo_error_ratio{{{selector_prefix},window="{short_window}"}} '
                    f"> {_decimal(threshold)} and ignoring(window) "
                    f'gda:slo_error_ratio{{{selector_prefix},window="{long_window}"}} '
                    f"> {_decimal(threshold)} and ignoring(window) "
                    f'gda:slo_events_total{{{selector_prefix},window="{long_window}"}} '
                    f">= {policy.minimum_events}"
                ),
                "for": f"{policy.for_seconds}s",
                "labels": {
                    **common_labels,
                    "burn_window": policy.name,
                    "severity": policy.severity.value,
                },
                "annotations": {
                    "summary": f"SLO error budget is burning for {service_id}",
                    "description": (
                        f"{policy.name} burn-rate windows exceeded the approved "
                        f"{definition.objective_basis_points / 100:.2f}% objective."
                    ),
                    "approval_case_ref": activation.approval_case_ref,
                    "runbook": "slo-error-budget-burn",
                },
            }
        )

    return {
        "groups": [
            {
                "name": f"gis-data-agent-slo-{slo_id}-v{definition.version}",
                "interval": "30s",
                "rules": rules,
            }
        ]
    }
