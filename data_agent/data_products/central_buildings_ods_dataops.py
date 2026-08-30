"""Governed ODS materialization for restricted Chongqing building data."""

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
SOURCE_RESOURCE_URN = (
    "gda://local-dev/dataset/chongqing-central-buildings-2021-source"
)
SOURCE_RESOURCE_VERSION_ID = UUID("c012afeb-9f1f-59a2-9e86-bb16169743af")
SOURCE_BUNDLE_SHA256 = (
    "e2697e8215a26de4b5c2a526eb9bce7401ebc27e1fc64d5f6c30bf85ff149c0d"
)
SOURCE_PHYSICAL_SHA256 = (
    "6fd8c873ffce0c0a91089c554b3b0d432527102272260a7363744cb75290bf29"
)
SOURCE_STORAGE_URI = (
    "s3://gis-agent-lakehouse/raw/planning/chongqing_central_buildings_2021/"
    f"bundle-sha256-{SOURCE_BUNDLE_SHA256}/"
    f"physical-sha256-{SOURCE_PHYSICAL_SHA256}/"
    "chongqing-central-buildings-2021.geojson"
)
DEFINITION_URN = (
    "gda://local-dev/definition/chongqing-central-buildings-ods-materialize"
)
DEFINITION_VERSION_ID = uuid5(NAMESPACE_URL, f"{DEFINITION_URN}:v1")
OUTPUT_RESOURCE_URN = (
    "gda://local-dev/table/chongqing-central-buildings-2021-ods"
)
ICEBERG_TABLE = "lakehouse.gis_ods.chongqing_central_buildings_2021"
ICEBERG_STORAGE_URI = (
    "iceberg://lakehouse/gis_ods/chongqing_central_buildings_2021"
)
WORKFLOW_NAME = "gda_chongqing_central_buildings_ods_v1"
WORKLOAD_SUBJECT = "workload:dolphinscheduler-gda-dataops"
WORKLOAD_SUBJECT_ID = WORKLOAD_SUBJECT.removeprefix("workload:")
POLICY_EVALUATOR_SUBJECT = "workload:gda-policy-evaluator"
QUALITY_EVALUATOR = "workload:ods-ingestion-quality-evaluator"
QUALITY_RULE_VERSION = (
    "gda://local-dev/quality_rule/chongqing-central-buildings-ods:v1"
)
EXECUTOR_SCHEMA = "gda.chongqing_central_buildings_ods_executor.v1"
EXPECTED_FEATURE_COUNT = 107452

MATERIALIZATION_CONTRACT = LakehouseMaterializationContract(
    output_resource_urn=OUTPUT_RESOURCE_URN,
    iceberg_table=ICEBERG_TABLE,
    iceberg_storage_uri=ICEBERG_STORAGE_URI,
    source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
    workload_subject=WORKLOAD_SUBJECT,
    quality_evaluator=QUALITY_EVALUATOR,
    quality_rule_version=QUALITY_RULE_VERSION,
    governance_ref={
        "classification": "restricted",
        "logical_stage": "ods",
        "standardization_status": "unmatched_holdout",
        "promotion_eligible": False,
        "source_bundle_sha256": SOURCE_BUNDLE_SHA256,
    },
    technical_refs=(
        {
            "provider": "spark_sedona_iceberg",
            "table": ICEBERG_TABLE,
            "format_version": 2,
            "spatial_contract": "geometry_wkb_srid_bbox",
        },
    ),
    output_artifact_identity="artifact:ods-iceberg-snapshot:v1",
    evidence_artifact_identity="artifact:ods-ingestion-quality-evidence:v1",
    lineage_event_identity="lineage:source-snapshot-to-ods:v1",
    output_artifact_key_prefix="cq_buildings_ods_snapshot",
    evidence_artifact_key_prefix="cq_buildings_ods_quality",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CentralBuildingsOdsCommand(_FrozenModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    run_id: UUID
    source_resource_version_id: UUID
    definition_version_id: UUID


class CentralBuildingsOdsResult(_FrozenModel):
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
    logical_stage: str = "ods"
    promotion_eligible: bool = False
    data_product_version_created: bool = False
    replayed: bool = False


class CentralBuildingsOdsExecutorConfig(_FrozenModel):
    repo_root: Path
    report_root: Path
    runtime_image: str = "gisdataagent/mmfe-spark-runtime:local"
    docker_network: str = "gisdataagent_agent-net"
    java_home: str = "/usr/lib/jvm/java-17-openjdk-arm64"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)

    @model_validator(mode="after")
    def _valid_paths(self) -> CentralBuildingsOdsExecutorConfig:
        if not self.repo_root.is_absolute() or not self.repo_root.is_dir():
            raise ValueError("repo_root must be an existing absolute directory")
        if not self.report_root.is_absolute():
            raise ValueError("report_root must be absolute")
        if not self.report_root.is_relative_to(self.repo_root):
            raise ValueError("report_root must be inside repo_root for the runtime mount")
        return self


LakehouseRunner = Callable[[UUID, Path], dict[str, Any]]


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


def build_central_buildings_ods_definition(
    task_code: int,
    *,
    executor_url: str = (
        "http://host.docker.internal:8090/v1/execute/"
        "chongqing-central-buildings-ods"
    ),
) -> PlatformDefinitionVersion:
    task = {
        "code": task_code,
        "name": "materialize_chongqing_central_buildings_ods",
        "version": 1,
        "description": "Preserve restricted building source in governed Iceberg ODS",
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
        "schema": "gda.chongqing_central_buildings_ods_definition.v1",
        "pipeline": {
            "profile": "default_lakehouse",
            "logical_stage": "ods",
            "classification": "restricted",
            "engine": "spark_sedona",
            "table_format": "iceberg_v2",
            "table": ICEBERG_TABLE,
            "spatial_contract": "geometry_wkb_srid_bbox",
            "standardization_status": "unmatched_holdout",
            "promotion_eligible": False,
        },
        "dolphinscheduler": {
            "name": WORKFLOW_NAME,
            "description": "Governed restricted-building ODS materialization",
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
            "semantic_type": "gis.building.source_snapshot",
            "resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "classification": "restricted",
            "access": "read_only",
        }
    }
    output_contract = {
        "resource_urn": OUTPUT_RESOURCE_URN,
        "table": ICEBERG_TABLE,
        "logical_stage": "ods",
        "format_version": 2,
        "promotion_eligible": False,
        "required_evidence": [
            "source_defects_preserved",
            "iceberg_snapshot",
            "spark_sedona_quality",
            "input_to_snapshot_lineage",
            "snapshot_time_travel",
            "idempotent_snapshot_reuse",
            "promotion_blocked",
        ],
    }
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="buildings.source_snapshot.ods_materialize",
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
        capability_id="buildings.source_snapshot.ods_materialize",
        portability_class="engine_family",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )


