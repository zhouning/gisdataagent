"""Tests for bounded PostGIS schema evidence and compatibility verdicts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.data_architecture_ledger import (
    ArchitectureProviderObservation,
    architecture_provider_observation_fingerprint,
)
from data_agent.postgis_schema_evidence import (
    PostgisSchemaColumn,
    PostgisSchemaCompatibilityAssessment,
    PostgisSchemaConstraint,
    PostgisSchemaIndex,
    PostgisSchemaSnapshot,
    SchemaCompatibilityVerdict,
    assess_postgis_schema_compatibility,
    build_postgis_schema_evidence_artifact,
    postgis_schema_snapshot_bytes,
    postgis_schema_snapshot_fingerprint,
)

NOW = datetime(2026, 8, 3, 10, tzinfo=UTC)
TENANT = "schema-evidence"
RESOURCE_VERSION_ID = UUID("10000000-0000-4000-8000-000000000001")


def _snapshot(
    *,
    added_column: PostgisSchemaColumn | None = None,
    remove_land_use: bool = False,
    constraint_hash: str = "d" * 64,
) -> PostgisSchemaSnapshot:
    columns = [
        PostgisSchemaColumn(
            ordinal=1,
            name="parcel_id",
            data_type="bigint",
            not_null=True,
            identity_kind="",
            generated_kind="",
        ),
        PostgisSchemaColumn(
            ordinal=2,
            name="land_use",
            data_type="text",
            not_null=True,
            identity_kind="",
            generated_kind="",
        ),
        PostgisSchemaColumn(
            ordinal=3,
            name="geom",
            data_type="geometry(Polygon,4326)",
            not_null=True,
            identity_kind="",
            generated_kind="",
        ),
    ]
    if remove_land_use:
        columns = [column for column in columns if column.name != "land_use"]
    if added_column is not None:
        columns.append(added_column)
    constraints = (
        PostgisSchemaConstraint(
            name="parcels_pkey",
            constraint_type="p",
            definition_sha256=constraint_hash,
        ),
    )
    indexes = (
        PostgisSchemaIndex(
            name="parcels_geom_gix",
            definition_sha256="e" * 64,
        ),
    )
    values = {
        "provider_namespace": "local/postgres",
        "provider_object_id": "public.parcels",
        "relation_kind": "r",
        "columns": tuple(columns),
        "constraints": constraints,
        "indexes": indexes,
    }
    return PostgisSchemaSnapshot(
        snapshot_sha256=postgis_schema_snapshot_fingerprint(**values),
        **values,
    )


def _observation(
    snapshot: PostgisSchemaSnapshot,
    *,
    observation_id: UUID,
    observed_at: datetime,
) -> ArchitectureProviderObservation:
    values = {
        "tenant_id": TENANT,
        "resource_version_id": RESOURCE_VERSION_ID,
        "provider_system": "postgis",
        "provider_namespace": snapshot.provider_namespace,
        "provider_object_id": snapshot.provider_object_id,
        "object_state": "present",
        "source_revision": f"schema-sha256:{snapshot.snapshot_sha256}",
        "schema_content_sha256": snapshot.snapshot_sha256,
        "schema_version_sha256": "a" * 64,
        "physical_location_sha256": "b" * 64,
        "observed_at": observed_at,
        "fresh_until": observed_at + timedelta(minutes=5),
    }
    return ArchitectureProviderObservation(
        observation_id=observation_id,
        observation_sha256=architecture_provider_observation_fingerprint(**values),
        observed_by="workload:postgis-harvester",
        recorded_at=observed_at,
        **values,
    )


def _assessment(
    baseline: PostgisSchemaSnapshot,
    candidate: PostgisSchemaSnapshot,
) -> PostgisSchemaCompatibilityAssessment:
    baseline_observation = _observation(
        baseline,
        observation_id=UUID("20000000-0000-4000-8000-000000000001"),
        observed_at=NOW,
    )
    candidate_observation = _observation(
        candidate,
        observation_id=UUID("20000000-0000-4000-8000-000000000002"),
        observed_at=NOW + timedelta(minutes=1),
    )
    baseline_artifact = build_postgis_schema_evidence_artifact(
        baseline,
        baseline_observation,
        artifact_id=UUID("30000000-0000-4000-8000-000000000001"),
        storage_uri="s3://architecture-evidence/baseline.json",
        created_by="workload:postgis-harvester",
    )
    candidate_artifact = build_postgis_schema_evidence_artifact(
        candidate,
        candidate_observation,
        artifact_id=UUID("30000000-0000-4000-8000-000000000002"),
        storage_uri="s3://architecture-evidence/candidate.json",
        created_by="workload:postgis-harvester",
    )
    return assess_postgis_schema_compatibility(
        baseline,
        candidate,
        baseline_observation,
        candidate_observation,
        baseline_artifact,
        candidate_artifact,
    )


def test_nullable_column_addition_is_backward_compatible() -> None:
    baseline = _snapshot()
    candidate = _snapshot(
        added_column=PostgisSchemaColumn(
            ordinal=4,
            name="zoning_code",
            data_type="text",
            not_null=False,
        )
    )

    assessment = _assessment(baseline, candidate)

    assert assessment.verdict is SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE
    assert assessment.breaking_change_count == 0
    assert [change.change_kind for change in assessment.changes] == ["column_added"]


def test_required_column_without_default_and_removed_column_are_breaking() -> None:
    baseline = _snapshot()
    required = _snapshot(
        added_column=PostgisSchemaColumn(
            ordinal=4,
            name="required_code",
            data_type="text",
            not_null=True,
        )
    )
    removed = _snapshot(remove_land_use=True)

    required_assessment = _assessment(baseline, required)
    removed_assessment = _assessment(baseline, removed)

    assert required_assessment.verdict is SchemaCompatibilityVerdict.BREAKING
    assert removed_assessment.verdict is SchemaCompatibilityVerdict.BREAKING
    assert removed_assessment.changes[0].change_kind == "column_removed"


def test_constraint_change_is_indeterminate_instead_of_guessed_compatible() -> None:
    assessment = _assessment(_snapshot(), _snapshot(constraint_hash="f" * 64))

    assert assessment.verdict is SchemaCompatibilityVerdict.INDETERMINATE
    assert assessment.indeterminate_change_count == 1
    assert assessment.changes[0].change_kind == "constraint_changed"


def test_snapshot_and_artifact_do_not_expose_provider_expressions() -> None:
    secret_literal = "sensitive-default-literal"
    snapshot = _snapshot(
        added_column=PostgisSchemaColumn(
            ordinal=4,
            name="zoning_code",
            data_type="text",
            not_null=True,
            default_expression_sha256="c" * 64,
        )
    )
    observation = _observation(
        snapshot,
        observation_id=UUID("20000000-0000-4000-8000-000000000003"),
        observed_at=NOW,
    )
    artifact = build_postgis_schema_evidence_artifact(
        snapshot,
        observation,
        artifact_id=UUID("30000000-0000-4000-8000-000000000003"),
        storage_uri="s3://architecture-evidence/default.json",
        created_by="workload:postgis-harvester",
    )

    assert secret_literal not in postgis_schema_snapshot_bytes(snapshot).decode()
    assert secret_literal not in artifact.model_dump_json()
    assert artifact.manifest["snapshot_sha256"] == snapshot.snapshot_sha256


def test_artifact_tampering_is_rejected_by_assessor() -> None:
    baseline = _snapshot()
    candidate = _snapshot(
        added_column=PostgisSchemaColumn(
            ordinal=4,
            name="zoning_code",
            data_type="text",
            not_null=False,
        )
    )
    baseline_observation = _observation(
        baseline,
        observation_id=UUID("20000000-0000-4000-8000-000000000001"),
        observed_at=NOW,
    )
    candidate_observation = _observation(
        candidate,
        observation_id=UUID("20000000-0000-4000-8000-000000000002"),
        observed_at=NOW + timedelta(minutes=1),
    )
    baseline_artifact = build_postgis_schema_evidence_artifact(
        baseline,
        baseline_observation,
        artifact_id=UUID("30000000-0000-4000-8000-000000000001"),
        storage_uri="s3://architecture-evidence/baseline.json",
        created_by="workload:postgis-harvester",
    )
    candidate_artifact = build_postgis_schema_evidence_artifact(
        candidate,
        candidate_observation,
        artifact_id=UUID("30000000-0000-4000-8000-000000000002"),
        storage_uri="s3://architecture-evidence/candidate.json",
        created_by="workload:postgis-harvester",
    ).model_copy(update={"content_sha256": "0" * 64})

    with pytest.raises(ValueError, match="does not bind"):
        assess_postgis_schema_compatibility(
            baseline,
            candidate,
            baseline_observation,
            candidate_observation,
            baseline_artifact,
            candidate_artifact,
        )


def test_compatibility_assessment_rejects_tampered_fingerprint() -> None:
    baseline = _snapshot()
    candidate = _snapshot(
        added_column=PostgisSchemaColumn(
            ordinal=4,
            name="zoning_code",
            data_type="text",
            not_null=False,
        )
    )
    assessment = _assessment(baseline, candidate)

    with pytest.raises(ValidationError, match="assessment_sha256"):
        PostgisSchemaCompatibilityAssessment.model_validate(
            assessment.model_dump() | {"assessment_sha256": "0" * 64}
        )
