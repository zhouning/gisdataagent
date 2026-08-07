"""Versioned reference-master authority with explainable match proposals."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Annotated, Any, Literal
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
from .platform_contracts import (
    ResourceURNText,
    ResourceVersion,
    Sha256,
    TenantId,
    build_resource_urn,
    parse_resource_urn,
)

GATEWAY_DATABASE_ROLE = "gda_control_gateway"
MASTER_DATA_ACTIVATION_ACTION = "master_data.entity.activate"
MASTER_MATCH_ALGORITHM_VERSION = "master-match-v1"
_TENANT_ADAPTER = TypeAdapter(TenantId)
_ACTOR_RE = re.compile(r"^(human|workload|agent):[^\s]{1,128}$")
_OWNER_RE = re.compile(r"^(human|team):[^\s]{1,128}$")

MasterBusinessKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    ),
]
MasterDisplayName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
SourceRevision = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    ),
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MasterDataDomain(StrEnum):
    ADMINISTRATIVE_UNIT = "administrative_unit"
    LAND_USE_CODE = "land_use_code"


class MasterMatchDisposition(StrEnum):
    RECOMMENDED = "recommended"
    REVIEW_REQUIRED = "review_required"
    CONFLICT = "conflict"


class MasterMatchStatus(StrEnum):
    MATCHED = "matched"
    REVIEW_REQUIRED = "review_required"
    CONFLICT = "conflict"
    UNMATCHED = "unmatched"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _bounded_json(value: dict[str, Any], *, maximum_bytes: int, name: str):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > maximum_bytes:
        raise ValueError(f"{name} exceeds {maximum_bytes} bytes")
    return dict(sorted(value.items()))


def _typed_actor(value: str, *, name: str) -> str:
    if _ACTOR_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must use a typed subject")
    return value


class MasterSourceRecordDraft(_FrozenContract):
    schema_id: Literal["gda.master_source_record.v1"] = "gda.master_source_record.v1"
    tenant_id: TenantId
    source_record_ref: ResourceURNText
    domain: MasterDataDomain
    source_system_ref: ResourceURNText
    source_record_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
    ]
    source_revision: SourceRevision
    business_key: MasterBusinessKey
    display_name: MasterDisplayName
    parent_business_key: MasterBusinessKey | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_by: str
    observed_at: datetime

    @field_validator("attributes")
    @classmethod
    def _valid_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(
            value,
            maximum_bytes=65_536,
            name="master source attributes",
        )

    @field_validator("observed_by")
    @classmethod
    def _valid_observer(cls, value: str) -> str:
        return _typed_actor(value, name="master source observer")

    @field_validator("observed_at")
    @classmethod
    def _valid_observed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "master source observed_at")

    @model_validator(mode="after")
    def _consistent_identity(self) -> MasterSourceRecordDraft:
        source_record = parse_resource_urn(self.source_record_ref)
        source_system = parse_resource_urn(self.source_system_ref)
        if source_record["tenant_id"] != self.tenant_id:
            raise ValueError("master source record tenant must match tenant_id")
        if source_record["resource_kind"] != "master_source_record":
            raise ValueError("master source record must use kind 'master_source_record'")
        if source_system["tenant_id"] != self.tenant_id:
            raise ValueError("master source system tenant must match tenant_id")
        return self


class MasterSourceRecord(MasterSourceRecordDraft):
    record_fingerprint: Sha256


class MasterMatchCandidate(_FrozenContract):
    tenant_id: TenantId
    match_candidate_ref: ResourceURNText
    source_record_ref: ResourceURNText
    candidate_entity_ref: ResourceURNText
    candidate_version_ref: ResourceURNText
    candidate_fingerprint: Sha256
    algorithm_version: Literal["master-match-v1"] = MASTER_MATCH_ALGORITHM_VERSION
    confidence_basis_points: Annotated[int, Field(ge=0, le=10_000)]
    disposition: MasterMatchDisposition
    evidence: dict[str, Any]
    proposal_fingerprint: Sha256
    proposed_by: str
    proposed_at: datetime

    @field_validator("evidence")
    @classmethod
    def _valid_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(
            value,
            maximum_bytes=16_384,
            name="master match evidence",
        )

    @field_validator("proposed_by")
    @classmethod
    def _valid_proposer(cls, value: str) -> str:
        value = _typed_actor(value, name="master match proposer")
        if not value.startswith(("workload:", "agent:")):
            raise ValueError("master match proposer must be a workload or agent")
        return value

    @field_validator("proposed_at")
    @classmethod
    def _valid_proposed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "master match proposed_at")

    @model_validator(mode="after")
    def _consistent_identity(self) -> MasterMatchCandidate:
        refs = {
            "match": parse_resource_urn(self.match_candidate_ref),
            "source": parse_resource_urn(self.source_record_ref),
            "entity": parse_resource_urn(self.candidate_entity_ref),
            "version": parse_resource_urn(self.candidate_version_ref),
        }
        if any(value["tenant_id"] != self.tenant_id for value in refs.values()):
            raise ValueError("master match references must use the same tenant")
        if refs["match"]["resource_kind"] != "master_match":
            raise ValueError("master match candidate must use kind 'master_match'")
        if refs["source"]["resource_kind"] != "master_source_record":
            raise ValueError("master match source must use kind 'master_source_record'")
        if refs["entity"]["resource_kind"] != "master_entity":
            raise ValueError("master match target must use kind 'master_entity'")
        if refs["version"]["resource_kind"] != "master_entity":
            raise ValueError("master match target version must use kind 'master_entity'")
        return self


class MasterMatchResult(_FrozenContract):
    tenant_id: TenantId
    source_record: MasterSourceRecord
    status: MasterMatchStatus
    algorithm_version: Literal["master-match-v1"] = MASTER_MATCH_ALGORITHM_VERSION
    candidates: tuple[MasterMatchCandidate, ...]


class MasterEntityVersionDraft(_FrozenContract):
    schema_id: Literal["gda.master_entity_version.v1"] = "gda.master_entity_version.v1"
    tenant_id: TenantId
    entity_ref: ResourceURNText
    entity_version_ref: ResourceURNText
    version: Annotated[int, Field(ge=1, le=1_000_000)]
    domain: MasterDataDomain
    business_key: MasterBusinessKey
    canonical_name: MasterDisplayName
    parent_entity_ref: ResourceURNText | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_record_refs: tuple[ResourceURNText, ...] = Field(min_length=1, max_length=100)
    match_candidate_refs: tuple[ResourceURNText, ...] = Field(default=(), max_length=100)
    valid_from: date
    valid_to: date | None = None
    owner_subject: str
    created_by: str
    creation_reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
    ]
    created_at: datetime

    @field_validator("attributes")
    @classmethod
    def _valid_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(
            value,
            maximum_bytes=65_536,
            name="master entity attributes",
        )

    @field_validator("source_record_refs", "match_candidate_refs")
    @classmethod
    def _canonical_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(value))) != value:
            raise ValueError("master evidence references must be unique and sorted")
        return value

    @field_validator("owner_subject")
    @classmethod
    def _valid_owner(cls, value: str) -> str:
        if _OWNER_RE.fullmatch(value) is None:
            raise ValueError("master entity owner must be a human or team subject")
        return value

    @field_validator("created_by")
    @classmethod
    def _valid_creator(cls, value: str) -> str:
        return _typed_actor(value, name="master entity creator")

    @field_validator("created_at")
    @classmethod
    def _valid_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "master entity created_at")

    @model_validator(mode="after")
    def _consistent_identity(self) -> MasterEntityVersionDraft:
        entity = parse_resource_urn(self.entity_ref)
        version = parse_resource_urn(self.entity_version_ref)
        if entity["tenant_id"] != self.tenant_id or version["tenant_id"] != self.tenant_id:
            raise ValueError("master entity references must use the same tenant")
        if entity["resource_kind"] != "master_entity":
            raise ValueError("master entity must use kind 'master_entity'")
        if version["resource_kind"] != "master_entity":
            raise ValueError("master entity version must use kind 'master_entity'")
        if self.entity_version_ref != f"{self.entity_ref}.v{self.version}":
            raise ValueError("master entity version reference is inconsistent")
        if self.parent_entity_ref is not None:
            parent = parse_resource_urn(self.parent_entity_ref)
            if parent["tenant_id"] != self.tenant_id:
                raise ValueError("master parent entity must use the same tenant")
            if parent["resource_kind"] != "master_entity":
                raise ValueError("master parent must use kind 'master_entity'")
            if self.parent_entity_ref == self.entity_ref:
                raise ValueError("master entity cannot be its own parent")
        for ref in self.source_record_refs:
            parsed = parse_resource_urn(ref)
            if (
                parsed["tenant_id"] != self.tenant_id
                or parsed["resource_kind"] != "master_source_record"
            ):
                raise ValueError("master source evidence reference is invalid")
        for ref in self.match_candidate_refs:
            parsed = parse_resource_urn(ref)
            if parsed["tenant_id"] != self.tenant_id or parsed["resource_kind"] != "master_match":
                raise ValueError("master match evidence reference is invalid")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("master entity valid_to must be after valid_from")
        return self


class MasterEntityVersion(MasterEntityVersionDraft):
    entity_fingerprint: Sha256


class MasterEntityActivation(_FrozenContract):
    tenant_id: TenantId
    entity_ref: ResourceURNText
    domain: MasterDataDomain
    business_key: MasterBusinessKey
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

    @field_validator("activated_by")
    @classmethod
    def _valid_activator(cls, value: str) -> str:
        return _typed_actor(value, name="master entity activator")

    @field_validator("activated_at")
    @classmethod
    def _valid_activated_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "master entity activated_at")


class MasterResourceProjection(_FrozenContract):
    tenant_id: TenantId
    entity_ref: ResourceURNText
    entity_version_ref: ResourceURNText
    entity_fingerprint: Sha256
    activation_version: Annotated[int, Field(ge=1)]
    resource_version: ResourceVersion
    previous_resource_version_id: UUID | None = None
    approval_case_ref: ResourceURNText
    projected_at: datetime

    @field_validator("projected_at")
    @classmethod
    def _valid_projected_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "master resource projected_at")

    @model_validator(mode="after")
    def _consistent_projection(self) -> MasterResourceProjection:
        entity = parse_resource_urn(self.entity_ref)
        version = parse_resource_urn(self.entity_version_ref)
        approval = parse_resource_urn(self.approval_case_ref)
        if any(
            value["tenant_id"] != self.tenant_id
            for value in (entity, version, approval)
        ):
            raise ValueError("master resource projection references must use one tenant")
        if entity["resource_kind"] != "master_entity":
            raise ValueError("master resource projection must bind a master entity")
        if (
            self.resource_version.tenant_id != self.tenant_id
            or self.resource_version.resource_urn != self.entity_ref
            or self.resource_version.content_sha256 != self.entity_fingerprint
        ):
            raise ValueError("master ResourceVersion must bind the exact entity version")
        authority = self.resource_version.authority_version_ref
        if (
            authority.get("authority_system") != "gda_control.master_data"
            or authority.get("entity_version_ref") != self.entity_version_ref
            or authority.get("entity_fingerprint") != self.entity_fingerprint
        ):
            raise ValueError("master ResourceVersion authority evidence is inconsistent")
        if approval["resource_kind"] != "approval_case":
            raise ValueError("master resource projection approval reference is invalid")
        return self


class MasterDataEvent(_FrozenContract):
    tenant_id: TenantId
    master_event_id: UUID
    subject_ref: ResourceURNText
    subject_fingerprint: Sha256
    event_type: Literal[
        "source_observed",
        "match_proposed",
        "version_staged",
        "version_activated",
    ]
    approval_case_ref: ResourceURNText | None = None
    actor_subject: str
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
    ]
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("actor_subject")
    @classmethod
    def _valid_actor(cls, value: str) -> str:
        return _typed_actor(value, name="master data event actor")

    @field_validator("occurred_at")
    @classmethod
    def _valid_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "master data event occurred_at")

    @model_validator(mode="after")
    def _approval_binding(self) -> MasterDataEvent:
        if (self.event_type == "version_activated") != (
            self.approval_case_ref is not None
        ):
            raise ValueError("only master activation events bind an ApprovalCase")
        return self


class MasterDataAuthorityError(RuntimeError):
    code = "master_data_authority_error"


class MasterDataConflictError(MasterDataAuthorityError):
    code = "master_data_conflict"


class MasterDataNotFoundError(MasterDataAuthorityError):
    code = "master_data_not_found"


class MasterDataForbiddenError(MasterDataAuthorityError):
    code = "master_data_forbidden"


class MasterDataValidationError(MasterDataAuthorityError):
    code = "master_data_validation_error"


class MasterDataConfigurationError(MasterDataAuthorityError):
    code = "master_data_authority_unavailable"


@dataclass(frozen=True)
class MasterEntityVersionPage:
    items: tuple[MasterEntityVersion, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class MasterResourceProjectionPage:
    items: tuple[MasterResourceProjection, ...]
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


def _normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


class MasterDataAuthority:
    """PostgreSQL authority for reference-master evidence and golden versions."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise MasterDataConfigurationError("master data authority requires PostgreSQL")
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
                        raise MasterDataConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except MasterDataAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise MasterDataConflictError("master data authority state conflict") from exc
            if state == "P0002":
                raise MasterDataNotFoundError("master data authority object was not found") from exc
            if state == "42501":
                raise MasterDataForbiddenError("master data tenant access was denied") from exc
            if state in {"22023", "22P02", "23502", "23503", "23514", "55000"}:
                raise MasterDataValidationError("master data contract was rejected") from exc
            raise MasterDataAuthorityError("master data database operation failed") from exc
        except SQLAlchemyError as exc:
            raise MasterDataAuthorityError("master data database operation failed") from exc

    @staticmethod
    def _source_from_row(row: Any) -> MasterSourceRecord:
        value = dict(row)
        value["attributes"] = _json_value(value["attributes"])
        return MasterSourceRecord.model_validate(value)

    @staticmethod
    def _candidate_from_row(row: Any) -> MasterMatchCandidate:
        value = dict(row)
        value["evidence"] = _json_value(value["evidence"])
        return MasterMatchCandidate.model_validate(value)

    @staticmethod
    def _version_from_row(row: Any) -> MasterEntityVersion:
        value = dict(row)
        value["attributes"] = _json_value(value["attributes"])
        value["source_record_refs"] = tuple(_json_value(value["source_record_refs"]))
        value["match_candidate_refs"] = tuple(_json_value(value["match_candidate_refs"]))
        return MasterEntityVersion.model_validate(value)

    @staticmethod
    def _activation_from_row(row: Any) -> MasterEntityActivation:
        return MasterEntityActivation.model_validate(dict(row))

    @staticmethod
    def _event_from_row(row: Any) -> MasterDataEvent:
        value = dict(row)
        value["details"] = _json_value(value["details"])
        return MasterDataEvent.model_validate(value)

    @staticmethod
    def _resource_projection_from_row(row: Any) -> MasterResourceProjection:
        value = dict(row)
        resource_version = ResourceVersion.model_validate(
            {
                "tenant_id": value["tenant_id"],
                "resource_urn": value["entity_ref"],
                "resource_version_id": value.pop("resource_version_id"),
                "version_key": value.pop("resource_version_key"),
                "predecessor_version_id": value.pop(
                    "resource_predecessor_version_id"
                ),
                "content_sha256": value["entity_fingerprint"],
                "authority_version_ref": _json_value(
                    value.pop("resource_authority_version_ref")
                ),
                "created_by": value.pop("resource_created_by"),
                "created_at": value.pop("resource_created_at"),
            }
        )
        value["resource_version"] = resource_version
        return MasterResourceProjection.model_validate(value)

    @classmethod
    def _load_source(
        cls,
        connection: Any,
        tenant_id: str,
        source_record_ref: str,
    ) -> MasterSourceRecord | None:
        row = connection.execute(
            text(
                """
                SELECT tenant_id, source_record_ref, domain, source_system_ref,
                       source_record_id, source_revision, business_key,
                       display_name, parent_business_key, attributes,
                       record_fingerprint, observed_by, observed_at
                FROM gda_control.master_source_record
                WHERE tenant_id = :tenant_id
                  AND source_record_ref = :source_record_ref
                """
            ),
            {"tenant_id": tenant_id, "source_record_ref": source_record_ref},
        ).mappings().one_or_none()
        return cls._source_from_row(row) if row is not None else None

    @classmethod
    def _load_version(
        cls,
        connection: Any,
        tenant_id: str,
        entity_version_ref: str,
    ) -> MasterEntityVersion | None:
        row = connection.execute(
            text(
                """
                SELECT tenant_id, entity_ref, entity_version_ref,
                       entity_version AS version, domain, business_key,
                       canonical_name, parent_entity_ref, attributes,
                       source_record_refs, match_candidate_refs,
                       valid_from, valid_to, owner_subject,
                       entity_fingerprint, created_by, creation_reason, created_at
                FROM gda_control.master_entity_version
                WHERE tenant_id = :tenant_id
                  AND entity_version_ref = :entity_version_ref
                """
            ),
            {"tenant_id": tenant_id, "entity_version_ref": entity_version_ref},
        ).mappings().one_or_none()
        return cls._version_from_row(row) if row is not None else None

    def observe(self, draft: MasterSourceRecordDraft) -> MasterSourceRecord:
        with self._transaction(draft.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.observe_master_source_record(
                        :tenant_id, :source_record_ref, :domain,
                        :source_system_ref, :source_record_id, :source_revision,
                        :business_key, :display_name, :parent_business_key,
                        CAST(:attributes AS jsonb), :observed_by, :observed_at
                    )
                    """
                ),
                {
                    "tenant_id": draft.tenant_id,
                    "source_record_ref": draft.source_record_ref,
                    "domain": draft.domain.value,
                    "source_system_ref": draft.source_system_ref,
                    "source_record_id": draft.source_record_id,
                    "source_revision": draft.source_revision,
                    "business_key": draft.business_key,
                    "display_name": draft.display_name,
                    "parent_business_key": draft.parent_business_key,
                    "attributes": _json(draft.attributes),
                    "observed_by": draft.observed_by,
                    "observed_at": draft.observed_at,
                },
            ).scalar_one()
            stored = self._load_source(
                connection,
                draft.tenant_id,
                draft.source_record_ref,
            )
            if stored is None:
                raise MasterDataNotFoundError("observed master source was not visible")
            comparable = stored.model_dump(exclude={"record_fingerprint", "observed_at"})
            if comparable != draft.model_dump(exclude={"observed_at"}):
                raise MasterDataConflictError("master source revision has different evidence")
            return stored

    def get_source(self, tenant_id: str, source_record_ref: str) -> MasterSourceRecord:
        with self._transaction(tenant_id) as connection:
            stored = self._load_source(connection, tenant_id, source_record_ref)
            if stored is None:
                raise MasterDataNotFoundError("master source record was not found")
            return stored

    @staticmethod
    def _score_candidate(
        source: MasterSourceRecord,
        candidate: MasterEntityVersion,
        *,
        candidate_parent_business_key: str | None,
    ) -> tuple[int, dict[str, Any]]:
        business_key_exact = source.business_key.casefold() == candidate.business_key.casefold()
        source_name = _normalized_name(source.display_name)
        candidate_name = _normalized_name(candidate.canonical_name)
        name_similarity_milli = int(
            round(SequenceMatcher(None, source_name, candidate_name).ratio() * 1000)
        )
        parent_key_exact = bool(
            source.parent_business_key
            and candidate.parent_entity_ref
            and candidate_parent_business_key
            and source.parent_business_key.casefold()
            == candidate_parent_business_key.casefold()
        )
        components = {
            "business_key": 6500 if business_key_exact else 0,
            "canonical_name": name_similarity_milli * 2500 // 1000,
            "parent_business_key": 1000 if parent_key_exact else 0,
        }
        score = sum(components.values())
        evidence = {
            "schema": "gda.master_match_evidence.v1",
            "business_key_exact": business_key_exact,
            "name_similarity_milli": name_similarity_milli,
            "parent_business_key_exact": parent_key_exact,
            "components_basis_points": components,
        }
        return score, evidence

    def match(
        self,
        tenant_id: str,
        source_record_ref: str,
        *,
        proposed_by: str,
        proposed_at: datetime,
        limit: int = 5,
    ) -> MasterMatchResult:
        proposed_by = _typed_actor(proposed_by, name="master match proposer")
        if not proposed_by.startswith(("workload:", "agent:")):
            raise ValueError("master match proposer must be a workload or agent")
        proposed_at = _aware_utc(proposed_at, "master match proposed_at")
        if not 1 <= limit <= 20:
            raise ValueError("master match limit must be between 1 and 20")
        with self._transaction(tenant_id) as connection:
            source = self._load_source(connection, tenant_id, source_record_ref)
            if source is None:
                raise MasterDataNotFoundError("master source record was not found")
            rows = connection.execute(
                text(
                    """
                    SELECT v.tenant_id, v.entity_ref, v.entity_version_ref,
                           v.entity_version AS version, v.domain, v.business_key,
                           v.canonical_name, v.parent_entity_ref, v.attributes,
                           v.source_record_refs, v.match_candidate_refs,
                           v.valid_from, v.valid_to, v.owner_subject,
                           v.entity_fingerprint, v.created_by,
                           v.creation_reason, v.created_at
                    FROM gda_control.master_entity_activation a
                    JOIN gda_control.master_entity_version v
                      ON v.tenant_id = a.tenant_id
                     AND v.entity_version_ref = a.active_version_ref
                     AND v.entity_fingerprint = a.active_fingerprint
                    WHERE a.tenant_id = :tenant_id
                      AND a.domain = :domain
                    ORDER BY v.business_key, v.entity_ref
                    """
                ),
                {"tenant_id": tenant_id, "domain": source.domain.value},
            ).mappings().all()
            versions = tuple(self._version_from_row(row) for row in rows)
            active_business_keys = {
                version.entity_ref: version.business_key for version in versions
            }
            scored = []
            for version in versions:
                parent_business_key = (
                    active_business_keys.get(version.parent_entity_ref)
                    if version.parent_entity_ref is not None
                    else None
                )
                score, evidence = self._score_candidate(
                    source,
                    version,
                    candidate_parent_business_key=parent_business_key,
                )
                if score >= 5500:
                    scored.append((score, version, evidence))
            scored.sort(key=lambda item: (-item[0], item[1].entity_ref))
            scored = scored[:limit]
            if not scored:
                return MasterMatchResult(
                    tenant_id=tenant_id,
                    source_record=source,
                    status=MasterMatchStatus.UNMATCHED,
                    candidates=(),
                )

            best_score = scored[0][0]
            runner_up = scored[1][0] if len(scored) > 1 else 0
            tied_best = sum(score == best_score for score, _, _ in scored) > 1
            candidates = []
            for index, (score, version, evidence) in enumerate(scored):
                if tied_best and score == best_score:
                    disposition = MasterMatchDisposition.CONFLICT
                elif index == 0 and score >= 8500 and score - runner_up >= 500:
                    disposition = MasterMatchDisposition.RECOMMENDED
                else:
                    disposition = MasterMatchDisposition.REVIEW_REQUIRED
                evidence = {
                    **evidence,
                    "confidence_margin_basis_points": (
                        score - runner_up if index == 0 else best_score - score
                    ),
                    "candidate_active_version_ref": version.entity_version_ref,
                    "candidate_active_fingerprint": version.entity_fingerprint,
                }
                candidate_ref = build_resource_urn(
                    tenant_id,
                    "master_match",
                    uuid5(
                        NAMESPACE_URL,
                        "|".join(
                            (
                                source.source_record_ref,
                                version.entity_version_ref,
                                version.entity_fingerprint,
                                MASTER_MATCH_ALGORITHM_VERSION,
                            )
                        ),
                    ).hex,
                )
                connection.execute(
                    text(
                        """
                        SELECT gda_control.propose_master_match_candidate(
                            :tenant_id, :match_candidate_ref, :source_record_ref,
                            :candidate_entity_ref, :candidate_version_ref,
                            :candidate_fingerprint, :algorithm_version,
                            :confidence_basis_points, :disposition,
                            CAST(:evidence AS jsonb), :proposed_by, :proposed_at
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "match_candidate_ref": candidate_ref,
                        "source_record_ref": source.source_record_ref,
                        "candidate_entity_ref": version.entity_ref,
                        "candidate_version_ref": version.entity_version_ref,
                        "candidate_fingerprint": version.entity_fingerprint,
                        "algorithm_version": MASTER_MATCH_ALGORITHM_VERSION,
                        "confidence_basis_points": score,
                        "disposition": disposition.value,
                        "evidence": _json(evidence),
                        "proposed_by": proposed_by,
                        "proposed_at": proposed_at,
                    },
                ).scalar_one()
                row = connection.execute(
                    text(
                        """
                        SELECT tenant_id, match_candidate_ref, source_record_ref,
                               candidate_entity_ref, candidate_version_ref,
                               candidate_fingerprint, algorithm_version,
                               confidence_basis_points, disposition, evidence,
                               proposal_fingerprint, proposed_by, proposed_at
                        FROM gda_control.master_match_candidate
                        WHERE tenant_id = :tenant_id
                          AND match_candidate_ref = :match_candidate_ref
                        """
                    ),
                    {"tenant_id": tenant_id, "match_candidate_ref": candidate_ref},
                ).mappings().one()
                candidates.append(self._candidate_from_row(row))

            if tied_best:
                status = MasterMatchStatus.CONFLICT
            elif candidates[0].disposition is MasterMatchDisposition.RECOMMENDED:
                status = MasterMatchStatus.MATCHED
            else:
                status = MasterMatchStatus.REVIEW_REQUIRED
            return MasterMatchResult(
                tenant_id=tenant_id,
                source_record=source,
                status=status,
                candidates=tuple(candidates),
            )

    def stage(self, draft: MasterEntityVersionDraft) -> MasterEntityVersion:
        with self._transaction(draft.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.stage_master_entity_version(
                        :tenant_id, :entity_ref, :entity_version_ref,
                        :entity_version, :domain, :business_key,
                        :canonical_name, :parent_entity_ref,
                        CAST(:attributes AS jsonb),
                        CAST(:source_record_refs AS jsonb),
                        CAST(:match_candidate_refs AS jsonb),
                        :valid_from, :valid_to, :owner_subject,
                        :created_by, :creation_reason, :created_at
                    )
                    """
                ),
                {
                    "tenant_id": draft.tenant_id,
                    "entity_ref": draft.entity_ref,
                    "entity_version_ref": draft.entity_version_ref,
                    "entity_version": draft.version,
                    "domain": draft.domain.value,
                    "business_key": draft.business_key,
                    "canonical_name": draft.canonical_name,
                    "parent_entity_ref": draft.parent_entity_ref,
                    "attributes": _json(draft.attributes),
                    "source_record_refs": _json(list(draft.source_record_refs)),
                    "match_candidate_refs": _json(list(draft.match_candidate_refs)),
                    "valid_from": draft.valid_from,
                    "valid_to": draft.valid_to,
                    "owner_subject": draft.owner_subject,
                    "created_by": draft.created_by,
                    "creation_reason": draft.creation_reason,
                    "created_at": draft.created_at,
                },
            ).scalar_one()
            stored = self._load_version(
                connection,
                draft.tenant_id,
                draft.entity_version_ref,
            )
            if stored is None:
                raise MasterDataNotFoundError("staged master entity was not visible")
            comparable = stored.model_dump(exclude={"entity_fingerprint", "created_at"})
            if comparable != draft.model_dump(exclude={"created_at"}):
                raise MasterDataConflictError("master entity version has different evidence")
            return stored

    def get(self, tenant_id: str, entity_version_ref: str) -> MasterEntityVersion:
        with self._transaction(tenant_id) as connection:
            stored = self._load_version(connection, tenant_id, entity_version_ref)
            if stored is None:
                raise MasterDataNotFoundError("master entity version was not found")
            return stored

    def list_versions(
        self,
        tenant_id: str,
        entity_ref: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> MasterEntityVersionPage:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        identity = parse_resource_urn(entity_ref)
        if identity["tenant_id"] != tenant or identity["resource_kind"] != "master_entity":
            raise ValueError("master entity identity does not match tenant")
        if not 1 <= limit <= 100:
            raise ValueError("master version query limit must be between 1 and 100")
        if not 0 <= offset <= 10_000:
            raise ValueError("master version query offset must be between 0 and 10000")
        with self._transaction(tenant) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT tenant_id, entity_ref, entity_version_ref,
                           entity_version AS version, domain, business_key,
                           canonical_name, parent_entity_ref, attributes,
                           source_record_refs, match_candidate_refs,
                           valid_from, valid_to, owner_subject,
                           entity_fingerprint, created_by, creation_reason, created_at
                    FROM gda_control.master_entity_version
                    WHERE tenant_id = :tenant_id AND entity_ref = :entity_ref
                    ORDER BY entity_version DESC, entity_version_ref DESC
                    LIMIT :row_limit OFFSET :offset
                    """
                ),
                {
                    "tenant_id": tenant,
                    "entity_ref": entity_ref,
                    "row_limit": limit + 1,
                    "offset": offset,
                },
            ).mappings().all()
        return MasterEntityVersionPage(
            items=tuple(self._version_from_row(row) for row in rows[:limit]),
            offset=offset,
            limit=limit,
            has_more=len(rows) > limit,
        )

    def activate(
        self,
        *,
        tenant_id: str,
        entity_version_ref: str,
        entity_fingerprint: str,
        approval_case_ref: str,
        expected_activation_version: int,
        actor_subject: str,
        reason: str,
    ) -> MasterEntityActivation:
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.activate_master_entity_version(
                        :tenant_id, :entity_version_ref, :entity_fingerprint,
                        :approval_case_ref, :expected_activation_version,
                        :actor_subject, :reason
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "entity_version_ref": entity_version_ref,
                    "entity_fingerprint": entity_fingerprint,
                    "approval_case_ref": approval_case_ref,
                    "expected_activation_version": expected_activation_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                },
            ).scalar_one()
            version = self._load_version(connection, tenant_id, entity_version_ref)
            if version is None:
                raise MasterDataNotFoundError("activated master version was not visible")
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, entity_ref, domain, business_key,
                           active_version_ref, active_fingerprint,
                           approval_case_ref, activation_version,
                           activated_by, activation_reason, activated_at
                    FROM gda_control.master_entity_activation
                    WHERE tenant_id = :tenant_id AND entity_ref = :entity_ref
                    """
                ),
                {"tenant_id": tenant_id, "entity_ref": version.entity_ref},
            ).mappings().one()
            return self._activation_from_row(row)

    def active(
        self,
        tenant_id: str,
        entity_ref: str,
    ) -> tuple[MasterEntityVersion, MasterEntityActivation]:
        with self._transaction(tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, entity_ref, domain, business_key,
                           active_version_ref, active_fingerprint,
                           approval_case_ref, activation_version,
                           activated_by, activation_reason, activated_at
                    FROM gda_control.master_entity_activation
                    WHERE tenant_id = :tenant_id AND entity_ref = :entity_ref
                    """
                ),
                {"tenant_id": tenant_id, "entity_ref": entity_ref},
            ).mappings().one_or_none()
            if row is None:
                raise MasterDataNotFoundError("active master entity was not found")
            activation = self._activation_from_row(row)
            version = self._load_version(connection, tenant_id, activation.active_version_ref)
            if version is None:
                raise MasterDataNotFoundError("active master entity version was not found")
            return version, activation

    def resource_projections(
        self,
        tenant_id: str,
        entity_ref: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> MasterResourceProjectionPage:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        identity = parse_resource_urn(entity_ref)
        if identity["tenant_id"] != tenant or identity["resource_kind"] != "master_entity":
            raise ValueError("master entity identity does not match tenant")
        if not 1 <= limit <= 100:
            raise ValueError("master resource projection limit must be between 1 and 100")
        if not 0 <= offset <= 10_000:
            raise ValueError("master resource projection offset must be between 0 and 10000")
        with self._transaction(tenant) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT projection.tenant_id, projection.entity_ref,
                           projection.entity_version_ref,
                           projection.entity_fingerprint,
                           projection.activation_version,
                           projection.resource_version_id,
                           projection.previous_resource_version_id,
                           projection.approval_case_ref,
                           projection.projected_at,
                           version.version_key AS resource_version_key,
                           version.predecessor_version_id
                               AS resource_predecessor_version_id,
                           version.authority_version_ref
                               AS resource_authority_version_ref,
                           version.created_by AS resource_created_by,
                           version.created_at AS resource_created_at
                    FROM gda_control.master_resource_projection projection
                    JOIN gda_control.resource_version version
                      ON version.tenant_id = projection.tenant_id
                     AND version.resource_version_id = projection.resource_version_id
                    WHERE projection.tenant_id = :tenant_id
                      AND projection.entity_ref = :entity_ref
                    ORDER BY projection.activation_version DESC
                    LIMIT :row_limit OFFSET :offset
                    """
                ),
                {
                    "tenant_id": tenant,
                    "entity_ref": entity_ref,
                    "row_limit": limit + 1,
                    "offset": offset,
                },
            ).mappings().all()
        return MasterResourceProjectionPage(
            items=tuple(
                self._resource_projection_from_row(row) for row in rows[:limit]
            ),
            offset=offset,
            limit=limit,
            has_more=len(rows) > limit,
        )

    def events(self, tenant_id: str, entity_ref: str) -> tuple[MasterDataEvent, ...]:
        with self._transaction(tenant_id) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT tenant_id, master_event_id, subject_ref,
                           subject_fingerprint, event_type, approval_case_ref,
                           actor_subject, reason, details, occurred_at
                    FROM gda_control.master_data_event
                    WHERE tenant_id = :tenant_id
                      AND (subject_ref = :entity_ref OR subject_ref LIKE :version_prefix)
                    ORDER BY occurred_at, master_event_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "entity_ref": entity_ref,
                    "version_prefix": f"{entity_ref}.v%",
                },
            ).mappings().all()
            return tuple(self._event_from_row(row) for row in rows)