def build_docker_lakehouse_runner(
    config: CentralBuildingsOdsExecutorConfig,
) -> LakehouseRunner:
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
            "scripts/smoke_chongqing_central_buildings_ods_lakehouse.py",
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
            raise RuntimeError(f"building ODS provider failed: {details}")
        value = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("building ODS provider report must be an object")
        return value

    return runner


class CentralBuildingsOdsExecutor:
    def __init__(
        self,
        config: CentralBuildingsOdsExecutorConfig,
        *,
        gateway: PlatformGateway | None = None,
        runner: LakehouseRunner | None = None,
    ) -> None:
        self.config = config
        self.gateway = gateway or PlatformGateway()
        self.runner = runner or build_docker_lakehouse_runner(config)
        self.recorder = LakehouseMaterializationRecorder(
            MATERIALIZATION_CONTRACT,
            gateway=self.gateway,
        )

    @staticmethod
    def _validate_run(run: PlatformRun, command: CentralBuildingsOdsCommand) -> None:
        if run.tenant_id != TENANT_ID or command.tenant_id != TENANT_ID:
            raise ValueError("building ODS executor only accepts the local-dev tenant")
        if run.definition_version_id != DEFINITION_VERSION_ID:
            raise ValueError("PlatformRun does not bind the building ODS definition")
        if command.definition_version_id != run.definition_version_id:
            raise ValueError("command definition does not match PlatformRun")
        if command.source_resource_version_id != SOURCE_RESOURCE_VERSION_ID:
            raise ValueError("command source does not match the immutable definition")
        if run.orchestration_class.value != "dataops":
            raise ValueError("building ODS executor only accepts DataOps runs")
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

    def execute(self, command: CentralBuildingsOdsCommand) -> CentralBuildingsOdsResult:
        run = self.gateway.get_run(command.tenant_id, command.run_id)
        self._validate_run(run, command)
        existing = self.recorder.existing(
            tenant_id=command.tenant_id,
            run_id=command.run_id,
            definition_version_id=command.definition_version_id,
        )
        if existing is not None:
            return self._result(existing)

        report_path = (
            self.config.report_root
            / command.tenant_id
            / str(command.run_id)
            / "provider-acceptance.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = self.runner(run.run_id, report_path)
        self._validate_provider_report(report, run.run_id)
        target_version_id = MATERIALIZATION_CONTRACT.output_resource_version_id(
            int(report["snapshot_id"])
        )
        record = self.recorder.record(
            run=run,
            provider_report=report,
            provider_report_path=report_path,
            evidence=self._materialization_evidence(
                report,
                run=run,
                target_version_id=target_version_id,
            ),
        )
        return self._result(record)

    @staticmethod
    def _result(
        record: LakehouseMaterializationRecord,
    ) -> CentralBuildingsOdsResult:
        return CentralBuildingsOdsResult(
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

    @staticmethod
    def _validate_provider_report(report: dict[str, Any], run_id: UUID) -> None:
        required_checks = {
            "row_count_preserved",
            "technical_fid_unique_complete",
            "source_id_defect_recorded",
            "null_geometry_defect_recorded",
            "duplicate_geometry_defect_recorded",
            "non_null_geometry_valid",
            "floor_range_preserved",
            "srid_is_4326",
            "bbox_preserved",
            "iceberg_readback",
            "content_fingerprint_preserved",
            "time_travel_readback",
            "idempotent_snapshot_reuse",
            "promotion_blocked",
        }
        checks = report.get("checks") or {}
        release = report.get("release_disposition") or {}
        if report.get("status") != "passed":
            raise RuntimeError("building ODS provider did not pass")
        if report.get("table") != ICEBERG_TABLE:
            raise RuntimeError("building ODS provider returned the wrong table")
        if report.get("logical_stage") != "ods":
            raise RuntimeError("building source escaped the ODS boundary")
        if report.get("classification") != "restricted":
            raise RuntimeError("building source classification was weakened")
        if report.get("materialization_run_id") != str(run_id):
            raise RuntimeError("provider report does not bind the materialization run")
        if int(report.get("row_count") or 0) != EXPECTED_FEATURE_COUNT:
            raise RuntimeError("provider row count is not the governed full dataset")
        if release.get("promotion_eligible") is not False:
            raise RuntimeError("building source must not be eligible for promotion")
        if release.get("data_product_version_created") is not False:
            raise RuntimeError("provider must not claim a DataProductVersion")
        if not required_checks.issubset(checks) or not all(
            bool(checks[check_id]) for check_id in required_checks
        ):
            raise RuntimeError("building ODS provider checks are incomplete")

    @staticmethod
    def _materialization_evidence(
        report: dict[str, Any],
        *,
        run: PlatformRun,
        target_version_id: UUID,
    ) -> LakehouseMaterializationEvidence:
        snapshot_id = int(report["snapshot_id"])
        defects = {
            "source_id_distinct": int(report["distinct_source_ids"]),
            "null_geometry": int(report["null_geometry"]),
            "duplicate_geometry": int(report["duplicate_geometry"]),
            "duplicate_non_null_geometry": int(
                report["duplicate_non_null_geometry"]
            ),
            "invalid_non_null_geometry": int(report["invalid_geometry"]),
        }
        release = report["release_disposition"]
        evidence_document = {
            "schema": "gda.ods_ingestion_quality_evidence.v1",
            "run_id": str(run.run_id),
            "definition_version_id": str(run.definition_version_id),
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "output_resource_version_id": str(target_version_id),
            "iceberg_table": ICEBERG_TABLE,
            "logical_stage": "ods",
            "classification": "restricted",
            "snapshot_id": snapshot_id,
            "history_count": int(report["history_count"]),
            "time_travel_rows": int(report["time_travel_rows"]),
            "feature_count": int(report["row_count"]),
            "defects": defects,
            "floor_range": [int(report["floor_min"]), int(report["floor_max"])],
            "semantic_sha256": report["semantic_sha256"],
            "source_sha256": report["source_sha256"],
            "content_fingerprint": report["content_fingerprint"],
            "spark_version": report["spark_version"],
            "sedona_version": report["sedona_version"],
            "iceberg_format_version": int(report["iceberg_format_version"]),
            "checks": report["checks"],
            "release_disposition": release,
            "evaluated_by": QUALITY_EVALUATOR,
            "evaluated_at": run.submitted_at.astimezone(UTC).isoformat(),
        }
        output_manifest = {
            "schema": "gda.iceberg_snapshot_artifact.v1",
            "iceberg_table": ICEBERG_TABLE,
            "logical_stage": "ods",
            "classification": "restricted",
            "snapshot_id": snapshot_id,
            "feature_count": int(report["row_count"]),
            "history_count": int(report["history_count"]),
            "time_travel_rows": int(report["time_travel_rows"]),
            "content_fingerprint": report["content_fingerprint"],
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "release_disposition": release,
        }
        lineage_facets = {
            "schema": "gda.default_lakehouse_materialization_lineage.v1",
            "operation": "spark_sedona_iceberg_materialize",
            "logical_stage": "ods",
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "materialization_run_id": str(run.run_id),
            "definition_version_id": str(run.definition_version_id),
            "iceberg_table": ICEBERG_TABLE,
            "snapshot_id": snapshot_id,
            "content_fingerprint": report["content_fingerprint"],
            "promotion_eligible": False,
        }
        quality_metrics = {
            "quality_scope": "ods_ingestion_integrity",
            "feature_count": int(report["row_count"]),
            "defects": defects,
            "snapshot_id": snapshot_id,
            "history_count": int(report["history_count"]),
            "time_travel_rows": int(report["time_travel_rows"]),
            "content_fingerprint": report["content_fingerprint"],
            "checks": report["checks"],
            "full_dataset_validated": True,
            "promotion_eligible": False,
            "data_product_version_created": False,
            "release_block_reasons": release["reasons"],
        }
        return LakehouseMaterializationEvidence(
            evidence_document=evidence_document,
            output_manifest=output_manifest,
            lineage_facets=lineage_facets,
            quality_metrics=quality_metrics,
        )
