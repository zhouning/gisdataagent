from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import unquote, urlsplit

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from data_agent.data_ingestion import (
    ArcGISIngestionExecutor,
    GeometryDimensionNormalizer,
    GeometryTypeNormalizer,
    GeoParquetLakeWriter,
    IngestionCancelled,
    IngestionDefinitionSpec,
    IngestionRepository,
    IngestionWorker,
    PostGISSnapshotWriter,
    QualityAccumulator,
    safe_table_name,
)


def _frame(start: int, count: int = 2) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "OBJECTID": list(range(start, start + count)),
            "name": [f"feature-{value}" for value in range(start, start + count)],
        },
        geometry=[Point(value, value) for value in range(start, start + count)],
        crs="EPSG:4326",
    )


def test_definition_requires_safe_postgis_target():
    with pytest.raises(ValueError, match="lowercase SQL identifier"):
        IngestionDefinitionSpec(
            target_name="DMT buildings",
            target_mode="postgis",
            target_table="Bad-Table",
        )
    spec = IngestionDefinitionSpec(
        target_name="DMT buildings",
        target_mode="lakehouse_postgis",
        target_table="dmt_buildings",
        schedule_policy="interval:30m",
    )
    assert spec.page_size == 2000
    assert safe_table_name("DMT Buildings 2026") == "dmt_buildings_2026"
    with pytest.raises(ValueError, match="geometry_dimension_policy"):
        IngestionDefinitionSpec(
            target_name="DMT buildings",
            target_mode="postgis",
            target_table="dmt_buildings",
            config={"geometry_dimension_policy": "mixed"},
        )
    with pytest.raises(ValueError, match="geometry_type_policy"):
        IngestionDefinitionSpec(
            target_name="DMT buildings",
            target_mode="postgis",
            target_table="dmt_buildings",
            config={"geometry_type_policy": "generic"},
        )


def test_postgis_staging_name_leaves_room_for_automatic_spatial_index():
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    writer = PostGISSnapshotWriter(
        engine,
        "dmt_building_survey_buildings_stg",
        "b4f7be7e-fead-4fbe-9a7c-e91612d4a7f5",
    )

    assert len(f"idx_{writer.staging_table}_geometry") <= 63


def test_geometry_dimension_normalizer_forces_contract_to_xy():
    frame = gpd.GeoDataFrame(
        {"OBJECTID": [1, 2]},
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]),
            Polygon([(0, 0, 7), (1, 0, 7), (1, 1, 7), (0, 0, 7)]),
        ],
        crs="EPSG:4326",
    )

    normalizer = GeometryDimensionNormalizer("xy")
    normalized = normalizer.normalize(frame)

    assert normalized.geometry.has_z.tolist() == [False, False]
    assert frame.geometry.has_z.tolist() == [False, True]
    assert normalizer.summary() == {
        "policy": "xy",
        "records_with_geometry": 2,
        "source_records_with_z": 1,
        "records_normalized": 1,
        "xyz_fill_value": None,
    }


def test_geometry_type_normalizer_promotes_polygons_to_multi():
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])
    frame = gpd.GeoDataFrame(
        {"OBJECTID": [1, 2]},
        geometry=[polygon, MultiPolygon([polygon])],
        crs="EPSG:4326",
    )

    normalizer = GeometryTypeNormalizer("multi")
    normalized = normalizer.normalize(frame)

    assert normalized.geometry.geom_type.tolist() == ["MultiPolygon", "MultiPolygon"]
    assert frame.geometry.geom_type.tolist() == ["Polygon", "MultiPolygon"]
    assert normalizer.summary() == {
        "policy": "multi",
        "source_type_counts": {"MultiPolygon": 1, "Polygon": 1},
        "records_normalized": 1,
    }


def test_geoparquet_lake_writer_commits_partition_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("GDA_INGEST_LAKE_ROOT", str(tmp_path))
    run = {
        "run_id": "a28d81b4-2235-4ed1-99c2-769ae5972cc3",
        "tenant_id": "local-dev",
        "owner_username": "admin",
        "source_id": 7,
    }
    definition = {"target_name": "DMT Buildings"}
    writer = GeoParquetLakeWriter(run, definition)
    first = writer.write(0, _frame(1))
    writer.write(1, _frame(3, 1))
    result = writer.finalize({"records_written": 3})

    output = Path(unquote(urlsplit(result["target_uri"]).path))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert first["content_sha256"]
    assert manifest["records_written"] == 3
    assert [part["records"] for part in manifest["parts"]] == [2, 1]
    assert (output / "_SUCCESS").read_text(encoding="ascii") == result["content_sha256"]


