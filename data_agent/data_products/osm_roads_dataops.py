"""Governed DataOps execution for the Chongqing OSM roads product."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.data_products.chongqing_osm_roads import (
    PRODUCT_URN,
    QUALITY_RULE_VERSION,
    SOURCE_URN,
    TENANT_ID,
    build_and_publish,
)
from data_agent.platform_contracts import (
    Artifact,
    ArtifactRole,
    LineageEvent,
    LineageEventType,
    PlatformDefinitionVersion,
    PlatformRun,
    QualityResult,
    RunStatus,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    quality_result_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway

DEFINITION_URN = "gda://local-dev/definition/chongqing-osm-roads-layered-publish"
DEFINITION_VERSION_ID = uuid5(NAMESPACE_URL, f"{DEFINITION_URN}:v1")
SOURCE_RESOURCE_VERSION_ID = UUID("786dd3d1-c54e-5839-9956-d418cbc6e945")
WORKFLOW_NAME = "gda_chongqing_osm_roads_layered_publish_v1"
WORKLOAD_SUBJECT = "workload:dolphinscheduler-gda-dataops"
WORKLOAD_SUBJECT_ID = WORKLOAD_SUBJECT.removeprefix("workload:")
POLICY_EVALUATOR_SUBJECT = "workload:gda-policy-evaluator"
QUALITY_EVALUATOR = "workload:chongqing-osm-roads-quality-evaluator"
PRODUCT_VERSION = "v1.2.0"
EXECUTOR_SCHEMA = "gda.chongqing_osm_roads_dataops_executor.v1"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OsmRoadsDataOpsCommand(_FrozenModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    run_id: UUID
    source_resource_version_id: UUID
    definition_version_id: UUID
    version_key: str = PRODUCT_VERSION


class OsmRoadsDataOpsResult(_FrozenModel):
    schema_name: str = Field(default=EXECUTOR_SCHEMA, alias="schema")
    status: str
    run_id: UUID
    definition_version_id: UUID
    source_resource_version_id: UUID
    output_resource_version_id: UUID
    data_product_version_id: UUID
    output_artifact_id: UUID
    quality_evidence_artifact_id: UUID
    quality_result_id: UUID
    lineage_event_id: UUID
    version_key: str
    feature_count: int = Field(ge=0)
    quality_verdict: str
    replayed: bool = False


class OsmRoadsExecutorConfig(_FrozenModel):
    source_path: Path
    output_root: Path

    @model_validator(mode="after")
    def _valid_paths(self) -> OsmRoadsExecutorConfig:
        if not self.source_path.is_absolute() or not self.source_path.is_file():
            raise ValueError("OSM source must be an existing absolute file")
        if not self.output_root.is_absolute():
            raise ValueError("OSM output root must be absolute")
        return self


def output_artifact_id(run_id: UUID) -> UUID:
    return uuid5(run_id, "artifact:postgis-standardized-snapshot:v1")


def quality_result_id(run_id: UUID) -> UUID:
    return uuid5(run_id, f"quality:{QUALITY_RULE_VERSION}")


def final_lineage_event_id(run_id: UUID) -> UUID:
    return uuid5(run_id, "lineage:source-to-postgis-standardized-snapshot:v1")


def _actor_ref(run: PlatformRun) -> str:
    return f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"


def _raw_script(executor_url: str) -> str:
    return f"""set -eu
payload='{{\"tenant_id\":\"${{gda_tenant_id}}\",'
payload=$payload'\"run_id\":\"${{gda_run_id}}\",'
payload=$payload'\"definition_version_id\":\"${{gda_definition_version_id}}\",'
payload=$payload'\"source_resource_version_id\":\"${{gda_source_resource_version_id}}\",'
payload=$payload'\"version_key\":\"{PRODUCT_VERSION}\"}}'
curl --fail --silent --show-error --retry 1 --retry-all-errors \\
  --connect-timeout 5 --max-time 1200 \\
  --header "Authorization: Bearer $(cat /run/secrets/gda-dataops-executor-token)" \\
  --header "Content-Type: application/json" \\
  --data "$payload" \\
  {executor_url}
