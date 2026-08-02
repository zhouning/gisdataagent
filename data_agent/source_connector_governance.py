"""Governed source contracts and evidence-backed connector certification."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.connectors import BaseConnector, ConnectorRegistry

CONTRACT_SCHEMA = "gda.source_connector_governance.v1"
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SECRET_KEYS = frozenset(
    {
        "access_key_id",
        "aws_access_key_id",
        "aws_secret_access_key",
        "key",
        "password",
        "secret",
        "secret_access_key",
        "session_token",
        "token",
    }
)


class SourceConnectorKind(StrEnum):
    DATABASE = "database"
    OBJECT_STORAGE = "object_storage"
    STAC = "stac"


class CredentialAuthType(StrEnum):
    NONE = "none"
    BASIC = "basic"
    AWS_SIGV4 = "aws_sigv4"
    BEARER = "bearer"
    APIKEY = "apikey"


class CapabilityOperation(StrEnum):
    CONNECT = "connect"
    DISCOVER = "discover"
    PREVIEW = "preview"
    PROFILE = "profile"


class CapabilityStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_SUPPORTED = "not_supported"
    NOT_EVALUATED = "not_evaluated"


class CertificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CredentialReference(_FrozenModel):
    """Secret-free reference to one immutable credential revision."""

    credential_id: str = Field(pattern=r"^[a-z][a-z0-9._:-]{2,127}$")
    version: int = Field(ge=1)
    auth_type: CredentialAuthType
    provider: str = Field(min_length=1, max_length=128)

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class DatabaseSourceConfig(_FrozenModel):
    table: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
    geom_column: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )


class ObjectStorageSourceConfig(_FrozenModel):
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,62}$")
    key: str = Field(min_length=1, max_length=1000)
    format: Literal["geojson", "csv", "parquet", "gpkg", "shapefile"]
    discovery_limit: int = Field(default=50, ge=1, le=1000)


class StacSourceConfig(_FrozenModel):
    collection_id: str = Field(min_length=1, max_length=256)
    datetime_range: str | None = Field(default=None, max_length=128)


SourceQueryConfig = DatabaseSourceConfig | ObjectStorageSourceConfig | StacSourceConfig


class SourceDefinition(_FrozenModel):
    """Owner-bound, versioned connector declaration with no embedded secret."""

    source_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,127}$")
    version: str
    source_kind: SourceConnectorKind
    endpoint_url: str = Field(min_length=1, max_length=1000)
    owner_ref: str = Field(pattern=r"^[a-z][a-z0-9._:-]{2,127}$")
    credential_reference: CredentialReference
    connector_version: str
    query_config: SourceQueryConfig
    read_only: bool = True

    @model_validator(mode="after")
    def _valid_definition(self) -> SourceDefinition:
        if not _SEMVER_RE.fullmatch(self.version):
            raise ValueError("source definition version must be semantic x.y.z")
        if not _SEMVER_RE.fullmatch(self.connector_version):
            raise ValueError("connector version must be semantic x.y.z")
        parts = urlsplit(self.endpoint_url)
        schemes = {
            SourceConnectorKind.DATABASE: {"postgresql", "postgresql+psycopg2"},
            SourceConnectorKind.OBJECT_STORAGE: {"http", "https", "s3"},
            SourceConnectorKind.STAC: {"http", "https"},
        }[self.source_kind]
        if parts.scheme not in schemes:
            raise ValueError(
                f"{self.source_kind.value} source does not allow endpoint scheme {parts.scheme!r}"
            )
        if parts.username is not None or parts.password is not None:
            raise ValueError("source endpoint must not embed credentials")
        expected_config = {
            SourceConnectorKind.DATABASE: DatabaseSourceConfig,
            SourceConnectorKind.OBJECT_STORAGE: ObjectStorageSourceConfig,
            SourceConnectorKind.STAC: StacSourceConfig,
        }[self.source_kind]
        if not isinstance(self.query_config, expected_config):
            raise ValueError(f"{self.source_kind.value} source has an incompatible query_config")
        if not self.read_only:
            raise ValueError("source connector certification is read-only")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class ProfileField(_FrozenModel):
    name: str = Field(min_length=1, max_length=256)
    data_type: str = Field(min_length=1, max_length=256)
    nullable: bool


class DiscoveredResource(_FrozenModel):
    name: str = Field(min_length=1, max_length=1000)
    resource_type: str = Field(min_length=1, max_length=64)
    fields: tuple[ProfileField, ...] = ()
    provider_version_token: str | None = None


class DiscoverySnapshot(_FrozenModel):
    resources: tuple[DiscoveredResource, ...]
    provider: str = Field(min_length=1, max_length=256)
    provider_version: str = Field(min_length=1, max_length=256)
    truncated: bool = False

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class SourceProfile(_FrozenModel):
    record_count: int = Field(ge=0)
    fields: tuple[ProfileField, ...]
    geometry_column: str | None = None
    crs: str | None = None

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class SourceCapability(_FrozenModel):
    operation: CapabilityOperation
    status: CapabilityStatus
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    message: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _passed_requires_evidence(self) -> SourceCapability:
        if self.status is CapabilityStatus.PASSED and not self.evidence_sha256:
            raise ValueError("passed capability requires evidence_sha256")
        return self


class ConnectorCertificationReport(_FrozenModel):
    schema_version: str = CONTRACT_SCHEMA
    source_id: str
    source_definition_version: str
    source_definition_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    credential_reference_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    connector_id: str
    connector_version: str
    provider: str
    provider_version: str
    certified_at: datetime
    status: CertificationStatus
    capabilities: tuple[SourceCapability, ...]
    discovery: DiscoverySnapshot | None = None
    profile: SourceProfile | None = None

    @model_validator(mode="after")
    def _coherent_report(self) -> ConnectorCertificationReport:
        operations = [capability.operation for capability in self.capabilities]
        if operations != list(CapabilityOperation):
            raise ValueError("certification must record each operation exactly once in order")
        all_passed = all(
            capability.status is CapabilityStatus.PASSED for capability in self.capabilities
        )
        if (self.status is CertificationStatus.PASSED) != all_passed:
            raise ValueError("certification status must match capability verdicts")
        return self

    @property
    def fingerprint(self) -> str:
        document = self.model_dump(mode="json", exclude={"certified_at"})
        return _canonical_sha256(document)


class SchemaFieldChange(_FrozenModel):
    resource_name: str = Field(min_length=1, max_length=1000)
    field_name: str = Field(min_length=1, max_length=256)
    change_kind: Literal[
        "added",
        "removed",
        "type_changed",
        "nullable_tightened",
        "nullable_relaxed",
    ]
    previous_type: str | None = None
    current_type: str | None = None
    previous_nullable: bool | None = None
    current_nullable: bool | None = None
    breaking: bool


class SchemaDriftEvent(_FrozenModel):
    source_id: str
    previous_discovery_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_discovery_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    added_resources: tuple[str, ...] = ()
    removed_resources: tuple[str, ...] = ()
    changed_resources: tuple[str, ...] = ()
    field_changes: tuple[SchemaFieldChange, ...] = ()
    breaking: bool

    @model_validator(mode="after")
    def _coherent_breaking_verdict(self) -> SchemaDriftEvent:
        expected = bool(self.removed_resources) or any(
            change.breaking for change in self.field_changes
        )
        if self.breaking != expected:
            raise ValueError("schema drift breaking verdict does not match its changes")
        return self

    @property
    def event_id(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class CredentialResolver(Protocol):
    def resolve(self, reference: CredentialReference) -> dict[str, Any]: ...


class MappingCredentialResolver:
    """In-memory resolver used by local certification and injected secret stores."""

    def __init__(self, credentials: Mapping[tuple[str, int], Mapping[str, Any]]) -> None:
        self._credentials = {key: dict(value) for key, value in credentials.items()}

    def resolve(self, reference: CredentialReference) -> dict[str, Any]:
        key = (reference.credential_id, reference.version)
        if key not in self._credentials:
            raise KeyError(
                f"credential reference not found: {reference.credential_id}:v{reference.version}"
            )
        resolved = dict(self._credentials[key])
        if resolved.get("type", "none") != reference.auth_type.value:
            raise ValueError("resolved credential auth type does not match reference")
        return resolved


async def certify_source_connector(
    definition: SourceDefinition,
    credential_resolver: CredentialResolver,
    *,
    connector: BaseConnector | None = None,
    certified_at: datetime | None = None,
) -> ConnectorCertificationReport:
    """Run bounded, read-only connector certification and retain only evidence."""

    runtime_connector = connector or ConnectorRegistry.get(definition.source_kind.value)
    if runtime_connector is None:
        raise ValueError(f"connector is not registered: {definition.source_kind.value}")

    try:
        auth_config = credential_resolver.resolve(definition.credential_reference)
    except Exception:
        auth_config = {}
        return _failed_report(
            definition,
            runtime_connector,
            certified_at,
            CapabilityOperation.CONNECT,
            "credential reference could not be resolved",
        )

    health: dict[str, Any]
    try:
        health = await runtime_connector.health_check(
            definition.endpoint_url,
            auth_config,
        )
    except Exception as exc:
        health = {"health": "error", "message": str(exc)}
    if health.get("health") != "healthy":
        return _failed_report(
            definition,
            runtime_connector,
            certified_at,
            CapabilityOperation.CONNECT,
            _redact_message(str(health.get("message") or "connection failed"), auth_config),
        )

    connect_evidence = _canonical_sha256(
        {
            "health": "healthy",
            "source_definition_fingerprint": definition.fingerprint,
            "credential_reference_fingerprint": definition.credential_reference.fingerprint,
        }
    )
    capabilities = [
        SourceCapability(
            operation=CapabilityOperation.CONNECT,
            status=CapabilityStatus.PASSED,
            evidence_sha256=connect_evidence,
        )
    ]

    try:
        raw_discovery = await runtime_connector.discover(
            definition.endpoint_url,
            auth_config,
            definition.query_config.model_dump(mode="json", exclude_none=True),
        )
    except Exception as exc:
        raw_discovery = {"error": str(exc)}
    if raw_discovery.get("discovery") is False:
        return _complete_failed_report(
            definition,
            runtime_connector,
            certified_at,
            capabilities,
            CapabilityOperation.DISCOVER,
            CapabilityStatus.NOT_SUPPORTED,
            _redact_message(str(raw_discovery.get("message") or "not supported"), auth_config),
        )
    if raw_discovery.get("error"):
        return _complete_failed_report(
            definition,
            runtime_connector,
            certified_at,
            capabilities,
            CapabilityOperation.DISCOVER,
            CapabilityStatus.FAILED,
            _redact_message(str(raw_discovery["error"]), auth_config),
        )
    discovery = _discovery_snapshot(raw_discovery)
    capabilities.append(
        SourceCapability(
            operation=CapabilityOperation.DISCOVER,
            status=CapabilityStatus.PASSED,
            evidence_sha256=discovery.fingerprint,
        )
    )

    try:
        preview = await runtime_connector.query(
            definition.endpoint_url,
            auth_config,
            definition.query_config.model_dump(mode="json", exclude_none=True),
            limit=10,
            target_crs=None,
        )
    except Exception as exc:
        preview = {"status": "error", "message": str(exc)}
    if isinstance(preview, dict) and preview.get("status") == "error":
        return _complete_failed_report(
            definition,
            runtime_connector,
            certified_at,
            capabilities,
            CapabilityOperation.PREVIEW,
            CapabilityStatus.FAILED,
            _redact_message(str(preview.get("message") or "preview failed"), auth_config),
            discovery=discovery,
        )
    try:
        profile = _profile_preview(preview)
    except Exception as exc:
        return _complete_failed_report(
            definition,
            runtime_connector,
            certified_at,
            capabilities,
            CapabilityOperation.PROFILE,
            CapabilityStatus.FAILED,
            _redact_message(str(exc), auth_config),
            discovery=discovery,
            preview_passed=True,
        )
    preview_evidence = _canonical_sha256(
        {"record_count": profile.record_count, "profile_fingerprint": profile.fingerprint}
    )
    capabilities.extend(
        [
            SourceCapability(
                operation=CapabilityOperation.PREVIEW,
                status=CapabilityStatus.PASSED,
                evidence_sha256=preview_evidence,
            ),
            SourceCapability(
                operation=CapabilityOperation.PROFILE,
                status=CapabilityStatus.PASSED,
                evidence_sha256=profile.fingerprint,
            ),
        ]
    )
    return ConnectorCertificationReport(
        source_id=definition.source_id,
        source_definition_version=definition.version,
        source_definition_fingerprint=definition.fingerprint,
        credential_reference_fingerprint=definition.credential_reference.fingerprint,
        connector_id=runtime_connector.SOURCE_TYPE,
        connector_version=definition.connector_version,
        provider=discovery.provider,
        provider_version=discovery.provider_version,
        certified_at=certified_at or datetime.now(UTC),
        status=CertificationStatus.PASSED,
        capabilities=tuple(capabilities),
        discovery=discovery,
        profile=profile,
    )


def detect_schema_drift(
    source_id: str,
    previous: DiscoverySnapshot,
    current: DiscoverySnapshot,
) -> SchemaDriftEvent | None:
    """Compare discovery schemas without treating object content changes as drift."""

    previous_by_name = {resource.name: resource for resource in previous.resources}
    current_by_name = {resource.name: resource for resource in current.resources}
    added = tuple(sorted(current_by_name.keys() - previous_by_name.keys()))
    removed = tuple(sorted(previous_by_name.keys() - current_by_name.keys()))
    field_changes: list[SchemaFieldChange] = []
    for resource_name in sorted(previous_by_name.keys() & current_by_name.keys()):
        old_fields = {field.name: field for field in previous_by_name[resource_name].fields}
        new_fields = {field.name: field for field in current_by_name[resource_name].fields}
        for field_name in sorted(new_fields.keys() - old_fields.keys()):
            field = new_fields[field_name]
            field_changes.append(
                SchemaFieldChange(
                    resource_name=resource_name,
                    field_name=field_name,
                    change_kind="added",
                    current_type=field.data_type,
                    current_nullable=field.nullable,
                    breaking=False,
                )
            )
        for field_name in sorted(old_fields.keys() - new_fields.keys()):
            field = old_fields[field_name]
            field_changes.append(
                SchemaFieldChange(
                    resource_name=resource_name,
                    field_name=field_name,
                    change_kind="removed",
                    previous_type=field.data_type,
                    previous_nullable=field.nullable,
                    breaking=True,
                )
            )
        for field_name in sorted(old_fields.keys() & new_fields.keys()):
            old_field = old_fields[field_name]
            new_field = new_fields[field_name]
            if old_field.data_type != new_field.data_type:
                field_changes.append(
                    SchemaFieldChange(
                        resource_name=resource_name,
                        field_name=field_name,
                        change_kind="type_changed",
                        previous_type=old_field.data_type,
                        current_type=new_field.data_type,
                        previous_nullable=old_field.nullable,
                        current_nullable=new_field.nullable,
                        breaking=True,
                    )
                )
            if old_field.nullable != new_field.nullable:
                tightened = old_field.nullable and not new_field.nullable
                field_changes.append(
                    SchemaFieldChange(
                        resource_name=resource_name,
                        field_name=field_name,
                        change_kind=("nullable_tightened" if tightened else "nullable_relaxed"),
                        previous_type=old_field.data_type,
                        current_type=new_field.data_type,
                        previous_nullable=old_field.nullable,
                        current_nullable=new_field.nullable,
                        breaking=tightened,
                    )
                )
    changed = tuple(sorted({change.resource_name for change in field_changes}))
    if not added and not removed and not changed:
        return None
    breaking = bool(removed) or any(change.breaking for change in field_changes)
    return SchemaDriftEvent(
        source_id=source_id,
        previous_discovery_fingerprint=previous.fingerprint,
        current_discovery_fingerprint=current.fingerprint,
        added_resources=added,
        removed_resources=removed,
        changed_resources=changed,
        field_changes=tuple(field_changes),
        breaking=breaking,
    )


def _discovery_snapshot(raw: dict[str, Any]) -> DiscoverySnapshot:
    resources = []
    for layer in raw.get("layers") or []:
        fields = tuple(
            ProfileField(
                name=str(column["name"]),
                data_type=str(column.get("type") or "unknown"),
                nullable=bool(column.get("nullable", True)),
            )
            for column in layer.get("columns") or []
        )
        physical = layer.get("etag")
        resources.append(
            DiscoveredResource(
                name=str(layer.get("name") or "unnamed"),
                resource_type=str(layer.get("type") or "unknown"),
                fields=fields,
                provider_version_token=str(physical) if physical else None,
            )
        )
    resources.sort(key=lambda resource: resource.name)
    return DiscoverySnapshot(
        resources=tuple(resources),
        provider=str(raw.get("provider") or raw.get("service") or "unknown"),
        provider_version=str(raw.get("provider_version") or "unknown"),
        truncated=bool(raw.get("truncated", False)),
    )


def _profile_preview(preview: Any) -> SourceProfile:
    if hasattr(preview, "columns") and hasattr(preview, "dtypes"):
        fields = tuple(
            ProfileField(
                name=str(column),
                data_type=str(preview.dtypes[column]),
                nullable=bool(preview[column].isna().any()),
            )
            for column in preview.columns
        )
        geometry_column = None
        geometry = getattr(preview, "geometry", None)
        if geometry is not None:
            geometry_column = str(getattr(geometry, "name", "geometry"))
        crs_value = getattr(preview, "crs", None)
        return SourceProfile(
            record_count=len(preview),
            fields=fields,
            geometry_column=geometry_column,
            crs=str(crs_value) if crs_value else None,
        )
    if isinstance(preview, list):
        rows = [row for row in preview if isinstance(row, dict)]
        field_names = sorted({key for row in rows for key in row})
        fields = tuple(
            ProfileField(
                name=field_name,
                data_type=_common_type(row.get(field_name) for row in rows),
                nullable=any(row.get(field_name) is None for row in rows),
            )
            for field_name in field_names
        )
        return SourceProfile(record_count=len(rows), fields=fields)
    raise ValueError("connector preview is not a tabular or record-list result")


def _common_type(values) -> str:
    types = sorted({type(value).__name__ for value in values if value is not None})
    return "|".join(types) if types else "null"


def _failed_report(
    definition: SourceDefinition,
    connector: BaseConnector,
    certified_at: datetime | None,
    failed_operation: CapabilityOperation,
    message: str,
) -> ConnectorCertificationReport:
    return _complete_failed_report(
        definition,
        connector,
        certified_at,
        [],
        failed_operation,
        CapabilityStatus.FAILED,
        message,
    )


def _complete_failed_report(
    definition: SourceDefinition,
    connector: BaseConnector,
    certified_at: datetime | None,
    completed: list[SourceCapability],
    failed_operation: CapabilityOperation,
    failed_status: CapabilityStatus,
    message: str,
    *,
    discovery: DiscoverySnapshot | None = None,
    preview_passed: bool = False,
) -> ConnectorCertificationReport:
    capabilities = list(completed)
    if preview_passed:
        capabilities.append(
            SourceCapability(
                operation=CapabilityOperation.PREVIEW,
                status=CapabilityStatus.PASSED,
                evidence_sha256=_canonical_sha256({"preview": "completed"}),
            )
        )
    capabilities.append(
        SourceCapability(
            operation=failed_operation,
            status=failed_status,
            message=message,
        )
    )
    completed_operations = {capability.operation for capability in capabilities}
    for operation in CapabilityOperation:
        if operation not in completed_operations:
            capabilities.append(
                SourceCapability(
                    operation=operation,
                    status=CapabilityStatus.NOT_EVALUATED,
                    message="blocked by earlier certification failure",
                )
            )
    capabilities.sort(key=lambda capability: list(CapabilityOperation).index(capability.operation))
    return ConnectorCertificationReport(
        source_id=definition.source_id,
        source_definition_version=definition.version,
        source_definition_fingerprint=definition.fingerprint,
        credential_reference_fingerprint=definition.credential_reference.fingerprint,
        connector_id=connector.SOURCE_TYPE,
        connector_version=definition.connector_version,
        provider=discovery.provider if discovery else "not_verified",
        provider_version=discovery.provider_version if discovery else "not_verified",
        certified_at=certified_at or datetime.now(UTC),
        status=CertificationStatus.FAILED,
        capabilities=tuple(capabilities),
        discovery=discovery,
    )


def _redact_message(message: str, auth_config: Mapping[str, Any]) -> str:
    redacted = message
    for key, value in auth_config.items():
        if key.casefold() in _SECRET_KEYS and isinstance(value, str) and value:
            redacted = redacted.replace(value, "[REDACTED]")
    return re.sub(r"(://[^:/\s]+:)[^@/\s]+@", r"\1[REDACTED]@", redacted)[:500]


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
