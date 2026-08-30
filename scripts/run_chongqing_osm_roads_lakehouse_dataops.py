#!/usr/bin/env python3
"""Run the governed Chongqing OSM Default Lakehouse workflow end to end."""

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

from data_agent.data_product_registry import DataProductRegistry  # noqa: E402
from data_agent.data_products.osm_roads_lakehouse_dataops import (  # noqa: E402
    DEFINITION_URN,
    DEFINITION_VERSION_ID,
    ICEBERG_TABLE,
    POLICY_EVALUATOR_SUBJECT,
    QUALITY_EVALUATOR,
    SOURCE_PRODUCT_VERSION_ID,
    SOURCE_RESOURCE_VERSION_ID,
    TENANT_ID,
    WORKFLOW_NAME,
    WORKLOAD_SUBJECT,
    WORKLOAD_SUBJECT_ID,
    build_osm_roads_lakehouse_definition,
    lineage_event_id,
    output_artifact_id,
    quality_result_id,
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

DEFAULT_PROFILE = REPO_ROOT / ".tmp/dolphinscheduler-sandbox/profile.json"
DEFAULT_RUNTIME_DIR = (
    REPO_ROOT / ".tmp/dolphinscheduler-sandbox/osm-roads-default-lakehouse-v1"
)
DEFAULT_EXECUTOR_TOKEN = REPO_ROOT / ".tmp/dolphinscheduler-sandbox/executor-token"
DEFAULT_CLIENT_REQUEST_ID = "osm-roads-default-lakehouse-v1-20260801-001"
EXECUTOR_URL = (
    "http://127.0.0.1:8090/v1/execute/"
    "chongqing-osm-roads-default-lakehouse"
)
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


def _deploy(
    gateway: PlatformGateway,
    profile: DolphinSchedulerProfile,
    runtime_dir: Path,
) -> tuple[dict[str, Any], UUID]:
    state_path = runtime_dir / "definition-state.json"
    created_at = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
    with DolphinSchedulerClient(profile) as client:
        if state_path.exists():
            task_code = int(_read_json(state_path)["task_code"])
        else:
            task_code = client.generate_task_codes(1)[0]
            _write_json(
                state_path,
                {
                    "schema": "gda.osm_roads_lakehouse_definition_state.v1",
                    "task_code": task_code,
                },
            )
        definition = build_osm_roads_lakehouse_definition(task_code)
        registration = DefinitionRegistration(
            resource=Resource(
                tenant_id=TENANT_ID,
                resource_urn=DEFINITION_URN,
                resource_kind="definition",
                authority_system="gda-control",
                authority_locator="definitions/osm-roads-default-lakehouse/v1",
                owner_ref="team:data-platform",
                governance_ref={
                    "classification": "internal",
                    "release_stage": "sandbox",
                    "source_product_version_id": str(SOURCE_PRODUCT_VERSION_ID),
                },
            ),
            resource_version=ResourceVersion(
                tenant_id=TENANT_ID,
                resource_urn=DEFINITION_URN,
                resource_version_id=DEFINITION_VERSION_ID,
                version_key="v1",
                content_sha256=definition.definition_sha256,
                authority_version_ref={
                    "schema": "gda.chongqing_osm_roads_default_lakehouse_definition.v1",
                    "table": ICEBERG_TABLE,
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
            raise RuntimeError("multiple workflows share the lakehouse definition name")
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
        "schema": "gda.osm_roads_lakehouse_deployment.v1",
        "status": "ready",
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "definition_sha256": definition.definition_sha256,
        "compiled_sha256": compiled.compiled_sha256,
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "source_product_version_id": str(SOURCE_PRODUCT_VERSION_ID),
        "iceberg_table": ICEBERG_TABLE,
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
            logical_start=datetime(2021, 1, 1, tzinfo=UTC),
            logical_end=datetime(2022, 1, 1, tzinfo=UTC),
            input_bindings=(
                ResourceBinding(
                    binding_name="source",
                    resource_version_id=SOURCE_RESOURCE_VERSION_ID,
                    semantic_type="gis.transportation.osm_roads.ads",
                ),
            ),
            execution_plan_artifact_id=binding_artifact_id,
            requester_subject="human:data-platform-operator",
            workload_subject_id=WORKLOAD_SUBJECT_ID,
            workload_roles=("platform_operator",),
            purpose="materialize Chongqing OSM roads into the Default Lakehouse",
            policy_version_ref=(
                "gda://local-dev/policy/osm-roads-default-lakehouse-sandbox:v1"
            ),
            policy_evaluator_subject=POLICY_EVALUATOR_SUBJECT,
            policy_ttl_seconds=86400,
            config_fingerprint=compiled_sha256,
        )
    )
    return {
        "schema": "gda.osm_roads_lakehouse_submission.v1",
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
            worker_id="worker:osm-roads-default-lakehouse-v1",
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
                            "DolphinScheduler lakehouse workflow failed",
                            {
                                "provider_state": state,
                                "workflow_instance_id": (
                                    reconciliation.workflow_instance_id
                                ),
                                "observation_id": str(
                                    reconciliation.observation.observation_id
                                ),
                            },
                        )
                    raise RuntimeError(
                        f"DolphinScheduler lakehouse workflow terminated as {state}"
                    )
                return (
                    {
                        "schema": "gda.osm_roads_lakehouse_provider_execution.v1",
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
        raise TimeoutError("DolphinScheduler lakehouse workflow did not finish in time")
    finally:
        adapter.client.close()


def _finalize(
    gateway: PlatformGateway,
    *,
    run_id: UUID,
    success_observation_id: UUID,
) -> dict[str, Any]:
    output_id = output_artifact_id(run_id)
    quality_id = quality_result_id(run_id)
    lineage_id = lineage_event_id(run_id)
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
        reason="DolphinScheduler and Default Lakehouse evidence passed",
    )
    output = gateway.get_artifact(TENANT_ID, output_id)
    quality = gateway.get_quality_result(TENANT_ID, quality_id)
    output_version = gateway.get_resource_version(
        TENANT_ID,
        output.resource_version_id,
    )
    return {
        "schema": "gda.osm_roads_lakehouse_finalization.v1",
        "run_id": str(run_id),
        "status": run.status.value,
        "state_version": run.state_version,
        "transitioned": before.status != run.status,
        "output_artifact_id": str(output.artifact_id),
        "output_resource_version_id": str(output.resource_version_id),
        "iceberg_table": output.manifest["iceberg_table"],
        "snapshot_id": output.manifest["snapshot_id"],
        "history_count": output.manifest["history_count"],
        "time_travel_rows": output.manifest["time_travel_rows"],
        "content_fingerprint": output_version.content_sha256,
        "quality_result_id": str(quality.quality_result_id),
        "quality_evidence_artifact_id": str(quality.evidence_artifact_id),
        "quality_verdict": quality.verdict.value,
        "quality_evaluator": quality.evaluated_by,
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
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed localhost URL
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("executor replay response must be an object")
    return value


def run(
    *,
    profile_path: Path,
    runtime_dir: Path,
    executor_token: Path,
    client_request_id: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    profile = _profile(_read_json(profile_path))
    gateway = PlatformGateway()
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
    product = DataProductRegistry().get_product(TENANT_ID, "chongqing-osm-roads")
    checks = {
        "definition_registered": deployment["status"] == "ready",
        "platform_run_bound_definition": (
            submission["definition_version_id"] == str(DEFINITION_VERSION_ID)
        ),
        "ads_resource_bound_to_run": (
            submission["source_resource_version_id"]
            == str(SOURCE_RESOURCE_VERSION_ID)
        ),
        "real_dolphinscheduler_success": provider["provider_state"] == "SUCCESS",
        "evidence_gated_run_success": finalization["status"] == "succeeded",
        "independent_quality_passed": (
            finalization["quality_verdict"] == "passed"
            and finalization["quality_evaluator"] == QUALITY_EVALUATOR
        ),
        "iceberg_snapshot_bound_to_run": (
            finalization["iceberg_table"] == ICEBERG_TABLE
            and int(finalization["snapshot_id"]) > 0
        ),
        "time_travel_full_dataset": finalization["time_travel_rows"] == 50366,
        "executor_replay_skipped_spark": executor_replay.get("replayed") is True,
        "source_product_unchanged": (
            product["current_version_id"] == str(SOURCE_PRODUCT_VERSION_ID)
            and len(product["versions"]) == 3
        ),
    }
    report = {
        "schema": "gda.osm_roads_lakehouse_orchestrated_acceptance.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "deployment": deployment,
        "submission": submission,
        "provider_execution": provider,
        "finalization": finalization,
        "executor_replay": executor_replay,
        "source_product": {
            "current_version_id": product["current_version_id"],
            "current_version_key": product["current_version_key"],
            "version_count": len(product["versions"]),
        },
    }
    report["evidence_sha256"] = canonical_json_fingerprint(report)
    _write_json(runtime_dir / "acceptance-report.json", report)
    if report["status"] != "passed":
        raise RuntimeError("lakehouse orchestrated acceptance checks did not all pass")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
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
        executor_token=args.executor_token.resolve(strict=True),
        client_request_id=args.client_request_id,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
