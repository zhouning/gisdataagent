"""Read-only AR-1 bridge contract for OpenMetadata and Apache Gravitino.

The bridge verifies that one GDA ResourceVersion resolves to the governance
and technical metadata authorities selected by ADR-006.  It deliberately has
no provider write methods: M1 establishes identity, replay and authority
boundaries before M2/M3 enable ingestion or catalog mutation.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from .platform_contracts import (
    Resource,
    ResourceURNText,
    ResourceVersion,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)

METADATA_FABRIC_BRIDGE_SCHEMA = "gda.metadata_fabric_bridge.v1"
METADATA_FABRIC_BINDING_SCHEMA = "gda.metadata_fabric_binding.v1"
METADATA_FABRIC_GOLDEN_SCHEMA = "gda.metadata_fabric_golden.v1"
OPENMETADATA_SERVER_VERSION = "1.13.1"
OPENMETADATA_API_PROFILE = "v1"
GRAVITINO_API_PROFILE = "v1"
DEFAULT_GOLDEN_FIXTURE = (
    Path(__file__).resolve().parent
    / "test_data"
    / "platform"
    / "metadata_fabric_land_use_golden.json"
)

_GRAVITINO_VERSION_RE = re.compile(r"^1\.3\.\d+$")
_PROVIDER_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_SECRET_KEYS = frozenset(
    {
        "accesskey",
        "apikey",
        "authorization",
        "credential",
        "password",
        "passwd",
        "privatekey",
        "secret",
        "secretkey",
        "token",
    }
)
_GDA_MAPPING_KEYS = (
    "gdaResourceUrn",
    "gdaResourceVersionId",
    "gdaContentSha256",
)
_GRAVITINO_MAPPING_KEYS = (
    "gda.resource_urn",
    "gda.resource_version_id",
    "gda.content_sha256",
    "gda.provider_revision",
)
_OPENMETADATA_FIELDS = "owners,domains,tags,extension,testSuite,dataProducts,lifeCycle"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
ProviderSegment = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$",
    ),
]


class MetadataFabricError(RuntimeError):
    code = "metadata_fabric_error"


class MetadataFabricConfigurationError(MetadataFabricError):
    code = "metadata_fabric_configuration_error"


class MetadataFabricProtocolError(MetadataFabricError):
    code = "metadata_fabric_protocol_error"


class MetadataFabricNotFoundError(MetadataFabricError):
    code = "metadata_fabric_not_found"


class MetadataFabricRejectedError(MetadataFabricError):
    code = "metadata_fabric_rejected"


class MetadataFabricUnavailableError(MetadataFabricError):
    code = "metadata_fabric_unavailable"


class ReconciliationStatus(str, Enum):
    VERIFIED = "verified"
    BLOCKED = "blocked"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _safe_api_root(value: str) -> str:
    normalized = value.rstrip("/")
    parts = urlsplit(normalized)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("provider base_url must be an absolute HTTPS URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("provider base_url must not contain credentials or URL state")
    if parts.path.rstrip("/") != "/api":
        raise ValueError("provider base_url must identify the /api root")
    return normalized


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _is_secret_key(value: object) -> bool:
    normalized = _normalized_key(value)
    return normalized in _SECRET_KEYS or normalized.endswith(
        ("accesskey", "apikey", "password", "passwd", "privatekey", "secret", "token")
    )


def _reject_secret_material(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_secret_key(key):
                raise MetadataFabricProtocolError(
                    f"{path}.{key} contains a forbidden secret-bearing field"
                )
            _reject_secret_material(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secret_material(item, path=f"{path}[{index}]")


def _provider_segment(value: object, *, field: str) -> str:
    text = str(value)
    if not _PROVIDER_SEGMENT_RE.fullmatch(text):
        raise MetadataFabricProtocolError(f"{field} is not a safe provider segment")
    return text


def _required_text(mapping: dict[str, Any], key: str, *, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MetadataFabricProtocolError(f"{path}.{key} must be a non-empty string")
    return value.strip()


class OpenMetadataProfile(_FrozenModel):
    base_url: str
    access_token: SecretStr
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=300)
    api_profile: Literal["v1"] = OPENMETADATA_API_PROFILE
    server_version: Literal["1.13.1"] = OPENMETADATA_SERVER_VERSION

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, value: str) -> str:
        return _safe_api_root(value)


class GravitinoProfile(_FrozenModel):
    base_url: str
    access_token: SecretStr
    server_version: str
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=300)
    api_profile: Literal["v1"] = GRAVITINO_API_PROFILE

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, value: str) -> str:
        return _safe_api_root(value)

    @field_validator("server_version")
    @classmethod
    def _supported_server_line(cls, value: str) -> str:
        if not _GRAVITINO_VERSION_RE.fullmatch(value):
            raise ValueError("Gravitino server_version must pin an exact 1.3.x patch")
        return value


class OpenMetadataTableRef(_FrozenModel):
    provider: Literal["openmetadata"] = "openmetadata"
    entity_type: Literal["table"] = "table"
    entity_id: UUID
    fully_qualified_name: NonEmptyText
    entity_version: str = Field(pattern=r"^\d+\.\d+$")
    api_profile: Literal["v1"] = OPENMETADATA_API_PROFILE
    server_version: Literal["1.13.1"] = OPENMETADATA_SERVER_VERSION


class GravitinoTableRef(_FrozenModel):
    provider: Literal["gravitino"] = "gravitino"
    object_type: Literal["table"] = "table"
    metalake: ProviderSegment
    catalog: ProviderSegment
    schema_name: ProviderSegment
    table_name: ProviderSegment
    provider_revision: NonEmptyText
    api_profile: Literal["v1"] = GRAVITINO_API_PROFILE
    server_version: str

    @field_validator("server_version")
    @classmethod
    def _supported_server_line(cls, value: str) -> str:
        if not _GRAVITINO_VERSION_RE.fullmatch(value):
            raise ValueError("Gravitino ref must pin an exact 1.3.x patch")
        return value

    @property
    def identity(self) -> str:
        return f"{self.metalake}/{self.catalog}/{self.schema_name}/{self.table_name}"


def openmetadata_governance_ref(ref: OpenMetadataTableRef) -> dict[str, Any]:
    return ref.model_dump(mode="json")


def gravitino_technical_ref(ref: GravitinoTableRef) -> dict[str, Any]:
    return ref.model_dump(mode="json")


def metadata_fabric_binding_fingerprint(
    *,
    tenant_id: str,
    resource_urn: str,
    resource_version_id: UUID,
    content_sha256: str,
    openmetadata: OpenMetadataTableRef,
    gravitino: tuple[GravitinoTableRef, ...],
) -> str:
    return canonical_json_fingerprint(
        {
            "tenant_id": tenant_id,
            "resource_urn": resource_urn,
            "resource_version_id": str(resource_version_id),
            "content_sha256": content_sha256,
            "openmetadata": openmetadata.model_dump(mode="json"),
            "gravitino": [item.model_dump(mode="json") for item in gravitino],
        }
    )


class MetadataFabricBinding(_FrozenModel):
    binding_schema: Literal["gda.metadata_fabric_binding.v1"] = Field(
        default=METADATA_FABRIC_BINDING_SCHEMA,
        alias="schema",
    )
    tenant_id: TenantId
    resource_urn: ResourceURNText
    resource_version_id: UUID
    content_sha256: Sha256
    openmetadata: OpenMetadataTableRef
    gravitino: tuple[GravitinoTableRef, ...] = Field(min_length=1)
    binding_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_binding(self) -> Self:
        if parse_resource_urn(self.resource_urn)["tenant_id"] != self.tenant_id:
            raise ValueError("binding ResourceURN tenant must match tenant_id")
        identities = [item.identity for item in self.gravitino]
        if len(identities) != len(set(identities)):
            raise ValueError("Gravitino technical refs must be unique")
        expected = metadata_fabric_binding_fingerprint(
            tenant_id=self.tenant_id,
            resource_urn=self.resource_urn,
            resource_version_id=self.resource_version_id,
            content_sha256=self.content_sha256,
            openmetadata=self.openmetadata,
            gravitino=self.gravitino,
        )
        if self.binding_sha256 != expected:
            raise ValueError("binding_sha256 does not match metadata fabric binding")
        return self


def build_metadata_fabric_binding(
    resource: Resource,
    version: ResourceVersion,
    *,
    openmetadata: OpenMetadataTableRef,
    gravitino: tuple[GravitinoTableRef, ...],
) -> MetadataFabricBinding:
    """Bind one immutable GDA version to its two external metadata layers."""
    if resource.tenant_id != version.tenant_id:
        raise MetadataFabricConfigurationError("resource and version tenant differ")
    if resource.resource_urn != version.resource_urn:
        raise MetadataFabricConfigurationError("resource and version URN differ")
    expected_governance = openmetadata_governance_ref(openmetadata)
    expected_technical = tuple(gravitino_technical_ref(item) for item in gravitino)
    if resource.governance_ref != expected_governance:
        raise MetadataFabricConfigurationError(
            "Resource governance_ref must exactly match the OpenMetadata ref"
        )
    if resource.technical_refs != expected_technical:
        raise MetadataFabricConfigurationError(
            "Resource technical_refs must exactly match ordered Gravitino refs"
        )
    fingerprint = metadata_fabric_binding_fingerprint(
        tenant_id=version.tenant_id,
        resource_urn=version.resource_urn,
        resource_version_id=version.resource_version_id,
        content_sha256=version.content_sha256,
        openmetadata=openmetadata,
        gravitino=gravitino,
    )
    return MetadataFabricBinding(
        tenant_id=version.tenant_id,
        resource_urn=version.resource_urn,
        resource_version_id=version.resource_version_id,
        content_sha256=version.content_sha256,
        openmetadata=openmetadata,
        gravitino=gravitino,
        binding_sha256=fingerprint,
    )


class OpenMetadataObservation(_FrozenModel):
    ref: OpenMetadataTableRef
    resource_urn: ResourceURNText
    resource_version_id: UUID
    content_sha256: Sha256
    owner_refs: tuple[NonEmptyText, ...] = Field(min_length=1)
    domain_refs: tuple[NonEmptyText, ...] = ()
    tag_refs: tuple[NonEmptyText, ...] = ()
    snapshot_sha256: Sha256
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)


class GravitinoObservation(_FrozenModel):
    ref: GravitinoTableRef
    resource_urn: ResourceURNText
    resource_version_id: UUID
    content_sha256: Sha256
    provider_revision: NonEmptyText
    snapshot_sha256: Sha256
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)


def _entity_ref(value: Any, *, path: str) -> str:
    if not isinstance(value, dict):
        raise MetadataFabricProtocolError(f"{path} must be an object")
    entity_type = _required_text(value, "type", path=path).lower()
    name = value.get("fullyQualifiedName") or value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MetadataFabricProtocolError(f"{path} must identify an entity")
    prefix = "team" if entity_type == "team" else entity_type
    return f"{prefix}:{name.strip()}"


def parse_openmetadata_table_observation(
    ref: OpenMetadataTableRef,
    payload: dict[str, Any],
    *,
    observed_at: datetime,
) -> OpenMetadataObservation:
    _reject_secret_material(payload, path="openmetadata")
    try:
        entity_id = UUID(_required_text(payload, "id", path="openmetadata"))
    except ValueError as exc:
        raise MetadataFabricProtocolError("OpenMetadata id is not a UUID") from exc
    if entity_id != ref.entity_id:
        raise MetadataFabricProtocolError("OpenMetadata entity id does not match ref")
    if _required_text(payload, "fullyQualifiedName", path="openmetadata") != (
        ref.fully_qualified_name
    ):
        raise MetadataFabricProtocolError("OpenMetadata FQN does not match ref")
    if str(payload.get("version")) != ref.entity_version:
        raise MetadataFabricProtocolError(
            "OpenMetadata entity version does not match ref"
        )
    if payload.get("deleted") is not False:
        raise MetadataFabricProtocolError(
            "OpenMetadata entity must explicitly be non-deleted"
        )
    extension = payload.get("extension")
    if not isinstance(extension, dict):
        raise MetadataFabricProtocolError("OpenMetadata extension mapping is missing")
    for key in _GDA_MAPPING_KEYS:
        _required_text(extension, key, path="openmetadata.extension")
    try:
        version_id = UUID(extension["gdaResourceVersionId"])
    except ValueError as exc:
        raise MetadataFabricProtocolError(
            "OpenMetadata gdaResourceVersionId is not a UUID"
        ) from exc
    owners = payload.get("owners")
    if not isinstance(owners, list) or not owners:
        raise MetadataFabricProtocolError("OpenMetadata owners are required")
    owner_refs = tuple(_entity_ref(item, path="openmetadata.owners") for item in owners)
    domains = payload.get("domains") or []
    if not isinstance(domains, list):
        raise MetadataFabricProtocolError("OpenMetadata domains must be a list")
    domain_refs = tuple(
        _entity_ref(item, path="openmetadata.domains") for item in domains
    )
    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        raise MetadataFabricProtocolError("OpenMetadata tags must be a list")
    tag_refs_list: list[str] = []
    for item in tags:
        if not isinstance(item, dict):
            raise MetadataFabricProtocolError(
                "OpenMetadata tag observation must be an object"
            )
        tag_refs_list.append(_required_text(item, "tagFQN", path="openmetadata.tags"))
    return OpenMetadataObservation(
        ref=ref,
        resource_urn=extension["gdaResourceUrn"],
        resource_version_id=version_id,
        content_sha256=extension["gdaContentSha256"],
        owner_refs=owner_refs,
        domain_refs=domain_refs,
        tag_refs=tuple(tag_refs_list),
        snapshot_sha256=canonical_json_fingerprint(payload),
        observed_at=observed_at,
    )


def parse_gravitino_table_observation(
    ref: GravitinoTableRef,
    payload: dict[str, Any],
    *,
    observed_at: datetime,
) -> GravitinoObservation:
    _reject_secret_material(payload, path="gravitino")
    if payload.get("code") != 0:
        raise MetadataFabricProtocolError("Gravitino response code is not zero")
    table = payload.get("table")
    if not isinstance(table, dict):
        raise MetadataFabricProtocolError("Gravitino response has no table object")
    if _required_text(table, "name", path="gravitino.table") != ref.table_name:
        raise MetadataFabricProtocolError("Gravitino table name does not match ref")
    properties = table.get("properties")
    if not isinstance(properties, dict):
        raise MetadataFabricProtocolError("Gravitino table properties are missing")
    for key in _GRAVITINO_MAPPING_KEYS:
        _required_text(properties, key, path="gravitino.table.properties")
    try:
        version_id = UUID(properties["gda.resource_version_id"])
    except ValueError as exc:
        raise MetadataFabricProtocolError(
            "Gravitino gda.resource_version_id is not a UUID"
        ) from exc
    if properties["gda.provider_revision"] != ref.provider_revision:
        raise MetadataFabricProtocolError(
            "Gravitino provider revision does not match ref"
        )
    return GravitinoObservation(
        ref=ref,
        resource_urn=properties["gda.resource_urn"],
        resource_version_id=version_id,
        content_sha256=properties["gda.content_sha256"],
        provider_revision=properties["gda.provider_revision"],
        snapshot_sha256=canonical_json_fingerprint(payload),
        observed_at=observed_at,
    )


def metadata_fabric_reconciliation_fingerprint(
    *,
    binding_sha256: str,
    openmetadata_snapshot_sha256: str,
    gravitino_snapshot_sha256s: tuple[str, ...],
    status: ReconciliationStatus,
    blockers: tuple[str, ...],
) -> str:
    return canonical_json_fingerprint(
        {
            "binding_sha256": binding_sha256,
            "openmetadata_snapshot_sha256": openmetadata_snapshot_sha256,
            "gravitino_snapshot_sha256s": list(gravitino_snapshot_sha256s),
            "status": status.value,
            "blockers": list(blockers),
        }
    )


class MetadataFabricReconciliation(_FrozenModel):
    reconciliation_schema: Literal["gda.metadata_fabric_bridge.v1"] = Field(
        default=METADATA_FABRIC_BRIDGE_SCHEMA,
        alias="schema",
    )
    binding_sha256: Sha256
    openmetadata_snapshot_sha256: Sha256
    gravitino_snapshot_sha256s: tuple[Sha256, ...] = ()
    status: ReconciliationStatus
    blockers: tuple[NonEmptyText, ...] = ()
    writes_performed: Literal[False] = False
    production_provider_verified: Literal[False] = False
    reconciliation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_result(self) -> Self:
        if (self.status == ReconciliationStatus.VERIFIED) != (not self.blockers):
            raise ValueError("verified reconciliation must have no blockers")
        expected = metadata_fabric_reconciliation_fingerprint(
            binding_sha256=self.binding_sha256,
            openmetadata_snapshot_sha256=self.openmetadata_snapshot_sha256,
            gravitino_snapshot_sha256s=self.gravitino_snapshot_sha256s,
            status=self.status,
            blockers=self.blockers,
        )
        if self.reconciliation_sha256 != expected:
            raise ValueError("reconciliation_sha256 does not match result")
        return self


def reconcile_metadata_fabric(
    resource: Resource,
    version: ResourceVersion,
    binding: MetadataFabricBinding,
    openmetadata: OpenMetadataObservation,
    gravitino: tuple[GravitinoObservation, ...],
) -> MetadataFabricReconciliation:
    """Compare both provider observations without mutating any authority."""
    blockers: list[str] = []
    expected_identity = (
        binding.resource_urn,
        binding.resource_version_id,
        binding.content_sha256,
    )
    if (
        resource.tenant_id != binding.tenant_id
        or version.tenant_id != binding.tenant_id
    ):
        blockers.append("tenant_mismatch")
    if resource.resource_urn != binding.resource_urn:
        blockers.append("resource_urn_mismatch")
    if resource.governance_ref != openmetadata_governance_ref(binding.openmetadata):
        blockers.append("resource_governance_ref_drift")
    if resource.technical_refs != tuple(
        gravitino_technical_ref(item) for item in binding.gravitino
    ):
        blockers.append("resource_technical_refs_drift")
    if version.resource_urn != binding.resource_urn:
        blockers.append("resource_version_urn_mismatch")
    if (
        version.resource_version_id != binding.resource_version_id
        or version.content_sha256 != binding.content_sha256
    ):
        blockers.append("resource_version_identity_mismatch")
    if openmetadata.ref != binding.openmetadata:
        blockers.append("openmetadata_ref_mismatch")
    if (
        openmetadata.resource_urn,
        openmetadata.resource_version_id,
        openmetadata.content_sha256,
    ) != expected_identity:
        blockers.append("openmetadata_gda_identity_drift")
    if resource.owner_ref not in openmetadata.owner_refs:
        blockers.append("openmetadata_owner_drift")
    expected_gravitino = {item.identity: item for item in binding.gravitino}
    observed_gravitino = {item.ref.identity: item for item in gravitino}
    if len(observed_gravitino) != len(gravitino):
        blockers.append("duplicate_gravitino_observation")
    if set(observed_gravitino) != set(expected_gravitino):
        blockers.append("gravitino_ref_set_mismatch")
    for identity, observation in observed_gravitino.items():
        expected_ref = expected_gravitino.get(identity)
        if expected_ref is None:
            continue
        if observation.ref != expected_ref:
            blockers.append(f"gravitino_ref_drift:{identity}")
        if (
            observation.resource_urn,
            observation.resource_version_id,
            observation.content_sha256,
        ) != expected_identity:
            blockers.append(f"gravitino_gda_identity_drift:{identity}")
        if observation.provider_revision != expected_ref.provider_revision:
            blockers.append(f"gravitino_provider_revision_drift:{identity}")
    blockers_tuple = tuple(sorted(set(blockers)))
    snapshots = tuple(
        observation.snapshot_sha256
        for observation in sorted(gravitino, key=lambda item: item.ref.identity)
    )
    status = (
        ReconciliationStatus.BLOCKED
        if blockers_tuple
        else ReconciliationStatus.VERIFIED
    )
    fingerprint = metadata_fabric_reconciliation_fingerprint(
        binding_sha256=binding.binding_sha256,
        openmetadata_snapshot_sha256=openmetadata.snapshot_sha256,
        gravitino_snapshot_sha256s=snapshots,
        status=status,
        blockers=blockers_tuple,
    )
    return MetadataFabricReconciliation(
        binding_sha256=binding.binding_sha256,
        openmetadata_snapshot_sha256=openmetadata.snapshot_sha256,
        gravitino_snapshot_sha256s=snapshots,
        status=status,
        blockers=blockers_tuple,
        reconciliation_sha256=fingerprint,
    )


class _ReadOnlyClient:
    provider_name = "provider"

    def __init__(
        self,
        *,
        base_url: str,
        access_token: SecretStr,
        timeout: float,
        accept: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {access_token.get_secret_value()}",
            },
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _get_json(
        self, path: str, *, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise MetadataFabricUnavailableError(
                f"{self.provider_name} request failed"
            ) from exc
        if response.status_code == 404:
            raise MetadataFabricNotFoundError(
                f"{self.provider_name} object was not found"
            )
        if response.status_code in {401, 403}:
            raise MetadataFabricRejectedError(
                f"{self.provider_name} rejected bridge identity"
            )
        if response.status_code >= 500:
            raise MetadataFabricUnavailableError(f"{self.provider_name} is unavailable")
        if response.status_code >= 400:
            raise MetadataFabricRejectedError(
                f"{self.provider_name} rejected read request"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetadataFabricProtocolError(
                f"{self.provider_name} returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise MetadataFabricProtocolError(
                f"{self.provider_name} response must be an object"
            )
        return payload


class OpenMetadataClient(_ReadOnlyClient):
    provider_name = "OpenMetadata"

    def __init__(
        self,
        profile: OpenMetadataProfile,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.profile = profile
        super().__init__(
            base_url=profile.base_url,
            access_token=profile.access_token,
            timeout=profile.request_timeout_seconds,
            accept="application/json",
            transport=transport,
        )

    def get_table(self, ref: OpenMetadataTableRef) -> dict[str, Any]:
        if ref.server_version != self.profile.server_version:
            raise MetadataFabricConfigurationError(
                "OpenMetadata ref and profile versions differ"
            )
        return self._get_json(
            f"v1/tables/{ref.entity_id}",
            params={"fields": _OPENMETADATA_FIELDS, "include": "non-deleted"},
        )


class GravitinoClient(_ReadOnlyClient):
    provider_name = "Gravitino"

    def __init__(
        self,
        profile: GravitinoProfile,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.profile = profile
        super().__init__(
            base_url=profile.base_url,
            access_token=profile.access_token,
            timeout=profile.request_timeout_seconds,
            accept="application/vnd.gravitino.v1+json",
            transport=transport,
        )

    def get_version(self) -> str:
        payload = self._get_json("version")
        version = payload.get("version")
        if not isinstance(version, str):
            raise MetadataFabricProtocolError("Gravitino version is missing")
        if version != self.profile.server_version:
            raise MetadataFabricProtocolError(
                "Gravitino live version does not match pinned profile"
            )
        return version

    def get_table(self, ref: GravitinoTableRef) -> dict[str, Any]:
        if ref.server_version != self.profile.server_version:
            raise MetadataFabricConfigurationError(
                "Gravitino ref and profile versions differ"
            )
        segments = (ref.metalake, ref.catalog, ref.schema_name, ref.table_name)
        for index, value in enumerate(segments):
            _provider_segment(value, field=f"gravitino path segment {index}")
        return self._get_json(
            "metalakes/"
            f"{ref.metalake}/catalogs/{ref.catalog}/schemas/{ref.schema_name}/"
            f"tables/{ref.table_name}"
        )


def probe_metadata_fabric(
    resource: Resource,
    version: ResourceVersion,
    binding: MetadataFabricBinding,
    *,
    openmetadata_client: OpenMetadataClient,
    gravitino_client: GravitinoClient,
    observed_at: datetime,
) -> MetadataFabricReconciliation:
    """Perform a read-only provider probe and return a content-bound verdict."""
    if gravitino_client.get_version() != binding.gravitino[0].server_version:
        raise MetadataFabricProtocolError("Gravitino binding version mismatch")
    governance = parse_openmetadata_table_observation(
        binding.openmetadata,
        openmetadata_client.get_table(binding.openmetadata),
        observed_at=observed_at,
    )
    technical = tuple(
        parse_gravitino_table_observation(
            ref,
            gravitino_client.get_table(ref),
            observed_at=observed_at,
        )
        for ref in binding.gravitino
    )
    return reconcile_metadata_fabric(
        resource,
        version,
        binding,
        governance,
        technical,
    )


def _load_golden_fixture(path: Path = DEFAULT_GOLDEN_FIXTURE) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema") != METADATA_FABRIC_GOLDEN_SCHEMA:
        raise MetadataFabricConfigurationError("metadata fabric fixture schema drift")
    return payload


def build_metadata_fabric_bridge_report(
    path: Path = DEFAULT_GOLDEN_FIXTURE,
) -> dict[str, Any]:
    payload = _load_golden_fixture(path)
    resource = Resource.model_validate(payload["resource"])
    version = ResourceVersion.model_validate(payload["resource_version"])
    openmetadata_ref = OpenMetadataTableRef.model_validate(payload["openmetadata_ref"])
    gravitino_refs = tuple(
        GravitinoTableRef.model_validate(item) for item in payload["gravitino_refs"]
    )
    binding = build_metadata_fabric_binding(
        resource,
        version,
        openmetadata=openmetadata_ref,
        gravitino=gravitino_refs,
    )
    observed_at = datetime.fromisoformat(payload["observed_at"])
    governance = parse_openmetadata_table_observation(
        openmetadata_ref,
        payload["openmetadata_response"],
        observed_at=observed_at,
    )
    technical = tuple(
        parse_gravitino_table_observation(ref, response, observed_at=observed_at)
        for ref, response in zip(
            gravitino_refs,
            payload["gravitino_responses"],
            strict=True,
        )
    )
    result = reconcile_metadata_fabric(
        resource,
        version,
        binding,
        governance,
        technical,
    )
    if result.status != ReconciliationStatus.VERIFIED:
        raise MetadataFabricConfigurationError(
            f"golden metadata mapping is blocked: {result.blockers}"
        )
    expected = payload.get("expected") or {}
    if expected.get("binding_sha256") != binding.binding_sha256:
        raise MetadataFabricConfigurationError("golden binding fingerprint drift")
    if expected.get("reconciliation_sha256") != result.reconciliation_sha256:
        raise MetadataFabricConfigurationError(
            "golden reconciliation fingerprint drift"
        )
    return {
        "schema": METADATA_FABRIC_BRIDGE_SCHEMA,
        "m1_contract_verified": True,
        "read_only": True,
        "writes_performed": False,
        "production_provider_verified": False,
        "openmetadata_server_version": OPENMETADATA_SERVER_VERSION,
        "gravitino_server_version": gravitino_refs[0].server_version,
        "resource_urn": binding.resource_urn,
        "resource_version_id": str(binding.resource_version_id),
        "binding_sha256": binding.binding_sha256,
        "reconciliation_sha256": result.reconciliation_sha256,
        "authority_boundaries": {
            "openmetadata": [
                "owner",
                "domain",
                "glossary",
                "classification",
                "quality_discovery",
                "generic_lineage",
            ],
            "gravitino": [
                "metalake",
                "catalog",
                "schema",
                "table",
                "technical_access_metadata",
            ],
            "gda_control": [
                "resource_urn",
                "resource_version",
                "content_sha256",
                "platform_run",
                "policy",
                "approval",
                "artifact",
                "evidence",
            ],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate metadata fabric M1 contract")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--fixture", type=Path, default=DEFAULT_GOLDEN_FIXTURE)
    args = parser.parse_args(argv)
    if args.command == "validate":
        report = build_metadata_fabric_bridge_report(args.fixture)
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
