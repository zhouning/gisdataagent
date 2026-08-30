"""Governed Default Lakehouse materialization for Chongqing OSM roads."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.lakehouse_materialization import (
    LakehouseMaterializationContract,
    LakehouseMaterializationEvidence,
    LakehouseMaterializationRecord,
    LakehouseMaterializationRecorder,
)
from data_agent.platform_contracts import (
    PlatformDefinitionVersion,
    PlatformRun,
    RunStatus,
    platform_definition_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway

TENANT_ID = "local-dev"
DEFINITION_URN = (
    "gda://local-dev/definition/chongqing-osm-roads-default-lakehouse-materialize"
)
DEFINITION_VERSION_ID = uuid5(NAMESPACE_URL, f"{DEFINITION_URN}:v1")
SOURCE_RESOURCE_VERSION_ID = UUID("04eaa6f8-475c-5dcd-8992-e54307fc0395")
SOURCE_PRODUCT_VERSION_ID = UUID("5bdffe0f-edd7-5de2-826f-a36486be44ba")
SOURCE_RUN_ID = UUID("859195f5-5e81-59a6-855a-de52b3b11d7d")
SOURCE_SEMANTIC_SHA256 = (
    "52645a3b7cdac54a89df26dc88004f2ae93ce96f81e36af940bdb2237262353d"
)
SOURCE_PHYSICAL_SHA256 = (
    "c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164"
)
OUTPUT_RESOURCE_URN = "gda://local-dev/table/chongqing_osm_roads_default_lakehouse"
ICEBERG_TABLE = "lakehouse.gis_dwd.chongqing_osm_roads"
ICEBERG_STORAGE_URI = "iceberg://lakehouse/gis_dwd/chongqing_osm_roads"
WORKFLOW_NAME = "gda_chongqing_osm_roads_default_lakehouse_v1"
WORKLOAD_SUBJECT = "workload:dolphinscheduler-gda-dataops"
WORKLOAD_SUBJECT_ID = WORKLOAD_SUBJECT.removeprefix("workload:")
POLICY_EVALUATOR_SUBJECT = "workload:gda-policy-evaluator"
QUALITY_EVALUATOR = "workload:default-lakehouse-quality-evaluator"
QUALITY_RULE_VERSION = "gda://local-dev/quality_rule/osm-roads-default-lakehouse:v1"
EXECUTOR_SCHEMA = "gda.chongqing_osm_roads_lakehouse_executor.v1"

MATERIALIZATION_CONTRACT = LakehouseMaterializationContract(
    output_resource_urn=OUTPUT_RESOURCE_URN,
    iceberg_table=ICEBERG_TABLE,
    iceberg_storage_uri=ICEBERG_STORAGE_URI,
    source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
    workload_subject=WORKLOAD_SUBJECT,
    quality_evaluator=QUALITY_EVALUATOR,
    quality_rule_version=QUALITY_RULE_VERSION,
    governance_ref={
        "classification": "public",
        "source_product_version_id": str(SOURCE_PRODUCT_VERSION_ID),
    },
    technical_refs=(
        {
            "provider": "spark_sedona_iceberg",
            "table": ICEBERG_TABLE,
            "format_version": 2,
        },
    ),
    output_artifact_identity="artifact:default-lakehouse-iceberg-snapshot:v1",
    evidence_artifact_identity="artifact:default-lakehouse-quality-evidence:v1",
    lineage_event_identity="lineage:ads-to-default-lakehouse:v1",
    output_artifact_key_prefix="cq_osm_iceberg_snapshot",
    evidence_artifact_key_prefix="cq_osm_lakehouse_quality",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OsmRoadsLakehouseCommand(_FrozenModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    run_id: UUID
    source_resource_version_id: UUID
    definition_version_id: UUID


class OsmRoadsLakehouseResult(_FrozenModel):
    schema_name: str = Field(default=EXECUTOR_SCHEMA, alias="schema")
    status: str
    run_id: UUID
    definition_version_id: UUID
    source_resource_version_id: UUID
    output_resource_version_id: UUID
    output_artifact_id: UUID
    evidence_artifact_id: UUID
    quality_result_id: UUID
    lineage_event_id: UUID
    iceberg_table: str
    snapshot_id: int
    feature_count: int = Field(ge=0)
    replayed: bool = False


class OsmRoadsLakehouseExecutorConfig(_FrozenModel):
    repo_root: Path
    report_root: Path
    runtime_image: str = "gisdataagent/mmfe-spark-runtime:local"
    docker_network: str = "gisdataagent_agent-net"
    java_home: str = "/usr/lib/jvm/java-17-openjdk-arm64"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)

    @model_validator(mode="after")
    def _valid_paths(self) -> OsmRoadsLakehouseExecutorConfig:
        if not self.repo_root.is_absolute() or not self.repo_root.is_dir():
            raise ValueError("repo_root must be an existing absolute directory")
        if not self.report_root.is_absolute():
            raise ValueError("report_root must be absolute")
        if not self.report_root.is_relative_to(self.repo_root):
            raise ValueError("report_root must be inside repo_root for the runtime mount")
        return self


LakehouseRunner = Callable[[UUID, Path], dict[str, Any]]


def output_artifact_id(run_id: UUID) -> UUID:
    return MATERIALIZATION_CONTRACT.output_artifact_id(run_id)


def evidence_artifact_id(run_id: UUID) -> UUID:
    return MATERIALIZATION_CONTRACT.evidence_artifact_id(run_id)


def quality_result_id(run_id: UUID) -> UUID:
    return MATERIALIZATION_CONTRACT.quality_result_id(run_id)


def lineage_event_id(run_id: UUID) -> UUID:
    return MATERIALIZATION_CONTRACT.lineage_event_id(run_id)


def output_resource_version_id(snapshot_id: int) -> UUID:
    return MATERIALIZATION_CONTRACT.output_resource_version_id(snapshot_id)


def _raw_script(executor_url: str) -> str:
    return f"""set -eu
