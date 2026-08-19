"""Tenant-bound bitemporal entity assertions and deterministic time-travel queries."""

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
from .platform_contracts import (
    ResourceURNText,
    Sha256,
    TenantId,
    parse_resource_urn,
)

TEMPORAL_ENTITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "160_bitemporal_entity_authority.sql"
)
GATEWAY_DATABASE_ROLE = "gda_control_gateway"

_TENANT_ADAPTER = TypeAdapter(TenantId)
_ACTOR_RE = re.compile(r"^(human|workload|agent):[^\s]{1,128}$")
_OWNER_RE = re.compile(r"^(human|team):[^\s]{1,128}$")

TemporalObjectType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_.-]{2,127}$",
    ),
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


class TemporalLifecycleState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"
    DELETED = "deleted"


class TemporalMutationKind(StrEnum):
    INITIAL = "initial"
    TRANSITION = "transition"
    CORRECTION = "correction"


class TemporalQueryMode(StrEnum):
    CURRENT = "current"
    VALID_AT = "valid_at"
    KNOWN_AT = "known_at"
    AS_OF = "as_of"


_ALLOWED_LIFECYCLE_TRANSITIONS = {
    TemporalLifecycleState.DRAFT: frozenset(
        {TemporalLifecycleState.ACTIVE, TemporalLifecycleState.DELETED}
    ),
    TemporalLifecycleState.ACTIVE: frozenset(
        {
            TemporalLifecycleState.SUSPENDED,
            TemporalLifecycleState.RETIRED,
            TemporalLifecycleState.DELETED,
        }
    ),
    TemporalLifecycleState.SUSPENDED: frozenset(
        {
            TemporalLifecycleState.ACTIVE,
            TemporalLifecycleState.RETIRED,
            TemporalLifecycleState.DELETED,
        }
    ),
    TemporalLifecycleState.RETIRED: frozenset(),
    TemporalLifecycleState.DELETED: frozenset(),
}


def temporal_transition_allowed(
    previous: TemporalLifecycleState,
    following: TemporalLifecycleState,
) -> bool:
    """Return whether two consecutive lifecycle events form a valid edge."""
    return following in _ALLOWED_LIFECYCLE_TRANSITIONS[previous]


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _bounded_attributes(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > 262_144:
        raise ValueError("temporal entity attributes exceed 262144 bytes")
    return dict(sorted(value.items()))


def _typed_subject(value: str, pattern: re.Pattern[str], field_name: str) -> str:
    value = value.strip()
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{field_name} must use a typed subject")
    return value


class TemporalEntityAssertionDraft(_FrozenContract):
    schema_id: Literal["gda.temporal-entity-assertion.v1"] = (
        "gda.temporal-entity-assertion.v1"
    )
    tenant_id: TenantId
    entity_ref: ResourceURNText
    object_type: TemporalObjectType
    lifecycle_state: TemporalLifecycleState
    attributes: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime
    valid_to: datetime | None = None
    source_version_refs: tuple[ResourceURNText, ...] = Field(
        min_length=1,
        max_length=100,
    )
    mutation_kind: TemporalMutationKind
    supersedes_assertion_id: UUID | None = None
    idempotency_key: IdempotencyKey
    owner_subject: str
    recorded_by: str
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
    ]

    @field_validator("attributes")
    @classmethod
    def _valid_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_attributes(value)

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _valid_time(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _aware_utc(value, info.field_name)

    @field_validator("source_version_refs")
    @classmethod
    def _canonical_sources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("source_version_refs must be sorted and unique")
        return values

    @field_validator("owner_subject")
    @classmethod
    def _valid_owner(cls, value: str) -> str:
        return _typed_subject(value, _OWNER_RE, "owner_subject")

    @field_validator("recorded_by")
    @classmethod
    def _valid_recorder(cls, value: str) -> str:
        return _typed_subject(value, _ACTOR_RE, "recorded_by")

    @model_validator(mode="after")
    def _consistent_assertion(self) -> TemporalEntityAssertionDraft:
        entity = parse_resource_urn(self.entity_ref)
        if entity["tenant_id"] != self.tenant_id:
            raise ValueError("temporal entity reference must use tenant_id")
        if entity["resource_kind"] != "entity":
            raise ValueError("temporal entity reference must use kind 'entity'")
        for source_ref in self.source_version_refs:
            source = parse_resource_urn(source_ref)
            if source["tenant_id"] != self.tenant_id:
                raise ValueError("temporal source versions must use tenant_id")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        is_correction = self.mutation_kind is TemporalMutationKind.CORRECTION
        if is_correction != (self.supersedes_assertion_id is not None):
            raise ValueError(
                "only corrections require supersedes_assertion_id"
            )
        return self


class TemporalEntityAssertion(TemporalEntityAssertionDraft):
    assertion_id: UUID
    assertion_sha256: Sha256
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def _valid_recorded_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "recorded_at")