def test_geoparquet_lake_writer_abort_discards_uncommitted_staging(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GDA_INGEST_LAKE_ROOT", str(tmp_path))
    run = {
        "run_id": "a28d81b4-2235-4ed1-99c2-769ae5972cc3",
        "tenant_id": "local-dev",
        "owner_username": "admin",
        "source_id": 7,
    }
    writer = GeoParquetLakeWriter(run, {"target_name": "DMT Buildings"})
    writer.write(0, _frame(1, 1))

    writer.abort()

    assert not writer.staging.exists()


def test_cloud_lake_uses_dedicated_bucket_and_commits_marker_last(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GDA_INGEST_LAKE_ROOT", str(tmp_path))
    monkeypatch.setenv("GDA_INGEST_LAKE_BACKEND", "cloud")
    monkeypatch.setenv("GDA_INGEST_LAKE_BUCKET", "dedicated-ingestion-lake")
    monkeypatch.setenv("GDA_INGEST_LAKE_PREFIX", "raw/arcgis")
    monkeypatch.setenv("CLOUD_STORAGE_PROVIDER", "aws")
    run = {
        "run_id": "a28d81b4-2235-4ed1-99c2-769ae5972cc3",
        "tenant_id": "local-dev",
        "owner_username": "admin",
        "source_id": 7,
    }
    adapter = MagicMock()
    adapter.exists.return_value = False
    adapter.upload.return_value = True
    adapter.get_bucket_name.return_value = "dedicated-ingestion-lake"

    with patch(
        "data_agent.cloud_storage.AWSS3Adapter", return_value=adapter
    ) as adapter_type:
        writer = GeoParquetLakeWriter(run, {"target_name": "DMT Buildings"})
        writer.write(0, _frame(1, 1))
        result = writer.finalize({"records_written": 1})

    adapter_type.assert_called_once_with(bucket="dedicated-ingestion-lake")
    uploaded_keys = [call.args[1] for call in adapter.upload.call_args_list]
    assert uploaded_keys[-1].endswith("/_SUCCESS")
    assert result["target_uri"].startswith(
        "s3://dedicated-ingestion-lake/raw/arcgis/"
    )


def test_cloud_lake_replay_verifies_committed_manifest_before_upload(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GDA_INGEST_LAKE_ROOT", str(tmp_path))
    run = {
        "run_id": "a28d81b4-2235-4ed1-99c2-769ae5972cc3",
        "tenant_id": "local-dev",
        "owner_username": "admin",
        "source_id": 7,
    }
    definition = {"target_name": "DMT Buildings"}
    writer = GeoParquetLakeWriter(run, definition)
    writer.write(0, _frame(1, 1))
    local = writer.finalize({"records_written": 1})

    monkeypatch.setenv("GDA_INGEST_LAKE_BACKEND", "cloud")
    monkeypatch.setenv("GDA_INGEST_LAKE_BUCKET", "ingestion-lake")
    monkeypatch.setenv("CLOUD_STORAGE_PROVIDER", "aws")
    adapter = MagicMock()
    adapter.exists.return_value = True
    adapter.get_bucket_name.return_value = "ingestion-lake"

    def download_manifest(_key, path):
        Path(path).write_text(
            json.dumps({"content_sha256": local["content_sha256"]}),
            encoding="utf-8",
        )
        return True

    adapter.download.side_effect = download_manifest
    with patch("data_agent.cloud_storage.AWSS3Adapter", return_value=adapter):
        replay = GeoParquetLakeWriter(run, definition)
        replay.write(0, _frame(1, 1))
        result = replay.finalize({"records_written": 1})

    assert result["content_sha256"] == local["content_sha256"]
    adapter.upload.assert_not_called()


@pytest.mark.asyncio
async def test_external_schedule_driver_does_not_create_schedule_runs():
    repository = MagicMock()
    repository.claim_next.return_value = None

    worked = await IngestionWorker(
        repository, worker_id="worker:test", schedule_driver="external"
    ).run_once()

    assert worked is False
    repository.enqueue_due_schedules.assert_not_called()
    repository.claim_next.assert_called_once_with("worker:test")


def test_repository_enforces_transition_row_count_and_reports_cancellation():
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    rejected_update = MagicMock(rowcount=0)
    current_state = MagicMock()
    current_state.mappings.return_value.one_or_none.return_value = {
        "status": "cancelling",
        "worker_id": "worker:test",
        "cancellation_requested": True,
    }
    connection.execute.side_effect = [rejected_update, current_state]

    with pytest.raises(IngestionCancelled, match="cancelled by user"):
        IngestionRepository(engine=engine).begin_commit(
            "a28d81b4-2235-4ed1-99c2-769ae5972cc3", "worker:test"
        )


def test_quality_accumulator_rejects_mid_snapshot_schema_drift():
    quality = QualityAccumulator()
    quality.observe(_frame(1))
    changed = _frame(3).rename(columns={"name": "label"})
    with pytest.raises(RuntimeError, match="schema changed"):
        quality.observe(changed)


def test_run_listing_prioritizes_active_runs_before_recent_terminal_history():
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    connection.execute.return_value = result

    IngestionRepository(engine=engine).list_runs(
        "admin", source_id=7, limit=30,
    )

    statement = str(connection.execute.call_args.args[0])
    assert "CASE WHEN status IN" in statement
    assert "'queued', 'running', 'committing', 'cancelling'" in statement


class _FakeRepository:
    def __init__(self) -> None:
        self.engine = MagicMock()
        self.definition = {
            "id": 9,
            "source_id": 7,
            "owner_username": "admin",
            "tenant_id": "local-dev",
            "target_name": "DMT Buildings",
            "target_mode": "lakehouse",
            "target_table": None,
            "schedule_policy": "on_demand",
            "write_mode": "full_snapshot",
            "max_records": 100,
            "page_size": 2,
        }
        self.initialized = None
        self.batches = []
        self.completed = None
        self.failed = None
        self.commit_started = None
        self.cancel_on_commit = False
        self.lease_renewals = []

    def get_definition(self, definition_id, owner):
        assert (definition_id, owner) == (9, "admin")
        return self.definition

    def initialize_run(self, run_id, worker_id, **values):
        self.initialized = (run_id, worker_id, values)

    def renew_lease(self, run_id, worker_id):
        self.lease_renewals.append((run_id, worker_id))
        return True

    def cancellation_requested(self, _run_id):
        return False

    def record_batch(self, run_id, worker_id, batch, **counts):
        self.batches.append((run_id, worker_id, batch, counts))

    def begin_commit(self, run_id, worker_id):
        if self.cancel_on_commit:
            from data_agent.data_ingestion import IngestionCancelled

            raise IngestionCancelled("ingestion cancelled by user")
        self.commit_started = (run_id, worker_id)

    def complete(self, run_id, worker_id, **values):
        self.completed = (run_id, worker_id, values)

    def fail(self, run_id, worker_id, message, *, cancelled=False):
        self.failed = (run_id, worker_id, message, cancelled)
        return True


@pytest.mark.asyncio
async def test_executor_streams_batches_then_publishes_one_asset():
    repository = _FakeRepository()
    run = {
        "run_id": "a28d81b4-2235-4ed1-99c2-769ae5972cc3",
        "definition_id": 9,
        "source_id": 7,
        "owner_username": "admin",
        "tenant_id": "local-dev",
        "trigger_type": "manual",
    }
    source = {
        "id": 7,
        "source_name": "DMT Buildings",
        "source_type": "arcgis_rest",
        "endpoint_url": "https://example.com/FeatureServer/0",
        "auth_config": {},
        "query_config": {},
        "schema_mapping": {},
        "default_crs": "EPSG:4326",
        "enabled": True,
    }
    snapshot = SimpleNamespace(
        layer_id=0,
        where="1=1",
        out_fields="*",
        object_id_field="OBJECTID",
        object_ids=(1, 2, 3),
        record_count=3,
        matched_record_count=3,
        truncated=False,
    )

    class FakeConnector:
        async def create_query_snapshot(self, *_args, **_kwargs):
            return snapshot

        async def iter_snapshot_pages(self, *_args, **_kwargs):
            for index, frame in enumerate((_frame(1), _frame(3, 1))):
                ids = snapshot.object_ids[index * 2 : index * 2 + len(frame)]
                yield {
                    "batch_index": index,
                    "object_ids": ids,
                    "frame": frame,
                    "records_read": len(frame),
                    "records_total": 3,
                }

    lake = MagicMock()
    lake.write.side_effect = [
        {"content_sha256": "1" * 64, "lake_uri": "file:///part-0"},
        {"content_sha256": "2" * 64, "lake_uri": "file:///part-1"},
    ]
    lake.finalize.return_value = {
        "target_uri": "file:///lake/snapshot",
        "content_sha256": "a" * 64,
        "manifest": {
            "records_written": 3,
            "parts": [
                {"name": "part-00000.parquet", "size_bytes": 120},
                {"name": "part-00001.parquet", "size_bytes": 80},
            ],
        },
    }
    publisher = MagicMock()
    publisher.publish.return_value = {
        "asset_id": 41,
        "source_asset_id": 40,
        "asset_version": 1,
    }

    with (
        patch("data_agent.virtual_sources.get_virtual_source", return_value=source),
        patch(
            "data_agent.connectors.arcgis_rest.ArcGISRestConnector",
            return_value=FakeConnector(),
        ),
        patch("data_agent.data_ingestion.GeoParquetLakeWriter", return_value=lake),
        patch("data_agent.data_ingestion.AssetPublisher", return_value=publisher),
        patch(
            "data_agent.data_ingestion.publish_platform_lineage",
            return_value={"status": "recorded"},
        ),
    ):
        await ArcGISIngestionExecutor(repository, worker_id="worker:test").execute(run)

    assert repository.failed is None
    assert repository.initialized[2]["records_total"] == 3
    assert [entry[3]["records_read"] for entry in repository.batches] == [2, 3]
    assert publisher.publish.call_count == 1
    assert publisher.publish.call_args.kwargs["file_size_bytes"] == 200
    assert repository.commit_started == (run["run_id"], "worker:test")
    assert repository.completed[2]["asset_id"] == 41
    assert repository.completed[2]["quality_summary"]["record_count_complete"] is True


@pytest.mark.asyncio
async def test_executor_does_not_publish_when_cancelled_at_commit_boundary():
    repository = _FakeRepository()
    repository.cancel_on_commit = True
    run = {
        "run_id": "a28d81b4-2235-4ed1-99c2-769ae5972cc3",
        "definition_id": 9,
        "source_id": 7,
        "owner_username": "admin",
        "tenant_id": "local-dev",
        "trigger_type": "manual",
    }
    source = {
        "id": 7,
        "source_name": "DMT Buildings",
        "source_type": "arcgis_rest",
        "endpoint_url": "https://example.com/FeatureServer/0",
        "auth_config": {},
        "query_config": {},
        "schema_mapping": {},
        "default_crs": "EPSG:4326",
        "enabled": True,
    }
    snapshot = SimpleNamespace(
        layer_id=0,
        where="1=1",
        out_fields="*",
        object_id_field="OBJECTID",
        object_ids=(1,),
        record_count=1,
        matched_record_count=1,
        truncated=False,
    )

    class FakeConnector:
        async def create_query_snapshot(self, *_args, **_kwargs):
            return snapshot

        async def iter_snapshot_pages(self, *_args, **_kwargs):
            yield {
                "batch_index": 0,
                "object_ids": (1,),
                "frame": _frame(1, 1),
                "records_read": 1,
                "records_total": 1,
            }

    lake = MagicMock()
    lake.write.return_value = {
        "content_sha256": "1" * 64,
        "lake_uri": "file:///part-0",
    }
    publisher = MagicMock()
    with (
        patch("data_agent.virtual_sources.get_virtual_source", return_value=source),
        patch(
            "data_agent.connectors.arcgis_rest.ArcGISRestConnector",
            return_value=FakeConnector(),
        ),
        patch("data_agent.data_ingestion.GeoParquetLakeWriter", return_value=lake),
        patch("data_agent.data_ingestion.AssetPublisher", return_value=publisher),
    ):
        await ArcGISIngestionExecutor(repository, worker_id="worker:test").execute(run)

    lake.finalize.assert_not_called()
    lake.abort.assert_called_once_with()
    publisher.publish.assert_not_called()
    assert repository.completed is None
    assert repository.failed[-1] is True


def test_ingestion_migration_has_durable_run_and_batch_ledgers():
    migration = (
        Path(__file__).parent / "migrations" / "127_arcgis_data_ingestion.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS agent_ingestion_definitions" in migration
    assert "CREATE TABLE IF NOT EXISTS agent_ingestion_runs" in migration
    assert "CREATE TABLE IF NOT EXISTS agent_ingestion_batches" in migration
    assert "'committing'" in migration
    assert "FOR UPDATE SKIP LOCKED" not in migration


def test_metadata_projection_waits_for_bindings_without_spending_retries():
    migration = (
        Path(__file__).parent
        / "migrations"
        / "130_metadata_projection_binding_dependency.sql"
    ).read_text(encoding="utf-8")
    assert "metadata_lineage_bindings_ready" in migration
    assert "attempt_count = greatest(change.attempt_count - 1, 0)" in migration
    assert "AND gda_control.metadata_lineage_bindings_ready(" in migration
