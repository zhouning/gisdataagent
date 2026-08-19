"""Append-only entity lineage authority for merge, split, and replacement."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, TypeAdapter, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .chongqing_entity_link_baseline import (
    ONTOLOGY_PACKAGE_ID,
    ONTOLOGY_PACKAGE_SHA256,
)
from .db_engine import get_engine
from .platform_contracts import (
    FrozenContract,
    ResourceURNText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE, _sqlstate

ENTITY_LINEAGE_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "164_entity_lineage_authority.sql"
)

_TENANT_ADAPTER = TypeAdapter(TenantId)
_ACTOR_RE = re.compile(r"^(human|workload|agent):[^\s]{1,128}$")
_OWNER_RE = re.compile(r"^(human|team):[^\s]{1,128}$")

IdempotencyKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$",
    ),
]
ReasonText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]


class EntityLineageKind(StrEnum):
    MERGE = "merge"
    SPLIT = "split"
    REPLACEMENT = "replacement"


class LinkPropagationDisposition(StrEnum):
    REDIRECT = "redirect"
    DEDUPLICATE = "deduplicate"
    RETRACT_ONLY = "retract_only"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _tenant_ref(value: str, tenant_id: str, kind: str, field_name: str) -> None:
    parsed = parse_resource_urn(value)
    if parsed["tenant_id"] != tenant_id or parsed["resource_kind"] != kind:
        raise ValueError(
            f"{field_name} must use tenant {tenant_id!r} and kind {kind!r}"
        )


def _bounded_evidence(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > 65_536:
        raise ValueError("lineage evidence exceeds 65536 bytes")
    return dict(sorted(value.items()))


def _typed_subject(value: str, pattern: re.Pattern[str], name: str) -> str:
    value = value.strip()
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{name} must use a typed subject")
    return value


class EntityLinkPropagationDraft(FrozenContract):
    schema_id: Literal["gda.entity-link-propagation-draft.v1"] = (
        "gda.entity-link-propagation-draft.v1"
    )
    source_link_ref: ResourceURNText
    disposition: LinkPropagationDisposition
    target_link_ref: ResourceURNText | None = None
    target_source_entity_ref: ResourceURNText | None = None
    target_target_entity_ref: ResourceURNText | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    reason: ReasonText

    @field_validator("evidence")
    @classmethod
    def _valid_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_evidence(value)

    @model_validator(mode="after")
    def _coherent_disposition(self) -> EntityLinkPropagationDraft:
        has_target = self.target_link_ref is not None
        has_endpoints = (
            self.target_source_entity_ref is not None
            and self.target_target_entity_ref is not None
        )
        partial_endpoints = (
            self.target_source_entity_ref is None
        ) != (self.target_target_entity_ref is None)
        if partial_endpoints:
            raise ValueError("target link endpoints must be provided together")
        if self.disposition is LinkPropagationDisposition.REDIRECT:
            if not has_target or not has_endpoints:
                raise ValueError(
                    "redirect requires target_link_ref and both target endpoints"
                )
        elif self.disposition is LinkPropagationDisposition.DEDUPLICATE:
            if not has_target or has_endpoints:
                raise ValueError(
                    "deduplicate requires target_link_ref and forbids endpoint overrides"
                )
        elif has_target or has_endpoints:
            raise ValueError("retract_only forbids a target link and endpoints")
        return self


class EntitySourceIdentityRedirectDraft(FrozenContract):
    schema_id: Literal["gda.entity-source-identity-redirect-draft.v1"] = (
        "gda.entity-source-identity-redirect-draft.v1"
    )
    source_identity_ref: ResourceURNText
    target_entity_ref: ResourceURNText
    evidence: dict[str, Any] = Field(default_factory=dict)
    reason: ReasonText

    @field_validator("evidence")
    @classmethod
    def _valid_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_evidence(value)


class EntityLineageRequest(FrozenContract):
    schema_id: Literal["gda.entity-lineage-request.v1"] = (
        "gda.entity-lineage-request.v1"
    )
    tenant_id: TenantId
    event_ref: ResourceURNText
    lineage_kind: EntityLineageKind
    effective_at: datetime
    source_entity_refs: tuple[ResourceURNText, ...] = Field(
        min_length=1,
        max_length=100,
    )
    target_entity_refs: tuple[ResourceURNText, ...] = Field(
        min_length=1,
        max_length=100,
    )
    source_version_refs: tuple[ResourceURNText, ...] = Field(
        min_length=1,
        max_length=100,
    )
    link_propagations: tuple[EntityLinkPropagationDraft, ...] = Field(
        default_factory=tuple,
        max_length=5_000,
    )
    source_identity_redirects: tuple[EntitySourceIdentityRedirectDraft, ...] = Field(
        default_factory=tuple,
        max_length=5_000,
    )
    ontology_package_id: Literal[ONTOLOGY_PACKAGE_ID] = ONTOLOGY_PACKAGE_ID
    ontology_package_sha256: Literal[ONTOLOGY_PACKAGE_SHA256] = (
        ONTOLOGY_PACKAGE_SHA256
    )
    ontology_review_status: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    decision_status: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    idempotency_key: IdempotencyKey
    owner_subject: str
    recorded_by: str
    reason: ReasonText

    @field_validator("effective_at")
    @classmethod
    def _valid_effective_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "effective_at")

    @field_validator("owner_subject")
    @classmethod
    def _valid_owner(cls, value: str) -> str:
        return _typed_subject(value, _OWNER_RE, "owner_subject")

    @field_validator("recorded_by")
    @classmethod
    def _valid_recorder(cls, value: str) -> str:
        return _typed_subject(value, _ACTOR_RE, "recorded_by")

    @field_validator("source_entity_refs", "target_entity_refs", "source_version_refs")
    @classmethod
    def _sorted_unique_refs(cls, values: tuple[str, ...], info) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError(f"{info.field_name} must be sorted and unique")
        return values

    @model_validator(mode="after")
    def _coherent_lineage(self) -> EntityLineageRequest:
        _tenant_ref(self.event_ref, self.tenant_id, "entity_lineage", "event_ref")
        for value in self.source_entity_refs:
            _tenant_ref(value, self.tenant_id, "entity", "source_entity_refs")
        for value in self.target_entity_refs:
            _tenant_ref(value, self.tenant_id, "entity", "target_entity_refs")
        for value in self.source_version_refs:
            _tenant_ref(
                value,
                self.tenant_id,
                "resource_version",
                "source_version_refs",
            )
        if set(self.source_entity_refs) & set(self.target_entity_refs):
            raise ValueError("source and target entities must be disjoint")
        cardinality = (
            len(self.source_entity_refs),
            len(self.target_entity_refs),
        )
        if self.lineage_kind is EntityLineageKind.MERGE:
            if cardinality[0] < 2 or cardinality[1] != 1:
                raise ValueError("merge requires N>=2 source entities and one target")
        elif self.lineage_kind is EntityLineageKind.SPLIT:
            if cardinality[0] != 1 or cardinality[1] < 2:
                raise ValueError("split requires one source entity and N>=2 targets")
        elif cardinality != (1, 1):
            raise ValueError("replacement requires one source and one target")

        source_links = tuple(item.source_link_ref for item in self.link_propagations)
        if tuple(sorted(set(source_links))) != source_links:
            raise ValueError(
                "link_propagations must be sorted and unique by source_link_ref"
            )
        source_identities = tuple(
            item.source_identity_ref for item in self.source_identity_redirects
        )
        if tuple(sorted(set(source_identities))) != source_identities:
            raise ValueError(
                "source_identity_redirects must be sorted and unique by source_identity_ref"
            )

        target_set = set(self.target_entity_refs)
        for item in self.link_propagations:
            _tenant_ref(
                item.source_link_ref,
                self.tenant_id,
                "entity_link",
                "source_link_ref",
            )
            if item.target_link_ref is not None:
                _tenant_ref(
                    item.target_link_ref,
                    self.tenant_id,
                    "entity_link",
                    "target_link_ref",
                )
                if item.target_link_ref == item.source_link_ref:
                    raise ValueError("propagated Link must use a new stable identity")
            for field_name, value in (
                ("target_source_entity_ref", item.target_source_entity_ref),
                ("target_target_entity_ref", item.target_target_entity_ref),
            ):
                if value is not None:
                    _tenant_ref(value, self.tenant_id, "entity", field_name)
            if item.disposition is LinkPropagationDisposition.REDIRECT:
                assert item.target_source_entity_ref is not None
                assert item.target_target_entity_ref is not None
                if not (
                    item.target_source_entity_ref in target_set
                    or item.target_target_entity_ref in target_set
                ):
                    raise ValueError(
                        "redirect must use at least one lineage target endpoint"
                    )

        singleton_target = (
            self.target_entity_refs[0]
            if self.lineage_kind is not EntityLineageKind.SPLIT
            else None
        )
        for item in self.source_identity_redirects:
            _tenant_ref(
                item.source_identity_ref,
                self.tenant_id,
                "source_identity",
                "source_identity_ref",
            )
            _tenant_ref(
                item.target_entity_ref,
                self.tenant_id,
                "entity",
                "target_entity_ref",
            )
            if item.target_entity_ref not in target_set:
                raise ValueError(
                    "source identity redirect must select a lineage target entity"
                )
            if singleton_target is not None and item.target_entity_ref != singleton_target:
                raise ValueError(
                    "merge and replacement redirects must use the single target"
                )
        return self

    @property
    def request_sha256(self) -> Sha256:
        return canonical_json_fingerprint(self.model_dump(mode="json"))


class EntityLineageReceipt(FrozenContract):
    schema_id: Literal["gda.entity-lineage-receipt.v1"] = (
        "gda.entity-lineage-receipt.v1"
    )
    tenant_id: TenantId
    event_id: UUID
    event_ref: ResourceURNText
    lineage_kind: EntityLineageKind
    effective_at: datetime
    request_sha256: Sha256
    event_sha256: Sha256
    recorded_at: datetime
    source_count: int = Field(ge=1)
    target_count: int = Field(ge=1)
    retired_source_count: int = Field(ge=1)
    link_retraction_count: int = Field(ge=0)
    link_creation_count: int = Field(ge=0)
    link_deduplication_count: int = Field(ge=0)
    link_retract_only_count: int = Field(ge=0)
    source_identity_redirect_count: int = Field(ge=0)
    idempotency_status: Literal["authority_idempotency_enforced"] = (
        "authority_idempotency_enforced"
    )
    technical_baseline_status: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    decision_status: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )

    @field_validator("effective_at", "recorded_at")
    @classmethod
    def _valid_time(cls, value: datetime, info) -> datetime:
        return _aware_utc(value, info.field_name)


class EntitySourceIdentityResolution(FrozenContract):
    schema_id: Literal["gda.entity-source-identity-resolution.v1"] = (
        "gda.entity-source-identity-resolution.v1"
    )
    tenant_id: TenantId
    source_identity_ref: ResourceURNText
    original_entity_ref: ResourceURNText
    resolved_entity_ref: ResourceURNText
    lineage_event_ref: ResourceURNText | None = None
    resolved_valid_from: datetime | None = None

    @field_validator("resolved_valid_from")
    @classmethod
    def _valid_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_utc(value, "resolved_valid_from")

    @model_validator(mode="after")
    def _consistent_resolution(self) -> EntitySourceIdentityResolution:
        _tenant_ref(
            self.source_identity_ref,
            self.tenant_id,
            "source_identity",
            "source_identity_ref",
        )
        _tenant_ref(
            self.original_entity_ref,
            self.tenant_id,
            "entity",
            "original_entity_ref",
        )
        _tenant_ref(
            self.resolved_entity_ref,
            self.tenant_id,
            "entity",
            "resolved_entity_ref",
        )
        if self.lineage_event_ref is not None:
            _tenant_ref(
                self.lineage_event_ref,
                self.tenant_id,
                "entity_lineage",
                "lineage_event_ref",
            )
        if (self.lineage_event_ref is None) != (self.resolved_valid_from is None):
            raise ValueError("lineage event and resolved valid time must appear together")
        return self


class EntityLineageAuthorityError(RuntimeError):
    code = "entity_lineage_authority_error"


class EntityLineageConfigurationError(EntityLineageAuthorityError):
    code = "entity_lineage_configuration_error"


class EntityLineageConflictError(EntityLineageAuthorityError):
    code = "entity_lineage_conflict"


class EntityLineageForbiddenError(EntityLineageAuthorityError):
    code = "entity_lineage_forbidden"


class EntityLineageNotFoundError(EntityLineageAuthorityError):
    code = "entity_lineage_not_found"


class EntityLineageValidationError(EntityLineageAuthorityError):
    code = "entity_lineage_validation_error"


class EntityLineageAuthority:
    """PostgreSQL authority for one atomic entity lineage event."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise EntityLineageConfigurationError(
                "entity lineage authority requires PostgreSQL"
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
                        raise EntityLineageConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except EntityLineageAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise EntityLineageConflictError(
                    "entity lineage state conflict"
                ) from exc
            if state == "42501":
                raise EntityLineageForbiddenError(
                    "entity lineage tenant or role was denied"
                ) from exc
            if state == "P0002":
                raise EntityLineageNotFoundError(
                    "entity lineage input was not found"
                ) from exc
            if state in {"22023", "23514"}:
                raise EntityLineageValidationError(
                    "entity lineage request was rejected"
                ) from exc
            raise EntityLineageConfigurationError(
                "entity lineage authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise EntityLineageConfigurationError(
                "entity lineage authority operation failed"
            ) from exc

    def record(self, request: EntityLineageRequest) -> EntityLineageReceipt:
        with self._transaction(request.tenant_id) as connection:
            value = connection.execute(
                text(
                    """
                    SELECT gda_control.record_entity_lineage_event(
                        :tenant_id, CAST(:request AS jsonb)
                    ) AS receipt
                    """
                ),
                {
                    "tenant_id": request.tenant_id,
                    "request": json.dumps(
                        request.model_dump(mode="json"),
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ).scalar_one()
        payload = json.loads(value) if isinstance(value, str) else dict(value)
        payload["request_sha256"] = request.request_sha256
        return EntityLineageReceipt.model_validate(payload)

    def resolve_source_identity(
        self,
        tenant_id: str,
        source_identity_ref: str,
        *,
        valid_at: datetime,
    ) -> EntitySourceIdentityResolution:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        _tenant_ref(
            source_identity_ref,
            tenant,
            "source_identity",
            "source_identity_ref",
        )
        resolved_at = _aware_utc(valid_at, "valid_at")
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.resolve_entity_source_identity(
                        :tenant_id, :source_identity_ref, :valid_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "source_identity_ref": source_identity_ref,
                    "valid_at": resolved_at,
                },
            ).mappings().one()
        return EntitySourceIdentityResolution.model_validate(
            {
                "schema_id": "gda.entity-source-identity-resolution.v1",
                **dict(row),
            }
        )


__all__ = [
    "ENTITY_LINEAGE_MIGRATION",
    "EntityLineageAuthority",
    "EntityLineageAuthorityError",
    "EntityLineageConfigurationError",
    "EntityLineageConflictError",
    "EntityLineageForbiddenError",
    "EntityLineageKind",
    "EntityLineageNotFoundError",
    "EntityLineageReceipt",
    "EntityLineageRequest",
    "EntityLineageValidationError",
    "EntityLinkPropagationDraft",
    "EntitySourceIdentityResolution",
    "EntitySourceIdentityRedirectDraft",
    "LinkPropagationDisposition",
]
