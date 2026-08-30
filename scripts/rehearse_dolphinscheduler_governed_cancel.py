#!/usr/bin/env python3
"""Run a real DolphinScheduler STOP rehearsal through the governed outbox."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from data_agent.dataops_cancel import DataOpsCancelSpec
from data_agent.dataops_manual import DataOpsManualTriggerSpec
from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerError,
    DolphinSchedulerProfile,
    compile_dolphinscheduler_workflow,
)
from data_agent.dolphinscheduler_command_consumer import (
    DolphinSchedulerCommandConsumer,
)
from data_agent.platform_contracts import (
    FrameworkAttemptObservation,
    PlatformDefinitionVersion,
    Resource,
    ResourceVersion,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
)
from data_agent.platform_gateway import DefinitionRegistration, PlatformGateway

TENANT = "local-dev"
DEFINITION_URN = "gda://local-dev/definition/dolphinscheduler-cancel-probe"
DEFINITION_VERSION_ID = uuid5(NAMESPACE_URL, f"{DEFINITION_URN}:v2")
WORKFLOW_NAME = "gda_governed_cancel_probe_v2"
WORKLOAD_SUBJECT = "workload:dolphinscheduler-gda-dataops"
POLICY_EVALUATOR = "workload:gda-policy-evaluator"
DEFAULT_REQUEST_ID = "dolphinscheduler-cancel-probe-20260801-002"


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


def _batch_report(value: Any) -> dict[str, Any]:
    if value is None:
        return {
            "claimed": 0,
            "completed": 0,
            "deferred_to_reconcile": 0,
            "retry_pending": 0,
            "failed": 0,
            "command_ids": [],
        }
    return {
        "claimed": value.claimed,
        "completed": value.completed,
        "deferred_to_reconcile": value.deferred_to_reconcile,
        "retry_pending": value.retry_pending,
        "failed": value.failed,
        "command_ids": [str(item) for item in value.command_ids],
    }


def _cancel_blocker(provider_state: str) -> str:
    state = provider_state.upper()
    if state == "READY_STOP":
        return "DolphinScheduler remained READY_STOP after accepting STOP"
    if state == "FAILURE":
        return "DolphinScheduler projected the killed task as workflow FAILURE, not STOP"
    if state == "SUCCESS":
        return "DolphinScheduler task completed naturally after STOP, without reaching STOP"
    return f"DolphinScheduler did not reach STOP; terminal observation was {state}"


def _profile(
    value: dict[str, Any],
    *,
    token_file: Path | None,
    base_url: str | None,
) -> DolphinSchedulerProfile:
    resolved_token = token_file or Path(str(value["token_file"]))
    token = resolved_token.read_text(encoding="utf-8").strip()
    return DolphinSchedulerProfile(
        base_url=base_url or str(value["base_url"]),
        access_token=token,
        project_code=int(value["project_code"]),
        workload_subject=WORKLOAD_SUBJECT,
        policy_evaluator_subject=POLICY_EVALUATOR,
        tenant_code=str(value["tenant_code"]),
        worker_group=str(value["worker_group"]),
        timezone_name="Asia/Tokyo",
        cancel_terminal_stop_capability="conformance_probe",
        cancel_terminal_stop_evidence_ref=(
            "gda://local-dev/evidence/dolphinscheduler-cancel-conformance:v1"
        ),
    )


def _definition(task_code: int) -> PlatformDefinitionVersion:
    task = {
        "code": task_code,
        "name": "hold_for_governed_cancel",
        "version": 1,
        "description": "Long-running sandbox task for real STOP conformance",
        "delayTime": 0,
        "taskType": "SHELL",
        "taskParams": {
            "localParams": [],
            "rawScript": (
                "set -eu\n"
                'test "${gda_tenant_id}" = "local-dev"\n'
                'test -n "${gda_run_id}"\n'
                'test -n "${gda_client_request_id}"\n'
                "sleep 600\n"
            ),
            "resourceList": [],
        },
        "flag": "YES",
        "taskPriority": "MEDIUM",
        "workerGroup": "gda_dataops_sandbox",
        "environmentCode": -1,
        "failRetryTimes": 0,
        "failRetryInterval": 1,
        "timeoutFlag": "OPEN",
        "timeoutNotifyStrategy": "WARN",
        "timeout": 900,
        "taskGroupId": 0,
        "taskGroupPriority": 0,
        "cpuQuota": -1,
        "memoryMax": -1,
    }
    definition_document = {
        "schema": "gda.dolphinscheduler_cancel_probe_definition.v2",
        "purpose": "sandbox_provider_cancel_conformance_only",
        "dolphinscheduler": {
            "name": WORKFLOW_NAME,
            "description": "Governed cancellation and terminal callback probe",
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
            "global_params": [],
            "timeout_seconds": 900,
            "execution_type": "PARALLEL",
        },
    }
    input_contract: dict[str, Any] = {}
    output_contract = {
        "artifacts": "none",
        "data_product_version": "forbidden",
        "terminal_status": "cancelled_only_after_provider_stop",
    }
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="dataops.cancel.conformance",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id=TENANT,
        definition_urn=DEFINITION_URN,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        capability_id="dataops.cancel.conformance",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )


def _deploy(
    gateway: PlatformGateway,
    client: DolphinSchedulerClient,
    adapter: DolphinSchedulerAdapter,
    runtime_dir: Path,
) -> tuple[PlatformDefinitionVersion, DolphinSchedulerDefinitionBinding, UUID]:
    state_path = runtime_dir / "definition-state-v2.json"
    if state_path.exists():
        task_code = int(_read_json(state_path)["task_code"])
    else:
        task_code = client.generate_task_codes(1)[0]
        _write_json(
            state_path,
            {
                "schema": "gda.dolphinscheduler_cancel_probe_state.v1",
                "task_code": task_code,
            },
        )
    definition = _definition(task_code)
    created_at = datetime(2026, 8, 1, tzinfo=UTC)
    gateway.register_definition(
        DefinitionRegistration(
            resource=Resource(
                tenant_id=TENANT,
                resource_urn=DEFINITION_URN,
                resource_kind="definition",
                authority_system="gda-control",
                authority_locator="definitions/dolphinscheduler-cancel-probe/v1",
                owner_ref="team:data-platform",
                governance_ref={"release_stage": "sandbox_conformance"},
            ),
            resource_version=ResourceVersion(
                tenant_id=TENANT,
                resource_urn=DEFINITION_URN,
                resource_version_id=DEFINITION_VERSION_ID,
                version_key="v2",
                content_sha256=definition.definition_sha256,
                authority_version_ref={
                    "schema": "gda.dolphinscheduler_cancel_probe_definition.v2"
                },
                created_by=WORKLOAD_SUBJECT,
                created_at=created_at,
            ),
            definition=definition,
        )
    )
    spec = compile_dolphinscheduler_workflow(definition)
    existing = [
        item
        for item in client.list_workflows(search_value=WORKFLOW_NAME)
        if item.get("name") == WORKFLOW_NAME
    ]
    if len(existing) > 1:
        raise RuntimeError("multiple cancel probe workflows share the same name")
    if existing:
        item = existing[0]
        binding = DolphinSchedulerDefinitionBinding(
            tenant_id=TENANT,
            definition_version_id=DEFINITION_VERSION_ID,
            project_code=adapter.profile.project_code,
            workflow_definition_code=int(item["code"]),
            workflow_definition_version=int(item["version"]),
            compiled_sha256=spec.compiled_sha256,
        )
        client.release_workflow(binding.workflow_definition_code)
    else:
        binding = client.create_workflow(spec)
    artifact = adapter.persist_binding(
        binding,
        actor_subject=WORKLOAD_SUBJECT,
        created_at=created_at,
    ).value
    return definition, binding, artifact.artifact_id


def rehearse(
    *,
    profile_path: Path,
    runtime_dir: Path,
    client_request_id: str,
    requester_subject: str,
    token_file: Path | None,
    base_url: str | None,
) -> dict[str, Any]:
    profile = _profile(
        _read_json(profile_path), token_file=token_file, base_url=base_url
    )
    gateway = PlatformGateway()
    adapter = DolphinSchedulerAdapter(profile, gateway=gateway)
    capability = adapter.capability_report()
    consumer = DolphinSchedulerCommandConsumer(adapter, gateway=gateway)
    try:
        definition, binding, plan_id = _deploy(
            gateway, adapter.client, adapter, runtime_dir
        )
        manual = gateway.submit_manual_trigger(
            DataOpsManualTriggerSpec(
                tenant_id=TENANT,
                client_request_id=client_request_id,
                definition_version_id=DEFINITION_VERSION_ID,
                logical_start=datetime(2026, 8, 1, tzinfo=UTC),
                logical_end=datetime(2026, 8, 2, tzinfo=UTC),
                input_bindings=(),
                execution_plan_artifact_id=plan_id,
                requester_subject=requester_subject,
                workload_subject_id=WORKLOAD_SUBJECT.removeprefix("workload:"),
                workload_roles=("platform_operator",),
                purpose="rehearse governed provider cancellation",
                policy_version_ref=(
                    "gda://local-dev/policy/dataops-cancel-probe-dispatch:v1"
                ),
                policy_evaluator_subject=POLICY_EVALUATOR,
            )
        )
        dispatch_batch = None
        run = gateway.get_run(TENANT, manual.run.run_id)
        if run.status.value == "accepted":
            dispatch_batch = consumer.run_once(
                TENANT, worker_id="worker:cancel-probe-dispatch", limit=100
            )
            run = gateway.get_run(TENANT, manual.run.run_id)
        if run.status.value not in {"dispatching", "running", "reconciling"}:
            if run.status.value not in {"cancelling", "cancelled"}:
                raise RuntimeError("provider dispatch did not reach a cancellable state")

        instance = None
        provider_states: list[str] = []
        correlation_deadline = time.monotonic() + 30
        while time.monotonic() < correlation_deadline:
            current = gateway.get_run(TENANT, run.run_id)
            try:
                matches = adapter.client.find_instances(
                    binding, current, manual.invocation
                )
            except DolphinSchedulerError:
                matches = []
            if len(matches) == 1:
                instance = adapter.client.get_instance(
                    matches[0].instance_id,
                    binding.workflow_definition_code,
                )
                provider_states.append(instance.state)
                break
            time.sleep(0.5)
        if instance is None:
            raise RuntimeError("DolphinScheduler correlation did not become visible")

        run = gateway.get_run(TENANT, run.run_id)
        cancel_expected_version = (
            run.state_version
            if run.status.value in {"dispatching", "running", "reconciling"}
            else run.state_version - 1
        )

        cancellation = gateway.admit_dataops_cancel(
            DataOpsCancelSpec(
                tenant_id=TENANT,
                run_id=run.run_id,
                client_request_id=f"{client_request_id}:cancel",
                expected_state_version=cancel_expected_version,
                requester_subject=requester_subject,
                reason="sandbox operator requested provider STOP",
                workload_subject=WORKLOAD_SUBJECT,
                policy_version_ref=(
                    "gda://local-dev/policy/dataops-cancel-conformance:v1"
                ),
                policy_evaluator_subject=POLICY_EVALUATOR,
            )
        )
        cancel_batch = None
        cancel_delivery_deadline = time.monotonic() + 45
        while time.monotonic() < cancel_delivery_deadline:
            stored_cancel = gateway.get_command(
                TENANT, cancellation.command.command_id
            )
            if stored_cancel.status.value == "done":
                break
            batch = consumer.run_once(
                TENANT, worker_id="worker:cancel-probe-stop", limit=100
            )
            if batch.claimed:
                cancel_batch = batch
            time.sleep(0.5)
        else:
            raise RuntimeError("cancel command did not reach delivered state")

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            instance = adapter.client.get_instance(
                instance.instance_id,
                binding.workflow_definition_code,
            )
            provider_states.append(instance.state)
            if instance.state in {"STOP", "FAILURE", "SUCCESS", "PAUSE"}:
                break
            time.sleep(0.5)
        if instance is None or instance.state != "STOP":
            reconcile_batch = consumer.run_once(
                TENANT, worker_id="worker:cancel-probe-reconcile", limit=100
            )
            current = gateway.get_run(TENANT, run.run_id)
            incidents = gateway.list_incidents(
                TENANT,
                status="open",
                run_id=current.run_id,
            )
            mismatch_incidents = tuple(
                item
                for item in incidents
                if item.incident_type == "provider_cancel_terminal_mismatch"
            )
            replay = gateway.admit_dataops_cancel(
                DataOpsCancelSpec(
                    tenant_id=TENANT,
                    run_id=run.run_id,
                    client_request_id=f"{client_request_id}:cancel",
                    expected_state_version=cancel_expected_version,
                    requester_subject=requester_subject,
                    reason="sandbox operator requested provider STOP",
                    workload_subject=WORKLOAD_SUBJECT,
                    policy_version_ref=(
                        "gda://local-dev/policy/dataops-cancel-conformance:v1"
                    ),
                    policy_evaluator_subject=POLICY_EVALUATOR,
                )
            )
            blocked_report = {
                "schema": "gda.dolphinscheduler_governed_cancel_rehearsal.v1",
                "status": "blocked",
                "scope": "sandbox_provider_cancel_conformance",
                "capability": capability.model_dump(mode="json"),
                "blocker": _cancel_blocker(instance.state),
                "run_id": str(current.run_id),
                "run_status": current.status.value,
                "run_state_version": current.state_version,
                "manual_request_id": client_request_id,
                "cancel_request_id": f"{client_request_id}:cancel",
                "cancel_request_sha256": cancellation.request_sha256,
                "dispatch_command_id": str(manual.command.command_id),
                "cancel_command_id": str(cancellation.command.command_id),
                "cancel_command_status": replay.command.status.value,
                "cancel_policy_artifact_id": str(
                    cancellation.policy_artifact.artifact_id
                ),
                "provider_instance_id": instance.instance_id,
                "provider_state": instance.state,
                "provider_states_observed": provider_states,
                "terminal_mismatch_incident_ids": [
                    str(item.incident_id) for item in mismatch_incidents
                ],
                "dispatch_batch": _batch_report(dispatch_batch),
                "cancel_batch": _batch_report(cancel_batch),
                "reconcile_batch": _batch_report(reconcile_batch),
                "late_callback_ignored_terminal": False,
                "data_product_version_created": False,
                "checks": {
                    "real_provider_instance_created": True,
                    "provider_accepted_stop": replay.command.status.value == "done",
                    "provider_reached_stop": False,
                    "platform_did_not_claim_cancelled": (
                        current.status.value != "cancelled"
                    ),
                    "platform_failed_on_terminal_mismatch": (
                        current.status.value == "failed"
                    ),
                    "terminal_mismatch_incident_opened": len(mismatch_incidents) == 1,
                    "cancel_policy_is_distinct": (
                        cancellation.policy_artifact.manifest["decision"]["action"]
                        == "dolphinscheduler.cancel"
                    ),
                    "cancel_replay_created_nothing": (
                        not replay.command_created
                        and not replay.policy_artifact_created
                    ),
                },
            }
            _write_json(
                runtime_dir / "governed-cancel-rehearsal-report.json",
                blocked_report,
            )
            return blocked_report

        reconcile_batch = consumer.run_once(
            TENANT, worker_id="worker:cancel-probe-reconcile", limit=100
        )
        terminal = gateway.get_run(TENANT, run.run_id)
        replay = gateway.admit_dataops_cancel(
            DataOpsCancelSpec(
                tenant_id=TENANT,
                run_id=run.run_id,
                client_request_id=f"{client_request_id}:cancel",
                expected_state_version=cancel_expected_version,
                requester_subject=requester_subject,
                reason="sandbox operator requested provider STOP",
                workload_subject=WORKLOAD_SUBJECT,
                policy_version_ref=(
                    "gda://local-dev/policy/dataops-cancel-conformance:v1"
                ),
                policy_evaluator_subject=POLICY_EVALUATOR,
            )
        )

        late_evidence = {
            "schema": "gda.dolphinscheduler_callback.v1",
            "source": "cancel_rehearsal_late_callback",
            "correlation_verified": True,
            "project_code": binding.project_code,
            "workflow_instance_id": instance.instance_id,
            "workflow_definition_code": binding.workflow_definition_code,
            "workflow_definition_version": binding.workflow_definition_version,
            "provider_state": instance.state,
        }
        late_observation = FrameworkAttemptObservation(
            tenant_id=TENANT,
            observation_id=uuid5(run.run_id, "late-callback-after-cancel:v1"),
            run_id=run.run_id,
            attempt_no=1,
            framework_kind="dolphinscheduler",
            external_namespace=str(binding.project_code),
            external_run_id=str(instance.instance_id),
            observed_state=instance.state.lower(),
            observation_sha256=canonical_json_fingerprint(late_evidence),
            evidence=late_evidence,
            observed_at=datetime.now(UTC),
        )
        late = gateway.record_attempt_and_enqueue_reconcile(
            late_observation,
            actor_subject=WORKLOAD_SUBJECT,
        )
    finally:
        adapter.client.close()

    checks = {
        "real_provider_instance_created": instance is not None,
        "provider_reached_stop": instance is not None and instance.state == "STOP",
        "platform_run_cancelled": terminal.status.value == "cancelled",
        "cancel_policy_is_distinct": (
            cancellation.policy_artifact.manifest["decision"]["action"]
            == "dolphinscheduler.cancel"
        ),
        "cancel_replay_created_nothing": (
            not replay.command_created and not replay.policy_artifact_created
        ),
        "late_callback_observation_retained": late.observation is not None,
        "late_callback_enqueued_nothing": (
            late.ignored_terminal and late.command is None and not late.command_created
        ),
        "no_output_contract": definition.output_contract["artifacts"] == "none",
    }
    report = {
        "schema": "gda.dolphinscheduler_governed_cancel_rehearsal.v1",
        "status": "verified" if all(checks.values()) else "failed",
        "scope": "sandbox_provider_cancel_conformance",
        "capability": capability.model_dump(mode="json"),
        "run_id": str(terminal.run_id),
        "run_status": terminal.status.value,
        "run_state_version": terminal.state_version,
        "manual_request_id": client_request_id,
        "cancel_request_id": f"{client_request_id}:cancel",
        "cancel_request_sha256": cancellation.request_sha256,
        "dispatch_command_id": str(manual.command.command_id),
        "cancel_command_id": str(cancellation.command.command_id),
        "cancel_command_status": replay.command.status.value,
        "cancel_policy_artifact_id": str(cancellation.policy_artifact.artifact_id),
        "provider_instance_id": instance.instance_id if instance else None,
        "provider_state": instance.state if instance else None,
        "provider_states_observed": provider_states,
        "dispatch_batch": _batch_report(dispatch_batch),
        "cancel_batch": _batch_report(cancel_batch),
        "reconcile_batch": _batch_report(reconcile_batch),
        "late_observation_id": str(late.observation.observation_id),
        "late_observation_created": late.observation_created,
        "late_callback_ignored_terminal": late.ignored_terminal,
        "data_product_version_created": False,
        "checks": checks,
    }
    _write_json(runtime_dir / "governed-cancel-rehearsal-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--client-request-id", default=DEFAULT_REQUEST_ID)
    parser.add_argument(
        "--requester-subject", default="human:data-platform-operator"
    )
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--base-url")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = rehearse(
        profile_path=args.profile,
        runtime_dir=args.runtime_dir,
        client_request_id=args.client_request_id,
        requester_subject=args.requester_subject,
        token_file=args.token_file,
        base_url=args.base_url,
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