payload='{{\"tenant_id\":\"${{gda_tenant_id}}\",'
payload=$payload'\"run_id\":\"${{gda_run_id}}\",'
payload=$payload'\"definition_version_id\":\"${{gda_definition_version_id}}\",'
payload=$payload'\"source_resource_version_id\":\"${{gda_source_resource_version_id}}\"}}'
curl --fail --silent --show-error --retry 1 --retry-all-errors \\
  --connect-timeout 5 --max-time 1800 \\
  --header "Authorization: Bearer $(cat /run/secrets/gda-dataops-executor-token)" \\
  --header "Content-Type: application/json" \\
  --data "$payload" \\
  {executor_url}
"""


def build_osm_roads_lakehouse_definition(
    task_code: int,
    *,
    executor_url: str = (
        "http://host.docker.internal:8090/v1/execute/"
        "chongqing-osm-roads-default-lakehouse"
    ),
) -> PlatformDefinitionVersion:
    """Build the immutable logical materialization and scheduler graph."""
    task = {
        "code": task_code,
        "name": "materialize_chongqing_osm_roads_default_lakehouse",
        "version": 1,
        "description": "Materialize governed OSM roads into Iceberg with Spark/Sedona",
        "delayTime": 0,
        "taskType": "SHELL",
        "taskParams": {
            "localParams": [],
            "rawScript": _raw_script(executor_url),
            "resourceList": [],
        },
        "flag": "YES",
        "taskPriority": "MEDIUM",
        "workerGroup": "gda_dataops_sandbox",
        "environmentCode": -1,
        "failRetryTimes": 1,
        "failRetryInterval": 10,
        "timeoutFlag": "OPEN",
        "timeoutNotifyStrategy": "WARN",
        "timeout": 2100,
        "taskGroupId": 0,
        "taskGroupPriority": 0,
        "cpuQuota": -1,
        "memoryMax": -1,
    }
    definition_document = {
        "schema": "gda.chongqing_osm_roads_default_lakehouse_definition.v1",
        "pipeline": {
            "profile": "default_lakehouse",
            "source_product_version_id": str(SOURCE_PRODUCT_VERSION_ID),
            "source_run_id": str(SOURCE_RUN_ID),
            "engine": "spark_sedona",
            "table_format": "iceberg_v2",
            "table": ICEBERG_TABLE,
            "spatial_contract": "geometry_wkb_srid_bbox",
        },
        "dolphinscheduler": {
            "name": WORKFLOW_NAME,
            "description": "Governed OSM roads Default Lakehouse materialization",
            "task_definitions": [task],
            "task_relations": [
                {
                    "name": "",
                    "preTaskCode": 0,
                    "preTaskVersion": 0,
                    "postTaskCode": task_code,
                    "postTaskVersion": 1,
                    "conditionType": "NONE",
                    "conditionParams": {},
                }
            ],
            "locations": [{"taskCode": task_code, "x": 180, "y": 120}],
            "global_params": [
                {
                    "prop": "gda_source_resource_version_id",
                    "direct": "IN",
                    "type": "VARCHAR",
                    "value": str(SOURCE_RESOURCE_VERSION_ID),
                }
            ],
            "timeout_seconds": 2400,
            "execution_type": "PARALLEL",
        },
    }
    input_contract = {
        "source": {
            "semantic_type": "gis.transportation.osm_roads.ads",
            "resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "product_version_id": str(SOURCE_PRODUCT_VERSION_ID),
            "access": "read_only",
        }
    }
    output_contract = {
        "resource_urn": OUTPUT_RESOURCE_URN,
        "table": ICEBERG_TABLE,
        "format_version": 2,
        "required_evidence": [
            "iceberg_snapshot",
            "spark_sedona_quality",
            "input_to_snapshot_lineage",
            "snapshot_time_travel",
            "idempotent_snapshot_reuse",
        ],
    }
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="transportation.osm_roads.default_lakehouse_materialize",
        portability_class="engine_family",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id=TENANT_ID,
        definition_urn=DEFINITION_URN,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        capability_id="transportation.osm_roads.default_lakehouse_materialize",
        portability_class="engine_family",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )


def build_docker_lakehouse_runner(
    config: OsmRoadsLakehouseExecutorConfig,
) -> LakehouseRunner:
    """Build the local sandbox Spark provider runner."""

    def runner(run_id: UUID, report_path: Path) -> dict[str, Any]:
        relative_report = report_path.relative_to(config.repo_root)
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            config.docker_network,
            "-e",
            f"JAVA_HOME={config.java_home}",
            "-v",
            f"{config.repo_root}:/workspace",
            "-w",
            "/workspace",
            config.runtime_image,
            "python",
            "scripts/smoke_chongqing_osm_roads_default_lakehouse.py",
            "--run-id",
            str(SOURCE_RUN_ID),
            "--materialization-run-id",
            str(run_id),
            "--report-path",
            str(relative_report),
        ]
        completed = subprocess.run(
            command,
            cwd=config.repo_root,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout)[-2000:]
            raise RuntimeError(f"Default Lakehouse provider failed: {details}")
        value = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("Default Lakehouse provider report must be an object")
        return value

    return runner


class OsmRoadsLakehouseExecutor:
    """Execute one admitted Default Lakehouse materialization."""

    def __init__(
        self,
        config: OsmRoadsLakehouseExecutorConfig,
        *,
        gateway: PlatformGateway | None = None,
        runner: LakehouseRunner | None = None,
    ):
        self.config = config
        self.gateway = gateway or PlatformGateway()
        self.runner = runner or build_docker_lakehouse_runner(config)
        self.recorder = LakehouseMaterializationRecorder(
            MATERIALIZATION_CONTRACT,
            gateway=self.gateway,
        )

    @staticmethod
    def _validate_run(run: PlatformRun, command: OsmRoadsLakehouseCommand) -> None:
        if run.tenant_id != TENANT_ID or command.tenant_id != TENANT_ID:
            raise ValueError("lakehouse executor only accepts the local-dev tenant")
        if run.definition_version_id != DEFINITION_VERSION_ID:
            raise ValueError("PlatformRun does not bind the lakehouse definition")
        if command.definition_version_id != run.definition_version_id:
            raise ValueError("command definition does not match PlatformRun")
        if command.source_resource_version_id != SOURCE_RESOURCE_VERSION_ID:
            raise ValueError("command source does not match the immutable definition")
        if run.orchestration_class.value != "dataops":
            raise ValueError("lakehouse executor only accepts DataOps runs")
        actor = f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
        if actor != WORKLOAD_SUBJECT:
            raise ValueError("run workload identity does not match the executor")
        if run.status not in {
            RunStatus.DISPATCHING,
            RunStatus.RUNNING,
            RunStatus.RECONCILING,
            RunStatus.SUCCEEDED,
        }:
            raise ValueError("run is not in an executable state")
        bindings = {binding.binding_name: binding for binding in run.input_bindings}
        source = bindings.get("source")
        if source is None or source.resource_version_id != SOURCE_RESOURCE_VERSION_ID:
            raise ValueError("source binding does not match the immutable PlatformRun input")

    def _existing_result(
        self,
        command: OsmRoadsLakehouseCommand,
    ) -> OsmRoadsLakehouseResult | None:
        existing = self.recorder.existing(
            tenant_id=command.tenant_id,
            run_id=command.run_id,
            definition_version_id=command.definition_version_id,
        )
        if existing is None:
            return None
        return self._result(existing)

    def execute(
        self,
        command: OsmRoadsLakehouseCommand,
    ) -> OsmRoadsLakehouseResult:
        run = self.gateway.get_run(command.tenant_id, command.run_id)
        self._validate_run(run, command)
        if existing := self._existing_result(command):
            return existing

        provider_report_path = (
            self.config.report_root
            / command.tenant_id
            / str(command.run_id)
            / "provider-acceptance.json"
        )
        provider_report_path.parent.mkdir(parents=True, exist_ok=True)
        provider_report = self.runner(run.run_id, provider_report_path)
        self._validate_provider_report(provider_report, run.run_id)
        snapshot_id = int(provider_report["snapshot_id"])
        target_version_id = output_resource_version_id(snapshot_id)
        record = self.recorder.record(
            run=run,
            provider_report=provider_report,
            provider_report_path=provider_report_path,
            evidence=self._materialization_evidence(
                provider_report,
                run=run,
                target_version_id=target_version_id,
            ),
        )
        return self._result(record)

    @staticmethod
    def _result(record: LakehouseMaterializationRecord) -> OsmRoadsLakehouseResult:
        return OsmRoadsLakehouseResult(
            status="completed",
            run_id=record.run_id,
            definition_version_id=record.definition_version_id,
            source_resource_version_id=record.source_resource_version_id,
            output_resource_version_id=record.output_resource_version_id,
            output_artifact_id=record.output_artifact_id,
            evidence_artifact_id=record.evidence_artifact_id,
            quality_result_id=record.quality_result_id,
            lineage_event_id=record.lineage_event_id,
            iceberg_table=record.iceberg_table,
            snapshot_id=record.snapshot_id,
            feature_count=record.feature_count,
            replayed=record.replayed,
        )

    @classmethod
    def _materialization_evidence(
        cls,
        report: dict[str, Any],
        *,
        run: PlatformRun,
        target_version_id: UUID,
    ) -> LakehouseMaterializationEvidence:
        snapshot_id = int(report["snapshot_id"])
        return LakehouseMaterializationEvidence(
            evidence_document=cls._evidence_document(
                report,
                run=run,
                target_version_id=target_version_id,
            ),
            output_manifest={
                "schema": "gda.iceberg_snapshot_artifact.v1",
                "iceberg_table": ICEBERG_TABLE,
                "snapshot_id": snapshot_id,
                "feature_count": int(report["row_count"]),
                "history_count": int(report["history_count"]),
                "time_travel_rows": int(report["time_travel_rows"]),
                "content_fingerprint": report["content_fingerprint"],
                "source_product_version_id": str(SOURCE_PRODUCT_VERSION_ID),
                "source_run_id": str(SOURCE_RUN_ID),
            },
            lineage_facets={
                "schema": "gda.default_lakehouse_materialization_lineage.v1",
                "operation": "spark_sedona_iceberg_materialize",
                "source_product_version_id": str(SOURCE_PRODUCT_VERSION_ID),
                "source_run_id": str(SOURCE_RUN_ID),
                "materialization_run_id": str(run.run_id),
                "definition_version_id": str(run.definition_version_id),
                "iceberg_table": ICEBERG_TABLE,
                "snapshot_id": snapshot_id,
                "content_fingerprint": report["content_fingerprint"],
            },
            quality_metrics={
                "feature_count": int(report["row_count"]),
                "distinct_road_ids": int(report["distinct_road_ids"]),
                "snapshot_id": snapshot_id,
                "history_count": int(report["history_count"]),
                "time_travel_rows": int(report["time_travel_rows"]),
                "content_fingerprint": report["content_fingerprint"],
                "checks": report["checks"],
                "full_dataset_validated": True,
            },
        )

    @staticmethod
    def _validate_provider_report(report: dict[str, Any], run_id: UUID) -> None:
        required_checks = {
            "row_count_preserved",
            "road_id_unique_complete",
            "geometry_valid_complete",
            "srid_is_4326",
            "bbox_preserved",
            "iceberg_readback",
            "content_fingerprint_preserved",
            "time_travel_readback",
            "idempotent_snapshot_reuse",
        }
        checks = report.get("checks") or {}
        if report.get("status") != "passed":
            raise RuntimeError("Default Lakehouse provider did not pass")
        if report.get("table") != ICEBERG_TABLE:
            raise RuntimeError("Default Lakehouse provider returned the wrong table")
        if report.get("materialization_run_id") != str(run_id):
            raise RuntimeError("provider report does not bind the materialization run")
        if int(report.get("row_count") or 0) != 50366:
            raise RuntimeError("provider report row count is not the governed full dataset")
        if not required_checks.issubset(checks) or not all(
            bool(checks[check_id]) for check_id in required_checks
        ):
            raise RuntimeError("Default Lakehouse provider checks are incomplete")

    @staticmethod
    def _evidence_document(
        report: dict[str, Any],
        *,
        run: PlatformRun,
        target_version_id: UUID,
    ) -> dict[str, Any]:
        return {
            "schema": "gda.default_lakehouse_quality_evidence.v1",
            "run_id": str(run.run_id),
            "definition_version_id": str(run.definition_version_id),
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "output_resource_version_id": str(target_version_id),
            "source_product_version_id": str(SOURCE_PRODUCT_VERSION_ID),
            "iceberg_table": ICEBERG_TABLE,
            "snapshot_id": int(report["snapshot_id"]),
            "history_count": int(report["history_count"]),
            "time_travel_rows": int(report["time_travel_rows"]),
            "feature_count": int(report["row_count"]),
            "distinct_road_ids": int(report["distinct_road_ids"]),
            "semantic_sha256": report["semantic_sha256"],
            "source_sha256": report["source_sha256"],
            "content_fingerprint": report["content_fingerprint"],
            "spark_version": report["spark_version"],
            "sedona_version": report["sedona_version"],
            "iceberg_format_version": int(report["iceberg_format_version"]),
            "checks": report["checks"],
            "evaluated_by": QUALITY_EVALUATOR,
            "evaluated_at": run.submitted_at.astimezone(UTC).isoformat(),
        }
