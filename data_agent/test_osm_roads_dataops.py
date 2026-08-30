from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from data_agent.data_products import osm_roads_dataops as module
from data_agent.data_products.osm_roads_dataops import (
    DEFINITION_VERSION_ID,
    PRODUCT_VERSION,
    SOURCE_RESOURCE_VERSION_ID,
    WORKLOAD_SUBJECT_ID,
    OsmRoadsDataOpsCommand,
    OsmRoadsDataOpsExecutor,
    OsmRoadsExecutorConfig,
    build_osm_roads_definition,
)
from data_agent.dolphinscheduler_adapter import compile_dolphinscheduler_workflow
from data_agent.platform_contracts import PlatformRun, ResourceBinding, SubjectContext

NOW = datetime(2026, 8, 1, 6, 0, tzinfo=UTC)
RUN_ID = UUID("8e5655eb-69cc-59b6-a213-ff7988db25dc")
OUTPUT_VERSION_ID = UUID("0ef76cad-5073-5a07-af33-05c9591aaead")
PRODUCT_VERSION_ID = UUID("08c2cc28-2810-5ad5-aee8-9c5875c33c3c")
PHYSICAL_OUTPUT_ID = UUID("856fab47-48c3-5838-9764-c3085b1ba9ac")
QUALITY_ARTIFACT_ID = UUID("52314a7d-7d28-573a-944f-cddfa71bcd74")


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
                purpose="publish OSM roads",
            ),
            input_bindings=(
                ResourceBinding(
                    binding_name="source",
                    resource_version_id=SOURCE_RESOURCE_VERSION_ID,
                    semantic_type="gis.transportation.osm_roads.source",
                ),
            ),
            idempotency_key="osm-roads-test",
            status="dispatching",
            state_version=1,
            submitted_at=NOW,
        )
        self.artifacts = {}
        self.lineage = {}
        self.quality = {}

    def get_run(self, tenant_id, run_id):
        assert tenant_id == "local-dev"
        assert run_id == RUN_ID
        return self.run

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

    def record_quality_result(self, value):
        created = value.quality_result_id not in self.quality
        previous = self.quality.setdefault(value.quality_result_id, value)
        assert previous == value
        return SimpleNamespace(value=value, created=created)


def _receipt(*, idempotent: bool) -> dict:
    return {
        "data_product_version_id": str(PRODUCT_VERSION_ID),
        "feature_count": 50366,
        "quality_verdict": "passed",
        "mapping": {"mapped_fields": 10, "review_required": 0},
        "semantic_sha256": "b" * 64,
        "source_bundle_sha256": "a" * 64,
        "postgis_table": "data_products.chongqing_osm_roads_bbbbbbbbbbbb",
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "output_resource_version_id": str(OUTPUT_VERSION_ID),
        "output_artifact_id": str(PHYSICAL_OUTPUT_ID),
        "quality_evidence_artifact_id": str(QUALITY_ARTIFACT_ID),
        "published_at": NOW.isoformat(),
        "layered_manifest": {
            "manifest_sha256": "c" * 64,
            "checks": [
                {"id": "raw", "status": "passed"},
                {"id": "layers", "status": "passed"},
            ],
        },
        "idempotent": idempotent,
    }


def test_definition_compiles_with_immutable_source_and_retry() -> None:
    definition = build_osm_roads_definition(123456)
    compiled = compile_dolphinscheduler_workflow(definition)

    assert definition.definition_version_id == DEFINITION_VERSION_ID
    assert definition.input_contract["source"]["resource_version_id"] == str(
        SOURCE_RESOURCE_VERSION_ID
    )
    assert definition.output_contract["product_version"] == PRODUCT_VERSION
    assert compiled.task_definitions[0]["failRetryTimes"] == 1
    assert str(DEFINITION_VERSION_ID) in {
        item["value"] for item in compiled.global_params
    }


def test_executor_records_run_bound_success_evidence_idempotently(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "OSM_roads.shp"
    source.write_bytes(b"source")
    output_root = tmp_path / "products"
    gateway = FakeGateway()
    calls = []

    def fake_build_and_publish(**kwargs):
        calls.append(kwargs)
        return _receipt(idempotent=len(calls) > 1)

    monkeypatch.setattr(module, "build_and_publish", fake_build_and_publish)
    executor = OsmRoadsDataOpsExecutor(
        OsmRoadsExecutorConfig(
            source_path=source.resolve(), output_root=output_root.resolve()
        ),
        gateway=gateway,
    )
    command = OsmRoadsDataOpsCommand(
        tenant_id="local-dev",
        run_id=RUN_ID,
        source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
        definition_version_id=DEFINITION_VERSION_ID,
    )

    first = executor.execute(command)
    replay = executor.execute(command)

    assert first.quality_verdict == "passed"
    assert first.replayed is False
    assert replay.replayed is True
    assert len(gateway.artifacts) == 1
    assert len(gateway.lineage) == 1
    assert len(gateway.quality) == 1
    artifact = next(iter(gateway.artifacts.values()))
    lineage = next(iter(gateway.lineage.values()))
    quality = next(iter(gateway.quality.values()))
    assert artifact.run_id == RUN_ID
    assert artifact.content_sha256 == "b" * 64
    assert lineage.run_id == RUN_ID
    assert lineage.definition_version_id == DEFINITION_VERSION_ID
    assert lineage.source_resource_version_id == SOURCE_RESOURCE_VERSION_ID
    assert quality.run_id == RUN_ID
    assert quality.evaluated_by != f"workload:{WORKLOAD_SUBJECT_ID}"
    assert calls[0]["run_id"] == RUN_ID
    assert calls[0]["definition_version_id"] == DEFINITION_VERSION_ID


def test_executor_rejects_command_source_outside_run_binding(tmp_path) -> None:
    source = tmp_path / "OSM_roads.shp"
    source.write_bytes(b"source")
    executor = OsmRoadsDataOpsExecutor(
        OsmRoadsExecutorConfig(
            source_path=source.resolve(), output_root=(tmp_path / "products").resolve()
        ),
        gateway=FakeGateway(),
    )
    command = OsmRoadsDataOpsCommand(
        tenant_id="local-dev",
        run_id=RUN_ID,
        source_resource_version_id=uuid4(),
        definition_version_id=DEFINITION_VERSION_ID,
    )

    with pytest.raises(ValueError, match="immutable definition"):
        executor.execute(command)
