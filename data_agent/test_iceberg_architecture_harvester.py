from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from data_agent.data_architecture_ledger import ProviderObjectState
from data_agent.iceberg_architecture_harvester import (
    IcebergArchitectureError,
    IcebergArchitectureTarget,
    harvest_gravitino_iceberg_table,
    project_iceberg_rest_table_response,
)


def _target() -> IcebergArchitectureTarget:
    tenant = "iceberg-harvest-test"
    return IcebergArchitectureTarget(
        tenant_id=tenant,
        resource_urn=f"gda://{tenant}/dataset/parcels",
        resource_version_id=uuid4(),
        metalake="lakehouse",
        catalog="prod",
        namespace="geo",
        object_name="parcels",
        snapshot_ref="iceberg-table:parcels",
        content_checksum="b" * 64,
    )


def _table(*, snapshot: str = "100", extra_column: bool = False) -> dict:
    columns = [
        {"name": "parcel_id", "type": "long", "nullable": False, "field-id": 1},
        {"name": "geom_wkb", "type": "binary", "nullable": True, "field-id": 2},
    ]
    if extra_column:
        columns.append({"name": "land_use", "type": "string", "nullable": True, "field-id": 3})
    return {
        "name": "parcels",
        "columns": columns,
        "properties": {
            "provider": "iceberg",
            "format-version": "2",
            "current-snapshot-id": snapshot,
            "current-schema-id": "3",
            "location": "s3://warehouse/geo/parcels",
        },
    }


def _table_with_lineage() -> dict:
    table = _table(snapshot="101")
    table["snapshots"] = [
        {"snapshot_id": "100", "parent_id": None, "operation": "append"},
        {"snapshot_id": "101", "parent_id": "100", "operation": "append"},
    ]
    return table


def test_iceberg_snapshot_and_schema_are_separate_revisions() -> None:
    target = _target()
    observed_at = datetime(2026, 8, 23, tzinfo=UTC)
    baseline = harvest_gravitino_iceberg_table(
        _table(), target, observed_by="workload:iceberg-harvester", observed_at=observed_at
    )
    replay = harvest_gravitino_iceberg_table(
        _table(), target, observed_by="workload:iceberg-harvester", observed_at=observed_at
    )
    same_schema_new_snapshot = harvest_gravitino_iceberg_table(
        _table(snapshot="101"),
        target,
        observed_by="workload:iceberg-harvester",
        observed_at=observed_at + timedelta(minutes=1),
    )
    schema_drift = harvest_gravitino_iceberg_table(
        _table(snapshot="102", extra_column=True),
        target,
        observed_by="workload:iceberg-harvester",
        observed_at=observed_at + timedelta(minutes=2),
    )

    assert baseline.observation == replay.observation
    assert baseline.observation.source_revision == "iceberg-snapshot:100"
    assert (
        same_schema_new_snapshot.observation.schema_content_sha256
        == baseline.observation.schema_content_sha256
    )
    assert (
        same_schema_new_snapshot.observation.physical_location_sha256
        != baseline.observation.physical_location_sha256
    )
    assert (
        schema_drift.observation.schema_content_sha256
        != baseline.observation.schema_content_sha256
    )
    assert (
        schema_drift.observation.physical_location_sha256
        != same_schema_new_snapshot.observation.physical_location_sha256
    )


def test_confirmed_not_found_is_the_only_tombstone_input() -> None:
    tombstone = harvest_gravitino_iceberg_table(
        None,
        _target(),
        observed_by="workload:iceberg-harvester",
    )

    assert tombstone.observation.object_state is ProviderObjectState.TOMBSTONED
    assert tombstone.schema_candidate is None

    with pytest.raises(IcebergArchitectureError, match="not backed by Iceberg"):
        harvest_gravitino_iceberg_table(
            _table() | {"properties": {"provider": "parquet"}},
            _target(),
            observed_by="workload:iceberg-harvester",
        )


def test_snapshot_lineage_is_bounded_and_ends_at_current_snapshot() -> None:
    harvest = harvest_gravitino_iceberg_table(
        _table_with_lineage(),
        _target(),
        observed_by="workload:iceberg-harvester",
    )

    assert harvest.snapshot_lineage is not None
    assert [entry.snapshot_id for entry in harvest.snapshot_lineage] == ["100", "101"]
    assert harvest.snapshot_lineage[-1].parent_id == "100"

    invalid = _table_with_lineage()
    invalid["snapshots"][1]["parent_id"] = "999"
    with pytest.raises(IcebergArchitectureError, match="parent must precede child"):
        harvest_gravitino_iceberg_table(
            invalid,
            _target(),
            observed_by="workload:iceberg-harvester",
        )


def test_iceberg_rest_metadata_projects_to_bounded_harvester_payload() -> None:
    response = {
        "metadata-location": "s3://warehouse/geo/parcels/metadata/v2.metadata.json",
        "metadata": {
            "format-version": 2,
            "location": "s3://warehouse/geo/parcels",
            "current-schema-id": 1,
            "current-snapshot-id": 101,
            "schemas": [
                {
                    "schema-id": 1,
                    "fields": [
                        {"id": 1, "name": "parcel_id", "required": True, "type": "long"},
                        {
                            "id": 2,
                            "name": "geom_wkb",
                            "required": False,
                            "type": {"type": "fixed", "length": 16},
                        },
                    ],
                }
            ],
            "snapshots": [
                {
                    "snapshot-id": 100,
                    "parent-snapshot-id": None,
                    "summary": {"operation": "append"},
                },
                {
                    "snapshot-id": 101,
                    "parent-snapshot-id": 100,
                    "summary": {"operation": "append"},
                },
            ],
        },
    }

    projected = project_iceberg_rest_table_response(response, object_name="parcels")

    assert projected["name"] == "parcels"
    assert projected["properties"]["current-snapshot-id"] == "101"
    assert projected["columns"][0]["nullable"] is False
    assert projected["columns"][1]["type"] == '{"length":16,"type":"fixed"}'
    assert projected["snapshots"][-1]["parent_id"] == "100"


def test_iceberg_rest_projection_rejects_missing_bounded_facts() -> None:
    with pytest.raises(IcebergArchitectureError, match="metadata"):
        project_iceberg_rest_table_response(
            {"metadata-location": "s3://warehouse"}, object_name="parcels"
        )


@pytest.mark.parametrize(
    "properties",
    [
        {"provider": "iceberg", "format-version": "2", "location": "s3://warehouse/geo/parcels"},
        {
            "provider": "iceberg",
            "format-version": "2",
            "current-snapshot-id": "not-a-number",
            "location": "s3://warehouse/geo/parcels",
        },
        {
            "provider": "iceberg",
            "format-version": "2",
            "current-snapshot-id": "100",
            "location": "s3://user:secret@warehouse/geo/parcels",
        },
    ],
)
def test_incomplete_or_credentialed_provider_facts_fail_closed(properties: dict) -> None:
    with pytest.raises(IcebergArchitectureError):
        harvest_gravitino_iceberg_table(
            _table() | {"properties": properties},
            _target(),
            observed_by="workload:iceberg-harvester",
        )
