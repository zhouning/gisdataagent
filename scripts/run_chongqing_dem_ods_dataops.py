#!/usr/bin/env python3
"""Run the real governed Chongqing DEM native-raster ODS control chain."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.data_product_registry import (  # noqa: E402
    DataProductNotFoundError,
    DataProductRegistry,
)
from data_agent.data_products.chongqing_dem_ods_dataops import (  # noqa: E402
    DEFINITION_URN,
    DEFINITION_VERSION_ID,
    MATERIALIZATION_CONTRACT,
    POLICY_EVALUATOR_SUBJECT,
    PRIMARY_STORAGE_URI,
    QUALITY_EVALUATOR,
    SOURCE_RESOURCE_URN,
    SOURCE_RESOURCE_VERSION_ID,
    TENANT_ID,
    WORKFLOW_NAME,
    WORKLOAD_SUBJECT,
    WORKLOAD_SUBJECT_ID,
    build_chongqing_dem_ods_definition,
)
from data_agent.dataops_manual import DataOpsManualTriggerSpec  # noqa: E402
from data_agent.dolphinscheduler_adapter import (  # noqa: E402
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerError,
    DolphinSchedulerProfile,
    compile_dolphinscheduler_workflow,
)
from data_agent.dolphinscheduler_command_consumer import (  # noqa: E402
    DolphinSchedulerCommandConsumer,
)
from data_agent.platform_contracts import (  # noqa: E402
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunSuccessEvidence,
    canonical_json_fingerprint,
    run_success_evidence_fingerprint,
)
from data_agent.platform_gateway import (  # noqa: E402
    DefinitionRegistration,
    PlatformGateway,
)
from scripts.stage_chongqing_dem import (  # noqa: E402
    EXPECTED_BUNDLE_SHA256,
    EXPECTED_PRIMARY_SHA256,
)

DEFAULT_PROFILE = REPO_ROOT / ".tmp/dolphinscheduler-sandbox/profile.json"
DEFAULT_RUNTIME_DIR = REPO_ROOT / ".tmp/dolphinscheduler-sandbox/chongqing-dem-ods-v1"
DEFAULT_SOURCE_MANIFEST = DEFAULT_RUNTIME_DIR / "source/source-snapshot-manifest.json"
DEFAULT_EXECUTOR_TOKEN = REPO_ROOT / ".tmp/dolphinscheduler-sandbox/executor-token"
DEFAULT_CLIENT_REQUEST_ID = "chongqing-dem-ods-v1-20260801-001"
EXECUTOR_URL = "http://127.0.0.1:8090/v1/execute/chongqing-dem-ods"
TERMINAL_PROVIDER_STATES = {
    "SUCCESS",
    "FAILURE",
    "STOP",
    "PAUSE",
    "NEED_FAULT_TOLERANCE",
    "KILL",
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _profile(value: dict[str, Any]) -> DolphinSchedulerProfile:
    token = Path(str(value["token_file"])).read_text(encoding="utf-8").strip()
    return DolphinSchedulerProfile(
        base_url=str(value["base_url"]),
        access_token=token,
        project_code=int(value["project_code"]),
        workload_subject=WORKLOAD_SUBJECT,
        policy_evaluator_subject=POLICY_EVALUATOR_SUBJECT,
        tenant_code=str(value["tenant_code"]),
        worker_group=str(value["worker_group"]),
        timezone_name="Asia/Tokyo",
    )


def _register_source(
    gateway: PlatformGateway,
    source_manifest: dict[str, Any],
) -> dict[str, Any]:
    bundle = source_manifest["source_bundle"]
    profile = source_manifest["source_profile"]
    snapshots = source_manifest["bundle_snapshot"]
    if bundle["bundle_sha256"] != EXPECTED_BUNDLE_SHA256:
        raise RuntimeError("source manifest does not bind the governed DEM bundle")
    if snapshots["members"][0]["physical_sha256"] != EXPECTED_PRIMARY_SHA256:
        raise RuntimeError("source manifest does not bind the governed primary TIFF")
    created_at = datetime(2026, 8, 1, 13, 0, tzinfo=UTC)
    resource_result = gateway.register_resource(
        Resource(
            tenant_id=TENANT_ID,
            resource_urn=SOURCE_RESOURCE_URN,
            resource_kind="dataset",
            authority_system="minio",
            authority_locator=(
                "gis-agent-lakehouse/raw/planning/chongqing_dem_2020/"
                f"bundle-sha256-{EXPECTED_BUNDLE_SHA256}"
            ),
            owner_ref="team:data-platform",
            governance_ref={
                "classification": "restricted",
                "redistribution_allowed": False,
                "logical_stage": "raw",
                "standardization_status": "unmatched_holdout",
                "promotion_eligible": False,
                "cog_conformance": "not_evaluated",
            },
            technical_refs=(
                {
                    "kind": "geotiff_bundle",
                    "driver": profile["driver"],
                    "crs": profile["crs"],
                    "width": profile["width"],
                    "height": profile["height"],
                    "member_count": snapshots["member_count"],
                    "primary_storage_uri": PRIMARY_STORAGE_URI,
                },
            ),
        )
    )
    version_result = gateway.register_resource_version(
        ResourceVersion(
            tenant_id=TENANT_ID,
            resource_urn=SOURCE_RESOURCE_URN,
            resource_version_id=SOURCE_RESOURCE_VERSION_ID,
            version_key=f"sha256-{EXPECTED_BUNDLE_SHA256[:12]}",
            content_sha256=EXPECTED_BUNDLE_SHA256,
            authority_version_ref={
                "bundle_sha256": EXPECTED_BUNDLE_SHA256,
                "primary_physical_sha256": EXPECTED_PRIMARY_SHA256,
                "member_count": snapshots["member_count"],
                "size_bytes": bundle["size_bytes"],
                "members": snapshots["members"],
                "adapter_fingerprint": source_manifest["source_adapter"]["fingerprint"],
                "valid_pixel_count": profile["bands"][0]["valid_pixel_count"],
                "nodata_pixel_count": profile["bands"][0]["nodata_pixel_count"],
                "standardization_status": "unmatched_holdout",
            },
            created_by="workload:dem-source-snapshotter",
            created_at=created_at,
        )
    )
    return {
        "schema": "gda.chongqing_dem_source_registration.v1",
        "resource_urn": SOURCE_RESOURCE_URN,
        "resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "bundle_sha256": EXPECTED_BUNDLE_SHA256,
        "primary_physical_sha256": EXPECTED_PRIMARY_SHA256,
        "member_count": snapshots["member_count"],
        "storage_uri": PRIMARY_STORAGE_URI,
        "classification": "restricted",
        "promotion_eligible": False,
        "resource_created": resource_result.created,
        "resource_version_created": version_result.created,
    }


def _deploy(
    gateway: PlatformGateway,
    profile: DolphinSchedulerProfile,
    runtime_dir: Path,
) -> tuple[dict[str, Any], UUID]:
    state_path = runtime_dir / "definition-state.json"
    created_at = datetime(2026, 8, 1, 13, 5, tzinfo=UTC)
    with DolphinSchedulerClient(profile) as client:
        if state_path.exists():
            task_code = int(_read_json(state_path)["task_code"])
        else:
            task_code = client.generate_task_codes(1)[0]
            _write_json(
                state_path,
                {
                    "schema": "gda.chongqing_dem_ods_definition_state.v1",
                    "task_code": task_code,
                },
            )
        definition = build_chongqing_dem_ods_definition(task_code)
        registration = DefinitionRegistration(
            resource=Resource(
                tenant_id=TENANT_ID,
                resource_urn=DEFINITION_URN,
                resource_kind="definition",
                authority_system="gda-control",
                authority_locator="definitions/chongqing-dem-ods/v1",
                owner_ref="team:data-platform",
                governance_ref={
                    "classification": "internal",
                    "release_stage": "sandbox",
                    "source_classification": "restricted",
                    "promotion_eligible": False,
                },
            ),
            resource_version=ResourceVersion(
                tenant_id=TENANT_ID,
                resource_urn=DEFINITION_URN,
                resource_version_id=DEFINITION_VERSION_ID,
                version_key="v1",
                content_sha256=definition.definition_sha256,
                authority_version_ref={
                    "schema": "gda.chongqing_dem_ods_definition.v1",
                    "storage_contract": "native_raster_bundle",
                    "logical_stage": "ods",
                    "promotion_eligible": False,
                },
                created_by=WORKLOAD_SUBJECT,
                created_at=created_at,
            ),
            definition=definition,
        )
        definition_result = gateway.register_definition(registration)
        compiled = compile_dolphinscheduler_workflow(definition)
        existing = [
            item
            for item in client.list_workflows(search_value=WORKFLOW_NAME)
            if item.get("name") == WORKFLOW_NAME
        ]
        if len(existing) > 1:
            raise RuntimeError("multiple workflows share the DEM ODS name")
        workflow_created = not existing
        if existing:
            item = existing[0]
            binding = DolphinSchedulerDefinitionBinding(
                tenant_id=TENANT_ID,
                definition_version_id=DEFINITION_VERSION_ID,
                project_code=profile.project_code,
                workflow_definition_code=int(item["code"]),
                workflow_definition_version=int(item["version"]),
                compiled_sha256=compiled.compiled_sha256,
            )
            client.release_workflow(binding.workflow_definition_code)
        else:
            binding = client.create_workflow(compiled)

    adapter = DolphinSchedulerAdapter(profile, gateway=gateway)
    try:
        binding_result = adapter.persist_binding(
            binding,
            actor_subject=WORKLOAD_SUBJECT,
            created_at=created_at,
        )
    finally:
        adapter.client.close()
    report = {
        "schema": "gda.chongqing_dem_ods_deployment.v1",
        "status": "ready",
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "definition_sha256": definition.definition_sha256,
        "compiled_sha256": compiled.compiled_sha256,
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "storage_contract": "native_raster_bundle",
        "logical_stage": "ods",
        "promotion_eligible": False,
        "project_code": profile.project_code,
        "workflow_definition_code": binding.workflow_definition_code,
        "workflow_definition_version": binding.workflow_definition_version,
        "binding_artifact_id": str(binding_result.value.artifact_id),
        "definition_created": definition_result.created,
        "workflow_created": workflow_created,
        "binding_created": binding_result.created,
    }
    _write_json(runtime_dir / "deployment-report.json", report)
    return report, binding_result.value.artifact_id


def _submit(
    gateway: PlatformGateway,
    *,
    binding_artifact_id: UUID,
    compiled_sha256: str,
    client_request_id: str,
) -> dict[str, Any]:
    result = gateway.submit_manual_trigger(
        DataOpsManualTriggerSpec(
            tenant_id=TENANT_ID,
            client_request_id=client_request_id,
            definition_version_id=DEFINITION_VERSION_ID,
            logical_start=datetime(2020, 1, 1, tzinfo=UTC),
            logical_end=datetime(2021, 1, 1, tzinfo=UTC),
            input_bindings=(
                ResourceBinding(
                    binding_name="source",
                    resource_version_id=SOURCE_RESOURCE_VERSION_ID,
                    semantic_type="gis.raster.dem.raw_bundle",
                ),
            ),
            execution_plan_artifact_id=binding_artifact_id,
            requester_subject="human:data-platform-operator",
            workload_subject_id=WORKLOAD_SUBJECT_ID,
            workload_roles=("platform_operator",),
            purpose="admit restricted Chongqing DEM bundle as native-raster ODS",
            policy_version_ref="gda://local-dev/policy/restricted-dem-ods-sandbox:v1",
            policy_evaluator_subject=POLICY_EVALUATOR_SUBJECT,
            policy_ttl_seconds=86400,
            config_fingerprint=compiled_sha256,
        )
    )
    return {
        "schema": "gda.chongqing_dem_ods_submission.v1",
        "run_id": str(result.run.run_id),
        "run_status": result.run.status.value,
        "run_state_version": result.run.state_version,
        "request_sha256": result.request_sha256,
        "definition_version_id": str(result.run.definition_version_id),
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "binding_artifact_id": str(binding_artifact_id),
        "dispatch_command_id": str(result.command.command_id),
        "dispatch_command_status": result.command.status.value,
        "platform_run_created": result.run_created,
        "dispatch_command_created": result.command_created,
    }


def _dispatch_and_wait(
    gateway: PlatformGateway,
    profile: DolphinSchedulerProfile,
    *,
    run_id: UUID,
    binding_artifact_id: UUID,
    timeout_seconds: int,
    poll_seconds: float,
) -> tuple[dict[str, Any], UUID]:
    adapter = DolphinSchedulerAdapter(profile, gateway=gateway)
    consumer = DolphinSchedulerCommandConsumer(adapter, gateway=gateway)
    try:
        batch = consumer.run_once(
            TENANT_ID,
            worker_id="worker:chongqing-dem-ods-v1",
            limit=10,
            lease_seconds=60,
        )
        deadline = time.monotonic() + timeout_seconds
        last_error: str | None = None
        while time.monotonic() < deadline:
            try:
                reconciliation = adapter.reconcile(
                    TENANT_ID,
                    run_id,
                    binding_artifact_id,
                    actor_subject=WORKLOAD_SUBJECT,
                )
            except DolphinSchedulerError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(poll_seconds)
                continue
            state = reconciliation.provider_state.upper()
            if state in TERMINAL_PROVIDER_STATES:
                if state != "SUCCESS":
                    failed_run = reconciliation.run
                    if failed_run.status.value != "failed":
                        gateway.transition_run(
                            TENANT_ID,
                            run_id,
                            failed_run.state_version,
                            "failed",
                            WORKLOAD_SUBJECT,
                            "DolphinScheduler DEM ODS workflow failed",
                            {
                                "provider_state": state,
                                "workflow_instance_id": reconciliation.workflow_instance_id,
                                "observation_id": str(
                                    reconciliation.observation.observation_id
                                ),
                            },
                        )
                    raise RuntimeError(
                        f"DolphinScheduler DEM ODS workflow terminated as {state}"
                    )
                return (
                    {
                        "schema": "gda.chongqing_dem_ods_provider_execution.v1",
                        "provider_state": state,
                        "workflow_instance_id": reconciliation.workflow_instance_id,
                        "success_observation_id": str(
                            reconciliation.observation.observation_id
                        ),
                        "observation_created": reconciliation.observation_created,
                        "outbox_claimed": batch.claimed,
                        "outbox_completed": batch.completed,
                        "outbox_retry_pending": batch.retry_pending,
                        "last_transient_error": last_error,
                    },
                    reconciliation.observation.observation_id,
                )
            time.sleep(poll_seconds)
        raise TimeoutError("DolphinScheduler DEM ODS workflow did not finish")
    finally:
        adapter.client.close()


def _finalize(
    gateway: PlatformGateway,
    *,
    run_id: UUID,
    success_observation_id: UUID,
) -> dict[str, Any]:
    output_id = MATERIALIZATION_CONTRACT.output_artifact_id(run_id)
    quality_id = MATERIALIZATION_CONTRACT.quality_result_id(run_id)
    lineage_id = MATERIALIZATION_CONTRACT.lineage_event_id(run_id)
    evidence = RunSuccessEvidence(
        tenant_id=TENANT_ID,
        run_id=run_id,
        attempt_observation_id=success_observation_id,
        output_artifact_id=output_id,
        quality_result_id=quality_id,
        lineage_event_id=lineage_id,
        evidence_sha256=run_success_evidence_fingerprint(
            tenant_id=TENANT_ID,
            run_id=run_id,
            attempt_observation_id=success_observation_id,
            output_artifact_id=output_id,
            quality_result_id=quality_id,
            lineage_event_id=lineage_id,
        ),
    )
    before = gateway.get_run(TENANT_ID, run_id)
    run = gateway.finalize_run_success(
        evidence,
        expected_state_version=before.state_version,
        actor_subject=WORKLOAD_SUBJECT,
        reason="DolphinScheduler and native-raster ODS integrity evidence passed",
    )
    output = gateway.get_artifact(TENANT_ID, output_id)
    quality = gateway.get_quality_result(TENANT_ID, quality_id)
    output_version = gateway.get_resource_version(TENANT_ID, output.resource_version_id)
    return {
        "schema": "gda.chongqing_dem_ods_finalization.v1",
        "run_id": str(run_id),
        "status": run.status.value,
        "state_version": run.state_version,
        "transitioned": before.status != run.status,
        "output_artifact_id": str(output.artifact_id),
        "output_resource_version_id": str(output.resource_version_id),
        "bundle_sha256": output.manifest["bundle_sha256"],
        "member_count": output.manifest["member_count"],
        "logical_stage": output.manifest["logical_stage"],
        "content_fingerprint": output_version.content_sha256,
        "quality_result_id": str(quality.quality_result_id),
        "quality_evidence_artifact_id": str(quality.evidence_artifact_id),
        "quality_verdict": quality.verdict.value,
        "quality_scope": quality.metrics["quality_scope"],
        "quality_evaluator": quality.evaluated_by,
        "valid_pixel_count": quality.metrics["valid_pixel_count"],
        "nodata_pixel_count": quality.metrics["nodata_pixel_count"],
        "cog_conformance": quality.metrics["cog_conformance"],
        "promotion_eligible": quality.metrics["promotion_eligible"],
        "data_product_version_created": quality.metrics["data_product_version_created"],
        "lineage_event_id": str(lineage_id),
        "success_evidence_sha256": evidence.evidence_sha256,
    }


def _executor_replay(token_file: Path, run_id: UUID) -> dict[str, Any]:
    payload = json.dumps(
        {
            "tenant_id": TENANT_ID,
            "run_id": str(run_id),
            "definition_version_id": str(DEFINITION_VERSION_ID),
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        EXECUTOR_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token_file.read_text(encoding='utf-8').strip()}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - localhost
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("executor replay response must be an object")
    return value


def _product_absent(registry: DataProductRegistry) -> bool:
    try:
        registry.get_product(TENANT_ID, "chongqing-dem-2020")
    except DataProductNotFoundError:
        return True
    return False


def run(
    *,
    profile_path: Path,
    runtime_dir: Path,
    source_manifest_path: Path,
    executor_token: Path,
    client_request_id: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    profile = _profile(_read_json(profile_path))
    source_manifest = _read_json(source_manifest_path)
    gateway = PlatformGateway()
    source = _register_source(gateway, source_manifest)
    deployment, binding_artifact_id = _deploy(gateway, profile, runtime_dir)
    submission = _submit(
        gateway,
        binding_artifact_id=binding_artifact_id,
        compiled_sha256=deployment["compiled_sha256"],
        client_request_id=client_request_id,
    )
    _write_json(runtime_dir / "submission-report.json", submission)
    run_id = UUID(submission["run_id"])
    provider, success_observation_id = _dispatch_and_wait(
        gateway,
        profile,
        run_id=run_id,
        binding_artifact_id=binding_artifact_id,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
    )
    finalization = _finalize(
        gateway,
        run_id=run_id,
        success_observation_id=success_observation_id,
    )
    executor_replay = _executor_replay(executor_token, run_id)
    product_absent = _product_absent(DataProductRegistry())
    replay = {
        "observed": (
            not submission["platform_run_created"]
            and not submission["dispatch_command_created"]
        ),
        "source_resource_reused": not source["resource_created"],
        "source_version_reused": not source["resource_version_created"],
        "definition_reused": not deployment["definition_created"],
        "binding_reused": not deployment["binding_created"],
        "workflow_reused": not deployment["workflow_created"],
        "outbox_not_reclaimed": provider["outbox_claimed"] == 0,
        "observation_reused": provider["observation_created"] is False,
        "run_terminal_state_reused": finalization["transitioned"] is False,
        "executor_skipped_provider": executor_replay.get("replayed") is True,
    }
    replay_checks = [value for key, value in replay.items() if key != "observed"]
    checks = {
        "restricted_source_registered": (
            source["classification"] == "restricted"
            and source["promotion_eligible"] is False
        ),
        "definition_registered": deployment["status"] == "ready",
        "platform_run_bound_definition": (
            submission["definition_version_id"] == str(DEFINITION_VERSION_ID)
        ),
        "source_snapshot_bound_to_run": (
            submission["source_resource_version_id"]
            == str(SOURCE_RESOURCE_VERSION_ID)
        ),
        "real_dolphinscheduler_success": provider["provider_state"] == "SUCCESS",
        "evidence_gated_run_success": finalization["status"] == "succeeded",
        "native_raster_ods_quality_passed": (
            finalization["quality_verdict"] == "passed"
            and finalization["quality_scope"]
            == "ods_native_raster_ingestion_integrity"
            and finalization["quality_evaluator"] == QUALITY_EVALUATOR
        ),
        "sealed_bundle_bound_to_output": (
            finalization["bundle_sha256"] == EXPECTED_BUNDLE_SHA256
            and finalization["member_count"] == 7
        ),
        "full_pixel_accounting_preserved": (
            finalization["valid_pixel_count"] == 998698
            and finalization["nodata_pixel_count"] == 1569066
        ),
        "cog_claim_not_inferred": finalization["cog_conformance"] == "not_evaluated",
        "promotion_and_product_publication_blocked": (
            finalization["promotion_eligible"] is False
            and finalization["data_product_version_created"] is False
            and product_absent
        ),
        "executor_replay_skipped_provider": executor_replay.get("replayed") is True,
        "complete_replay_idempotent_when_observed": (
            not replay["observed"] or all(replay_checks)
        ),
    }
    report = {
        "schema": "gda.chongqing_dem_ods_orchestrated_acceptance.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "source": source,
        "deployment": deployment,
        "submission": submission,
        "provider_execution": provider,
        "finalization": finalization,
        "executor_replay": executor_replay,
        "replay": replay,
        "dem_product_absent": product_absent,
    }
    report["evidence_sha256"] = canonical_json_fingerprint(report)
    _write_json(runtime_dir / "acceptance-report.json", report)
    if report["status"] != "passed":
        raise RuntimeError("DEM ODS acceptance checks did not all pass")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--executor-token", type=Path, default=DEFAULT_EXECUTOR_TOKEN)
    parser.add_argument("--client-request-id", default=DEFAULT_CLIENT_REQUEST_ID)
    parser.add_argument("--timeout-seconds", type=int, default=2400)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run(
        profile_path=args.profile.resolve(strict=True),
        runtime_dir=args.runtime_dir.resolve(),
        source_manifest_path=args.source_manifest.resolve(strict=True),
        executor_token=args.executor_token.resolve(strict=True),
        client_request_id=args.client_request_id,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
