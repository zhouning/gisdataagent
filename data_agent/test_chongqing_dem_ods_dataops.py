"""Tests for governed native-raster DEM ODS admission."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from data_agent.data_products.chongqing_dem_ods_dataops import (
    DEFINITION_VERSION_ID,
    EXPECTED_BUNDLE_SHA256,
    EXPECTED_VALID_PIXEL_COUNT,
    QUALITY_EVALUATOR,
    SOURCE_RESOURCE_VERSION_ID,
    WORKLOAD_SUBJECT_ID,
    ChongqingDemOdsCommand,
    ChongqingDemOdsExecutor,
    ChongqingDemOdsExecutorConfig,
    ChongqingDemOdsResult,
    build_chongqing_dem_ods_definition,
)
from data_agent.dataops_executor import create_app
from data_agent.dolphinscheduler_adapter import compile_dolphinscheduler_workflow
from data_agent.platform_contracts import PlatformRun, ResourceBinding, SubjectContext
from data_agent.platform_gateway import GatewayNotFoundError
from data_agent.source_adapter_registry import CHONGQING_DEM_SOURCE_ADAPTER

NOW = datetime(2026, 8, 1, 13, 0, tzinfo=UTC)
RUN_ID = UUID("8a4eb0e2-c7bf-50c5-96b4-cc4b748b8939")


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
                purpose="admit restricted DEM bundle into ODS",
            ),
            input_bindings=(
                ResourceBinding(
                    binding_name="source",
                    resource_version_id=SOURCE_RESOURCE_VERSION_ID,
                    semantic_type="gis.raster.dem.raw_bundle",
                ),
            ),
            idempotency_key="chongqing-dem-ods-test",
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
        assert run_id == self.run.run_id
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

    def get_resource_version(self, tenant_id, resource_version_id):
        try:
            return self.versions[resource_version_id]
        except KeyError as exc:
            raise GatewayNotFoundError("not found") from exc

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
    member = {
        "name": "Chongqing_aster_gdem_80m.tif",
        "physical_sha256": "d" * 64,
        "size_bytes": 1765790,
        "storage_uri": "s3://test/bundle/terrain.tif",
        "local_created": True,
        "object_created": True,
        "readback_verified": True,
    }
    return {
        "schema": "gda.chongqing_dem_source_snapshot.v1",
        "status": "ready",
        "classification": "restricted",
        "snapshot_stage": "raw",
        "logical_target_stage": "ods",
        "publication_eligible": False,
        "standardization_status": "unmatched_holdout",
        "source_adapter": CHONGQING_DEM_SOURCE_ADAPTER.reference(),
        "source_bundle": {
            "bundle_sha256": EXPECTED_BUNDLE_SHA256,
            "size_bytes": 2360205,
            "members": [{"name": "Chongqing_aster_gdem_80m.tif"}],
        },
        "source_profile": {
            "driver": "GTiff",
            "epsg": 4490,
            "crs": "EPSG:4490",
            "width": 1766,
            "height": 1454,
            "transform": [0.002777, 0, 105.2, 0, -0.002777, 32.2],
            "bounds": [105.2, 28.1, 110.1, 32.2],
            "bands": [
                {
                    "pixel_count": 2567764,
                    "valid_pixel_count": EXPECTED_VALID_PIXEL_COUNT,
                    "nodata_pixel_count": 1569066,
                    "min": 24,
                    "max": 2802,
                }
            ],
        },
        "bundle_snapshot": {
            "member_count": 7,
            "members": [member] * 7,
            "all_readback_verified": True,
        },
        "quality_state": {
            "raw_source_integrity": "passed",
            "full_pixel_scan": "passed",
            "cog_conformance": "not_evaluated",
            "ods_admission": "not_evaluated",
            "standard_mapping": "not_evaluated",
            "promotion": "blocked",
            "promotion_blockers": [
                "license_unconfirmed",
                "cog_conformance_not_evaluated",
                "standard_mapping_unapproved",
            ],
        },
    }


def _config(tmp_path: Path) -> ChongqingDemOdsExecutorConfig:
    source = tmp_path / "source.tif"
    source.write_bytes(b"source")
    return ChongqingDemOdsExecutorConfig(
        source_path=source.resolve(),
        output_root=(tmp_path / "output").resolve(),
        report_root=(tmp_path / "reports").resolve(),
    )


def _command(run_id: UUID = RUN_ID) -> ChongqingDemOdsCommand:
    return ChongqingDemOdsCommand(
        tenant_id="local-dev",
        run_id=run_id,
        source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
        definition_version_id=DEFINITION_VERSION_ID,
    )


def test_dem_definition_binds_registry_and_native_raster_boundary() -> None:
    definition = build_chongqing_dem_ods_definition(987656)
    compiled = compile_dolphinscheduler_workflow(definition)

    assert definition.input_contract["source"]["source_kind"] == "raster"
    assert definition.input_contract["source"]["adapter_fingerprint"] == (
        CHONGQING_DEM_SOURCE_ADAPTER.fingerprint
    )
    assert definition.output_contract["storage_contract"] == "native_raster_bundle"
    assert definition.output_contract["cog_conformance"] == "not_evaluated"
    assert definition.output_contract["promotion_eligible"] is False
    assert compiled.task_definitions[0]["failRetryTimes"] == 1


def test_dem_ods_records_object_evidence_and_replays_without_provider(
    tmp_path: Path,
) -> None:
    gateway = FakeGateway()
    calls = []

    def runner(run_id, report_path):
        calls.append((run_id, report_path))
        return _report()

    executor = ChongqingDemOdsExecutor(
        _config(tmp_path),
        gateway=gateway,
        runner=runner,
    )
    first = executor.execute(_command())
    replay = executor.execute(_command())

    assert first.logical_stage == "ods"
    assert first.promotion_eligible is False
    assert first.data_product_version_created is False
    assert first.bundle_sha256 == EXPECTED_BUNDLE_SHA256
    assert first.member_count == 7
    assert first.valid_pixel_count == EXPECTED_VALID_PIXEL_COUNT
    assert replay.replayed is True
    assert len(calls) == 1
    assert len(gateway.resources) == 1
    assert len(gateway.versions) == 1
    assert len(gateway.artifacts) == 2
    assert len(gateway.lineage) == 1
    assert len(gateway.quality) == 1
    quality = gateway.quality[first.quality_result_id]
    assert quality.verdict.value == "passed"
    assert quality.evaluated_by == QUALITY_EVALUATOR
    assert quality.metrics["quality_scope"] == "ods_native_raster_ingestion_integrity"
    assert quality.metrics["cog_conformance"] == "not_evaluated"


def test_dem_ods_reuses_content_version_across_distinct_runs(tmp_path: Path) -> None:
    gateway = FakeGateway()
    calls = []

    def runner(run_id, report_path):
        calls.append(run_id)
        return _report()

    executor = ChongqingDemOdsExecutor(
        _config(tmp_path),
        gateway=gateway,
        runner=runner,
    )
    first = executor.execute(_command())
    second_run_id = UUID("5ea21635-c270-55ca-9122-c5731866ecaa")
    gateway.run = gateway.run.model_copy(
        update={
            "run_id": second_run_id,
            "idempotency_key": "chongqing-dem-ods-second-run",
            "submitted_at": datetime(2026, 8, 1, 14, 0, tzinfo=UTC),
        }
    )
    second = executor.execute(_command(second_run_id))

    assert second.run_id == second_run_id
    assert second.output_resource_version_id == first.output_resource_version_id
    assert second.output_artifact_id != first.output_artifact_id
    assert second.replayed is False
    assert calls == [RUN_ID, second_run_id]
    assert len(gateway.resources) == 1
    assert len(gateway.versions) == 1
    assert len(gateway.artifacts) == 4
    assert len(gateway.lineage) == 2
    assert len(gateway.quality) == 2


def test_dem_ods_rejects_false_cog_claim(tmp_path: Path) -> None:
    report = _report()
    report["quality_state"]["cog_conformance"] = "passed"
    executor = ChongqingDemOdsExecutor(
        _config(tmp_path),
        gateway=FakeGateway(),
        runner=lambda run_id, report_path: report,
    )
    with pytest.raises(RuntimeError, match="quality states"):
        executor.execute(_command())


def test_dem_ods_http_endpoint_requires_token(tmp_path: Path) -> None:
    token_file = tmp_path / "executor-token"
    token_file.write_text("secret-token", encoding="utf-8")
    root_service = SimpleNamespace(config=SimpleNamespace(token_file=token_file))
    calls = []

    class FakeDemService:
        def execute(self, command):
            calls.append(command)
            return ChongqingDemOdsResult(
                status="completed",
                run_id=command.run_id,
                definition_version_id=command.definition_version_id,
                source_resource_version_id=command.source_resource_version_id,
                output_resource_version_id=UUID("f31b60d6-7ec0-515b-9ab2-20b21eea4ebd"),
                output_artifact_id=UUID("b3ea5973-8f73-5229-9edf-13dcd1df446a"),
                evidence_artifact_id=UUID("bf89ad15-75a2-5b31-828a-4451a68b5813"),
                quality_result_id=UUID("a64a14bd-7e26-510d-ab54-1005897bf532"),
                lineage_event_id=UUID("83a2304c-b50e-5cc4-9806-e47d2d31074b"),
                bundle_sha256=EXPECTED_BUNDLE_SHA256,
                member_count=7,
                valid_pixel_count=EXPECTED_VALID_PIXEL_COUNT,
            )

    client = TestClient(
        create_app(root_service, dem_ods_service=FakeDemService())
    )
    path = "/v1/execute/chongqing-dem-ods"
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
    assert health.json()["dem_ods_configured"] is True
    assert len(calls) == 1
