"""Tests for the governed restricted-building ODS materialization."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from data_agent.data_products.central_buildings_ods_dataops import (
    DEFINITION_VERSION_ID,
    ICEBERG_TABLE,
    QUALITY_EVALUATOR,
    SOURCE_RESOURCE_VERSION_ID,
    WORKLOAD_SUBJECT_ID,
    CentralBuildingsOdsCommand,
    CentralBuildingsOdsExecutor,
    CentralBuildingsOdsExecutorConfig,
    CentralBuildingsOdsResult,
    build_central_buildings_ods_definition,
)
from data_agent.dataops_executor import create_app
from data_agent.dolphinscheduler_adapter import compile_dolphinscheduler_workflow
from data_agent.platform_contracts import PlatformRun, ResourceBinding, SubjectContext
from data_agent.platform_gateway import GatewayNotFoundError

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
RUN_ID = UUID("b8cdded1-5e9c-5f6d-acf3-bcbdc8290fc5")
SNAPSHOT_ID = 2900773797038828981


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
                purpose="materialize restricted building source into ODS",
            ),
            input_bindings=(
                ResourceBinding(
                    binding_name="source",
                    resource_version_id=SOURCE_RESOURCE_VERSION_ID,
                    semantic_type="gis.building.source_snapshot",
                ),
            ),
            idempotency_key="central-buildings-ods-test",
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


def _report() -> dict:
    checks = {
        "row_count_preserved": True,
        "technical_fid_unique_complete": True,
        "source_id_defect_recorded": True,
        "null_geometry_defect_recorded": True,
        "duplicate_geometry_defect_recorded": True,
        "non_null_geometry_valid": True,
        "floor_range_preserved": True,
        "srid_is_4326": True,
        "bbox_preserved": True,
        "iceberg_readback": True,
        "content_fingerprint_preserved": True,
        "time_travel_readback": True,
        "idempotent_snapshot_reuse": True,
        "promotion_blocked": True,
    }
    return {
        "status": "passed",
        "table": ICEBERG_TABLE,
        "logical_stage": "ods",
        "classification": "restricted",
        "materialization_run_id": str(RUN_ID),
        "snapshot_id": SNAPSHOT_ID,
        "row_count": 107452,
        "distinct_source_fids": 107452,
        "distinct_source_ids": 1,
        "null_geometry": 417,
        "duplicate_geometry": 416,
        "duplicate_non_null_geometry": 0,
        "invalid_geometry": 0,
        "floor_min": 1,
        "floor_max": 66,
        "history_count": 1,
        "time_travel_rows": 107452,
        "content_fingerprint": "c" * 64,
        "semantic_sha256": "e" * 64,
        "source_sha256": "6" * 64,
        "spark_version": "3.5.0",
        "sedona_version": "1.9.0",
        "iceberg_format_version": 2,
        "warehouse_uri": "s3a://gis-agent-lakehouse/warehouse/iceberg",
        "checks": checks,
        "release_disposition": {
            "promotion_eligible": False,
            "highest_allowed_stage": "ods",
            "data_product_version_created": False,
            "reasons": [
                "standard_mapping_unresolved",
                "source_id_not_unique",
                "null_geometry_present",
            ],
        },
    }


def _command() -> CentralBuildingsOdsCommand:
    return CentralBuildingsOdsCommand(
        tenant_id="local-dev",
        run_id=RUN_ID,
        source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
        definition_version_id=DEFINITION_VERSION_ID,
    )


def test_building_ods_definition_is_restricted_and_not_promotable() -> None:
    definition = build_central_buildings_ods_definition(987655)
    compiled = compile_dolphinscheduler_workflow(definition)

    assert definition.definition_version_id == DEFINITION_VERSION_ID
    assert definition.input_contract["source"]["classification"] == "restricted"
    assert definition.output_contract["logical_stage"] == "ods"
    assert definition.output_contract["promotion_eligible"] is False
    assert compiled.task_definitions[0]["failRetryTimes"] == 1


def test_building_ods_records_defects_and_replays_without_provider(tmp_path) -> None:
    gateway = FakeGateway()
    calls = []

    def runner(run_id, report_path):
        calls.append((run_id, report_path))
        return _report()

    executor = CentralBuildingsOdsExecutor(
        CentralBuildingsOdsExecutorConfig(
            repo_root=tmp_path.resolve(),
            report_root=(tmp_path / "reports").resolve(),
        ),
        gateway=gateway,
        runner=runner,
    )
    first = executor.execute(_command())
    replay = executor.execute(_command())

    assert first.logical_stage == "ods"
    assert first.promotion_eligible is False
    assert first.data_product_version_created is False
    assert first.feature_count == 107452
    assert replay.replayed is True
    assert len(calls) == 1
    assert len(gateway.resources) == 1
    assert len(gateway.versions) == 1
    assert len(gateway.artifacts) == 2
    assert len(gateway.lineage) == 1
    assert len(gateway.quality) == 1
    resource = next(iter(gateway.resources.values()))
    quality = gateway.quality[first.quality_result_id]
    assert resource.governance_ref["classification"] == "restricted"
    assert resource.governance_ref["promotion_eligible"] is False
    assert quality.verdict.value == "passed"
    assert quality.evaluated_by == QUALITY_EVALUATOR
    assert quality.metrics["quality_scope"] == "ods_ingestion_integrity"
    assert quality.metrics["defects"]["null_geometry"] == 417
    assert quality.metrics["promotion_eligible"] is False


def test_building_ods_rejects_false_promotion_claim(tmp_path) -> None:
    report = _report()
    report["release_disposition"]["promotion_eligible"] = True
    executor = CentralBuildingsOdsExecutor(
        CentralBuildingsOdsExecutorConfig(
            repo_root=tmp_path.resolve(),
            report_root=(tmp_path / "reports").resolve(),
        ),
        gateway=FakeGateway(),
        runner=lambda run_id, report_path: report,
    )

    with pytest.raises(RuntimeError, match="must not be eligible"):
        executor.execute(_command())


def test_building_ods_http_endpoint_requires_token(tmp_path) -> None:
    token_file = tmp_path / "executor-token"
    token_file.write_text("secret-token", encoding="utf-8")
    root_service = SimpleNamespace(config=SimpleNamespace(token_file=token_file))
    calls = []

    class FakeBuildingService:
        def execute(self, command):
            calls.append(command)
            return CentralBuildingsOdsResult(
                status="completed",
                run_id=command.run_id,
                definition_version_id=command.definition_version_id,
                source_resource_version_id=command.source_resource_version_id,
                output_resource_version_id=UUID(
                    "e36703d6-ba3b-53be-96c1-fb8aeb8465b6"
                ),
                output_artifact_id=UUID("e69a8cdf-c219-5260-9661-b2a1a42a6e67"),
                evidence_artifact_id=UUID("f58db211-e251-51a2-a514-3d7de7138106"),
                quality_result_id=UUID("c0cb6e6f-d89a-5750-87f6-3a367f687da0"),
                lineage_event_id=UUID("2f7baa57-d4a5-5ede-9cc7-d51b6ee274bf"),
                iceberg_table=ICEBERG_TABLE,
                snapshot_id=SNAPSHOT_ID,
                feature_count=107452,
            )

    client = TestClient(
        create_app(root_service, building_ods_service=FakeBuildingService())
    )
    path = "/v1/execute/chongqing-central-buildings-ods"
    payload = _command().model_dump(mode="json")

    assert client.post(path, json=payload).status_code == 401
    response = client.post(
        path,
        json=payload,
        headers={"Authorization": "Bearer secret-token"},
    )
    health = client.get("/health")

    assert response.status_code == 200
    assert response.json()["promotion_eligible"] is False
    assert health.json()["building_ods_configured"] is True
    assert len(calls) == 1
