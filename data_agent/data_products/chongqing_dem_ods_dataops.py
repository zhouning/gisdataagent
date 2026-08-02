"""Governed native-raster ODS admission for the restricted Chongqing DEM."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.fusion.s3_materialization_adapter import build_s3_materialization_executor
from data_agent.object_materialization import (
    ObjectMaterializationContract,
    ObjectMaterializationEvidence,
    ObjectMaterializationRecord,
    ObjectMaterializationRecorder,
)
from data_agent.platform_contracts import (
    PlatformDefinitionVersion,
    PlatformRun,
    RunStatus,
    platform_definition_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway
from data_agent.source_adapter_registry import CHONGQING_DEM_SOURCE_ADAPTER
from scripts.stage_chongqing_dem import (
    DEFAULT_BUCKET,
    EXPECTED_BUNDLE_SHA256,
    EXPECTED_PRIMARY_SHA256,
    EXPECTED_VALID_PIXEL_COUNT,
    stage_source,
)

TENANT_ID = "local-dev"
SOURCE_RESOURCE_URN = "gda://local-dev/dataset/chongqing-dem-2020-raw"
SOURCE_RESOURCE_VERSION_ID = uuid5(
    NAMESPACE_URL,
    f"{SOURCE_RESOURCE_URN}:bundle-sha256:{EXPECTED_BUNDLE_SHA256}",
)
PRIMARY_STORAGE_URI = (
    "s3://gis-agent-lakehouse/raw/planning/chongqing_dem_2020/"
    f"bundle-sha256-{EXPECTED_BUNDLE_SHA256}/"
    f"physical-sha256-{EXPECTED_PRIMARY_SHA256}/Chongqing_aster_gdem_80m.tif"
)
DEFINITION_URN = "gda://local-dev/definition/chongqing-dem-ods-admission"
DEFINITION_VERSION_ID = uuid5(NAMESPACE_URL, f"{DEFINITION_URN}:v1")
OUTPUT_RESOURCE_URN = "gda://local-dev/dataset/chongqing-dem-2020-ods"
WORKFLOW_NAME = "gda_chongqing_dem_ods_v1"
WORKLOAD_SUBJECT = "workload:dolphinscheduler-gda-dataops"
WORKLOAD_SUBJECT_ID = WORKLOAD_SUBJECT.removeprefix("workload:")
POLICY_EVALUATOR_SUBJECT = "workload:gda-policy-evaluator"
QUALITY_EVALUATOR = "workload:raster-ods-ingestion-quality-evaluator"
QUALITY_RULE_VERSION = "gda://local-dev/quality_rule/chongqing-dem-ods:v1"
EXECUTOR_SCHEMA = "gda.chongqing_dem_ods_executor.v1"

MATERIALIZATION_CONTRACT = ObjectMaterializationContract(
    output_resource_urn=OUTPUT_RESOURCE_URN,
    output_resource_kind="dataset",
    authority_system="minio",
    authority_locator=PRIMARY_STORAGE_URI,
    source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
    workload_subject=WORKLOAD_SUBJECT,
    quality_evaluator=QUALITY_EVALUATOR,
    quality_rule_version=QUALITY_RULE_VERSION,
    governance_ref={
        "classification": "restricted",
        "logical_stage": "ods",
        "standardization_status": "unmatched_holdout",
        "promotion_eligible": False,
        "cog_conformance": "not_evaluated",
        "source_bundle_sha256": EXPECTED_BUNDLE_SHA256,
        "source_adapter_fingerprint": CHONGQING_DEM_SOURCE_ADAPTER.fingerprint,
    },
    technical_refs=(
        {
            "kind": "native_raster_bundle",
            "driver": "GTiff",
            "crs": "EPSG:4490",
            "width": 1766,
            "height": 1454,
            "band_count": 1,
            "primary_storage_uri": PRIMARY_STORAGE_URI,
        },
    ),
    output_artifact_identity="artifact:dem-ods-object-bundle:v1",
    evidence_artifact_identity="artifact:dem-ods-quality-evidence:v1",
    lineage_event_identity="lineage:dem-raw-to-ods-object:v1",
    output_artifact_key_prefix="cq_dem_ods_bundle",
    evidence_artifact_key_prefix="cq_dem_ods_quality",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChongqingDemOdsCommand(_FrozenModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    run_id: UUID
    source_resource_version_id: UUID
    definition_version_id: UUID


class ChongqingDemOdsResult(_FrozenModel):
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
    bundle_sha256: str
    member_count: int = Field(ge=1)
    valid_pixel_count: int = Field(ge=0)
    logical_stage: str = "ods"
    promotion_eligible: bool = False
    data_product_version_created: bool = False
    replayed: bool = False


class ChongqingDemOdsExecutorConfig(_FrozenModel):
    source_path: Path
    output_root: Path
    report_root: Path
    bucket: str = DEFAULT_BUCKET
    endpoint_url: str = "http://localhost:9000"
    access_key_id: str = "minio_admin"
    secret_access_key: str = "local_dev_minio_secret"

    @model_validator(mode="after")
    def _valid_paths(self) -> ChongqingDemOdsExecutorConfig:
        if not self.source_path.is_absolute() or not self.source_path.is_file():
            raise ValueError("source_path must be an existing absolute file")
        if not self.output_root.is_absolute() or not self.report_root.is_absolute():
            raise ValueError("output_root and report_root must be absolute")
        return self


ObjectRunner = Callable[[UUID, Path], dict[str, Any]]


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


def build_chongqing_dem_ods_definition(
    task_code: int,
    *,
    executor_url: str = "http://host.docker.internal:8090/v1/execute/chongqing-dem-ods",
) -> PlatformDefinitionVersion:
    task = {
        "code": task_code,
        "name": "admit_chongqing_dem_native_raster_ods",
        "version": 1,
        "description": "Admit sealed restricted DEM bundle as native-raster ODS",
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
        "schema": "gda.chongqing_dem_ods_definition.v1",
        "pipeline": {
            "profile": "default_lakehouse",
            "logical_stage": "ods",
            "classification": "restricted",
            "storage_contract": "native_raster_bundle",
            "table_format": None,
            "cog_conformance": "not_evaluated",
            "standardization_status": "unmatched_holdout",
            "promotion_eligible": False,
            "source_adapter": CHONGQING_DEM_SOURCE_ADAPTER.reference(),
        },
        "dolphinscheduler": {
            "name": WORKFLOW_NAME,
            "description": "Governed restricted DEM native-raster ODS admission",
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
                },
                {
                    "prop": "gda_definition_version_id",
                    "direct": "IN",
                    "type": "VARCHAR",
                    "value": str(DEFINITION_VERSION_ID),
                },
            ],
        },
    }
    input_contract = {
        "source": {
            "resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "semantic_type": "gis.raster.dem.raw_bundle",
            "source_kind": "raster",
            "classification": "restricted",
            "bundle_sha256": EXPECTED_BUNDLE_SHA256,
            "adapter_fingerprint": CHONGQING_DEM_SOURCE_ADAPTER.fingerprint,
        }
    }
    output_contract = {
        "resource_urn": OUTPUT_RESOURCE_URN,
        "semantic_type": "gis.raster.dem.ods_native_bundle",
        "logical_stage": "ods",
        "classification": "restricted",
        "storage_contract": "native_raster_bundle",
        "required_checks": list(CHONGQING_DEM_SOURCE_ADAPTER.required_checks),
        "cog_conformance": "not_evaluated",
        "promotion_eligible": False,
        "data_product_version_created": False,
    }
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="dem.native_raster.ods_admit",
        portability_class="portable",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id=TENANT_ID,
        definition_urn=DEFINITION_URN,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        capability_id="dem.native_raster.ods_admit",
        portability_class="portable",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )


def build_object_runner(config: ChongqingDemOdsExecutorConfig) -> ObjectRunner:
    materializer = build_s3_materialization_executor(
        endpoint_url=config.endpoint_url,
        access_key_id=config.access_key_id,
        secret_access_key=config.secret_access_key,
    )

    def runner(_run_id: UUID, report_path: Path) -> dict[str, Any]:
        report = stage_source(
            source_path=config.source_path,
            output_root=config.output_root,
            bucket=config.bucket,
            materializer=materializer,
            expected_bundle_sha256=EXPECTED_BUNDLE_SHA256,
            expected_primary_sha256=EXPECTED_PRIMARY_SHA256,
            expected_valid_pixel_count=EXPECTED_VALID_PIXEL_COUNT,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        temporary = report_path.with_name(f".{report_path.name}.{os.getpid()}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o640)
        os.replace(temporary, report_path)
        return report

    return runner


class ChongqingDemOdsExecutor:
    def __init__(
        self,
        config: ChongqingDemOdsExecutorConfig,
        *,
        gateway: PlatformGateway | None = None,
        runner: ObjectRunner | None = None,
    ) -> None:
        self.config = config
        self.gateway = gateway or PlatformGateway()
        self.runner = runner or build_object_runner(config)
        self.recorder = ObjectMaterializationRecorder(
            MATERIALIZATION_CONTRACT,
            gateway=self.gateway,
        )

    @staticmethod
    def _validate_run(run: PlatformRun, command: ChongqingDemOdsCommand) -> None:
        if run.tenant_id != TENANT_ID or command.tenant_id != TENANT_ID:
            raise ValueError("DEM ODS executor only accepts the local-dev tenant")
        if run.definition_version_id != DEFINITION_VERSION_ID:
            raise ValueError("PlatformRun does not bind the DEM ODS definition")
        if command.definition_version_id != run.definition_version_id:
            raise ValueError("command definition does not match PlatformRun")
        if command.source_resource_version_id != SOURCE_RESOURCE_VERSION_ID:
            raise ValueError("command source does not match the immutable definition")
        if run.orchestration_class.value != "dataops":
            raise ValueError("DEM ODS executor only accepts DataOps runs")
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

    def execute(self, command: ChongqingDemOdsCommand) -> ChongqingDemOdsResult:
        run = self.gateway.get_run(command.tenant_id, command.run_id)
        self._validate_run(run, command)
        existing = self.recorder.existing(
            tenant_id=command.tenant_id,
            run_id=command.run_id,
            definition_version_id=command.definition_version_id,
        )
        if existing is not None:
            return self._result(existing, valid_pixel_count=EXPECTED_VALID_PIXEL_COUNT)

        report_path = (
            self.config.report_root
            / command.tenant_id
            / str(command.run_id)
            / "provider-acceptance.json"
        )
        report = self.runner(run.run_id, report_path)
        self._validate_provider_report(report)
        bundle = report["source_bundle"]
        snapshots = report["bundle_snapshot"]["members"]
        primary_storage_uri = str(snapshots[0]["storage_uri"])
        evidence = self._materialization_evidence(report, run=run)
        record = self.recorder.record(
            run=run,
            bundle_sha256=str(bundle["bundle_sha256"]),
            member_count=int(report["bundle_snapshot"]["member_count"]),
            size_bytes=int(bundle["size_bytes"]),
            primary_storage_uri=primary_storage_uri,
            authority_version_ref={
                "provider": "minio",
                "storage_contract": "native_raster_bundle",
                "bundle_sha256": bundle["bundle_sha256"],
                "members": snapshots,
                "adapter_fingerprint": report["source_adapter"]["fingerprint"],
                "logical_stage": "ods",
            },
            evidence_path=report_path.with_name("quality-evidence.json"),
            evidence=evidence,
        )
        return self._result(
            record,
            valid_pixel_count=int(report["source_profile"]["bands"][0]["valid_pixel_count"]),
        )

    @staticmethod
    def _result(
        record: ObjectMaterializationRecord,
        *,
        valid_pixel_count: int,
    ) -> ChongqingDemOdsResult:
        return ChongqingDemOdsResult(
            status="completed",
            run_id=record.run_id,
            definition_version_id=record.definition_version_id,
            source_resource_version_id=record.source_resource_version_id,
            output_resource_version_id=record.output_resource_version_id,
            output_artifact_id=record.output_artifact_id,
            evidence_artifact_id=record.evidence_artifact_id,
            quality_result_id=record.quality_result_id,
            lineage_event_id=record.lineage_event_id,
            bundle_sha256=record.bundle_sha256,
            member_count=record.member_count,
            valid_pixel_count=valid_pixel_count,
            replayed=record.replayed,
        )

    @staticmethod
    def _validate_provider_report(report: dict[str, Any]) -> None:
        bundle = report.get("source_bundle") or {}
        profile = report.get("source_profile") or {}
        snapshot = report.get("bundle_snapshot") or {}
        quality = report.get("quality_state") or {}
        adapter = report.get("source_adapter") or {}
        if report.get("status") != "ready":
            raise RuntimeError("DEM source staging is not ready")
        if report.get("classification") != "restricted":
            raise RuntimeError("DEM source classification was weakened")
        if report.get("logical_target_stage") != "ods":
            raise RuntimeError("DEM source escaped the ODS boundary")
        if report.get("publication_eligible") is not False:
            raise RuntimeError("DEM source must not be eligible for publication")
        if bundle.get("bundle_sha256") != EXPECTED_BUNDLE_SHA256:
            raise RuntimeError("DEM provider returned the wrong bundle")
        if adapter.get("fingerprint") != CHONGQING_DEM_SOURCE_ADAPTER.fingerprint:
            raise RuntimeError("DEM provider used an ungoverned adapter")
        if profile.get("driver") != "GTiff" or profile.get("epsg") != 4490:
            raise RuntimeError("DEM provider returned the wrong raster grid contract")
        if profile.get("width") != 1766 or profile.get("height") != 1454:
            raise RuntimeError("DEM provider returned the wrong raster dimensions")
        if int(profile["bands"][0]["valid_pixel_count"]) != EXPECTED_VALID_PIXEL_COUNT:
            raise RuntimeError("DEM provider did not scan the governed valid pixels")
        if snapshot.get("member_count") != 7 or snapshot.get("all_readback_verified") is not True:
            raise RuntimeError("DEM bundle readback evidence is incomplete")
        expected_quality = {
            "raw_source_integrity": "passed",
            "full_pixel_scan": "passed",
            "cog_conformance": "not_evaluated",
            "ods_admission": "not_evaluated",
            "standard_mapping": "not_evaluated",
            "promotion": "blocked",
        }
        if any(quality.get(key) != value for key, value in expected_quality.items()):
            raise RuntimeError("DEM provider quality states are inconsistent")

    @staticmethod
    def _materialization_evidence(
        report: dict[str, Any],
        *,
        run: PlatformRun,
    ) -> ObjectMaterializationEvidence:
        bundle = report["source_bundle"]
        profile = report["source_profile"]
        snapshot = report["bundle_snapshot"]
        band = profile["bands"][0]
        output_manifest = {
            "schema": "gda.native_raster_ods_bundle.v1",
            "bundle_sha256": bundle["bundle_sha256"],
            "member_count": snapshot["member_count"],
            "size_bytes": bundle["size_bytes"],
            "members": snapshot["members"],
            "logical_stage": "ods",
            "classification": "restricted",
            "driver": profile["driver"],
            "crs": profile["crs"],
            "grid": {
                "width": profile["width"],
                "height": profile["height"],
                "transform": profile["transform"],
                "bounds": profile["bounds"],
            },
            "cog_conformance": "not_evaluated",
            "promotion_eligible": False,
        }
        quality_metrics = {
            "quality_scope": "ods_native_raster_ingestion_integrity",
            "bundle_sha256": bundle["bundle_sha256"],
            "member_count": snapshot["member_count"],
            "all_readback_verified": snapshot["all_readback_verified"],
            "pixel_count": band["pixel_count"],
            "valid_pixel_count": band["valid_pixel_count"],
            "nodata_pixel_count": band["nodata_pixel_count"],
            "value_range": [band["min"], band["max"]],
            "full_dataset_validated": True,
            "cog_conformance": "not_evaluated",
            "promotion_eligible": False,
            "data_product_version_created": False,
            "release_block_reasons": report["quality_state"]["promotion_blockers"],
        }
        evidence_document = {
            "schema": "gda.native_raster_ods_quality_evidence.v1",
            "run_id": str(run.run_id),
            "definition_version_id": str(run.definition_version_id),
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "source_adapter": report["source_adapter"],
            "source_bundle": bundle,
            "source_profile": profile,
            "quality_state": report["quality_state"],
            "quality_metrics": quality_metrics,
            "evaluated_by": QUALITY_EVALUATOR,
            "evaluated_at": run.submitted_at.isoformat(),
        }
        lineage_facets = {
            "schema": "gda.native_raster_ods_lineage.v1",
            "operation": "byte_preserving_bundle_admission",
            "logical_stage": "ods",
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "materialization_run_id": str(run.run_id),
            "definition_version_id": str(run.definition_version_id),
            "bundle_sha256": bundle["bundle_sha256"],
            "adapter_fingerprint": report["source_adapter"]["fingerprint"],
            "bytes_transformed": False,
            "cog_conformance": "not_evaluated",
            "promotion_eligible": False,
        }
        return ObjectMaterializationEvidence(
            evidence_document=evidence_document,
            output_manifest=output_manifest,
            lineage_facets=lineage_facets,
            quality_metrics=quality_metrics,
        )