class TemporalEntityQuery(_FrozenContract):
    tenant_id: TenantId
    entity_ref: ResourceURNText
    mode: TemporalQueryMode = TemporalQueryMode.CURRENT
    valid_at: datetime | None = None
    known_at: datetime | None = None

    @field_validator("valid_at", "known_at")
    @classmethod
    def _valid_query_time(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def _mode_parameters(self) -> TemporalEntityQuery:
        entity = parse_resource_urn(self.entity_ref)
        if entity["tenant_id"] != self.tenant_id:
            raise ValueError("temporal query entity must use tenant_id")
        if entity["resource_kind"] != "entity":
            raise ValueError("temporal query entity must use kind 'entity'")
        expected = {
            TemporalQueryMode.CURRENT: (False, False),
            TemporalQueryMode.VALID_AT: (True, False),
            TemporalQueryMode.KNOWN_AT: (False, True),
            TemporalQueryMode.AS_OF: (True, True),
        }[self.mode]
        actual = (self.valid_at is not None, self.known_at is not None)
        if actual != expected:
            raise ValueError(
                f"{self.mode.value} query requires valid_at={expected[0]} "
                f"and known_at={expected[1]}"
            )
        return self

    def resolve_axes(self, evaluated_at: datetime) -> tuple[datetime, datetime]:
        evaluated_at = _aware_utc(evaluated_at, "evaluated_at")
        if self.mode is TemporalQueryMode.CURRENT:
            return evaluated_at, evaluated_at
        if self.mode is TemporalQueryMode.VALID_AT:
            assert self.valid_at is not None
            return self.valid_at, evaluated_at
        if self.mode is TemporalQueryMode.KNOWN_AT:
            assert self.known_at is not None
            return self.known_at, self.known_at
        assert self.valid_at is not None and self.known_at is not None
        return self.valid_at, self.known_at


class TemporalEntitySnapshot(_FrozenContract):
    schema_id: Literal["gda.temporal-entity-snapshot.v1"] = (
        "gda.temporal-entity-snapshot.v1"
    )
    tenant_id: TenantId
    entity_ref: ResourceURNText
    query_mode: TemporalQueryMode
    resolved_valid_at: datetime
    resolved_known_at: datetime
    evaluated_at: datetime
    assertion: TemporalEntityAssertion
    is_tombstone: bool

    @field_validator("resolved_valid_at", "resolved_known_at", "evaluated_at")
    @classmethod
    def _valid_snapshot_time(cls, value: datetime, info) -> datetime:
        return _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def _consistent_snapshot(self) -> TemporalEntitySnapshot:
        if (
            self.assertion.tenant_id != self.tenant_id
            or self.assertion.entity_ref != self.entity_ref
        ):
            raise ValueError("snapshot assertion identity is inconsistent")
        if self.is_tombstone != (
            self.assertion.lifecycle_state is TemporalLifecycleState.DELETED
        ):
            raise ValueError("snapshot tombstone state is inconsistent")
        if self.resolved_known_at > self.evaluated_at:
            raise ValueError("snapshot cannot claim knowledge from the future")
        return self


class TemporalEntityHistoryError(ValueError):
    """Stored bitemporal assertions do not form a deterministic history."""


def resolve_temporal_snapshot(
    assertions: Sequence[TemporalEntityAssertion],
    query: TemporalEntityQuery,
    *,
    evaluated_at: datetime,
) -> TemporalEntitySnapshot | None:
    """Resolve one entity over independent valid-time and knowledge-time axes."""
    evaluated_at = _aware_utc(evaluated_at, "evaluated_at")
    valid_at, known_at = query.resolve_axes(evaluated_at)
    if known_at > evaluated_at:
        raise TemporalEntityHistoryError("known_at cannot be later than evaluated_at")
    history = tuple(assertions)
    if any(
        item.tenant_id != query.tenant_id or item.entity_ref != query.entity_ref
        for item in history
    ):
        raise TemporalEntityHistoryError(
            "temporal history contains a cross-tenant or cross-entity assertion"
        )
    all_by_id = {item.assertion_id: item for item in history}
    if len(all_by_id) != len(history):
        raise TemporalEntityHistoryError("temporal history contains duplicate assertion IDs")

    identity_pairs = {(item.object_type, item.owner_subject) for item in history}
    if len(identity_pairs) > 1:
        raise TemporalEntityHistoryError(
            "temporal history changes the stable object type or owner"
        )

    visible = tuple(item for item in history if item.recorded_at <= known_at)
    visible_by_id = {item.assertion_id: item for item in visible}
    superseded: set[UUID] = set()
    superseder_count: dict[UUID, int] = {}
    base_instants: set[datetime] = set()
    for item in visible:
        if item.supersedes_assertion_id is None:
            if item.valid_from in base_instants:
                raise TemporalEntityHistoryError(
                    "temporal history contains duplicate base valid-time events"
                )
            base_instants.add(item.valid_from)
            continue
        target = all_by_id.get(item.supersedes_assertion_id)
        if target is None:
            raise TemporalEntityHistoryError("correction target is absent from history")
        if target.assertion_id not in visible_by_id:
            raise TemporalEntityHistoryError("correction became visible before its target")
        if item.recorded_at <= target.recorded_at:
            raise TemporalEntityHistoryError("correction must be recorded after its target")
        if item.valid_from != target.valid_from:
            raise TemporalEntityHistoryError(
                "correction cannot move the target valid-time event"
            )
        if (
            item.lifecycle_state is not target.lifecycle_state
            or item.object_type != target.object_type
        ):
            raise TemporalEntityHistoryError(
                "correction cannot change the target lifecycle transition"
            )
        superseder_count[target.assertion_id] = (
            superseder_count.get(target.assertion_id, 0) + 1
        )
        if superseder_count[target.assertion_id] > 1:
            raise TemporalEntityHistoryError(
                "an assertion has multiple competing corrections"
            )
        superseded.add(target.assertion_id)

    effective = [item for item in visible if item.assertion_id not in superseded]
    effective_ordered = sorted(
        effective,
        key=lambda value: (value.valid_from, value.recorded_at, str(value.assertion_id)),
    )
    event_origins: list[TemporalEntityAssertion] = []
    for item in effective_ordered:
        origin = item
        visited: set[UUID] = set()
        while origin.supersedes_assertion_id is not None:
            if origin.assertion_id in visited:
                raise TemporalEntityHistoryError("temporal correction chain contains a cycle")
            visited.add(origin.assertion_id)
            origin = visible_by_id[origin.supersedes_assertion_id]
        event_origins.append(origin)

    for index, (item, origin) in enumerate(
        zip(effective_ordered, event_origins, strict=True)
    ):
        expected_kind = (
            TemporalMutationKind.INITIAL
            if index == 0
            else TemporalMutationKind.TRANSITION
        )
        if origin.mutation_kind is not expected_kind:
            raise TemporalEntityHistoryError(
                "temporal history must start with one initial event followed by transitions"
            )
        if index and not temporal_transition_allowed(
            effective_ordered[index - 1].lifecycle_state,
            item.lifecycle_state,
        ):
            raise TemporalEntityHistoryError(
                "temporal history contains an invalid lifecycle transition"
            )

    candidates = [item for item in effective if item.valid_from <= valid_at]
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda item: (item.valid_from, item.recorded_at, str(item.assertion_id)),
    )
    # A later lifecycle event replaces earlier states on its valid-time axis.
    # Once that event expires, the entity is absent rather than falling back.
    if selected.valid_to is not None and valid_at >= selected.valid_to:
        return None
    return TemporalEntitySnapshot(
        tenant_id=query.tenant_id,
        entity_ref=query.entity_ref,
        query_mode=query.mode,
        resolved_valid_at=valid_at,
        resolved_known_at=known_at,
        evaluated_at=evaluated_at,
        assertion=selected,
        is_tombstone=selected.lifecycle_state is TemporalLifecycleState.DELETED,
    )


