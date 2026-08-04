from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from data_agent.data_architecture_ledger import (
    DATA_ARCHITECTURE_OBSERVATION_MIGRATION,
    ArchitectureProviderObservation,
    ProviderObjectState,
    architecture_provider_observation_fingerprint,
)
from data_agent.postgis_architecture_harvester import (
    PostgisArchitectureTarget,
    harvest_postgis_architecture,
)


def _observation(*, state: str = "present") -> ArchitectureProviderObservation:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    values = {
        "tenant_id": "harvest-test",
        "resource_version_id": uuid4(),
        "provider_system": "postgis",
        "provider_namespace": "local/postgres",
        "provider_object_id": "geo.parcels",
        "object_state": state,
        "source_revision": "schema-sha256:" + "a" * 64,
        "schema_content_sha256": "a" * 64,
        "schema_version_sha256": "b" * 64,
        "physical_location_sha256": "c" * 64,
        "observed_at": observed_at,
        "fresh_until": observed_at + timedelta(minutes=5),
    }
    if state == "tombstoned":
        for field in (
            "source_revision",
            "schema_content_sha256",
            "schema_version_sha256",
            "physical_location_sha256",
        ):
            values[field] = None
    fingerprint = architecture_provider_observation_fingerprint(**values)
    return ArchitectureProviderObservation(
        observation_id=uuid4(),
        observation_sha256=fingerprint,
        observed_by="workload:postgis-harvester",
        recorded_at=observed_at,
        **values,
    )


def test_provider_observation_requires_bounded_present_or_empty_tombstone() -> None:
    present = _observation()
    tombstone = _observation(state=ProviderObjectState.TOMBSTONED)

    assert present.object_state == ProviderObjectState.PRESENT
    assert tombstone.schema_content_sha256 is None
    with pytest.raises(ValidationError, match="requires revision and fingerprints"):
        ArchitectureProviderObservation.model_validate(
            present.model_dump() | {"source_revision": None}
        )
    with pytest.raises(ValidationError, match="cannot carry current fingerprints"):
        ArchitectureProviderObservation.model_validate(
            tombstone.model_dump() | {"schema_content_sha256": "a" * 64}
        )


def test_harvester_rejects_non_postgresql_engine_before_access() -> None:
    target = PostgisArchitectureTarget(
        tenant_id="harvest-test",
        resource_version_id=uuid4(),
        provider_ref="local-postgis",
        schema_name="geo",
        table_name="parcels",
        snapshot_ref="snapshot:1",
        content_checksum="a" * 64,
    )
    engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    with pytest.raises(ValueError, match="requires PostgreSQL"):
        harvest_postgis_architecture(
            engine,
            target,
            observed_by="workload:postgis-harvester",
        )


def test_observation_rejects_non_positive_freshness_window() -> None:
    observation = _observation()

    with pytest.raises(ValidationError, match="freshness must be 5..86400"):
        ArchitectureProviderObservation.model_validate(
            observation.model_dump()
            | {"fresh_until": observation.observed_at}
        )


def test_observation_migration_is_reference_only_rls_and_append_only() -> None:
    sql = DATA_ARCHITECTURE_OBSERVATION_MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS gda_control.architecture_provider_observation" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "reject_immutable_mutation()" in sql
    assert "GRANT SELECT, INSERT" in sql
    assert "JSONB" not in sql
