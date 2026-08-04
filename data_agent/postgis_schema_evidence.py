"""Bounded PostGIS schema evidence and deterministic compatibility assessment."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from .data_architecture_ledger import ArchitectureProviderObservation, ExternalReference
from .platform_contracts import (
    Artifact,
    ArtifactRole,
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_bytes,
    canonical_json_fingerprint,
)

POSTGIS_SCHEMA_SNAPSHOT_SCHEMA = "gda.postgis_schema_snapshot.v1"
POSTGIS_SCHEMA_COMPATIBILITY_SCHEMA = "gda.postgis_schema_compatibility.v1"
POSTGIS_SCHEMA_EVIDENCE_MEDIA_TYPE = "application/vnd.gda.postgis-schema-snapshot+json"

PostgresCatalogValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PostgisSchemaColumn(_FrozenModel):
    ordinal: int = Field(ge=1)
    name: PostgresCatalogValue
    data_type: PostgresCatalogValue
    not_null: bool
    identity_kind: str = Field(default="", max_length=1)
    generated_kind: str = Field(default="", max_length=1)
    default_expression_sha256: Sha256 | None = None

    @property
    def fingerprint(self) -> str:
        return canonical_json_fingerprint(
            {
                "schema": POSTGIS_SCHEMA_SNAPSHOT_SCHEMA,
                "component": "column",
                **self.model_dump(mode="json"),
            }
        )


class PostgisSchemaConstraint(_FrozenModel):
    name: PostgresCatalogValue
    constraint_type: str = Field(min_length=1, max_length=1)
    definition_sha256: Sha256

    @property
    def fingerprint(self) -> str:
        return canonical_json_fingerprint(
            {
                "schema": POSTGIS_SCHEMA_SNAPSHOT_SCHEMA,
                "component": "constraint",
                **self.model_dump(mode="json"),
            }
        )


class PostgisSchemaIndex(_FrozenModel):
    name: PostgresCatalogValue
    definition_sha256: Sha256

    @property
    def fingerprint(self) -> str:
        return canonical_json_fingerprint(
            {
                "schema": POSTGIS_SCHEMA_SNAPSHOT_SCHEMA,
                "component": "index",
                **self.model_dump(mode="json"),
            }
        )


def postgis_schema_snapshot_fingerprint(
    *,
    provider_namespace: str,
    provider_object_id: str,
    relation_kind: str,
    columns: tuple[PostgisSchemaColumn, ...],
    constraints: tuple[PostgisSchemaConstraint, ...],
    indexes: tuple[PostgisSchemaIndex, ...],
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": POSTGIS_SCHEMA_SNAPSHOT_SCHEMA,
            "provider_namespace": provider_namespace,
            "provider_object_id": provider_object_id,
            "relation_kind": relation_kind,
            "columns": [column.model_dump(mode="json") for column in columns],
            "constraints": [constraint.model_dump(mode="json") for constraint in constraints],
            "indexes": [index.model_dump(mode="json") for index in indexes],
        }
    )


class PostgisSchemaSnapshot(_FrozenModel):
    """Credential-free schema evidence with sensitive expressions hashed."""

    schema_version: Literal[POSTGIS_SCHEMA_SNAPSHOT_SCHEMA] = POSTGIS_SCHEMA_SNAPSHOT_SCHEMA
    provider_namespace: ExternalReference
    provider_object_id: ExternalReference
    relation_kind: str = Field(min_length=1, max_length=1)
    columns: tuple[PostgisSchemaColumn, ...]
    constraints: tuple[PostgisSchemaConstraint, ...]
    indexes: tuple[PostgisSchemaIndex, ...]
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_snapshot(self) -> PostgisSchemaSnapshot:
        ordinals = [column.ordinal for column in self.columns]
        names = [column.name for column in self.columns]
        if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            raise ValueError("PostGIS schema column ordinals must be ordered and unique")
        if len(names) != len(set(names)):
            raise ValueError("PostGIS schema column names must be unique")
        constraint_keys = [
            (constraint.constraint_type, constraint.name) for constraint in self.constraints
        ]
        if constraint_keys != sorted(constraint_keys) or len(constraint_keys) != len(
            set(constraint_keys)
        ):
            raise ValueError("PostGIS schema constraints must be ordered and unique")
        index_names = [index.name for index in self.indexes]
        if index_names != sorted(index_names) or len(index_names) != len(set(index_names)):
            raise ValueError("PostGIS schema indexes must be ordered and unique")
        expected = postgis_schema_snapshot_fingerprint(
            provider_namespace=self.provider_namespace,
            provider_object_id=self.provider_object_id,
            relation_kind=self.relation_kind,
            columns=self.columns,
            constraints=self.constraints,
            indexes=self.indexes,
        )
        if self.snapshot_sha256 != expected:
            raise ValueError("snapshot_sha256 does not match PostGIS schema evidence")
        return self


def postgis_schema_snapshot_bytes(snapshot: PostgisSchemaSnapshot) -> bytes:
    return canonical_json_bytes(snapshot.model_dump(mode="json"))


def _schema_evidence_manifest(
    snapshot: PostgisSchemaSnapshot,
    observation: ArchitectureProviderObservation,
) -> dict[str, str]:
    return {
        "schema": POSTGIS_SCHEMA_SNAPSHOT_SCHEMA,
        "observation_id": str(observation.observation_id),
        "observation_sha256": observation.observation_sha256,
        "snapshot_sha256": snapshot.snapshot_sha256,
    }


def build_postgis_schema_evidence_artifact(
    snapshot: PostgisSchemaSnapshot,
    observation: ArchitectureProviderObservation,
    *,
    artifact_id: UUID,
    storage_uri: str,
    created_by: NonEmptyText,
) -> Artifact:
    """Build an Artifact reference after callers durably store the returned bytes."""

    if observation.schema_content_sha256 != snapshot.snapshot_sha256:
        raise ValueError("schema snapshot must match its provider observation")
    if (
        observation.provider_namespace != snapshot.provider_namespace
        or observation.provider_object_id != snapshot.provider_object_id
    ):
        raise ValueError("schema snapshot must match provider object identity")
    content = postgis_schema_snapshot_bytes(snapshot)
    return Artifact(
        tenant_id=observation.tenant_id,
        artifact_id=artifact_id,
        artifact_key=f"postgis-schema-{observation.observation_id.hex}",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri=storage_uri,
        media_type=POSTGIS_SCHEMA_EVIDENCE_MEDIA_TYPE,
        content_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        resource_version_id=observation.resource_version_id,
        manifest=_schema_evidence_manifest(snapshot, observation),
        created_by=created_by,
        created_at=observation.recorded_at,
    )


def validate_postgis_schema_evidence_artifact(
    snapshot: PostgisSchemaSnapshot,
    observation: ArchitectureProviderObservation,
    artifact: Artifact,
) -> None:
    expected = build_postgis_schema_evidence_artifact(
        snapshot,
        observation,
        artifact_id=artifact.artifact_id,
        storage_uri=artifact.storage_uri,
        created_by=artifact.created_by,
    )
    if artifact != expected:
        raise ValueError("Artifact does not bind the PostGIS schema snapshot")


class SchemaCompatibilityVerdict(StrEnum):
    BACKWARD_COMPATIBLE = "backward_compatible"
    BREAKING = "breaking"
    INDETERMINATE = "indeterminate"


class SchemaCompatibilityChangeKind(StrEnum):
    RELATION_KIND_CHANGED = "relation_kind_changed"
    COLUMN_ADDED = "column_added"
    COLUMN_REMOVED = "column_removed"
    COLUMN_TYPE_CHANGED = "column_type_changed"
    COLUMN_ORDINAL_CHANGED = "column_ordinal_changed"
    NULLABILITY_TIGHTENED = "nullability_tightened"
    NULLABILITY_RELAXED = "nullability_relaxed"
    DEFAULT_ADDED = "default_added"
    DEFAULT_REMOVED = "default_removed"
    DEFAULT_CHANGED = "default_changed"
    IDENTITY_CHANGED = "identity_changed"
    GENERATED_CHANGED = "generated_changed"
    CONSTRAINT_ADDED = "constraint_added"
    CONSTRAINT_REMOVED = "constraint_removed"
    CONSTRAINT_CHANGED = "constraint_changed"
    INDEX_ADDED = "index_added"
    INDEX_REMOVED = "index_removed"
    INDEX_CHANGED = "index_changed"


class PostgisSchemaCompatibilityChange(_FrozenModel):
    component: Literal["relation", "column", "constraint", "index"]
    subject: PostgresCatalogValue
    change_kind: SchemaCompatibilityChangeKind
    verdict: SchemaCompatibilityVerdict
    previous_fingerprint: Sha256 | None = None
    current_fingerprint: Sha256 | None = None


def postgis_schema_compatibility_fingerprint(
    *,
    tenant_id: str,
    resource_version_id: UUID,
    baseline_observation_id: UUID,
    candidate_observation_id: UUID,
    baseline_evidence_artifact_id: UUID,
    candidate_evidence_artifact_id: UUID,
    baseline_snapshot_sha256: str,
    candidate_snapshot_sha256: str,
    baseline_evidence_sha256: str,
    candidate_evidence_sha256: str,
    changes: tuple[PostgisSchemaCompatibilityChange, ...],
    verdict: SchemaCompatibilityVerdict | str,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": POSTGIS_SCHEMA_COMPATIBILITY_SCHEMA,
            "tenant_id": tenant_id,
            "resource_version_id": str(resource_version_id),
            "baseline_observation_id": str(baseline_observation_id),
            "candidate_observation_id": str(candidate_observation_id),
            "baseline_evidence_artifact_id": str(baseline_evidence_artifact_id),
            "candidate_evidence_artifact_id": str(candidate_evidence_artifact_id),
            "baseline_snapshot_sha256": baseline_snapshot_sha256,
            "candidate_snapshot_sha256": candidate_snapshot_sha256,
            "baseline_evidence_sha256": baseline_evidence_sha256,
            "candidate_evidence_sha256": candidate_evidence_sha256,
            "changes": [change.model_dump(mode="json") for change in changes],
            "verdict": SchemaCompatibilityVerdict(verdict).value,
        }
    )


class PostgisSchemaCompatibilityAssessment(_FrozenModel):
    schema_version: Literal[POSTGIS_SCHEMA_COMPATIBILITY_SCHEMA] = (
        POSTGIS_SCHEMA_COMPATIBILITY_SCHEMA
    )
    tenant_id: TenantId
    resource_version_id: UUID
    baseline_observation_id: UUID
    candidate_observation_id: UUID
    baseline_evidence_artifact_id: UUID
    candidate_evidence_artifact_id: UUID
    baseline_snapshot_sha256: Sha256
    candidate_snapshot_sha256: Sha256
    baseline_evidence_sha256: Sha256
    candidate_evidence_sha256: Sha256
    changes: tuple[PostgisSchemaCompatibilityChange, ...] = Field(min_length=1)
    verdict: SchemaCompatibilityVerdict
    breaking_change_count: int = Field(ge=0)
    indeterminate_change_count: int = Field(ge=0)
    assessment_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_assessment(self) -> PostgisSchemaCompatibilityAssessment:
        if self.baseline_observation_id == self.candidate_observation_id:
            raise ValueError("compatibility assessment requires two observations")
        if self.baseline_snapshot_sha256 == self.candidate_snapshot_sha256:
            raise ValueError("compatibility assessment requires changed schema evidence")
        expected_breaking = sum(
            change.verdict is SchemaCompatibilityVerdict.BREAKING for change in self.changes
        )
        expected_indeterminate = sum(
            change.verdict is SchemaCompatibilityVerdict.INDETERMINATE for change in self.changes
        )
        if (
            self.breaking_change_count != expected_breaking
            or self.indeterminate_change_count != expected_indeterminate
        ):
            raise ValueError("compatibility change counts do not match evidence")
        expected_verdict = (
            SchemaCompatibilityVerdict.BREAKING
            if expected_breaking
            else SchemaCompatibilityVerdict.INDETERMINATE
            if expected_indeterminate
            else SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE
        )
        if self.verdict is not expected_verdict:
            raise ValueError("compatibility verdict does not match changes")
        expected = postgis_schema_compatibility_fingerprint(
            tenant_id=self.tenant_id,
            resource_version_id=self.resource_version_id,
            baseline_observation_id=self.baseline_observation_id,
            candidate_observation_id=self.candidate_observation_id,
            baseline_evidence_artifact_id=self.baseline_evidence_artifact_id,
            candidate_evidence_artifact_id=self.candidate_evidence_artifact_id,
            baseline_snapshot_sha256=self.baseline_snapshot_sha256,
            candidate_snapshot_sha256=self.candidate_snapshot_sha256,
            baseline_evidence_sha256=self.baseline_evidence_sha256,
            candidate_evidence_sha256=self.candidate_evidence_sha256,
            changes=self.changes,
            verdict=self.verdict,
        )
        if self.assessment_sha256 != expected:
            raise ValueError("assessment_sha256 does not match compatibility evidence")
        return self


def _change(
    *,
    component: Literal["relation", "column", "constraint", "index"],
    subject: str,
    change_kind: SchemaCompatibilityChangeKind,
    verdict: SchemaCompatibilityVerdict,
    previous_fingerprint: str | None = None,
    current_fingerprint: str | None = None,
) -> PostgisSchemaCompatibilityChange:
    return PostgisSchemaCompatibilityChange(
        component=component,
        subject=subject,
        change_kind=change_kind,
        verdict=verdict,
        previous_fingerprint=previous_fingerprint,
        current_fingerprint=current_fingerprint,
    )


def _column_changes(
    baseline: PostgisSchemaSnapshot,
    candidate: PostgisSchemaSnapshot,
) -> list[PostgisSchemaCompatibilityChange]:
    changes: list[PostgisSchemaCompatibilityChange] = []
    old = {column.name: column for column in baseline.columns}
    new = {column.name: column for column in candidate.columns}
    for name in sorted(new.keys() - old.keys()):
        column = new[name]
        safely_populated = (
            not column.not_null
            or column.default_expression_sha256 is not None
            or bool(column.identity_kind)
            or bool(column.generated_kind)
        )
        changes.append(
            _change(
                component="column",
                subject=name,
                change_kind=SchemaCompatibilityChangeKind.COLUMN_ADDED,
                verdict=(
                    SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE
                    if safely_populated
                    else SchemaCompatibilityVerdict.BREAKING
                ),
                current_fingerprint=column.fingerprint,
            )
        )
    for name in sorted(old.keys() - new.keys()):
        changes.append(
            _change(
                component="column",
                subject=name,
                change_kind=SchemaCompatibilityChangeKind.COLUMN_REMOVED,
                verdict=SchemaCompatibilityVerdict.BREAKING,
                previous_fingerprint=old[name].fingerprint,
            )
        )
    for name in sorted(old.keys() & new.keys()):
        previous = old[name]
        current = new[name]
        fingerprints = {
            "previous_fingerprint": previous.fingerprint,
            "current_fingerprint": current.fingerprint,
        }
        if previous.data_type != current.data_type:
            changes.append(
                _change(
                    component="column",
                    subject=name,
                    change_kind=SchemaCompatibilityChangeKind.COLUMN_TYPE_CHANGED,
                    verdict=SchemaCompatibilityVerdict.BREAKING,
                    **fingerprints,
                )
            )
        if previous.ordinal != current.ordinal:
            changes.append(
                _change(
                    component="column",
                    subject=name,
                    change_kind=SchemaCompatibilityChangeKind.COLUMN_ORDINAL_CHANGED,
                    verdict=SchemaCompatibilityVerdict.INDETERMINATE,
                    **fingerprints,
                )
            )
        if previous.not_null != current.not_null:
            tightened = not previous.not_null and current.not_null
            changes.append(
                _change(
                    component="column",
                    subject=name,
                    change_kind=(
                        SchemaCompatibilityChangeKind.NULLABILITY_TIGHTENED
                        if tightened
                        else SchemaCompatibilityChangeKind.NULLABILITY_RELAXED
                    ),
                    verdict=(
                        SchemaCompatibilityVerdict.BREAKING
                        if tightened
                        else SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE
                    ),
                    **fingerprints,
                )
            )
        if previous.identity_kind != current.identity_kind:
            changes.append(
                _change(
                    component="column",
                    subject=name,
                    change_kind=SchemaCompatibilityChangeKind.IDENTITY_CHANGED,
                    verdict=SchemaCompatibilityVerdict.INDETERMINATE,
                    **fingerprints,
                )
            )
        if previous.generated_kind != current.generated_kind:
            changes.append(
                _change(
                    component="column",
                    subject=name,
                    change_kind=SchemaCompatibilityChangeKind.GENERATED_CHANGED,
                    verdict=SchemaCompatibilityVerdict.INDETERMINATE,
                    **fingerprints,
                )
            )
        if previous.default_expression_sha256 != current.default_expression_sha256:
            if previous.default_expression_sha256 is None:
                kind = SchemaCompatibilityChangeKind.DEFAULT_ADDED
                verdict = SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE
            elif current.default_expression_sha256 is None:
                kind = SchemaCompatibilityChangeKind.DEFAULT_REMOVED
                verdict = SchemaCompatibilityVerdict.INDETERMINATE
            else:
                kind = SchemaCompatibilityChangeKind.DEFAULT_CHANGED
                verdict = SchemaCompatibilityVerdict.INDETERMINATE
            changes.append(
                _change(
                    component="column",
                    subject=name,
                    change_kind=kind,
                    verdict=verdict,
                    **fingerprints,
                )
            )
    return changes


def _named_component_changes(
    *,
    component: Literal["constraint", "index"],
    baseline: dict[str, PostgisSchemaConstraint | PostgisSchemaIndex],
    candidate: dict[str, PostgisSchemaConstraint | PostgisSchemaIndex],
) -> list[PostgisSchemaCompatibilityChange]:
    changes: list[PostgisSchemaCompatibilityChange] = []
    verdict = (
        SchemaCompatibilityVerdict.INDETERMINATE
        if component == "constraint"
        else SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE
    )
    kinds = {
        "constraint": (
            SchemaCompatibilityChangeKind.CONSTRAINT_ADDED,
            SchemaCompatibilityChangeKind.CONSTRAINT_REMOVED,
            SchemaCompatibilityChangeKind.CONSTRAINT_CHANGED,
        ),
        "index": (
            SchemaCompatibilityChangeKind.INDEX_ADDED,
            SchemaCompatibilityChangeKind.INDEX_REMOVED,
            SchemaCompatibilityChangeKind.INDEX_CHANGED,
        ),
    }[component]
    for name in sorted(candidate.keys() - baseline.keys()):
        changes.append(
            _change(
                component=component,
                subject=name,
                change_kind=kinds[0],
                verdict=verdict,
                current_fingerprint=candidate[name].fingerprint,
            )
        )
    for name in sorted(baseline.keys() - candidate.keys()):
        changes.append(
            _change(
                component=component,
                subject=name,
                change_kind=kinds[1],
                verdict=verdict,
                previous_fingerprint=baseline[name].fingerprint,
            )
        )
    for name in sorted(baseline.keys() & candidate.keys()):
        if baseline[name] != candidate[name]:
            changes.append(
                _change(
                    component=component,
                    subject=name,
                    change_kind=kinds[2],
                    verdict=verdict,
                    previous_fingerprint=baseline[name].fingerprint,
                    current_fingerprint=candidate[name].fingerprint,
                )
            )
    return changes


def assess_postgis_schema_compatibility(
    baseline_snapshot: PostgisSchemaSnapshot,
    candidate_snapshot: PostgisSchemaSnapshot,
    baseline_observation: ArchitectureProviderObservation,
    candidate_observation: ArchitectureProviderObservation,
    baseline_artifact: Artifact,
    candidate_artifact: Artifact,
) -> PostgisSchemaCompatibilityAssessment:
    """Classify bounded PostGIS changes conservatively and deterministically."""

    validate_postgis_schema_evidence_artifact(
        baseline_snapshot, baseline_observation, baseline_artifact
    )
    validate_postgis_schema_evidence_artifact(
        candidate_snapshot, candidate_observation, candidate_artifact
    )
    if (
        baseline_artifact.tenant_id != candidate_artifact.tenant_id
        or baseline_artifact.resource_version_id != candidate_artifact.resource_version_id
    ):
        raise ValueError("schema evidence artifacts must bind one ResourceVersion")
    if (
        baseline_snapshot.provider_namespace != candidate_snapshot.provider_namespace
        or baseline_snapshot.provider_object_id != candidate_snapshot.provider_object_id
    ):
        raise ValueError("schema compatibility requires one provider object")
    changes: list[PostgisSchemaCompatibilityChange] = []
    if baseline_snapshot.relation_kind != candidate_snapshot.relation_kind:
        changes.append(
            _change(
                component="relation",
                subject=candidate_snapshot.provider_object_id,
                change_kind=SchemaCompatibilityChangeKind.RELATION_KIND_CHANGED,
                verdict=SchemaCompatibilityVerdict.BREAKING,
                previous_fingerprint=canonical_json_fingerprint(
                    {"relation_kind": baseline_snapshot.relation_kind}
                ),
                current_fingerprint=canonical_json_fingerprint(
                    {"relation_kind": candidate_snapshot.relation_kind}
                ),
            )
        )
    changes.extend(_column_changes(baseline_snapshot, candidate_snapshot))
    changes.extend(
        _named_component_changes(
            component="constraint",
            baseline={item.name: item for item in baseline_snapshot.constraints},
            candidate={item.name: item for item in candidate_snapshot.constraints},
        )
    )
    changes.extend(
        _named_component_changes(
            component="index",
            baseline={item.name: item for item in baseline_snapshot.indexes},
            candidate={item.name: item for item in candidate_snapshot.indexes},
        )
    )
    changes.sort(key=lambda item: (item.component, item.subject, item.change_kind.value))
    if not changes:
        raise ValueError("schema compatibility requires changed normalized evidence")
    changes_tuple = tuple(changes)
    breaking_count = sum(
        change.verdict is SchemaCompatibilityVerdict.BREAKING for change in changes_tuple
    )
    indeterminate_count = sum(
        change.verdict is SchemaCompatibilityVerdict.INDETERMINATE for change in changes_tuple
    )
    verdict = (
        SchemaCompatibilityVerdict.BREAKING
        if breaking_count
        else SchemaCompatibilityVerdict.INDETERMINATE
        if indeterminate_count
        else SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE
    )
    values = {
        "tenant_id": baseline_artifact.tenant_id,
        "resource_version_id": baseline_observation.resource_version_id,
        "baseline_observation_id": baseline_observation.observation_id,
        "candidate_observation_id": candidate_observation.observation_id,
        "baseline_evidence_artifact_id": baseline_artifact.artifact_id,
        "candidate_evidence_artifact_id": candidate_artifact.artifact_id,
        "baseline_snapshot_sha256": baseline_snapshot.snapshot_sha256,
        "candidate_snapshot_sha256": candidate_snapshot.snapshot_sha256,
        "baseline_evidence_sha256": baseline_artifact.content_sha256,
        "candidate_evidence_sha256": candidate_artifact.content_sha256,
        "changes": changes_tuple,
        "verdict": verdict,
    }
    return PostgisSchemaCompatibilityAssessment(
        breaking_change_count=breaking_count,
        indeterminate_change_count=indeterminate_count,
        assessment_sha256=postgis_schema_compatibility_fingerprint(**values),
        **values,
    )
