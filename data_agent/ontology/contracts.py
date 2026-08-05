"""Strong runtime contracts for immutable ontology packages."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


ONTOLOGY_KEY = "natural-resource-one-map"
BASE_URI = "https://ontology.gis-data-agent.local/natural-resource/one-map/"
PACKAGE_FORMAT = "gda-ontology-package-v1"
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[+-][A-Za-z0-9.-]+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ConceptKind(StrEnum):
    DOMAIN_CLASS = "DomainClass"
    PROCESS_CLASS = "ProcessClass"
    STATE_CLASS = "StateClass"
    ROLE_CLASS = "RoleClass"
    INFORMATION_CLASS = "InformationClass"
    OBSERVATION_CLASS = "ObservationClass"
    REFERENCE_SCHEME = "ReferenceScheme"
    REFERENCE_CONCEPT = "ReferenceConcept"
    SCHEMA_ARTIFACT = "SchemaArtifact"
    CRS_REFERENCE = "CRSReference"
    META_CLASS = "MetaClass"
    DOMAIN = "Domain"
    STANDARD_DOCUMENT = "StandardDocument"
    PACKAGE = "Package"
    FEATURE_TYPE = "FeatureType"
    DATASET_SCHEMA = "DatasetSchema"
    OBJECT_TYPE = "ObjectType"
    ACTION_TYPE = "ActionType"
    FUNCTION_TYPE = "FunctionType"
    INTERFACE_TYPE = "InterfaceType"
    CRS = "CRS"
    VALUE_DOMAIN = "ValueDomain"
    VALUE_DOMAIN_MEMBER = "ValueDomainMember"
    QUALITY_RULE = "QualityRule"
    SPATIAL_POLICY = "SpatialPolicy"


class MappingStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    REJECTED = "rejected"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRecord(FrozenModel):
    source_id: str
    source_kind: str
    title: str
    locator: str
    source_version: str | None = None
    sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be lowercase hexadecimal")
        return value


class ConceptRecord(FrozenModel):
    concept_id: str
    uri: str
    kind: str
    code: str | None = None
    pref_label: str
    alt_labels: list[str] = Field(default_factory=list)
    definition: str = ""
    domain_id: str | None = None
    source_system: str
    source_id: str
    source_object_id: str | None = None
    ea_guid: str | None = None
    package_path: str | None = None
    geometry_type: str | None = None
    lifecycle_status: str = "active"
    provenance: dict[str, Any] = Field(default_factory=dict)


class PropertyRecord(FrozenModel):
    property_id: str
    owner_concept_id: str
    uri: str
    code: str
    pref_label: str
    datatype: str | None = None
    length: int | None = None
    precision_value: int | None = None
    scale_value: int | None = None
    min_count: int = 0
    max_count: int | None = 1
    ordinal: int = 0
    value_domain: dict[str, Any] | list[Any] | str | None = None
    default_value: str | None = None
    lifecycle_status: str = "active"
    source_id: str
    source_object_id: str | None = None
    ea_guid: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class RelationRecord(FrozenModel):
    relation_id: str
    relation_type: str
    source_concept_id: str
    target_concept_id: str
    pref_label: str = ""
    direction: str = "directed"
    transitive: bool = False
    symmetric: bool = False
    source_id: str
    source_object_id: str | None = None
    ea_guid: str | None = None
    lifecycle_status: str = "active"
    provenance: dict[str, Any] = Field(default_factory=dict)


class MappingRecord(FrozenModel):
    mapping_id: str
    source_concept_id: str
    target_concept_id: str
    mapping_type: str
    mapping_status: MappingStatus
    confidence: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class ArtifactRecord(FrozenModel):
    path: str
    media_type: str
    sha256: str
    record_count: int | None = None
    bytes: int


class PackageManifest(FrozenModel):
    package_format: str = PACKAGE_FORMAT
    package_id: str
    ontology_key: str = ONTOLOGY_KEY
    ontology_version_id: str
    semantic_version: str
    title: str
    description: str
    namespace_uri: str = BASE_URI
    model_profile: str = "owl2-rl-bounded"
    generated_at: datetime
    source_fingerprint: str
    content_sha256: str
    stats: dict[str, int]
    domain_stats: list[dict[str, Any]]
    artifacts: dict[str, ArtifactRecord]
    vocabularies: list[str]
    validation_summary: dict[str, Any]
    compatibility: dict[str, Any] = Field(default_factory=dict)

    @field_validator("semantic_version")
    @classmethod
    def validate_semver(cls, value: str) -> str:
        if not SEMVER_RE.fullmatch(value):
            raise ValueError("semantic_version must be SemVer")
        return value

    @field_validator("source_fingerprint", "content_sha256")
    @classmethod
    def validate_manifest_hashes(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("manifest hash must be lowercase hexadecimal")
        return value


def canonical_json(value: Any) -> bytes:
    """Return the canonical bytes used by package and evidence hashes."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def stable_token(*parts: Any, length: int = 24) -> str:
    payload = "\x1f".join(str(part or "") for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]