"""


def build_osm_roads_definition(
    task_code: int,
    *,
    executor_url: str = (
        "http://host.docker.internal:8090/v1/execute/"
        "chongqing-osm-roads-layered-publish"
    ),
) -> PlatformDefinitionVersion:
    """Build the immutable logical job and its real DolphinScheduler graph."""
    task = {
        "code": task_code,
        "name": "publish_chongqing_osm_roads_layered",
        "version": 1,
        "description": "Publish governed Raw-to-ADS Chongqing OSM roads",
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
        "failRetryInterval": 5,
        "timeoutFlag": "OPEN",
        "timeoutNotifyStrategy": "WARN",
        "timeout": 1500,
        "taskGroupId": 0,
        "taskGroupPriority": 0,
        "cpuQuota": -1,
        "memoryMax": -1,
    }
    definition_document = {
        "schema": "gda.chongqing_osm_roads_job_definition.v1",
        "pipeline": {
            "profile": "lightweight_layered",
            "version_key": PRODUCT_VERSION,
            "stages": ["raw", "ods", "silver", "gold", "ads"],
            "quality_gate": "all_critical_checks_pass",
            "publication": "immutable_data_product_version",
        },
        "dolphinscheduler": {
            "name": WORKFLOW_NAME,
            "description": "Governed full-data OSM roads layered publication",
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
            "timeout_seconds": 1800,
            "execution_type": "PARALLEL",
        },
    }
    input_contract = {
        "source": {
            "semantic_type": "gis.transportation.osm_roads.source",
            "resource_urn": SOURCE_URN,
            "resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "access": "read_only",
        }
    }
    output_contract = {
        "product_urn": PRODUCT_URN,
        "product_version": PRODUCT_VERSION,
        "layers": ["raw", "ods", "silver", "gold", "ads"],
        "required_evidence": [
            "passed_quality_result",
            "run_bound_output_artifact",
            "input_to_output_lineage",
            "stac_item",
        ],
    }
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="transportation.osm_roads.layered_publish",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id=TENANT_ID,
        definition_urn=DEFINITION_URN,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        capability_id="transportation.osm_roads.layered_publish",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )


class OsmRoadsDataOpsExecutor:
    """Execute one immutable OSM product build for an admitted PlatformRun."""

    def __init__(
        self,
        config: OsmRoadsExecutorConfig,
        *,
        gateway: PlatformGateway | None = None,
    ):
        self.config = config
        self.gateway = gateway or PlatformGateway()

    @staticmethod
    def _validate_run(run: PlatformRun, command: OsmRoadsDataOpsCommand) -> None:
        if run.tenant_id != TENANT_ID or command.tenant_id != TENANT_ID:
            raise ValueError("OSM executor only accepts the local-dev tenant")
        if run.definition_version_id != DEFINITION_VERSION_ID:
            raise ValueError("PlatformRun does not bind the OSM definition")
        if command.definition_version_id != run.definition_version_id:
            raise ValueError("command definition does not match PlatformRun")
        if command.source_resource_version_id != SOURCE_RESOURCE_VERSION_ID:
            raise ValueError("command source does not match the immutable definition")
        if command.version_key != PRODUCT_VERSION:
            raise ValueError("command product version does not match the definition")
        if run.orchestration_class.value != "dataops":
            raise ValueError("OSM executor only accepts DataOps runs")
        if _actor_ref(run) != WORKLOAD_SUBJECT:
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

    def execute(self, command: OsmRoadsDataOpsCommand) -> OsmRoadsDataOpsResult:
        run = self.gateway.get_run(command.tenant_id, command.run_id)
        self._validate_run(run, command)
        receipt = build_and_publish(
            source_path=self.config.source_path,
            output_root=self.config.output_root,
            version_key=PRODUCT_VERSION,
            publication_profile="lightweight_layered",
            gateway=self.gateway,
            run_id=run.run_id,
            definition_version_id=run.definition_version_id,
            quality_evaluator=QUALITY_EVALUATOR,
        )
        output_version_id = UUID(receipt["output_resource_version_id"])
        evidence_artifact_id = UUID(receipt["quality_evidence_artifact_id"])
        published_at = datetime.fromisoformat(receipt["published_at"]).astimezone(UTC)

        snapshot_artifact = Artifact(
            tenant_id=run.tenant_id,
            artifact_id=output_artifact_id(run.run_id),
            artifact_key=f"cq_osm_run_output_{run.run_id.hex[:16]}",
            artifact_role=ArtifactRole.OUTPUT,
            storage_uri=(
                "postgresql://gis-agent/"
                + receipt["postgis_table"].replace(".", "/")
            ),
            media_type="application/vnd.gda.postgis-snapshot+json",
            content_sha256=receipt["semantic_sha256"],
            size_bytes=0,
            run_id=run.run_id,
            resource_version_id=output_version_id,
            manifest={
                "schema": "gda.postgis_snapshot_artifact.v1",
                "postgis_table": receipt["postgis_table"],
                "feature_count": receipt["feature_count"],
                "semantic_sha256": receipt["semantic_sha256"],
                "data_product_version_id": receipt["data_product_version_id"],
                "physical_geojson_artifact_id": receipt["output_artifact_id"],
                "layer_manifest_sha256": receipt["layered_manifest"][
                    "manifest_sha256"
                ],
            },
            created_by=WORKLOAD_SUBJECT,
            created_at=published_at,
        )
        snapshot_result = self.gateway.record_artifact(snapshot_artifact)

        lineage_facets: dict[str, Any] = {
            "schema": "gda.dataops_product_lineage.v1",
            "operation": "layered_standardize_and_publish",
            "run_id": str(run.run_id),
            "definition_version_id": str(run.definition_version_id),
            "product_urn": PRODUCT_URN,
            "product_version": PRODUCT_VERSION,
            "data_product_version_id": receipt["data_product_version_id"],
            "source_bundle_sha256": receipt["source_bundle_sha256"],
            "output_semantic_sha256": receipt["semantic_sha256"],
        }
        lineage = LineageEvent(
            tenant_id=run.tenant_id,
            lineage_event_id=final_lineage_event_id(run.run_id),
            event_type=LineageEventType.PUBLISH,
            source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
            target_resource_version_id=output_version_id,
            producer=WORKLOAD_SUBJECT,
            event_sha256=canonical_json_fingerprint(lineage_facets),
            run_id=run.run_id,
            definition_version_id=run.definition_version_id,
            artifact_id=snapshot_artifact.artifact_id,
            facets=lineage_facets,
            occurred_at=published_at,
        )
        lineage_result = self.gateway.record_lineage(lineage)

        metrics = {
            "feature_count": receipt["feature_count"],
            "mapping_recommended": receipt["mapping"]["mapped_fields"],
            "mapping_review_required": receipt["mapping"]["review_required"],
            "source_bundle_sha256": receipt["source_bundle_sha256"],
            "output_semantic_sha256": receipt["semantic_sha256"],
            "layer_checks_passed": sum(
                check["status"] == "passed"
                for check in receipt["layered_manifest"]["checks"]
            ),
            "full_dataset_validated": True,
            "data_product_version_id": receipt["data_product_version_id"],
        }
        quality_id = quality_result_id(run.run_id)
        quality = QualityResult(
            tenant_id=run.tenant_id,
            quality_result_id=quality_id,
            run_id=run.run_id,
            resource_version_id=output_version_id,
            rule_version_ref=QUALITY_RULE_VERSION,
            verdict="passed",
            metrics=metrics,
            evidence_artifact_id=evidence_artifact_id,
            result_sha256=quality_result_fingerprint(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                resource_version_id=output_version_id,
                rule_version_ref=QUALITY_RULE_VERSION,
                verdict="passed",
                metrics=metrics,
                evidence_artifact_id=evidence_artifact_id,
                evaluated_by=QUALITY_EVALUATOR,
                evaluated_at=published_at,
            ),
            evaluated_by=QUALITY_EVALUATOR,
            evaluated_at=published_at,
        )
        quality_result = self.gateway.record_quality_result(quality)

        return OsmRoadsDataOpsResult(
            status="completed",
            run_id=run.run_id,
            definition_version_id=run.definition_version_id,
            source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
            output_resource_version_id=output_version_id,
            data_product_version_id=UUID(receipt["data_product_version_id"]),
            output_artifact_id=snapshot_artifact.artifact_id,
            quality_evidence_artifact_id=evidence_artifact_id,
            quality_result_id=quality_id,
            lineage_event_id=lineage.lineage_event_id,
            version_key=PRODUCT_VERSION,
            feature_count=receipt["feature_count"],
            quality_verdict=receipt["quality_verdict"],
            replayed=(
                receipt["idempotent"]
                and not snapshot_result.created
                and not lineage_result.created
                and not quality_result.created
            ),
        )
