from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from data_agent.data_architecture_ledger import ProviderObjectState
from data_agent.duckdb_architecture_harvester import (
    DuckdbArchitectureTarget,
    harvest_duckdb_architecture,
)


def _target(database: Path) -> DuckdbArchitectureTarget:
    return DuckdbArchitectureTarget(
        tenant_id="duckdb-harvest-test",
        resource_version_id=uuid4(),
        provider_ref="local-duckdb",
        database_ref="land-use",
        schema_name="geo",
        table_name="parcels",
        snapshot_ref="snapshot:1",
        content_checksum="a" * 64,
    )


def test_real_duckdb_file_harvest_is_deterministic_and_read_only(tmp_path: Path) -> None:
    import duckdb

    database = tmp_path / "land-use.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("CREATE SCHEMA geo")
    connection.execute(
        "CREATE TABLE geo.parcels ("
        "parcel_id INTEGER PRIMARY KEY, "
        "land_use VARCHAR NOT NULL, "
        "area DOUBLE DEFAULT 0"
        ")"
    )
    connection.execute("CREATE INDEX parcels_land_use_idx ON geo.parcels(land_use)")
    connection.close()

    target = _target(database)
    observed_at = datetime(2026, 8, 23, 12, tzinfo=UTC)
    first = harvest_duckdb_architecture(
        database,
        target,
        observed_by="workload:duckdb-harvester",
        observed_at=observed_at,
    )
    second = harvest_duckdb_architecture(
        database,
        target,
        observed_by="workload:duckdb-harvester",
        observed_at=observed_at,
    )

    assert first.observation.object_state is ProviderObjectState.PRESENT
    assert first.schema_snapshot is not None
    assert first.schema_candidate is not None
    assert first.physical_location_candidate is not None
    assert [column.name for column in first.schema_snapshot.columns] == [
        "parcel_id",
        "land_use",
        "area",
    ]
    assert first.schema_snapshot.snapshot_sha256 == first.observation.schema_content_sha256
    assert first.observation == second.observation
    assert first.schema_snapshot == second.schema_snapshot
    assert "CREATE TABLE" not in first.schema_snapshot.model_dump_json()


def test_duckdb_schema_drift_keeps_location_and_changes_schema(tmp_path: Path) -> None:
    import duckdb

    database = tmp_path / "land-use.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("CREATE SCHEMA geo")
    connection.execute("CREATE TABLE geo.parcels (parcel_id INTEGER, land_use VARCHAR)")
    connection.close()
    target = _target(database)
    baseline = harvest_duckdb_architecture(
        database,
        target,
        observed_by="workload:duckdb-harvester",
        observed_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
    )

    connection = duckdb.connect(str(database))
    connection.execute("ALTER TABLE geo.parcels ADD COLUMN area DOUBLE")
    connection.close()
    changed = harvest_duckdb_architecture(
        database,
        target,
        observed_by="workload:duckdb-harvester",
        observed_at=datetime(2026, 8, 23, 12, 1, tzinfo=UTC),
    )

    assert baseline.schema_snapshot is not None
    assert changed.schema_snapshot is not None
    assert baseline.observation.schema_content_sha256 != changed.observation.schema_content_sha256
    assert baseline.observation.physical_location_sha256 == (
        changed.observation.physical_location_sha256
    )
    assert baseline.observation.source_revision != changed.observation.source_revision


def test_duckdb_drop_emits_tombstone_without_candidates(tmp_path: Path) -> None:
    import duckdb

    database = tmp_path / "land-use.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("CREATE SCHEMA geo")
    connection.execute("CREATE TABLE geo.parcels (parcel_id INTEGER)")
    connection.close()
    target = _target(database)
    present = harvest_duckdb_architecture(
        database,
        target,
        observed_by="workload:duckdb-harvester",
        observed_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
    )
    assert present.observation.object_state is ProviderObjectState.PRESENT

    connection = duckdb.connect(str(database))
    connection.execute("DROP TABLE geo.parcels")
    connection.close()
    tombstone = harvest_duckdb_architecture(
        database,
        target,
        observed_by="workload:duckdb-harvester",
        observed_at=datetime(2026, 8, 23, 12, 1, tzinfo=UTC),
    )

    assert tombstone.observation.object_state is ProviderObjectState.TOMBSTONED
    assert tombstone.observation.source_revision is None
    assert tombstone.schema_snapshot is None
    assert tombstone.schema_candidate is None
    assert tombstone.physical_location_candidate is None