class TemporalEntityAuthorityError(RuntimeError):
    code = "temporal_entity_authority_error"


class TemporalEntityConfigurationError(TemporalEntityAuthorityError):
    code = "temporal_entity_configuration_error"


class TemporalEntityConflictError(TemporalEntityAuthorityError):
    code = "temporal_entity_conflict"


class TemporalEntityForbiddenError(TemporalEntityAuthorityError):
    code = "temporal_entity_forbidden"


class TemporalEntityNotFoundError(TemporalEntityAuthorityError):
    code = "temporal_entity_not_found"


class TemporalEntityValidationError(TemporalEntityAuthorityError):
    code = "temporal_entity_validation_error"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class TemporalEntityAuthority:
    """PostgreSQL authority for append-only bitemporal entity assertions."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise TemporalEntityConfigurationError(
                "temporal entity authority requires PostgreSQL"
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
                        raise TemporalEntityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except TemporalEntityAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise TemporalEntityConflictError(
                    "temporal entity state conflict"
                ) from exc
            if state == "42501":
                raise TemporalEntityForbiddenError(
                    "temporal entity tenant or role was denied"
                ) from exc
            if state == "P0002":
                raise TemporalEntityNotFoundError(
                    "temporal entity assertion was not found"
                ) from exc
            if state in {"22023", "23514"}:
                raise TemporalEntityValidationError(
                    "temporal entity assertion was rejected"
                ) from exc
            raise TemporalEntityConfigurationError(
                "temporal entity authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise TemporalEntityConfigurationError(
                "temporal entity authority operation failed"
            ) from exc

    @staticmethod
    def _assertion_from_row(row: Any) -> TemporalEntityAssertion:
        values = dict(row)
        values["attributes"] = _json_value(values["attributes"])
        values["source_version_refs"] = tuple(
            _json_value(values["source_version_refs"])
        )
        values["schema_id"] = "gda.temporal-entity-assertion.v1"
        return TemporalEntityAssertion.model_validate(values)

    def record(self, draft: TemporalEntityAssertionDraft) -> TemporalEntityAssertion:
        with self._transaction(draft.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.record_temporal_entity_assertion(
                        :tenant_id, :entity_ref, :object_type, :lifecycle_state,
                        CAST(:attributes AS jsonb), :valid_from, :valid_to,
                        CAST(:source_version_refs AS jsonb), :mutation_kind,
                        :supersedes_assertion_id, :idempotency_key,
                        :owner_subject, :recorded_by, :reason
                    )
                    """
                ),
                {
                    "tenant_id": draft.tenant_id,
                    "entity_ref": draft.entity_ref,
                    "object_type": draft.object_type,
                    "lifecycle_state": draft.lifecycle_state.value,
                    "attributes": _json(draft.attributes),
                    "valid_from": draft.valid_from,
                    "valid_to": draft.valid_to,
                    "source_version_refs": _json(draft.source_version_refs),
                    "mutation_kind": draft.mutation_kind.value,
                    "supersedes_assertion_id": draft.supersedes_assertion_id,
                    "idempotency_key": draft.idempotency_key,
                    "owner_subject": draft.owner_subject,
                    "recorded_by": draft.recorded_by,
                    "reason": draft.reason,
                },
            ).mappings().one()
            return self._assertion_from_row(row)

    def record_batch(
        self,
        drafts: Sequence[TemporalEntityAssertionDraft],
        *,
        max_batch_size: int = 500,
    ) -> tuple[TemporalEntityAssertion, ...]:
        """Record one atomic bounded batch through the PostgreSQL authority."""
        items = tuple(drafts)
        if not items:
            raise TemporalEntityValidationError("temporal entity batch cannot be empty")
        if max_batch_size < 1 or max_batch_size > 500:
            raise TemporalEntityValidationError("temporal entity batch size must be 1..500")
        if len(items) > max_batch_size:
            raise TemporalEntityValidationError(
                f"temporal entity batch contains {len(items)} items; maximum is {max_batch_size}"
            )
        tenant_ids = {item.tenant_id for item in items}
        if len(tenant_ids) != 1:
            raise TemporalEntityValidationError(
                "temporal entity batch must use one tenant"
            )
        tenant_id = items[0].tenant_id
        with self._transaction(tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT gda_control.record_temporal_entity_assertion_batch(
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
            raise TemporalEntityConfigurationError(
                "temporal entity batch authority returned an invalid result"
            )
        try:
            return tuple(self._assertion_from_row(row) for row in rows)
        except (TypeError, ValueError, KeyError) as exc:
            raise TemporalEntityConfigurationError(
                "temporal entity batch authority returned invalid rows"
            ) from exc

    def history(
        self,
        tenant_id: str,
        entity_ref: str,
        *,
        known_through: datetime | None = None,
        limit: int = 1_000,
    ) -> tuple[TemporalEntityAssertion, ...]:
        if limit < 1 or limit > 10_000:
            raise TemporalEntityValidationError("history limit must be 1..10000")
        parsed = parse_resource_urn(entity_ref)
        if parsed["tenant_id"] != tenant_id or parsed["resource_kind"] != "entity":
            raise TemporalEntityValidationError("invalid temporal entity identity")
        if known_through is not None:
            known_through = _aware_utc(known_through, "known_through")
        with self._transaction(tenant_id) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT tenant_id, entity_ref, object_type, lifecycle_state,
                           attributes, valid_from, valid_to, source_version_refs,
                           mutation_kind, supersedes_assertion_id, idempotency_key,
                           owner_subject, recorded_by, reason, assertion_id,
                           assertion_sha256, recorded_at
                    FROM gda_control.temporal_entity_assertion
                    WHERE tenant_id = :tenant_id
                      AND entity_ref = :entity_ref
                      AND (:known_through IS NULL OR recorded_at <= :known_through)
                    ORDER BY valid_from, recorded_at, assertion_id
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "entity_ref": entity_ref,
                    "known_through": known_through,
                    "limit": limit,
                },
            ).mappings().all()
            return tuple(self._assertion_from_row(row) for row in rows)

    def resolve(
        self,
        query: TemporalEntityQuery,
        *,
        evaluated_at: datetime | None = None,
    ) -> TemporalEntitySnapshot:
        evaluated_at = _aware_utc(
            evaluated_at or datetime.now(UTC),
            "evaluated_at",
        )
        _, known_at = query.resolve_axes(evaluated_at)
        if known_at > evaluated_at:
            raise TemporalEntityValidationError(
                "known_at cannot be later than evaluated_at"
            )
        assertions = self.history(
            query.tenant_id,
            query.entity_ref,
            known_through=known_at,
            limit=10_000,
        )
        try:
            snapshot = resolve_temporal_snapshot(
                assertions,
                query,
                evaluated_at=evaluated_at,
            )
        except TemporalEntityHistoryError as exc:
            raise TemporalEntityConflictError(str(exc)) from exc
        if snapshot is None:
            raise TemporalEntityNotFoundError(
                "no temporal entity state exists on the requested time axes"
            )
        return snapshot
