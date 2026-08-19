"""Tenant-bound source identity bindings and versioned instance links.

This module is deliberately small: temporal entities remain authoritative for
entity lifecycle, while this authority owns source-to-entity resolution and
typed links between those entities.  It is suitable for technical iteration
before domain sign-off; every link type carries the exact ontology package and
review status used to produce it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
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
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE, _aware_utc, _json_value, _sqlstate

ENTITY_LINK_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "161_entity_link_authority.sql"
)

_TENANT_ADAPTER = TypeAdapter(TenantId)
_ACTOR_RE = re.compile(r"^(human|workload|agent):[^\s]{1,128}$")
_OWNER_RE = re.compile(r"^(human|team):[^\s]{1,128}$")
_OBJECT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
_URI_RE = re.compile(r"^https?://[^\s]{1,511}$")

ObjectType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_.-]{2,127}$",
    ),
]
SourceObjectId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
HttpUri = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=12, max_length=512),
]
IdempotencyKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$",
    ),
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntityResolutionMethod(StrEnum):
    AUTHORITATIVE_IDENTIFIER = "authoritative_identifier"
    AUTHORITATIVE_COMPOSITE_KEY = "authoritative_composite_key"
    SPATIAL_OVERLAY = "spatial_overlay"
    REVIEWED_MATCH = "reviewed_match"


class InstanceLinkKind(StrEnum):
    SPATIAL = "spatial"
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"
    HIERARCHICAL = "hierarchical"
    IDENTIFIER = "identifier"


class InstanceLinkLifecycle(StrEnum):
    ACTIVE = "active"
    RETRACTED = "retracted"


class InstanceLinkMutationKind(StrEnum):
    INITIAL = "initial"
    TRANSITION = "transition"
    CORRECTION = "correction"


class InstanceLinkQueryMode(StrEnum):
    CURRENT = "current"
    VALID_AT = "valid_at"
    KNOWN_AT = "known_at"
    AS_OF = "as_of"


class InstanceLinkReviewStatus(StrEnum):
    TECHNICAL_BASELINE_UNREVIEWED = "technical_baseline_unreviewed"
    DOMAIN_APPROVED = "domain_approved"


def _bounded_json(value: dict[str, Any], *, name: str, maximum_bytes: int) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{name} exceeds {maximum_bytes} bytes")
    return dict(sorted(value.items()))


def _typed_uri(value: str, name: str) -> str:
    if _URI_RE.fullmatch(value.strip()) is None:
        raise ValueError(f"{name} must be an http(s) URI")
    return value.strip()


def _typed_subject(value: str, pattern: re.Pattern[str], name: str) -> str:
    value = value.strip()
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{name} must use a typed subject")
    return value


class EntitySourceBindingDraft(_FrozenContract):
    schema_id: Literal["gda.entity-source-binding.v1"] = "gda.entity-source-binding.v1"
    tenant_id: TenantId
    source_identity_ref: ResourceURNText
    source_system_ref: ResourceURNText
    source_object_type: ObjectType
    source_object_id: SourceObjectId
    entity_ref: ResourceURNText
    entity_object_type: ObjectType
    ontology_class_uri: HttpUri
    source_version_ref: ResourceURNText
    valid_from: datetime
    valid_to: datetime | None = None
    resolution_method: EntityResolutionMethod
    confidence_basis_points: int = Field(ge=0, le=10_000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: IdempotencyKey
    owner_subject: str
    recorded_by: str
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]

    @field_validator("ontology_class_uri")
    @classmethod
    def _class_uri(cls, value: str) -> str:
        return _typed_uri(value, "ontology_class_uri")

    @field_validator("evidence")
    @classmethod
    def _evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, name="source binding evidence", maximum_bytes=65_536)

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _valid_time(cls, value: datetime | None, info) -> datetime | None:
        return None if value is None else _aware_utc(value, info.field_name)

    @field_validator("owner_subject")
    @classmethod
    def _owner(cls, value: str) -> str:
        return _typed_subject(value, _OWNER_RE, "owner_subject")

    @field_validator("recorded_by")
    @classmethod
    def _recorder(cls, value: str) -> str:
        return _typed_subject(value, _ACTOR_RE, "recorded_by")

    @model_validator(mode="after")
    def _identity(self) -> EntitySourceBindingDraft:
        refs = {
            "identity": parse_resource_urn(self.source_identity_ref),
            "system": parse_resource_urn(self.source_system_ref),
            "entity": parse_resource_urn(self.entity_ref),
            "version": parse_resource_urn(self.source_version_ref),
        }
        if any(value["tenant_id"] != self.tenant_id for value in refs.values()):
            raise ValueError("source binding references must use the same tenant")
        if refs["identity"]["resource_kind"] != "source_identity":
            raise ValueError("source_identity_ref must use kind 'source_identity'")
        if refs["system"]["resource_kind"] != "resource":
            raise ValueError("source_system_ref must use kind 'resource'")
        if refs["entity"]["resource_kind"] != "entity":
            raise ValueError("entity_ref must use kind 'entity'")
        if refs["version"]["resource_kind"] != "resource_version":
            raise ValueError("source_version_ref must use kind 'resource_version'")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class EntitySourceBinding(EntitySourceBindingDraft):
    binding_id: UUID
    binding_sha256: Sha256
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def _recorded_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "recorded_at")


class InstanceLinkTypeDraft(_FrozenContract):
    schema_id: Literal["gda.instance-link-type.v1"] = "gda.instance-link-type.v1"
    tenant_id: TenantId
    link_type_ref: ResourceURNText
    predicate_uri: HttpUri
    link_kind: InstanceLinkKind
    source_object_type: ObjectType
    target_object_type: ObjectType
    source_ontology_class_uri: HttpUri
    target_ontology_class_uri: HttpUri
    ontology_package_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=256),
    ]
    ontology_package_sha256: Sha256
    ontology_review_status: InstanceLinkReviewStatus = (
        InstanceLinkReviewStatus.TECHNICAL_BASELINE_UNREVIEWED
    )
    directed: bool = True
    allow_self: bool = False
    max_targets_per_source: int | None = Field(default=None, ge=1, le=100_000)
    max_sources_per_target: int | None = Field(default=None, ge=1, le=100_000)
    owner_subject: str
    created_by: str
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]

    @field_validator("predicate_uri", "source_ontology_class_uri", "target_ontology_class_uri")
    @classmethod
    def _uris(cls, value: str, info) -> str:
        return _typed_uri(value, info.field_name)

    @field_validator("owner_subject")
    @classmethod
    def _owner(cls, value: str) -> str:
        return _typed_subject(value, _OWNER_RE, "owner_subject")

    @field_validator("created_by")
    @classmethod
    def _creator(cls, value: str) -> str:
        return _typed_subject(value, _ACTOR_RE, "created_by")

    @model_validator(mode="after")
    def _identity(self) -> InstanceLinkTypeDraft:
        ref = parse_resource_urn(self.link_type_ref)
        if ref["tenant_id"] != self.tenant_id or ref["resource_kind"] != "link_type":
            raise ValueError("link_type_ref must use this tenant and kind 'link_type'")
        return self


class InstanceLinkType(InstanceLinkTypeDraft):
    type_sha256: Sha256
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "created_at")


class InstanceLinkAssertionDraft(_FrozenContract):
    schema_id: Literal["gda.instance-link-assertion.v1"] = "gda.instance-link-assertion.v1"
    tenant_id: TenantId
    link_ref: ResourceURNText
    link_type_ref: ResourceURNText
    source_entity_ref: ResourceURNText
    target_entity_ref: ResourceURNText
    lifecycle_state: InstanceLinkLifecycle
    attributes: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime
    valid_to: datetime | None = None
    source_version_refs: tuple[ResourceURNText, ...] = Field(min_length=1, max_length=100)
    mutation_kind: InstanceLinkMutationKind
    supersedes_assertion_id: UUID | None = None
    confidence_basis_points: int = Field(ge=0, le=10_000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: IdempotencyKey
    owner_subject: str
    recorded_by: str
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]

    @field_validator("attributes")
    @classmethod
    def _attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, name="link attributes", maximum_bytes=65_536)

    @field_validator("evidence")
    @classmethod
    def _evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, name="link evidence", maximum_bytes=65_536)

    @field_validator("source_version_refs")
    @classmethod
    def _sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(value))) != value:
            raise ValueError("source_version_refs must be sorted and unique")
        return value

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _valid_time(cls, value: datetime | None, info) -> datetime | None:
        return None if value is None else _aware_utc(value, info.field_name)

    @field_validator("owner_subject")
    @classmethod
    def _owner(cls, value: str) -> str:
        return _typed_subject(value, _OWNER_RE, "owner_subject")

    @field_validator("recorded_by")
    @classmethod
    def _recorder(cls, value: str) -> str:
        return _typed_subject(value, _ACTOR_RE, "recorded_by")

    @model_validator(mode="after")
    def _identity(self) -> InstanceLinkAssertionDraft:
        refs = {
            "link": parse_resource_urn(self.link_ref),
            "type": parse_resource_urn(self.link_type_ref),
            "source": parse_resource_urn(self.source_entity_ref),
            "target": parse_resource_urn(self.target_entity_ref),
        }
        if any(value["tenant_id"] != self.tenant_id for value in refs.values()):
            raise ValueError("link references must use the same tenant")
        if refs["link"]["resource_kind"] != "entity_link":
            raise ValueError("link_ref must use kind 'entity_link'")
        if refs["type"]["resource_kind"] != "link_type":
            raise ValueError("link_type_ref must use kind 'link_type'")
        if (
            refs["source"]["resource_kind"] != "entity"
            or refs["target"]["resource_kind"] != "entity"
        ):
            raise ValueError("link endpoints must use kind 'entity'")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        is_correction = self.mutation_kind is InstanceLinkMutationKind.CORRECTION
        if is_correction != (self.supersedes_assertion_id is not None):
            raise ValueError("only corrections require supersedes_assertion_id")
        return self


class InstanceLinkAssertion(InstanceLinkAssertionDraft):
    assertion_id: UUID
    assertion_sha256: Sha256
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def _recorded_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "recorded_at")


class InstanceLinkQuery(_FrozenContract):
    tenant_id: TenantId
    link_ref: ResourceURNText
    mode: InstanceLinkQueryMode = InstanceLinkQueryMode.CURRENT
    valid_at: datetime | None = None
    known_at: datetime | None = None

    @field_validator("valid_at", "known_at")
    @classmethod
    def _time(cls, value: datetime | None, info) -> datetime | None:
        return None if value is None else _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def _parameters(self) -> InstanceLinkQuery:
        ref = parse_resource_urn(self.link_ref)
        if ref["tenant_id"] != self.tenant_id or ref["resource_kind"] != "entity_link":
            raise ValueError("link query must use this tenant and kind 'entity_link'")
        expected = {
            InstanceLinkQueryMode.CURRENT: (False, False),
            InstanceLinkQueryMode.VALID_AT: (True, False),
            InstanceLinkQueryMode.KNOWN_AT: (False, True),
            InstanceLinkQueryMode.AS_OF: (True, True),
        }[self.mode]
        if (self.valid_at is not None, self.known_at is not None) != expected:
            raise ValueError(
                f"{self.mode} query requires valid_at={expected[0]} and known_at={expected[1]}"
            )
        return self

    def resolve_axes(self, evaluated_at: datetime) -> tuple[datetime, datetime]:
        evaluated_at = _aware_utc(evaluated_at, "evaluated_at")
        if self.mode is InstanceLinkQueryMode.CURRENT:
            return evaluated_at, evaluated_at
        if self.mode is InstanceLinkQueryMode.VALID_AT:
            assert self.valid_at is not None
            return self.valid_at, evaluated_at
        if self.mode is InstanceLinkQueryMode.KNOWN_AT:
            assert self.known_at is not None
            return self.known_at, self.known_at
        assert self.valid_at is not None and self.known_at is not None
        return self.valid_at, self.known_at


class InstanceLinkSnapshot(_FrozenContract):
    schema_id: Literal["gda.instance-link-snapshot.v1"] = "gda.instance-link-snapshot.v1"
    tenant_id: TenantId
    link_ref: ResourceURNText
    query_mode: InstanceLinkQueryMode
    resolved_valid_at: datetime
    resolved_known_at: datetime
    evaluated_at: datetime
    assertion: InstanceLinkAssertion
    is_retracted: bool

    @field_validator("resolved_valid_at", "resolved_known_at", "evaluated_at")
    @classmethod
    def _snapshot_time(cls, value: datetime, info) -> datetime:
        return _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def _consistent_snapshot(self) -> InstanceLinkSnapshot:
        if (
            self.assertion.tenant_id != self.tenant_id
            or self.assertion.link_ref != self.link_ref
        ):
            raise ValueError("snapshot assertion identity is inconsistent")
        if self.is_retracted != (
            self.assertion.lifecycle_state is InstanceLinkLifecycle.RETRACTED
        ):
            raise ValueError("snapshot retraction state is inconsistent")
        if self.resolved_known_at > self.evaluated_at:
            raise ValueError("snapshot cannot claim knowledge from the future")
        return self


class EntityLinkHistoryError(ValueError):
    """Stored source bindings or links are not deterministic."""


def resolve_instance_link_snapshot(
    assertions: Sequence[InstanceLinkAssertion],
    query: InstanceLinkQuery,
    *,
    evaluated_at: datetime,
) -> InstanceLinkSnapshot | None:
    evaluated_at = _aware_utc(evaluated_at, "evaluated_at")
    valid_at, known_at = query.resolve_axes(evaluated_at)
    if known_at > evaluated_at:
        raise EntityLinkHistoryError("known_at cannot be later than evaluated_at")
    history = tuple(assertions)
    if any(
        item.tenant_id != query.tenant_id or item.link_ref != query.link_ref
        for item in history
    ):
        raise EntityLinkHistoryError(
            "link history contains a cross-tenant or cross-link assertion"
        )
    by_id = {item.assertion_id: item for item in history}
    if len(by_id) != len(history):
        raise EntityLinkHistoryError("link history contains duplicate assertion IDs")
    identity_tuples = {
        (
            item.link_type_ref,
            item.source_entity_ref,
            item.target_entity_ref,
            item.owner_subject,
        )
        for item in history
    }
    if len(identity_tuples) > 1:
        raise EntityLinkHistoryError("link history changes stable identity or owner")
    visible = tuple(item for item in history if item.recorded_at <= known_at)
    visible_by_id = {item.assertion_id: item for item in visible}
    superseded: set[UUID] = set()
    superseder_count: dict[UUID, int] = {}
    base_instants: set[datetime] = set()
    for item in visible:
        if item.supersedes_assertion_id is None:
            if item.valid_from in base_instants:
                raise EntityLinkHistoryError(
                    "link history contains duplicate base valid-time events"
                )
            base_instants.add(item.valid_from)
            continue
        target = by_id.get(item.supersedes_assertion_id)
        if target is None or target.assertion_id not in visible_by_id:
            raise EntityLinkHistoryError("link correction target is absent or not yet known")
        if item.recorded_at <= target.recorded_at:
            raise EntityLinkHistoryError("link correction must be recorded after its target")
        if (
            item.link_type_ref != target.link_type_ref
            or item.source_entity_ref != target.source_entity_ref
            or item.target_entity_ref != target.target_entity_ref
            or item.valid_from != target.valid_from
            or item.valid_to != target.valid_to
            or item.lifecycle_state is not target.lifecycle_state
        ):
            raise EntityLinkHistoryError("link correction cannot change identity or lifecycle")
        superseder_count[target.assertion_id] = superseder_count.get(target.assertion_id, 0) + 1
        if superseder_count[target.assertion_id] > 1:
            raise EntityLinkHistoryError("a link assertion has competing corrections")
        superseded.add(target.assertion_id)
    effective = [item for item in visible if item.assertion_id not in superseded]
    ordered = sorted(
        effective,
        key=lambda item: (item.valid_from, item.recorded_at, str(item.assertion_id)),
    )
    origins: list[InstanceLinkAssertion] = []
    for item in ordered:
        origin = item
        seen: set[UUID] = set()
        while origin.supersedes_assertion_id is not None:
            if origin.assertion_id in seen:
                raise EntityLinkHistoryError("link correction chain contains a cycle")
            seen.add(origin.assertion_id)
            origin = visible_by_id[origin.supersedes_assertion_id]
        origins.append(origin)
    for index, (item, origin) in enumerate(zip(ordered, origins, strict=True)):
        expected = (
            InstanceLinkMutationKind.INITIAL
            if index == 0
            else InstanceLinkMutationKind.TRANSITION
        )
        if origin.mutation_kind is not expected:
            raise EntityLinkHistoryError("link history must start with initial then transitions")
        if index == 0 and item.lifecycle_state is not InstanceLinkLifecycle.ACTIVE:
            raise EntityLinkHistoryError("initial link lifecycle must be active")
        if index and item.lifecycle_state is origins[index - 1].lifecycle_state:
            raise EntityLinkHistoryError("link transition must change lifecycle")
    candidates = [item for item in effective if item.valid_from <= valid_at]
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda item: (item.valid_from, item.recorded_at, str(item.assertion_id)),
    )
    if selected.valid_to is not None and valid_at >= selected.valid_to:
        return None
    return InstanceLinkSnapshot(
        tenant_id=query.tenant_id,
        link_ref=query.link_ref,
        query_mode=query.mode,
        resolved_valid_at=valid_at,
        resolved_known_at=known_at,
        evaluated_at=evaluated_at,
        assertion=selected,
        is_retracted=selected.lifecycle_state is InstanceLinkLifecycle.RETRACTED,
    )


class EntityLinkAuthorityError(RuntimeError):
    code = "entity_link_authority_error"


class EntityLinkConfigurationError(EntityLinkAuthorityError):
    code = "entity_link_configuration_error"


class EntityLinkConflictError(EntityLinkAuthorityError):
    code = "entity_link_conflict"


class EntityLinkForbiddenError(EntityLinkAuthorityError):
    code = "entity_link_forbidden"


class EntityLinkNotFoundError(EntityLinkAuthorityError):
    code = "entity_link_not_found"


class EntityLinkValidationError(EntityLinkAuthorityError):
    code = "entity_link_validation_error"


class EntityLinkAuthority:
    """PostgreSQL authority for source identity evidence and instance links."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise EntityLinkConfigurationError("entity link authority requires PostgreSQL")
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"')
                    except DBAPIError as exc:
                        raise EntityLinkConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except EntityLinkAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise EntityLinkConflictError("entity link state conflict") from exc
            if state == "42501":
                raise EntityLinkForbiddenError("entity link tenant or role was denied") from exc
            if state == "P0002":
                raise EntityLinkNotFoundError("entity link target was not found") from exc
            if state in {"22023", "23514"}:
                raise EntityLinkValidationError("entity link assertion was rejected") from exc
            raise EntityLinkConfigurationError("entity link authority operation failed") from exc
        except SQLAlchemyError as exc:
            raise EntityLinkConfigurationError("entity link authority operation failed") from exc

    @staticmethod
    def _binding_from_row(row: Any) -> EntitySourceBinding:
        values = dict(row)
        values["evidence"] = _json_value(values["evidence"])
        values["schema_id"] = "gda.entity-source-binding.v1"
        return EntitySourceBinding.model_validate(values)

    @staticmethod
    def _type_from_row(row: Any) -> InstanceLinkType:
        values = dict(row)
        values["schema_id"] = "gda.instance-link-type.v1"
        return InstanceLinkType.model_validate(values)

    @staticmethod
    def _assertion_from_row(row: Any) -> InstanceLinkAssertion:
        values = dict(row)
        for key in ("attributes", "source_version_refs", "evidence"):
            values[key] = _json_value(values[key])
        values["source_version_refs"] = tuple(values["source_version_refs"])
        values["schema_id"] = "gda.instance-link-assertion.v1"
        return InstanceLinkAssertion.model_validate(values)

    def bind_source(self, draft: EntitySourceBindingDraft) -> EntitySourceBinding:
        with self._transaction(draft.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.bind_entity_source_identity(
                        :tenant_id, :source_identity_ref, :source_system_ref,
                        :source_object_type, :source_object_id, :entity_ref,
                        :entity_object_type, :ontology_class_uri, :source_version_ref,
                        :valid_from, :valid_to, :resolution_method,
                        :confidence_basis_points, CAST(:evidence AS jsonb),
                        :idempotency_key, :owner_subject, :recorded_by, :reason
                    )
                    """
                ),
                {
                    **draft.model_dump(mode="python"),
                    "resolution_method": draft.resolution_method.value,
                    "evidence": json.dumps(
                        draft.evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ).mappings().one()
            return self._binding_from_row(row)

    def bind_sources_batch(
        self,
        drafts: Sequence[EntitySourceBindingDraft],
        *,
        max_batch_size: int = 500,
    ) -> tuple[EntitySourceBinding, ...]:
        """Bind one atomic bounded source-identity batch."""
        items = tuple(drafts)
        if not items:
            raise EntityLinkValidationError("source binding batch cannot be empty")
        if max_batch_size < 1 or max_batch_size > 500:
            raise EntityLinkValidationError("source binding batch size must be 1..500")
        if len(items) > max_batch_size:
            raise EntityLinkValidationError(
                f"source binding batch contains {len(items)} items; maximum is {max_batch_size}"
            )
        tenant_ids = {item.tenant_id for item in items}
        if len(tenant_ids) != 1:
            raise EntityLinkValidationError("source binding batch must use one tenant")
        tenant_id = items[0].tenant_id
        with self._transaction(tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT gda_control.bind_entity_source_identity_batch(
                        :tenant_id, CAST(:items AS jsonb)
                    ) AS results
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "items": json.dumps(
                        [item.model_dump(mode="json") for item in items],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ).scalar_one()
        rows = _json_value(result)
        if not isinstance(rows, list) or len(rows) != len(items):
            raise EntityLinkConfigurationError(
                "source binding batch authority returned an invalid result"
            )
        try:
            return tuple(self._binding_from_row(row) for row in rows)
        except (TypeError, ValueError, KeyError) as exc:
            raise EntityLinkConfigurationError(
                "source binding batch authority returned invalid rows"
            ) from exc

    def source_binding_history(
        self,
        tenant_id: str,
        source_identity_ref: str,
        *,
        known_through: datetime | None = None,
        limit: int = 1_000,
    ) -> tuple[EntitySourceBinding, ...]:
        """Return append-only binding evidence for one stable source identity."""
        if limit < 1 or limit > 10_000:
            raise EntityLinkValidationError(
                "source binding history limit must be 1..10000"
            )
        parsed = parse_resource_urn(source_identity_ref)
        if (
            parsed["tenant_id"] != tenant_id
            or parsed["resource_kind"] != "source_identity"
        ):
            raise EntityLinkValidationError("invalid source identity reference")
        if known_through is not None:
            known_through = _aware_utc(known_through, "known_through")
        with self._transaction(tenant_id) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT identity.tenant_id, identity.source_identity_ref,
                           identity.source_system_ref, identity.source_object_type,
                           identity.source_object_id, identity.entity_ref,
                           identity.entity_object_type, identity.ontology_class_uri,
                           binding.source_version_ref, binding.valid_from,
                           binding.valid_to, binding.resolution_method,
                           binding.confidence_basis_points, binding.evidence,
                           binding.idempotency_key, identity.owner_subject,
                           binding.recorded_by, binding.reason, binding.binding_id,
                           binding.binding_sha256, binding.recorded_at
                    FROM gda_control.entity_source_identity AS identity
                    JOIN gda_control.entity_source_binding_evidence AS binding
                      ON binding.tenant_id = identity.tenant_id
                     AND binding.source_identity_ref = identity.source_identity_ref
                    WHERE identity.tenant_id = :tenant_id
                      AND identity.source_identity_ref = :source_identity_ref
                      AND (:known_through IS NULL
                           OR binding.recorded_at <= :known_through)
                    ORDER BY binding.valid_from, binding.recorded_at,
                             binding.binding_id
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "source_identity_ref": source_identity_ref,
                    "known_through": known_through,
                    "limit": limit,
                },
            ).mappings().all()
        return tuple(self._binding_from_row(row) for row in rows)

    def resolve_source_binding(
        self,
        tenant_id: str,
        source_identity_ref: str,
        *,
        valid_at: datetime,
        known_at: datetime | None = None,
        evaluated_at: datetime | None = None,
    ) -> EntitySourceBinding:
        """Resolve the latest known evidence that covers one valid-time point."""
        valid_at = _aware_utc(valid_at, "valid_at")
        evaluated_at = _aware_utc(
            evaluated_at or datetime.now(UTC),
            "evaluated_at",
        )
        known_at = _aware_utc(known_at or evaluated_at, "known_at")
        if known_at > evaluated_at:
            raise EntityLinkValidationError(
                "source binding known_at cannot be later than evaluated_at"
            )
        history = self.source_binding_history(
            tenant_id,
            source_identity_ref,
            known_through=known_at,
            limit=10_000,
        )
        candidates = [
            item
            for item in history
            if item.valid_from <= valid_at
            and (item.valid_to is None or valid_at < item.valid_to)
        ]
        if not candidates:
            raise EntityLinkNotFoundError(
                "no source binding evidence exists on the requested time axes"
            )
        return max(
            candidates,
            key=lambda item: (
                item.valid_from,
                item.recorded_at,
                str(item.binding_id),
            ),
        )

    def register_link_type(self, draft: InstanceLinkTypeDraft) -> InstanceLinkType:
        with self._transaction(draft.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.register_entity_link_type(
                        :tenant_id, :link_type_ref, :predicate_uri, :link_kind,
                        :source_object_type, :target_object_type,
                        :source_ontology_class_uri, :target_ontology_class_uri,
                        :ontology_package_id, :ontology_package_sha256,
                        :ontology_review_status, :directed, :allow_self,
                        :max_targets_per_source, :max_sources_per_target,
                        :owner_subject, :created_by, :reason
                    )
                    """
                ),
                {
                    **draft.model_dump(mode="python"),
                    "link_kind": draft.link_kind.value,
                    "ontology_review_status": draft.ontology_review_status.value,
                },
            ).mappings().one()
            return self._type_from_row(row)

    def register_link_types_batch(
        self,
        drafts: Sequence[InstanceLinkTypeDraft],
        *,
        max_batch_size: int = 500,
    ) -> tuple[InstanceLinkType, ...]:
        """Register one atomic bounded Link-type batch."""
        items = tuple(drafts)
        if not items:
            raise EntityLinkValidationError("Link type batch cannot be empty")
        if max_batch_size < 1 or max_batch_size > 500:
            raise EntityLinkValidationError("Link type batch size must be 1..500")
        if len(items) > max_batch_size:
            raise EntityLinkValidationError(
                f"Link type batch contains {len(items)} items; maximum is {max_batch_size}"
            )
        tenant_ids = {item.tenant_id for item in items}
        if len(tenant_ids) != 1:
            raise EntityLinkValidationError("Link type batch must use one tenant")
        tenant_id = items[0].tenant_id
        with self._transaction(tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT gda_control.register_entity_link_type_batch(
                        :tenant_id, CAST(:items AS jsonb)
                    ) AS results
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "items": json.dumps(
                        [item.model_dump(mode="json") for item in items],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ).scalar_one()
        rows = _json_value(result)
        if not isinstance(rows, list) or len(rows) != len(items):
            raise EntityLinkConfigurationError(
                "Link type batch authority returned an invalid result"
            )
        try:
            return tuple(self._type_from_row(row) for row in rows)
        except (TypeError, ValueError, KeyError) as exc:
            raise EntityLinkConfigurationError(
                "Link type batch authority returned invalid rows"
            ) from exc

    def record_link(self, draft: InstanceLinkAssertionDraft) -> InstanceLinkAssertion:
        with self._transaction(draft.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.record_entity_link_assertion(
                        :tenant_id, :link_ref, :link_type_ref, :source_entity_ref,
                        :target_entity_ref, :lifecycle_state,
                        CAST(:attributes AS jsonb), :valid_from, :valid_to,
                        CAST(:source_version_refs AS jsonb), :mutation_kind,
                        :supersedes_assertion_id, :confidence_basis_points,
                        CAST(:evidence AS jsonb), :idempotency_key, :owner_subject,
                        :recorded_by, :reason
                    )
                    """
                ),
                {
                    **draft.model_dump(mode="python"),
                    "lifecycle_state": draft.lifecycle_state.value,
                    "attributes": json.dumps(
                        draft.attributes,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "source_version_refs": json.dumps(
                        draft.source_version_refs,
                        ensure_ascii=False,
                    ),
                    "mutation_kind": draft.mutation_kind.value,
                    "evidence": json.dumps(
                        draft.evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ).mappings().one()
            return self._assertion_from_row(row)

    def record_links_batch(
        self,
        drafts: Sequence[InstanceLinkAssertionDraft],
        *,
        max_batch_size: int = 500,
    ) -> tuple[InstanceLinkAssertion, ...]:
        """Record one atomic bounded Link-assertion batch."""
        items = tuple(drafts)
        if not items:
            raise EntityLinkValidationError("Link assertion batch cannot be empty")
        if max_batch_size < 1 or max_batch_size > 500:
            raise EntityLinkValidationError("Link assertion batch size must be 1..500")
        if len(items) > max_batch_size:
            raise EntityLinkValidationError(
                f"Link assertion batch contains {len(items)} items; maximum is {max_batch_size}"
            )
        tenant_ids = {item.tenant_id for item in items}
        if len(tenant_ids) != 1:
            raise EntityLinkValidationError("Link assertion batch must use one tenant")
        tenant_id = items[0].tenant_id
        with self._transaction(tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT gda_control.record_entity_link_assertion_batch(
                        :tenant_id, CAST(:items AS jsonb)
                    ) AS results
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "items": json.dumps(
                        [item.model_dump(mode="json") for item in items],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ).scalar_one()
        rows = _json_value(result)
        if not isinstance(rows, list) or len(rows) != len(items):
            raise EntityLinkConfigurationError(
                "Link assertion batch authority returned an invalid result"
            )
        try:
            return tuple(self._assertion_from_row(row) for row in rows)
        except (TypeError, ValueError, KeyError) as exc:
            raise EntityLinkConfigurationError(
                "Link assertion batch authority returned invalid rows"
            ) from exc

    def history(
        self,
        tenant_id: str,
        link_ref: str,
        *,
        known_through: datetime | None = None,
        limit: int = 1_000,
    ) -> tuple[InstanceLinkAssertion, ...]:
        if limit < 1 or limit > 10_000:
            raise EntityLinkValidationError("link history limit must be 1..10000")
        ref = parse_resource_urn(link_ref)
        if ref["tenant_id"] != tenant_id or ref["resource_kind"] != "entity_link":
            raise EntityLinkValidationError("invalid entity link identity")
        if known_through is not None:
            known_through = _aware_utc(known_through, "known_through")
        with self._transaction(tenant_id) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT tenant_id, link_ref, link_type_ref, source_entity_ref,
                           target_entity_ref, lifecycle_state, attributes, valid_from,
                           valid_to, source_version_refs, mutation_kind,
                           supersedes_assertion_id, confidence_basis_points, evidence,
                           idempotency_key, owner_subject, recorded_by, reason,
                           assertion_id, assertion_sha256, recorded_at
                    FROM gda_control.entity_link_assertion
                    WHERE tenant_id = :tenant_id AND link_ref = :link_ref
                      AND (:known_through IS NULL OR recorded_at <= :known_through)
                    ORDER BY valid_from, recorded_at, assertion_id
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "link_ref": link_ref,
                    "known_through": known_through,
                    "limit": limit,
                },
            ).mappings().all()
            return tuple(self._assertion_from_row(row) for row in rows)

    def resolve(
        self, query: InstanceLinkQuery, *, evaluated_at: datetime | None = None
    ) -> InstanceLinkSnapshot:
        evaluated_at = _aware_utc(evaluated_at or datetime.now(UTC), "evaluated_at")
        _, known_at = query.resolve_axes(evaluated_at)
        if known_at > evaluated_at:
            raise EntityLinkValidationError("known_at cannot be later than evaluated_at")
        assertions = self.history(query.tenant_id, query.link_ref, known_through=known_at)
        try:
            snapshot = resolve_instance_link_snapshot(
                assertions,
                query,
                evaluated_at=evaluated_at,
            )
        except EntityLinkHistoryError as exc:
            raise EntityLinkConflictError(str(exc)) from exc
        if snapshot is None:
            raise EntityLinkNotFoundError("no link state exists on the requested time axes")
        return snapshot
