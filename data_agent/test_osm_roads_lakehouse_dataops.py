"""Tests for governed Chongqing OSM Default Lakehouse materialization."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from data_agent.data_products.osm_roads_lakehouse_dataops import (
    DEFINITION_VERSION_ID,
    ICEBERG_TABLE,
    QUALITY_EVALUATOR,
    SOURCE_RESOURCE_VERSION_ID,
    WORKLOAD_SUBJECT_ID,
    OsmRoadsLakehouseCommand,
    OsmRoadsLakehouseExecutor,
    OsmRoadsLakehouseExecutorConfig,
    OsmRoadsLakehouseResult,
    build_osm_roads_lakehouse_definition,
)
from data_agent.dataops_executor import create_app
from data_agent.dolphinscheduler_adapter import compile_dolphinscheduler_workflow
from data_agent.platform_contracts import PlatformRun, ResourceBinding, SubjectContext
from data_agent.platform_gateway import GatewayNotFoundError

NOW = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
RUN_ID = UUID("ba404527-9605-55c7-92e2-0e00f3d87b91")
SNAPSHOT_ID = 6767532492674345422


class FakeGateway:
    def __init__(self) -> None:
        self.run = PlatformRun(
            tenant_id="local-dev",
            run_id=RUN_ID,
            definition_version_id=DEFINITION_VERSION_ID,
            orchestration_class="dataops",
            subject_context=SubjectContext(
                tenant_id="local-dev",
                subject_id=WORKLOAD_SUBJECT_ID,
                subject_type="workload",
                roles=("platform_operator",),
                purpose="materialize OSM roads into the default lakehouse",
            ),
            input_bindings=(
                ResourceBinding(
                    binding_name="source",
                    resource_version_id=SOURCE_RESOURCE_VERSION_ID,
                    semantic_type="gis.transportation.osm_roads.ads",
                ),
            ),
            idempotency_key="osm-roads-default-lakehouse-test",
            status="dispatching",
            state_version=1,
            submitted_at=NOW,
        )
        self.resources = {}
        self.versions = {}
        self.artifacts = {}
        self.lineage = {}
        self.quality = {}

    def get_run(self, tenant_id, run_id):
        assert tenant_id == "local-dev"
        assert run_id == RUN_ID
        return self.run

    def register_resource(self, value):
        created = value.resource_urn not in self.resources
        previous = self.resources.setdefault(value.resource_urn, value)
        assert previous == value
        return SimpleNamespace(value=value, created=created)

    def register_resource_version(self, value):
        created = value.resource_version_id not in self.versions
        previous = self.versions.setdefault(value.resource_version_id, value)
        assert previous == value
        return SimpleNamespace(value=value, created=created)

    def get_artifact(self, tenant_id, artifact_id):
        try:
            return self.artifacts[artifact_id]
        except KeyError as exc:
            raise GatewayNotFoundError("not found") from exc

    def record_artifact(self, value):
        created = value.artifact_id not in self.artifacts
        previous = self.artifacts.setdefault(value.artifact_id, value)
        assert previous == value
        return SimpleNamespace(value=value, created=created)

    def record_lineage(self, value):
        created = value.lineage_event_id not in self.lineage
        previous = self.lineage.setdefault(value.lineage_event_id, value)
        assert previous == value
        return SimpleNamespace(value=value, created=created)

    def get_quality_result(self, tenant_id, quality_result_id):
        try:
            return self.quality[quality_result_id]
        except KeyError as exc:
            raise GatewayNotFoundError("not found") from exc

    def record_quality_result(self, value):
        created = value.quality_result_id not in self.quality
        previous = self.quality.setdefault(value.quality_result_id, value)
        assert previous == value
        return SimpleNamespace(value=value, created=created)


def _provider_report() -> dict:
    checks = {
        "row_count_preserved": True,
        "road_id_unique_complete": True,
        "geometry_valid_complete": True,
        "srid_is_4326": True,
        "bbox_preserved": True,
        "iceberg_readback": True,
        "content_fingerprint_preserved": True,
        "time_travel_readback": True,
        "idempotent_snapshot_reuse": True,
    }
    return {
        "status": "passed",
        "table": ICEBERG_TABLE,
        "materialization_run_id": str(RUN_ID),
        "snapshot_id": SNAPSHOT_ID,
        "row_count": 50366,
        "distinct_road_ids": 50366,
        "history_count": 1,
        "time_travel_rows": 50366,
        "content_fingerprint": "2" * 64,
        "semantic_sha256": "5" * 64,
        "source_sha256": "c" * 64,
        "spark_version": "3.5.0",
        "sedona_version": "1.9.0",
        "iceberg_format_version": 2,
        "warehouse_uri": "s3a://gis-agent-lakehouse/warehouse/iceberg",
        "checks": checks,
    }


def _executor(tmp_path, gateway, runner):
    return OsmRoadsLakehouseExecutor(
        OsmRoadsLakehouseExecutorConfig(
            repo_root=tmp_path.resolve(),
            report_root=(tmp_path / "reports").resolve(),
        ),
        gateway=gateway,
        runner=runner,
    )


def _command() -> OsmRoadsLakehouseCommand:
    return OsmRoadsLakehouseCommand(
        tenant_id="local-dev",
        run_id=RUN_ID,
        source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
        definition_version_id=DEFINITION_VERSION_ID,
    )


def test_lakehouse_definition_compiles_with_immutable_ads_input() -> None:
    definition = build_osm_roads_lakehouse_definition(987654)
    compiled = compile_dolphinscheduler_workflow(definition)

    assert definition.definition_version_id == DEFINITION_VERSION_ID
    assert definition.portability_class.value == "engine_family"
    assert definition.input_contract["source"]["resource_version_id"] == str(
        SOURCE_RESOURCE_VERSION_ID
    )
    assert definition.output_contract["table"] == ICEBERG_TABLE
    assert compiled.task_definitions[0]["failRetryTimes"] == 1
    assert str(DEFINITION_VERSION_ID) in {
        item["value"] for item in compiled.global_params
    }


def test_lakehouse_executor_records_evidence_and_skips_runner_on_replay(tmp_path) -> None:
    gateway = FakeGateway()
    calls = []

    def runner(run_id, report_path):
        calls.append((run_id, report_path))
        return _provider_report()

    executor = _executor(tmp_path, gateway, runner)
    first = executor.execute(_command())
    replay = executor.execute(_command())

    assert first.status == "completed"
    assert first.feature_count == 50366
    assert first.snapshot_id == SNAPSHOT_ID
    assert first.replayed is False
    assert replay.replayed is True
    assert len(calls) == 1
    assert len(gateway.resources) == 1
    assert len(gateway.versions) == 1
    assert len(gateway.artifacts) == 2
    assert len(gateway.lineage) == 1
    assert len(gateway.quality) == 1
    output = gateway.artifacts[first.output_artifact_id]
    quality = gateway.quality[first.quality_result_id]
    lineage = gateway.lineage[first.lineage_event_id]
    assert output.run_id == RUN_ID
    assert output.resource_version_id == first.output_resource_version_id
    assert output.manifest["snapshot_id"] == SNAPSHOT_ID
    assert quality.evaluated_by == QUALITY_EVALUATOR
    assert quality.evaluated_by != f"workload:{WORKLOAD_SUBJECT_ID}"
    assert lineage.run_id == RUN_ID
    assert lineage.definition_version_id == DEFINITION_VERSION_ID
    assert lineage.source_resource_version_id == SOURCE_RESOURCE_VERSION_ID
    assert lineage.target_resource_version_id == first.output_resource_version_id


def test_lakehouse_executor_rejects_incomplete_provider_evidence(tmp_path) -> None:
    report = _provider_report()
    report["checks"]["time_travel_readback"] = False
    executor = _executor(tmp_path, FakeGateway(), lambda run_id, path: report)

    with pytest.raises(RuntimeError, match="checks are incomplete"):
        executor.execute(_command())


def test_lakehouse_executor_rejects_source_outside_run_binding(tmp_path) -> None:
    command = _command().model_copy(
        update={"source_resource_version_id": uuid4()}
    )
    executor = _executor(tmp_path, FakeGateway(), lambda run_id, path: _provider_report())

    with pytest.raises(ValueError, match="immutable definition"):
        executor.execute(command)


def test_lakehouse_http_executor_requires_token_and_exposes_capability(tmp_path) -> None:
    token_file = tmp_path / "executor-token"
    token_file.write_text("secret-token", encoding="utf-8")
    service = SimpleNamespace(config=SimpleNamespace(token_file=token_file))
    calls = []

    class FakeLakehouseService:
        def execute(self, command):
            calls.append(command)
            return OsmRoadsLakehouseResult(
                status="completed",
                run_id=command.run_id,
                definition_version_id=command.definition_version_id,
                source_resource_version_id=command.source_resource_version_id,
                output_resource_version_id=uuid4(),
                output_artifact_id=uuid4(),
                evidence_artifact_id=uuid4(),
                quality_result_id=uuid4(),
                lineage_event_id=uuid4(),
                iceberg_table=ICEBERG_TABLE,
                snapshot_id=SNAPSHOT_ID,
                feature_count=50366,
            )

    client = TestClient(
        create_app(service, lakehouse_service=FakeLakehouseService())
    )
    path = "/v1/execute/chongqing-osm-roads-default-lakehouse"
    payload = _command().model_dump(mode="json")

    assert client.post(path, json=payload).status_code == 401
    response = client.post(
        path,
        json=payload,
        headers={"Authorization": "Bearer secret-token"},
    )
    health = client.get("/health")

    assert response.status_code == 200
    assert response.json()["snapshot_id"] == SNAPSHOT_ID
    assert len(calls) == 1
    assert health.json()["default_lakehouse_configured"] is True
