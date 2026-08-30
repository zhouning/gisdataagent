#!/usr/bin/env python3
"""Certify fail-closed PostgreSQL CDC admission across physical failover."""

from __future__ import annotations

import argparse
import hmac
import json
import re
import secrets
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text

from data_agent.dataops_schedule import (
    DataOpsScheduleWindowSpec,
    dataops_schedule_run_id,
)
from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerError,
    DolphinSchedulerProfile,
    compile_dolphinscheduler_workflow,
)
from data_agent.dolphinscheduler_command_consumer import DolphinSchedulerCommandConsumer
from data_agent.platform_contracts import (
    Artifact,
    ArtifactRole,
    FrameworkAttemptObservation,
    FrameworkKind,
    LineageEvent,
    LineageEventType,
    PlatformDefinitionVersion,
    PostgresqlCdcFailoverRecoveryPlan,
    PostgresqlCdcFailoverResnapshotAdmission,
    QualityResult,
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunSuccessEvidence,
    SourceSyncCommit,
    SourceSyncDefinitionVersion,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    postgresql_cdc_failover_recovery_plan_fingerprint,
    postgresql_cdc_failover_resnapshot_admission_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_definition_fingerprint,
)
from data_agent.platform_gateway import (
    DefinitionRegistration,
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
)
from data_agent.postgresql_cdc_recovery_controller import (
    PostgresqlCdcRecoveryControllerRuntime,
    build_slot_continuity_observation,
)
from data_agent.source_sync_authority import SourceSyncAuthority
from scripts.certify_chongqing_osm_flink_stream import (
    DEFAULT_FLINK_IMAGE,
    DEFAULT_JAVA_HOME,
    DEFAULT_JDK_IMAGE,
    DEFAULT_SOURCE,
    REPO_ROOT,
    _committed_lines,
    _sha256_file,
    compile_flink_job,
    docker_image_id,
)
from scripts.certify_chongqing_osm_postgres_cdc import (
    CHECKPOINT_RE,
    DEFAULT_CONNECTOR,
    DEFAULT_NETWORK,
    DEFAULT_POSTGRES_IMAGE,
    JAVA_SOURCE,
    MAIN_CLASS,
    CdcPostgresSandbox,
    FlinkCdcSandbox,
    _container_absent,
    _container_network_attached,
    _lsn_value,
    _run_command,
    _sql_literal,
    _sync_definition,
    build_cdc_plan,
    verify_connector_artifact,
)
from scripts.certify_chongqing_osm_postgres_cdc_slot_invalidation import (
    TERMINAL_FLINK_STATES,
    _exception_summary,
    _success_evidence_counts,
)
from scripts.certify_source_sync_authority import (
    WORKLOAD,
    _commit_governance_evidence,
    _definition_registration,
    _metadata_change_id,
    _PostgresDatabaseSandbox,
    _quarantine_evidence,
    _register_resource_only,
    _register_resource_version,
    _run,
    _settings,
    _submit_run,
)
from scripts.source_sync_certification_support import connection_url as _connection_url
from scripts.source_sync_certification_support import main_sync_counts

DEFAULT_REPORT = (
    REPO_ROOT
    / ".tmp/source-sync-certification/"
    "chongqing-osm-postgres-cdc-failover-report.json"
)
DEFAULT_DOLPHINSCHEDULER_PROFILE = (
    REPO_ROOT / ".tmp/dolphinscheduler-sandbox/profile.json"
)
DEFAULT_DOLPHINSCHEDULER_EXECUTOR_TOKEN = (
    REPO_ROOT / ".tmp/dolphinscheduler-sandbox/executor-token"
)
DOLPHINSCHEDULER_WORKLOAD = "workload:dolphinscheduler-gda-dataops"
DOLPHINSCHEDULER_POLICY_EVALUATOR = "workload:gda-policy-evaluator"
DOLPHINSCHEDULER_CONTAINER = (
    "gisdataagent-dolphinscheduler-sandbox-dolphinscheduler-1"
)
RECOVERY_CONTROLLER_MIGRATION = (
    REPO_ROOT / "data_agent/migrations/147_postgresql_cdc_recovery_observation.sql"
)
RESNAPSHOT_EXECUTOR_PATH = (
    "/v1/execute/chongqing-osm-postgres-cdc-resnapshot"
)
STANDBY_RESOURCE_RE = re.compile(
    r"^gda-cdc-(?:standby|standby-data)-[0-9a-f]{10}$"
)


def _resnapshot_source_version_id(
    definition: SourceSyncDefinitionVersion, source_snapshot_sha256: str
) -> UUID:
    return uuid5(
        definition.sync_definition_version_id,
        f"gda.postgresql_cdc.resnapshot.source.v1:{source_snapshot_sha256}",
    )


def _dolphinscheduler_profile(path: Path) -> DolphinSchedulerProfile:
    value = json.loads(path.read_text(encoding="utf-8"))
    token_file = Path(str(value["token_file"]))
    return DolphinSchedulerProfile(
        base_url=str(value["base_url"]),
        access_token=token_file.read_text(encoding="utf-8").strip(),
        project_code=int(value["project_code"]),
        workload_subject=DOLPHINSCHEDULER_WORKLOAD,
        policy_evaluator_subject=str(
            value.get("policy_evaluator_subject", DOLPHINSCHEDULER_POLICY_EVALUATOR)
        ),
        tenant_code=str(value["tenant_code"]),
        worker_group=str(value["worker_group"]),
        timezone_name="Asia/Tokyo",
    )


def build_postgresql_cdc_resnapshot_platform_definition(
    *,
    definition_urn: str,
    definition_version_id: UUID,
    source_resource_urn: str,
    target_resource_urn: str,
    source_resource_version_id: UUID,
    workflow_name: str,
    task_code: int,
    worker_group: str,
    executor_url: str,
    source_snapshot_sha256: str,
    target_content_sha256: str,
    recovery_plan_sha256: str,
) -> PlatformDefinitionVersion:
    """Compile the resnapshot confirmation into the standard DS contract."""

    task = {
        "code": task_code,
        "name": "execute_governed_postgresql_cdc_resnapshot",
        "version": 1,
        "description": "Materialize and verify the promoted PostgreSQL snapshot",
        "delayTime": 0,
        "taskType": "SHELL",
        "taskParams": {
            "localParams": [],
            "rawScript": (
                "set -eu\n"
                "payload='{\"tenant_id\":\"${gda_tenant_id}\",'\n"
                "payload=$payload'\"run_id\":\"${gda_run_id}\",'\n"
                "payload=$payload'\"definition_version_id\":\"${gda_definition_version_id}\",'\n"
                "payload=$payload'\"source_resource_version_id\":\"${gda_resnapshot_source_resource_version_id}\",'\n"
                "payload=$payload'\"source_snapshot_sha256\":\"${gda_resnapshot_source_snapshot_sha256}\",'\n"
                "payload=$payload'\"target_content_sha256\":\"${gda_resnapshot_target_content_sha256}\",'\n"
                "payload=$payload'\"recovery_plan_sha256\":\"${gda_resnapshot_recovery_plan_sha256}\"}'\n"
                "curl --fail --silent --show-error --retry 1 --retry-all-errors \\\n"
                "  --connect-timeout 5 --max-time 1200 \\\n"
                "  --header \"Authorization: Bearer $(cat "
                "/run/secrets/gda-dataops-executor-token)\" \\\n"
                "  --header \"Content-Type: application/json\" \\\n"
                "  --data \"$payload\" \\\n"
                f"  {executor_url}\n"
            ),
            "resourceList": [],
        },
        "flag": "YES",
        "taskPriority": "MEDIUM",
        "workerGroup": worker_group,
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
        "schema": "gda.postgresql_cdc_resnapshot_job_definition.v1",
        "pipeline": {
            "recovery_mode": "resnapshot_and_reconcile",
            "cursor_disposition": "old_checkpoint_unchanged",
            "provider_commit": "source_sync_authority",
        },
        "dolphinscheduler": {
            "name": workflow_name,
            "description": "Governed PostgreSQL CDC failover resnapshot",
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
                    "prop": "gda_resnapshot_source_resource_version_id",
                    "direct": "IN",
                    "type": "VARCHAR",
                    "value": str(source_resource_version_id),
                },
                {
                    "prop": "gda_resnapshot_source_snapshot_sha256",
                    "direct": "IN",
                    "type": "VARCHAR",
                    "value": source_snapshot_sha256,
                },
                {
                    "prop": "gda_resnapshot_target_content_sha256",
                    "direct": "IN",
                    "type": "VARCHAR",
                    "value": target_content_sha256,
                },
                {
                    "prop": "gda_resnapshot_recovery_plan_sha256",
                    "direct": "IN",
                    "type": "VARCHAR",
                    "value": recovery_plan_sha256,
                },
            ],
            "timeout_seconds": 1800,
            "execution_type": "PARALLEL",
        },
    }
    input_contract = {
        "source": {
            "resource_urn": source_resource_urn,
            "resource_version_id": str(source_resource_version_id),
            "semantic_type": "gis.postgresql_cdc.failover_resnapshot.source",
            "access": "read_only",
        }
    }
    output_contract = {
        "target_resource_urn": target_resource_urn,
        "required_evidence": [
            "dolphinscheduler_success_observation",
            "source_sync_commit",
            "passed_quality_result",
            "input_to_output_lineage",
        ],
    }
    definition_sha256 = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="source.postgresql_cdc.failover_resnapshot",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id="local-dev",
        definition_urn=definition_urn,
        definition_version_id=definition_version_id,
        orchestration_class="dataops",
        capability_id="source.postgresql_cdc.failover_resnapshot",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=definition_sha256,
    )


class _ResnapshotExecutionServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address, handler, *, token: str, context: dict[str, Any]):
        super().__init__(server_address, handler)
        self.token = token
        self.context = context
        self.execution_lock = threading.Lock()


class _ResnapshotExecutionHandler(BaseHTTPRequestHandler):
    server: _ResnapshotExecutionServer

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._respond(HTTPStatus.OK, {"status": "ok"})
            return
        self._respond(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != RESNAPSHOT_EXECUTOR_PATH:
            self._respond(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        authorization = self.headers.get("Authorization", "")
        supplied = authorization.removeprefix("Bearer ")
        if not authorization.startswith("Bearer ") or not hmac.compare_digest(
            supplied, self.server.token
        ):
            self._respond(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 256 * 1024:
                raise ValueError("request body size is invalid")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("request body must be an object")
            context = self.server.context
            expected = {
                "tenant_id": "local-dev",
                "definition_version_id": str(context["definition"].platform_definition_version_id),
                "source_resource_version_id": str(context["source_resource_version_id"]),
                "source_snapshot_sha256": context["source_snapshot_sha256"],
                "target_content_sha256": context["target_content_sha256"],
                "recovery_plan_sha256": context["admission"].recovery_plan.plan_sha256,
            }
            for key, value in expected.items():
                if body.get(key) != value:
                    raise ValueError(f"resnapshot request {key} is not bound to admission")
            run_id = UUID(str(body.get("run_id")))
            if run_id != context["run_id"]:
                raise ValueError("resnapshot request run_id does not match admission")
            with self.server.execution_lock:
                execution = context.get("execution")
                if execution is None:
                    current_run = context["gateway"].get_run("local-dev", run_id)
                    execution = execute_governed_postgresql_cdc_resnapshot(
                        gateway=context["gateway"],
                        authority=context["authority"],
                        definition=context["definition"],
                        admission=context["admission"],
                        run=current_run,
                        source_snapshot=context["source_snapshot"],
                        created_at=context["created_at"],
                    )
                    context["execution"] = execution
            self._respond(
                HTTPStatus.OK,
                {
                    "schema": "gda.postgresql_cdc_resnapshot_executor.v1",
                    "status": "completed",
                    "run_id": str(run_id),
                    "target_content_sha256": context["target_content_sha256"],
                    "commit_id": execution["commit"]["sync_commit_id"],
                },
            )
        except Exception as exc:  # provider must fail the DS task, never fabricate success
            detail = f"{type(exc).__name__}: {exc}"
            cause = exc.__cause__
            original = getattr(cause, "orig", None)
            diagnostic = getattr(original, "diag", None)
            primary = getattr(diagnostic, "message_primary", None)
            constraint = getattr(diagnostic, "constraint_name", None)
            if primary:
                detail += f"; database={primary}"
            if constraint:
                detail += f"; constraint={constraint}"
            self.server.context["error"] = detail
            self._respond(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {
                    "error": "resnapshot_execution_failed",
                    "error_type": type(exc).__name__,
                    "error_message": detail[:500],
                },
            )

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _start_resnapshot_executor(
    *, token: str, context: dict[str, Any]
) -> tuple[_ResnapshotExecutionServer, threading.Thread, int]:
    server = _ResnapshotExecutionServer(
        ("0.0.0.0", 0),
        _ResnapshotExecutionHandler,
        token=token,
        context=context,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="postgres-cdc-resnapshot-executor",
        daemon=True,
    )
    thread.start()
    return server, thread, int(server.server_address[1])


def _stop_resnapshot_executor(
    server: _ResnapshotExecutionServer, thread: threading.Thread
) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _probe_resnapshot_executor_from_dolphinscheduler(
    *, container: str, port: int
) -> dict[str, Any]:
    url = f"http://host.docker.internal:{port}/health"
    completed = subprocess.run(
        ["docker", "exec", container, "curl", "--fail", "--silent", url],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "DolphinScheduler cannot reach the resnapshot executor: "
            f"{completed.stderr.strip()}"
        )
    return {
        "container": container,
        "url": url,
        "reachable": True,
        "response": json.loads(completed.stdout),
    }


def _deploy_resnapshot_dolphinscheduler_workflow(
    *,
    gateway: PlatformGateway,
    client: DolphinSchedulerClient,
    profile: DolphinSchedulerProfile,
    source_definition: SourceSyncDefinitionVersion,
    definition_version_id: UUID,
    source_resource_version_id: UUID,
    source_snapshot_sha256: str,
    target_content_sha256: str,
    recovery_plan_sha256: str,
    namespace: str,
    executor_port: int,
    created_at: datetime,
) -> dict[str, Any]:
    task_code = client.generate_task_codes(1)[0]
    definition_urn = f"gda://local-dev/definition/{namespace}"
    workflow_name = f"gda_cdc_resnapshot_{namespace.replace('-', '_')}"
    definition = build_postgresql_cdc_resnapshot_platform_definition(
        definition_urn=definition_urn,
        definition_version_id=definition_version_id,
        source_resource_urn=source_definition.source_resource_urn,
        target_resource_urn=source_definition.target_resource_urn,
        source_resource_version_id=source_resource_version_id,
        workflow_name=workflow_name,
        task_code=task_code,
        worker_group=profile.worker_group,
        executor_url=(
            f"http://host.docker.internal:{executor_port}{RESNAPSHOT_EXECUTOR_PATH}"
        ),
        source_snapshot_sha256=source_snapshot_sha256,
        target_content_sha256=target_content_sha256,
        recovery_plan_sha256=recovery_plan_sha256,
    )
    registration = gateway.register_definition(
        DefinitionRegistration(
            resource=Resource(
                tenant_id="local-dev",
                resource_urn=definition_urn,
                resource_kind="definition",
                authority_system="gda-control",
                authority_locator=f"definitions/{namespace}",
                owner_ref="team:data-platform",
                governance_ref={
                    "classification": "internal",
                    "release_stage": "isolated-certification",
                    "recovery_plan_sha256": recovery_plan_sha256,
                },
            ),
            resource_version=ResourceVersion(
                tenant_id="local-dev",
                resource_urn=definition_urn,
                resource_version_id=definition_version_id,
                version_key=f"sha256-{definition.definition_sha256[:12]}",
                content_sha256=definition.definition_sha256,
                authority_version_ref={
                    "schema": "gda.postgresql_cdc_resnapshot_job_definition.v1",
                    "source_sync_definition_version_id": str(
                        source_definition.sync_definition_version_id
                    ),
                },
                created_by=DOLPHINSCHEDULER_WORKLOAD,
                created_at=created_at,
            ),
            definition=definition,
        )
    )
    compiled = compile_dolphinscheduler_workflow(definition)
    binding = client.create_workflow(compiled)
    adapter = DolphinSchedulerAdapter(profile, gateway=gateway, client=client)
    binding_result = adapter.persist_binding(
        binding,
        actor_subject=DOLPHINSCHEDULER_WORKLOAD,
        created_at=created_at,
    )
    return {
        "definition": definition,
        "compiled": compiled,
        "binding": binding,
        "binding_artifact": binding_result.value,
        "definition_created": registration.created,
        "binding_created": binding_result.created,
        "workflow_created": True,
    }


def _resnapshot_recovery_schedule_spec(
    *,
    definition_version_id: UUID,
    source_resource_version_id: UUID,
    binding_artifact_id: UUID,
    compiled_sha256: str,
    namespace: str,
    recovery_plan_sha256: str,
    created_at: datetime,
) -> DataOpsScheduleWindowSpec:
    return DataOpsScheduleWindowSpec(
        tenant_id="local-dev",
        definition_version_id=definition_version_id,
        logical_start=created_at,
        logical_end=created_at + timedelta(minutes=1),
        schedule_ref=(
            "gda://local-dev/recovery/postgresql-cdc-failover/"
            f"{namespace}/{recovery_plan_sha256}"
        ),
        scheduled_for=created_at,
        input_bindings=(
            ResourceBinding(
                binding_name="source",
                resource_version_id=source_resource_version_id,
                semantic_type="gis.postgresql_cdc.failover_resnapshot.source",
            ),
        ),
        execution_plan_artifact_id=binding_artifact_id,
        workload_subject_id=DOLPHINSCHEDULER_WORKLOAD.removeprefix("workload:"),
        workload_roles=("platform_operator",),
        purpose="automatically trigger the governed PostgreSQL CDC failover resnapshot",
        policy_version_ref=(
            "gda://local-dev/policy/postgresql-cdc-failover-resnapshot-sandbox:v1"
        ),
        policy_evaluator_subject=DOLPHINSCHEDULER_POLICY_EVALUATOR,
        policy_ttl_seconds=86400,
        config_fingerprint=compiled_sha256,
        invocation_owner_ref="team:data-platform",
    )


def _dispatch_resnapshot_and_wait(
    *,
    gateway: PlatformGateway,
    client: DolphinSchedulerClient,
    profile: DolphinSchedulerProfile,
    run_id: UUID,
    binding_artifact_id: UUID,
    command_id: UUID,
    timeout_seconds: int,
    executor_context: dict[str, Any],
) -> dict[str, Any]:
    adapter = DolphinSchedulerAdapter(profile, gateway=gateway, client=client)
    batch = DolphinSchedulerCommandConsumer(adapter, gateway=gateway).run_once(
        "local-dev",
        worker_id="worker:postgres-cdc-failover-resnapshot-certification",
        limit=1,
        lease_seconds=60,
    )
    command = gateway.get_command("local-dev", command_id)
    if batch.claimed != 1 or batch.completed != 1:
        raise RuntimeError(
            "DolphinScheduler resnapshot dispatch did not complete: "
            f"status={command.status.value}, error={command.last_error}"
        )
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            reconciliation = adapter.reconcile(
                "local-dev",
                run_id,
                binding_artifact_id,
                actor_subject=DOLPHINSCHEDULER_WORKLOAD,
            )
        except DolphinSchedulerError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5)
            continue
        provider_state = reconciliation.provider_state.upper()
        if provider_state in {
            "SUCCESS",
            "FAILURE",
            "STOP",
            "PAUSE",
            "NEED_FAULT_TOLERANCE",
            "KILL",
        }:
            if provider_state != "SUCCESS":
                raise RuntimeError(
                    "DolphinScheduler resnapshot workflow terminated as "
                    f"{provider_state}"
                )
            return {
                "provider_state": provider_state,
                "workflow_instance_id": reconciliation.workflow_instance_id,
                "success_observation": reconciliation.observation,
                "observation_created": reconciliation.observation_created,
                "run": reconciliation.run,
                "outbox": batch,
                "command": command,
                "last_transient_error": last_error,
            }
        time.sleep(0.5)
    raise TimeoutError(
        "DolphinScheduler resnapshot workflow did not finish before timeout"
        + (
            f"; executor_error={executor_context['error']}"
            if executor_context.get("error")
            else ""
        )
    )


def _finalize_resnapshot_run(
    *,
    gateway: PlatformGateway,
    run_id: UUID,
    success_observation_id: UUID,
    execution: dict[str, Any],
) -> dict[str, Any]:
    output_artifact_id = UUID(execution["output_artifact"]["artifact_id"])
    quality_result_id = UUID(execution["quality_result"]["quality_result_id"])
    lineage_event_id = UUID(execution["lineage_event"]["lineage_event_id"])
    evidence = RunSuccessEvidence(
        tenant_id="local-dev",
        run_id=run_id,
        attempt_observation_id=success_observation_id,
        output_artifact_id=output_artifact_id,
        quality_result_id=quality_result_id,
        lineage_event_id=lineage_event_id,
        evidence_sha256=run_success_evidence_fingerprint(
            tenant_id="local-dev",
            run_id=run_id,
            attempt_observation_id=success_observation_id,
            output_artifact_id=output_artifact_id,
            quality_result_id=quality_result_id,
            lineage_event_id=lineage_event_id,
        ),
    )
    before = gateway.get_run("local-dev", run_id)
    final = gateway.finalize_run_success(
        evidence,
        expected_state_version=before.state_version,
        actor_subject=DOLPHINSCHEDULER_WORKLOAD,
        reason="DolphinScheduler and governed resnapshot evidence passed",
    )
    return {
        "before": before,
        "run": final,
        "evidence": evidence,
    }


def assess_failover_continuity(evidence: dict[str, Any]) -> dict[str, Any]:
    """Admit only a replayed, fenced source with continuous slot identity."""

    primary = evidence.get("primary_identity")
    standby = evidence.get("standby_identity_before_promotion")
    promoted = evidence.get("promoted_identity")
    primary_slot = evidence.get("primary_slot")
    promoted_slot = evidence.get("promoted_slot")
    reasons: list[str] = []

    identities = (primary, standby, promoted)
    if not all(isinstance(identity, dict) for identity in identities):
        reasons.append("postgresql_failover_identity_evidence_missing")
    else:
        required = {"system_identifier", "timeline_id", "in_recovery"}
        if any(not required.issubset(identity) for identity in identities) or any(
            not isinstance(identity["system_identifier"], str)
            or not isinstance(identity["timeline_id"], int)
            or not isinstance(identity["in_recovery"], bool)
            for identity in identities
        ):
            reasons.append("postgresql_failover_identity_evidence_incomplete")
        else:
            system_identifiers = {
                identity["system_identifier"] for identity in identities
            }
            if len(system_identifiers) != 1:
                reasons.append("postgresql_system_identifier_changed")
            if primary["in_recovery"] is not False:
                reasons.append("postgresql_original_primary_role_unproven")
            if standby["in_recovery"] is not True:
                reasons.append("postgresql_physical_standby_role_unproven")
            if promoted["in_recovery"] is not False:
                reasons.append("postgresql_standby_promotion_unproven")
            if promoted["timeline_id"] != primary["timeline_id"] + 1:
                reasons.append("postgresql_timeline_did_not_increment_once")

    if evidence.get("mutation_replayed_before_promotion") is not True:
        reasons.append("postgresql_failover_mutation_replay_unproven")
    if evidence.get("primary_stopped_before_promotion") is not True:
        reasons.append("postgresql_primary_stop_order_unproven")
    fencing = evidence.get("fencing")
    if not isinstance(fencing, dict):
        reasons.append("postgresql_primary_fencing_evidence_missing")
    else:
        required_fencing = {
            "schema",
            "mode",
            "old_primary_stopped",
            "old_primary_network_detached",
            "old_primary_write_probe",
        }
        if not required_fencing.issubset(fencing):
            reasons.append("postgresql_primary_fencing_evidence_incomplete")
        else:
            if fencing["schema"] != "gda.postgresql_primary_fencing.v1":
                reasons.append("postgresql_primary_fencing_schema_unrecognized")
            if fencing["mode"] != "stop_and_detach":
                reasons.append("postgresql_primary_fencing_mode_unapproved")
            if fencing["old_primary_stopped"] is not True:
                reasons.append("postgresql_primary_not_fenced_before_promotion")
            if fencing["old_primary_network_detached"] is not True:
                reasons.append("postgresql_primary_network_not_fenced_before_promotion")
            probe = fencing["old_primary_write_probe"]
            if not isinstance(probe, dict):
                reasons.append("postgresql_primary_write_fence_probe_missing")
            elif (
                probe.get("attempted") is not True
                or probe.get("accepted") is not False
            ):
                reasons.append("postgresql_primary_write_fence_probe_failed")
    if evidence.get("publication_present_after_promotion") is not True:
        reasons.append("postgresql_publication_missing_after_promotion")

    required_slot = {
        "exists",
        "slot_name",
        "plugin",
        "slot_type",
        "database_identity",
        "system_identifier",
    }
    if not isinstance(primary_slot, dict) or not required_slot.issubset(primary_slot):
        reasons.append("logical_replication_slot_primary_evidence_missing")
    elif primary_slot["exists"] is not True:
        reasons.append("logical_replication_slot_missing_before_failover")
    if not isinstance(promoted_slot, dict):
        reasons.append("logical_replication_slot_promoted_evidence_missing")
    elif promoted_slot.get("exists") is not True:
        reasons.append("logical_replication_slot_missing_after_promotion")
    elif isinstance(primary_slot, dict) and required_slot.issubset(primary_slot):
        comparable = {
            "slot_name",
            "plugin",
            "slot_type",
            "database_identity",
            "system_identifier",
        }
        if any(primary_slot[key] != promoted_slot.get(key) for key in comparable):
            reasons.append("logical_replication_slot_identity_changed_after_promotion")

    admitted = not reasons
    return {
        "schema": "gda.postgres_cdc_failover_continuity_admission.v1",
        "admitted": admitted,
        "disposition": "admitted" if admitted else "rejected_fail_closed",
        "reason_codes": sorted(set(reasons)),
        "system_identifier": (
            primary.get("system_identifier") if isinstance(primary, dict) else None
        ),
        "original_timeline_id": (
            primary.get("timeline_id") if isinstance(primary, dict) else None
        ),
        "promoted_timeline_id": (
            promoted.get("timeline_id") if isinstance(promoted, dict) else None
        ),
        "fencing_mode": fencing.get("mode") if isinstance(fencing, dict) else None,
    }


def build_postgresql_cdc_failover_recovery_plan(
    *,
    tenant_id: str,
    sync_definition_urn: str,
    sync_definition_version_id: UUID,
    source_resource_urn: str,
    target_resource_urn: str,
    checkpoint_state_version: int,
    checkpoint_cursor: dict[str, Any],
    admission: dict[str, Any],
    admission_evidence: dict[str, Any],
    created_by: str,
    created_at: datetime,
) -> PostgresqlCdcFailoverRecoveryPlan:
    """Turn a rejected failover into an explicit, non-advancing recovery boundary."""

    if admission.get("admitted") is True:
        raise ValueError("an admitted failover cannot create a recovery plan")
    if admission.get("disposition") != "rejected_fail_closed":
        raise ValueError("failover recovery requires rejected_fail_closed admission")
    reason_codes = admission.get("reason_codes")
    if not isinstance(reason_codes, list) or not reason_codes:
        raise ValueError("failover recovery requires admission reason codes")
    if not all(isinstance(reason, str) and reason for reason in reason_codes):
        raise ValueError("failover recovery reason codes must be non-empty strings")
    admission_evidence_sha256 = canonical_json_fingerprint(admission_evidence)
    values = {
        "schema": "gda.postgresql_cdc_failover_recovery_plan.v1",
        "tenant_id": tenant_id,
        "sync_definition_urn": sync_definition_urn,
        "sync_definition_version_id": sync_definition_version_id,
        "source_resource_urn": source_resource_urn,
        "target_resource_urn": target_resource_urn,
        "checkpoint_state_version": checkpoint_state_version,
        "checkpoint_cursor": checkpoint_cursor,
        "checkpoint_cursor_sha256": canonical_json_fingerprint(checkpoint_cursor),
        "admission_schema": "gda.postgres_cdc_failover_continuity_admission.v1",
        "admission_reason_codes": tuple(sorted(reason_codes)),
        "admission_evidence_sha256": admission_evidence_sha256,
        "recovery_mode": "resnapshot_and_reconcile",
        "cursor_disposition": "do_not_advance",
        "requires_new_run": True,
        "created_by": created_by,
        "created_at": created_at,
    }
    values["plan_sha256"] = postgresql_cdc_failover_recovery_plan_fingerprint(
        tenant_id=tenant_id,
        sync_definition_urn=sync_definition_urn,
        sync_definition_version_id=sync_definition_version_id,
        source_resource_urn=source_resource_urn,
        target_resource_urn=target_resource_urn,
        checkpoint_state_version=checkpoint_state_version,
        checkpoint_cursor=checkpoint_cursor,
        admission_reason_codes=values["admission_reason_codes"],
        admission_evidence_sha256=admission_evidence_sha256,
        created_by=created_by,
        created_at=created_at,
    )
    return PostgresqlCdcFailoverRecoveryPlan.model_validate(values)


def build_postgresql_cdc_failover_recovery_artifact(
    plan: PostgresqlCdcFailoverRecoveryPlan,
    *,
    run_id: UUID,
) -> Artifact:
    """Project one recovery plan into the existing immutable evidence ledger."""

    manifest = plan.model_dump(mode="json")
    content = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return Artifact(
        tenant_id=plan.tenant_id,
        artifact_id=uuid5(
            run_id,
            f"gda.postgresql_cdc_failover_recovery_plan.v1:{plan.plan_sha256}",
        ),
        artifact_key=f"cdc-failover-recovery-{plan.plan_sha256[:16]}",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri=(
            "postgresql://gda-control/recovery-plans/"
            f"{plan.tenant_id}/{plan.plan_sha256}"
        ),
        media_type="application/vnd.gda.postgresql-cdc-recovery-plan+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(content.encode("utf-8")),
        run_id=run_id,
        resource_version_id=plan.sync_definition_version_id,
        manifest=manifest,
        created_by=plan.created_by,
        created_at=plan.created_at,
    )


def build_postgresql_cdc_failover_resnapshot_definition(
    source_definition: SourceSyncDefinitionVersion,
    plan: PostgresqlCdcFailoverRecoveryPlan,
    *,
    sync_definition_urn: str,
    sync_definition_version_id: UUID,
    platform_definition_version_id: UUID,
    created_by: str,
    created_at: datetime,
) -> SourceSyncDefinitionVersion:
    """Build a new full/overwrite definition without mutating the rejected definition."""

    if source_definition.tenant_id != plan.tenant_id:
        raise ValueError("resnapshot source definition tenant must match recovery plan")
    if source_definition.sync_definition_version_id != plan.sync_definition_version_id:
        raise ValueError("resnapshot source definition must be the rejected definition")
    if source_definition.source_resource_urn != plan.source_resource_urn:
        raise ValueError("resnapshot source definition does not match recovery plan")
    if source_definition.target_resource_urn != plan.target_resource_urn:
        raise ValueError("resnapshot target definition does not match recovery plan")
    governance = source_definition.governance_contract
    if governance is None:
        raise ValueError("resnapshot requires a governed source definition")
    governance_values = governance.model_dump(mode="python", by_alias=True)
    governance_values["capture_kind"] = "batch"
    governance_values["event_time_field"] = None
    governance_values["watermark_delay_seconds"] = None
    config = {
        **source_definition.config,
        "recovery_mode": "resnapshot_and_reconcile",
        "recovery_plan_sha256": plan.plan_sha256,
        "recovered_from_sync_definition_version_id": str(
            source_definition.sync_definition_version_id
        ),
    }
    values: dict[str, Any] = {
        "tenant_id": source_definition.tenant_id,
        "sync_definition_urn": sync_definition_urn,
        "sync_definition_version_id": sync_definition_version_id,
        "platform_definition_version_id": platform_definition_version_id,
        "source_resource_urn": source_definition.source_resource_urn,
        "source_definition_fingerprint": source_definition.source_definition_fingerprint,
        "target_resource_urn": source_definition.target_resource_urn,
        "mode": "full",
        "write_disposition": "overwrite",
        "cursor_kind": "none",
        "cursor_field": None,
        "primary_keys": (),
        "delete_mode": "ignore",
        "config": config,
        "governance_contract": governance_values,
    }
    return SourceSyncDefinitionVersion(
        **values,
        definition_sha256=source_sync_definition_fingerprint(**values),
        created_by=created_by,
        created_at=created_at,
    )


def build_postgresql_cdc_failover_resnapshot_admission(
    plan: PostgresqlCdcFailoverRecoveryPlan,
    new_definition: SourceSyncDefinitionVersion,
    *,
    new_run_id: UUID,
    admitted_by: str,
    admitted_at: datetime,
) -> PostgresqlCdcFailoverResnapshotAdmission:
    values = {
        "schema": "gda.postgresql_cdc_failover_resnapshot_admission.v1",
        "tenant_id": plan.tenant_id,
        "recovery_plan": plan,
        "previous_sync_definition_version_id": plan.sync_definition_version_id,
        "new_sync_definition": new_definition,
        "new_run_id": new_run_id,
        "admission_mode": "resnapshot_and_reconcile",
        "cursor_disposition": "old_checkpoint_unchanged",
        "admitted_by": admitted_by,
        "admitted_at": admitted_at,
    }
    values["admission_sha256"] = postgresql_cdc_failover_resnapshot_admission_fingerprint(
        recovery_plan_sha256=plan.plan_sha256,
        previous_sync_definition_version_id=plan.sync_definition_version_id,
        new_sync_definition=new_definition,
        new_run_id=new_run_id,
        admitted_by=admitted_by,
        admitted_at=admitted_at,
    )
    return PostgresqlCdcFailoverResnapshotAdmission.model_validate(values)


def build_postgresql_cdc_failover_resnapshot_admission_artifact(
    admission: PostgresqlCdcFailoverResnapshotAdmission,
) -> Artifact:
    """Project a resnapshot admission into the existing evidence ledger."""

    manifest = admission.model_dump(mode="json")
    content = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return Artifact(
        tenant_id=admission.tenant_id,
        artifact_id=uuid5(
            admission.new_run_id,
            f"gda.postgresql_cdc_failover_resnapshot_admission.v1:{admission.admission_sha256}",
        ),
        artifact_key=f"cdc-resnapshot-admission-{admission.admission_sha256[:16]}",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri=(
            "postgresql://gda-control/recovery-admissions/"
            f"{admission.tenant_id}/{admission.admission_sha256}"
        ),
        media_type="application/vnd.gda.postgresql-cdc-resnapshot-admission+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(content.encode("utf-8")),
        run_id=admission.new_run_id,
        resource_version_id=admission.new_sync_definition.sync_definition_version_id,
        manifest=manifest,
        created_by=admission.admitted_by,
        created_at=admission.admitted_at,
    )


def _failover_fault_checks(evidence: dict[str, Any]) -> dict[str, bool]:
    primary = evidence["primary_identity"]
    standby = evidence["standby_identity_before_promotion"]
    promoted = evidence["promoted_identity"]
    replay = evidence["standby_replay"]
    post_probe = evidence["post_promotion_probe"]
    admission = evidence["admission"]
    return {
        "physical_standby_was_built_and_streaming": (
            evidence["basebackup"]["completed"]
            and evidence["physical_replication"]["state"] == "streaming"
            and evidence["physical_replication"]["application_name"]
            == evidence["basebackup"]["application_name"]
            and standby["in_recovery"] is True
        ),
        "same_cluster_system_identifier_was_preserved": (
            primary["system_identifier"]
            == standby["system_identifier"]
            == promoted["system_identifier"]
        ),
        "exact_source_mutation_replayed_before_promotion": (
            evidence["event_sequence"]["source_mutated"]
            < evidence["event_sequence"]["standby_replay_reached_target"]
            < evidence["event_sequence"]["primary_stopped"]
            and _lsn_value(replay["replay_lsn"])
            >= _lsn_value(evidence["source_mutation"]["target_lsn"])
            and replay["row"] == evidence["source_mutation"]["row"]
            and evidence["mutation_replayed_before_promotion"]
        ),
        "pre_failover_sink_state_was_checkpoint_protected": (
            evidence["pre_failover_sink"]["accepted"] == 5
            and evidence["pre_failover_sink"]["rejected"] == 0
            and evidence["pre_failover_sink"]["checkpoint_count"] >= 5
        ),
        "primary_stop_preceded_standby_promotion": (
            evidence["event_sequence"]["primary_stopped"]
            < evidence["event_sequence"]["standby_promoted"]
            and evidence["primary_stop"]["stopped"]
            and evidence["primary_stopped_before_promotion"]
        ),
        "primary_fencing_was_observed_before_promotion": (
            evidence["event_sequence"]["primary_fence_verified"]
            < evidence["event_sequence"]["standby_promoted"]
            and evidence["fencing"]["mode"] == "stop_and_detach"
            and evidence["fencing"]["old_primary_stopped"]
            and evidence["fencing"]["old_primary_network_detached"]
            and evidence["fencing"]["old_primary_write_probe"]["attempted"]
            and not evidence["fencing"]["old_primary_write_probe"]["accepted"]
        ),
        "promotion_incremented_exactly_one_timeline": (
            promoted["timeline_id"] == primary["timeline_id"] + 1
            and promoted["in_recovery"] is False
        ),
        "promoted_source_preserved_publication_and_replayed_row": (
            evidence["publication_present_after_promotion"]
            and evidence["promoted_row"] == evidence["source_mutation"]["row"]
        ),
        "postgresql_16_promoted_source_lacked_original_logical_slot": (
            evidence["postgres_major_version"] == 16
            and evidence["primary_slot"]["exists"]
            and evidence["primary_slot"]["active"]
            and not evidence["promoted_slot"]["exists"]
        ),
        "controller_rejected_only_missing_slot_continuity": (
            not admission["admitted"]
            and admission["disposition"] == "rejected_fail_closed"
            and admission["reason_codes"]
            == ["logical_replication_slot_missing_after_promotion"]
            and evidence["event_sequence"]["admission_rejected"]
            < evidence["event_sequence"]["post_promotion_probe_mutated"]
            < evidence["event_sequence"]["runtime_terminated"]
        ),
        "stable_source_alias_moved_only_after_primary_stop": (
            evidence["source_alias_transfer"]["primary_detached"]
            and evidence["source_alias_transfer"]["standby_attached"]
            and evidence["source_alias_transfer"]["source_alias"]
            in evidence["source_alias_transfer"]["standby_network_aliases"]
            and evidence["event_sequence"]["primary_stopped"]
            < evidence["event_sequence"]["source_alias_transferred"]
        ),
        "post_promotion_probe_advanced_source_but_not_sink": (
            _lsn_value(post_probe["target_lsn"])
            > _lsn_value(evidence["source_mutation"]["target_lsn"])
            and post_probe["row"]["revision"]
            > evidence["source_mutation"]["row"]["revision"]
            and evidence["sink"]["accepted_after"]
            == evidence["sink"]["accepted_before"]
            and evidence["sink"]["rejected_after"]
            == evidence["sink"]["rejected_before"]
            and evidence["sink"]["post_failover_accepted_delta"] == 0
            and evidence["sink"]["post_failover_rejected_delta"] == 0
            and evidence["post_failover_observation_seconds"] >= 1.0
        ),
        "runtime_terminal_state_remained_separate_evidence": (
            evidence["runtime_termination"]["final_job_status"]
            in TERMINAL_FLINK_STATES
            and evidence["runtime_termination"]["origin"]
            == "controller_cancel_after_failover_admission_rejection"
        ),
    }


def _docker_volume_absent(name: str) -> bool:
    completed = subprocess.run(
        ["docker", "volume", "inspect", name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return completed.returncode != 0


def _container_network_aliases(name: str, network: str) -> list[str]:
    completed = _run_command(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .NetworkSettings.Networks}}",
            name,
        ],
        stage="inspect promoted PostgreSQL source aliases",
    )
    try:
        networks = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Docker network alias evidence is malformed") from exc
    attachment = networks.get(network)
    if not isinstance(attachment, dict):
        raise RuntimeError("promoted PostgreSQL source network evidence is missing")
    aliases = attachment.get("Aliases")
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) for alias in aliases
    ):
        raise RuntimeError("promoted PostgreSQL source aliases are missing")
    return sorted(set(aliases))


def _observe_primary_fencing(
    postgres: CdcPostgresSandbox,
    *,
    stop_result: dict[str, Any],
    detach_result: dict[str, Any],
) -> dict[str, Any]:
    """Capture a bounded, secret-free witness that the old primary is fenced."""

    probe = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            f"PGPASSWORD={postgres.admin_password}",
            postgres.container,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            postgres.admin_user,
            "-d",
            postgres.database,
            "-At",
            "-c",
            "SELECT 1;",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    network_detached = not _container_network_attached(
        postgres.container, postgres.network
    )
    return {
        "schema": "gda.postgresql_primary_fencing.v1",
        "mode": "stop_and_detach",
        "old_primary_stopped": stop_result.get("stopped") is True,
        "old_primary_network_detached": (
            detach_result.get("disconnected") is True and network_detached
        ),
        "old_primary_write_probe": {
            "attempted": True,
            "accepted": probe.returncode == 0,
            "transport": "docker_exec",
            "rejection_witness": (
                "container_unavailable" if probe.returncode != 0 else "write_path_open"
            ),
        },
    }


class PhysicalStandbySandbox:
    def __init__(
        self,
        *,
        source: CdcPostgresSandbox,
        image: str,
        network: str,
        token: str,
        source_alias: str,
    ) -> None:
        self.source = source
        self.image = image
        self.network = network
        self.source_alias = source_alias
        self.container = f"gda-cdc-standby-{token}"
        self.volume = f"gda-cdc-standby-data-{token}"
        self.application_name = f"gda_physical_standby_{token}"
        self.started = False
        self.volume_created = False
        for resource in (self.container, self.volume):
            if not STANDBY_RESOURCE_RE.fullmatch(resource):
                raise RuntimeError("generated physical standby resource is invalid")

    def _psql(self, sql: str) -> str:
        completed = _run_command(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={self.source.admin_password}",
                self.container,
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                self.source.admin_user,
                "-d",
                self.source.database,
                "-At",
                "-c",
                sql,
            ],
            stage="execute isolated PostgreSQL standby statement",
        )
        return completed.stdout

    def build_and_start(self) -> dict[str, Any]:
        _run_command(
            ["docker", "volume", "create", self.volume],
            stage="create isolated PostgreSQL standby volume",
        )
        self.volume_created = True
        _run_command(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{self.volume}:/var/lib/postgresql/data",
                self.image,
                "chown",
                "postgres:postgres",
                "/var/lib/postgresql/data",
            ],
            stage="prepare isolated PostgreSQL standby volume ownership",
        )
        _run_command(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "postgres",
                "--network",
                self.network,
                "-e",
                f"PGPASSWORD={self.source.reader_password}",
                "-v",
                f"{self.volume}:/var/lib/postgresql/data",
                self.image,
                "pg_basebackup",
                "--host",
                self.source.container,
                "--port",
                "5432",
                "--username",
                self.source.reader_user,
                "--pgdata",
                "/var/lib/postgresql/data",
                "--write-recovery-conf",
                "--wal-method=stream",
                "--checkpoint=fast",
                "--no-password",
                "--dbname",
                (
                    f"host={self.source.container} port=5432 "
                    f"user={self.source.reader_user} "
                    f"application_name={self.application_name}"
                ),
            ],
            stage="build PostgreSQL physical standby with pg_basebackup",
            timeout=180,
        )
        _run_command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.container,
                "--network",
                self.network,
                "-v",
                f"{self.volume}:/var/lib/postgresql/data",
                self.image,
                "postgres",
            ],
            stage="start PostgreSQL physical standby",
        )
        self.started = True
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container,
                    "pg_isready",
                    "-U",
                    self.source.admin_user,
                    "-d",
                    self.source.database,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if ready.returncode == 0:
                identity = self.replication_identity()
                if identity["in_recovery"] is True:
                    return {
                        "completed": True,
                        "application_name": self.application_name,
                        "container": self.container,
                        "volume": self.volume,
                        "identity": identity,
                    }
            time.sleep(0.5)
        raise RuntimeError("PostgreSQL physical standby did not enter recovery")

    def replication_identity(self) -> dict[str, Any]:
        payload = self._psql(
            "SELECT json_build_object("
            "'system_identifier', system_identifier::text, "
            "'timeline_id', timeline_id, "
            "'previous_timeline_id', prev_timeline_id, "
            "'checkpoint_lsn', checkpoint_lsn::text, "
            "'redo_lsn', redo_lsn::text, "
            "'in_recovery', pg_is_in_recovery(), "
            "'observation_lsn', CASE WHEN pg_is_in_recovery() "
            "THEN pg_last_wal_replay_lsn()::text "
            "ELSE pg_current_wal_lsn()::text END, "
            "'receive_lsn', COALESCE(pg_last_wal_receive_lsn()::text, ''), "
            "'replay_lsn', COALESCE(pg_last_wal_replay_lsn()::text, ''))::text "
            "FROM pg_control_system() CROSS JOIN pg_control_checkpoint();"
        ).strip()
        try:
            return dict(json.loads(payload))
        except json.JSONDecodeError as exc:
            raise RuntimeError("PostgreSQL standby identity is malformed") from exc

    def wait_for_replay(
        self,
        *,
        target_lsn: str,
        expected_row: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_identity: dict[str, Any] | None = None
        last_row: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            last_identity = self.replication_identity()
            last_row = self.row(int(expected_row["road_id"]))
            replay_lsn = last_identity["replay_lsn"]
            if (
                replay_lsn
                and _lsn_value(replay_lsn) >= _lsn_value(target_lsn)
                and last_row == expected_row
            ):
                return {
                    "target_lsn": target_lsn,
                    "replay_lsn": replay_lsn,
                    "row": last_row,
                    "identity": last_identity,
                }
            time.sleep(0.25)
        raise RuntimeError(
            "PostgreSQL standby did not replay the exact source mutation: "
            f"identity={last_identity}, row={last_row}, target_lsn={target_lsn}"
        )

    def row(self, road_id: int) -> dict[str, Any]:
        value = self._psql(
            "SELECT road_id::text || E'\\t' || revision::text || E'\\t' || "
            "road_name_base64 || E'\\t' || geometry_sha256 "
            f"FROM public.{self.source.table} WHERE road_id = {road_id};"
        ).strip()
        fields = value.split("\t") if value else []
        if len(fields) != 4:
            raise RuntimeError("PostgreSQL standby source row is missing")
        return {
            "road_id": int(fields[0]),
            "revision": int(fields[1]),
            "road_name_base64": fields[2],
            "geometry_sha256": fields[3],
        }

    def snapshot_rows(self) -> list[dict[str, Any]]:
        payload = self._psql(
            "SELECT COALESCE(json_agg(json_build_object("
            "'road_id', road_id, 'revision', revision, "
            "'road_name_base64', road_name_base64, "
            "'geometry_sha256', geometry_sha256) ORDER BY road_id), '[]'::json)::text "
            f"FROM public.{self.source.table};"
        ).strip()
        try:
            rows = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("PostgreSQL standby snapshot is malformed") from exc
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("PostgreSQL standby full snapshot is empty")
        expected_fields = {
            "road_id",
            "revision",
            "road_name_base64",
            "geometry_sha256",
        }
        if any(not isinstance(row, dict) or set(row) != expected_fields for row in rows):
            raise RuntimeError("PostgreSQL standby full snapshot fields are invalid")
        if [row["road_id"] for row in rows] != sorted(row["road_id"] for row in rows):
            raise RuntimeError("PostgreSQL standby full snapshot is not ordered")
        return rows

    def slot_observation(self) -> dict[str, Any]:
        system_identifier = self.replication_identity()["system_identifier"]
        value = self._psql(
            "SELECT slot_name || E'\\t' || plugin || E'\\t' || slot_type || "
            "E'\\t' || database::text || E'\\t' || active::text "
            "FROM pg_replication_slots WHERE slot_name = "
            f"{_sql_literal(self.source.slot)};"
        ).strip()
        if not value:
            return {
                "exists": False,
                "slot_name": self.source.slot,
                "system_identifier": system_identifier,
            }
        fields = value.split("\t")
        if len(fields) != 5:
            raise RuntimeError("promoted PostgreSQL slot observation is malformed")
        return {
            "exists": True,
            "slot_name": fields[0],
            "plugin": fields[1],
            "slot_type": fields[2],
            "database_identity": fields[3],
            "active": fields[4] in {"t", "true"},
            "system_identifier": system_identifier,
        }

    def publication_present(self) -> bool:
        value = self._psql(
            "SELECT EXISTS(SELECT 1 FROM pg_publication WHERE pubname = "
            f"{_sql_literal(self.source.publication)})::text;"
        ).strip()
        return value in {"t", "true"}

    def promote(self, *, timeout: int) -> dict[str, Any]:
        _run_command(
            [
                "docker",
                "exec",
                "--user",
                "postgres",
                self.container,
                "pg_ctl",
                "-D",
                "/var/lib/postgresql/data",
                "promote",
                "-w",
                "-t",
                str(timeout),
            ],
            stage="promote PostgreSQL physical standby",
            timeout=timeout + 15,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            identity = self.replication_identity()
            if identity["in_recovery"] is False:
                self._psql("CHECKPOINT;")
                identity = self.replication_identity()
                return {"promoted": True, "identity": identity}
            time.sleep(0.25)
        raise RuntimeError("PostgreSQL standby promotion did not complete")

    def transfer_source_alias(self) -> dict[str, Any]:
        if _container_network_attached(self.container, self.network):
            _run_command(
                ["docker", "network", "disconnect", self.network, self.container],
                stage="detach promoted PostgreSQL source before alias transfer",
            )
        _run_command(
            [
                "docker",
                "network",
                "connect",
                "--alias",
                self.source_alias,
                self.network,
                self.container,
            ],
            stage="attach promoted PostgreSQL source alias",
        )
        attached = _container_network_attached(self.container, self.network)
        if not attached:
            raise RuntimeError("promoted PostgreSQL source alias was not attached")
        aliases = _container_network_aliases(self.container, self.network)
        if self.source_alias not in aliases:
            raise RuntimeError("promoted PostgreSQL stable source alias is missing")
        return {
            "source_alias": self.source_alias,
            "primary_detached": not _container_network_attached(
                self.source.container, self.network
            ),
            "standby_attached": attached,
            "standby_network_aliases": aliases,
        }

    def mutate_after_promotion(self, source_row: dict[str, Any]) -> dict[str, Any]:
        revision = int(source_row["revision"]) + 1
        self._psql(
            f"UPDATE public.{self.source.table} SET revision = {revision} "
            f"WHERE road_id = {int(source_row['road_id'])};"
        )
        return {
            "target_lsn": self.replication_identity()["observation_lsn"],
            "row": self.row(int(source_row["road_id"])),
        }

    def cleanup(self) -> dict[str, bool]:
        if self.started and not _container_absent(self.container):
            subprocess.run(
                ["docker", "rm", "-f", self.container],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        if self.volume_created and not _docker_volume_absent(self.volume):
            subprocess.run(
                ["docker", "volume", "rm", self.volume],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        return {
            "cdc_standby_container_removed": _container_absent(self.container),
            "cdc_standby_volume_removed": _docker_volume_absent(self.volume),
        }


def _physical_replication_observation(
    source: CdcPostgresSandbox,
    *,
    application_name: str,
    timeout: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        value = source._psql(
            "SELECT application_name || E'\\t' || state || E'\\t' || sync_state || "
            "E'\\t' || COALESCE(sent_lsn::text, '') || E'\\t' || "
            "COALESCE(write_lsn::text, '') || E'\\t' || "
            "COALESCE(flush_lsn::text, '') || E'\\t' || "
            "COALESCE(replay_lsn::text, '') FROM pg_stat_replication "
            f"WHERE application_name = {_sql_literal(application_name)};"
        ).strip()
        fields = value.split("\t") if value else []
        if len(fields) == 7:
            last = {
                "application_name": fields[0],
                "state": fields[1],
                "sync_state": fields[2],
                "sent_lsn": fields[3],
                "write_lsn": fields[4],
                "flush_lsn": fields[5],
                "replay_lsn": fields[6],
            }
            if last["state"] == "streaming":
                return last
        time.sleep(0.25)
    raise RuntimeError(
        "PostgreSQL physical replication did not become streaming: "
        f"observation={last}"
    )


def _enable_isolated_physical_replication(
    source: CdcPostgresSandbox,
) -> dict[str, Any]:
    hba_file = source._psql("SHOW hba_file;").strip()
    if not re.fullmatch(r"/var/lib/postgresql/data/[a-z0-9_.-]+", hba_file):
        raise RuntimeError("PostgreSQL HBA path escaped the isolated data directory")
    rule = (
        f"host replication {source.reader_user} samenet scram-sha-256"
    )
    _run_command(
        [
            "docker",
            "exec",
            "--user",
            "postgres",
            source.container,
            "sed",
            "-i",
            f"$a{rule}",
            hba_file,
        ],
        stage="enable isolated PostgreSQL physical replication access",
    )
    reloaded = source._psql("SELECT pg_reload_conf()::text;").strip()
    observation = source._psql(
        "SELECT type || E'\\t' || database::text || E'\\t' || "
        "user_name::text || E'\\t' || COALESCE(address, '') || E'\\t' || "
        "auth_method || E'\\t' || COALESCE(error, '<none>') "
        "FROM pg_hba_file_rules WHERE database = ARRAY['replication'] "
        f"AND user_name = ARRAY[{_sql_literal(source.reader_user)}] "
        "ORDER BY line_number DESC LIMIT 1;"
    ).strip()
    fields = observation.split("\t") if observation else []
    if (
        reloaded not in {"t", "true"}
        or len(fields) != 6
        or fields[0] != "host"
        or fields[3] != "samenet"
        or fields[4] != "scram-sha-256"
        or fields[5] != "<none>"
    ):
        raise RuntimeError(
            "isolated PostgreSQL physical replication HBA rule was not loaded: "
            f"reloaded={reloaded}, fields={fields}"
        )
    return {
        "database": "replication",
        "role": source.reader_user,
        "address_scope": "samenet",
        "auth_method": "scram-sha-256",
        "loaded": True,
        "rule_sha256": canonical_json_fingerprint({"rule": rule}),
    }


def _wait_for_checkpoint_count(
    flink: FlinkCdcSandbox,
    *,
    job_id: str,
    minimum_count: int,
    timeout: int,
) -> int:
    deadline = time.monotonic() + timeout
    maximum = 0
    while time.monotonic() < deadline:
        output = flink.task_output()
        counts = [int(count) for _, count in CHECKPOINT_RE.findall(output)]
        maximum = max(counts, default=0)
        if maximum >= minimum_count:
            return maximum
        status = flink.job_status(job_id)
        if status in TERMINAL_FLINK_STATES:
            raise RuntimeError(
                "Flink terminated before the pre-failover checkpoint: "
                f"status={status}, checkpoint_count={maximum}"
            )
        time.sleep(0.5)
    raise RuntimeError(
        "Flink did not checkpoint the pre-failover source mutation: "
        f"checkpoint_count={maximum}"
    )


def run_failover_provider(
    *,
    args: argparse.Namespace,
    work_dir: Path,
    token: str,
    plan: dict[str, Any],
    connector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    jar_path = compile_flink_job(
        work_dir=work_dir,
        flink_image=args.flink_image,
        jdk_image=args.jdk_image,
        java_home=args.java_home,
        timeout=args.timeout_seconds,
        java_source=JAVA_SOURCE,
        main_class=MAIN_CLASS,
    )
    source_alias = f"gda-cdc-source-{token}"
    postgres = CdcPostgresSandbox(
        image=args.postgres_image,
        network=args.docker_network,
        token=token,
        network_alias=source_alias,
    )
    standby = PhysicalStandbySandbox(
        source=postgres,
        image=args.postgres_image,
        network=args.docker_network,
        token=token,
        source_alias=source_alias,
    )
    flink = FlinkCdcSandbox(
        image=args.flink_image,
        network=args.docker_network,
        token=token,
        connector=args.connector,
        password=postgres.reader_password,
        work_dir=work_dir,
    )
    cleanup: dict[str, bool] = {}
    try:
        postgres_start = postgres.start(plan["initial"])
        physical_replication_access = _enable_isolated_physical_replication(
            postgres
        )
        flink_cluster = flink.start()
        job_id = flink.submit(
            jar_path=jar_path,
            source=postgres,
            source_hostname=source_alias,
            fail_after_count=1_000_000,
        )
        initial_lines = flink.wait_for_output(
            expected=plan["milestone_counts"]["initial_snapshot_accepted"],
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        _wait_for_checkpoint_count(
            flink,
            job_id=job_id,
            minimum_count=len(initial_lines),
            timeout=args.timeout_seconds,
        )
        postgres.wait_for_slot_active(timeout=args.timeout_seconds)

        basebackup = standby.build_and_start()
        physical_replication = _physical_replication_observation(
            postgres,
            application_name=standby.application_name,
            timeout=args.timeout_seconds,
        )
        source_mutation = postgres.mutate_for_failover(plan)
        standby_replay = standby.wait_for_replay(
            target_lsn=source_mutation["target_lsn"],
            expected_row=source_mutation["row"],
            timeout=args.timeout_seconds,
        )
        pre_failover_lines = flink.wait_for_output(
            expected=5,
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        checkpoint_count = _wait_for_checkpoint_count(
            flink,
            job_id=job_id,
            minimum_count=len(pre_failover_lines),
            timeout=args.timeout_seconds,
        )
        accepted_before, accepted_files_before = _committed_lines(
            work_dir / "silver/v1/changelog"
        )
        rejected_before, rejected_files_before = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        primary_identity = postgres.replication_identity()
        standby_identity = standby.replication_identity()
        primary_slot = postgres.slot_observation()

        primary_stop = postgres.stop(timeout=args.primary_stop_timeout_seconds)
        primary_detach = postgres.disconnect_network()
        fencing = _observe_primary_fencing(
            postgres,
            stop_result=primary_stop,
            detach_result=primary_detach,
        )
        promotion = standby.promote(timeout=args.promotion_timeout_seconds)
        promoted_identity = promotion["identity"]
        promoted_slot = standby.slot_observation()
        publication_present = standby.publication_present()
        promoted_row = standby.row(int(source_mutation["row"]["road_id"]))
        admission_evidence = {
            "primary_identity": primary_identity,
            "standby_identity_before_promotion": standby_identity,
            "promoted_identity": promoted_identity,
            "primary_slot": primary_slot,
            "promoted_slot": promoted_slot,
            "mutation_replayed_before_promotion": True,
            "primary_stopped_before_promotion": True,
            "fencing": fencing,
            "publication_present_after_promotion": publication_present,
        }
        admission = assess_failover_continuity(admission_evidence)
        if admission["admitted"]:
            raise RuntimeError("controller admitted failover without slot continuity")

        alias_transfer = standby.transfer_source_alias()
        post_probe = standby.mutate_after_promotion(source_mutation["row"])
        resnapshot_rows = standby.snapshot_rows()
        resnapshot_source_identity = standby.replication_identity()
        resnapshot_source = {
            "rows": resnapshot_rows,
            "row_count": len(resnapshot_rows),
            "source_snapshot_sha256": canonical_json_fingerprint(resnapshot_rows),
            "source_observation_lsn": resnapshot_source_identity["observation_lsn"],
            "source_identity": resnapshot_source_identity,
        }
        time.sleep(args.post_failover_observation_seconds)
        status_before_cancel = flink.job_status(job_id)
        exceptions_before_cancel = _exception_summary(flink.job_exceptions(job_id))
        final_status = flink.cancel(job_id, timeout=args.timeout_seconds)
        exceptions_after_cancel = _exception_summary(flink.job_exceptions(job_id))
        accepted_after, accepted_files_after = _committed_lines(
            work_dir / "silver/v1/changelog"
        )
        rejected_after, rejected_files_after = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        failover = {
            "event_sequence": {
                "initial_checkpoint_completed": 1,
                "physical_basebackup_completed": 2,
                "source_mutated": 3,
                "standby_replay_reached_target": 4,
                "pre_failover_sink_checkpoint_completed": 5,
                "primary_stopped": 6,
                "primary_fence_verified": 7,
                "standby_promoted": 8,
                "admission_rejected": 9,
                "source_alias_transferred": 10,
                "post_promotion_probe_mutated": 11,
                "runtime_terminated": 12,
            },
            "postgres_major_version": int(postgres_start["version"].split(".", 1)[0]),
            "basebackup": basebackup,
            "physical_replication_access": physical_replication_access,
            "physical_replication": physical_replication,
            "source_mutation": source_mutation,
            "standby_replay": standby_replay,
            "primary_identity": primary_identity,
            "standby_identity_before_promotion": standby_identity,
            "primary_slot": primary_slot,
            "pre_failover_sink": {
                "accepted": len(accepted_before),
                "rejected": len(rejected_before),
                "checkpoint_count": checkpoint_count,
                "accepted_files": accepted_files_before,
                "rejected_files": rejected_files_before,
            },
            "primary_stop": primary_stop,
            "primary_network_detach": primary_detach,
            "primary_stopped_before_promotion": True,
            "fencing": fencing,
            "promotion": promotion,
            "promoted_identity": promoted_identity,
            "promoted_slot": promoted_slot,
            "publication_present_after_promotion": publication_present,
            "promoted_row": promoted_row,
            "mutation_replayed_before_promotion": True,
            "admission": admission,
            "source_alias_transfer": alias_transfer,
            "post_promotion_probe": post_probe,
            "resnapshot_source": resnapshot_source,
            "post_failover_observation_seconds": (
                args.post_failover_observation_seconds
            ),
            "runtime_termination": {
                "status_before_controller_cancel": status_before_cancel,
                "final_job_status": final_status,
                "origin": "controller_cancel_after_failover_admission_rejection",
                "exceptions_before_cancel": exceptions_before_cancel,
                "exceptions_after_cancel": exceptions_after_cancel,
            },
            "sink": {
                "accepted_before": len(accepted_before),
                "accepted_after": len(accepted_after),
                "rejected_before": len(rejected_before),
                "rejected_after": len(rejected_after),
                "post_failover_accepted_delta": len(accepted_after)
                - len(accepted_before),
                "post_failover_rejected_delta": len(rejected_after)
                - len(rejected_before),
                "accepted_files_after": accepted_files_after,
                "accepted_manifest_sha256": canonical_json_fingerprint(
                    accepted_files_after
                ),
                "rejected_files_after": rejected_files_after,
                "rejected_manifest_sha256": canonical_json_fingerprint(
                    rejected_files_after
                ),
            },
        }
        checks = _failover_fault_checks(failover)
        return (
            {
                "schema": "gda.postgres_cdc_physical_failover_provider.negative.v1",
                "status": "passed" if all(checks.values()) else "failed",
                "expected_outcome": "rejected_fail_closed",
                "checks": checks,
                "failover": failover,
                "postgres": {
                    **postgres_start,
                    "image": args.postgres_image,
                    "image_id": docker_image_id(
                        args.postgres_image, timeout=args.timeout_seconds
                    ),
                    "publication": postgres.publication,
                    "source_alias": source_alias,
                },
                "runtime": {
                    "flink_image": args.flink_image,
                    "flink_image_id": docker_image_id(
                        args.flink_image, timeout=args.timeout_seconds
                    ),
                    "cluster": flink_cluster,
                    "connector": connector,
                    "job_source_sha256": _sha256_file(JAVA_SOURCE),
                    "job_jar_sha256": _sha256_file(jar_path),
                },
            },
            cleanup,
        )
    finally:
        cleanup.update(flink.cleanup())
        cleanup.update(standby.cleanup())
        cleanup.update(postgres.cleanup())


def execute_governed_postgresql_cdc_resnapshot(
    *,
    gateway: PlatformGateway,
    authority: SourceSyncAuthority,
    definition: SourceSyncDefinitionVersion,
    admission: PostgresqlCdcFailoverResnapshotAdmission,
    run: Any,
    source_snapshot: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    """Materialize the promoted source snapshot through the governed commit path."""

    # The provider may be admitted after the physical failover takes several
    # seconds; all immutable evidence must remain at or after Run admission.
    created_at = max(created_at, run.submitted_at)
    rows = source_snapshot.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("resnapshot provider requires a non-empty source snapshot")
    source_snapshot_sha256 = canonical_json_fingerprint(rows)
    if source_snapshot_sha256 != source_snapshot.get("source_snapshot_sha256"):
        raise ValueError("resnapshot source snapshot fingerprint drifted")
    target_content_sha256 = canonical_json_fingerprint(rows)
    source_version_id = _resnapshot_source_version_id(
        definition, source_snapshot_sha256
    )
    source_binding = {
        binding.binding_name: binding for binding in run.input_bindings
    }.get("source")
    if source_binding is None or source_binding.resource_version_id != source_version_id:
        raise ValueError(
            "resnapshot Run source input binding is not frozen to the provider snapshot"
        )
    run_actor = f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
    target_version_id = uuid5(run.run_id, "gda.postgresql_cdc.resnapshot.target.v1")
    quarantine_version_id = uuid5(
        run.run_id, "gda.postgresql_cdc.resnapshot.quarantine.v1"
    )
    quarantine_content_sha256 = canonical_json_fingerprint(
        {"records_rejected": 0, "reason_counts": {}}
    )
    quarantine_urn = definition.governance_contract.quarantine_resource_urn
    if quarantine_urn is None:
        raise ValueError("resnapshot provider requires a quarantine Resource")
    try:
        stored_source_version = gateway.get_resource_version(
            definition.tenant_id, source_version_id
        )
    except GatewayNotFoundError:
        _register_resource_version(
            gateway,
            tenant_id=definition.tenant_id,
            resource_urn=definition.source_resource_urn,
            resource_version_id=source_version_id,
            content_sha256=source_snapshot_sha256,
            created_at=created_at,
        )
    else:
        if (
            stored_source_version.resource_urn != definition.source_resource_urn
            or stored_source_version.content_sha256 != source_snapshot_sha256
        ):
            raise ValueError("resnapshot source ResourceVersion payload drifted")
    _register_resource_version(
        gateway,
        tenant_id=definition.tenant_id,
        resource_urn=definition.target_resource_urn,
        resource_version_id=target_version_id,
        content_sha256=target_content_sha256,
        created_at=created_at,
    )
    _register_resource_only(
        gateway,
        tenant_id=definition.tenant_id,
        resource_urn=quarantine_urn,
    )
    _register_resource_version(
        gateway,
        tenant_id=definition.tenant_id,
        resource_urn=quarantine_urn,
        resource_version_id=quarantine_version_id,
        content_sha256=quarantine_content_sha256,
        created_at=created_at,
    )

    provider_ref = {
        "provider": "postgresql-full-resnapshot",
        "mode": definition.mode.value,
        "write_disposition": definition.write_disposition.value,
        "source_snapshot_sha256": source_snapshot_sha256,
        "target_content_sha256": target_content_sha256,
        "source_observation_lsn": source_snapshot["source_observation_lsn"],
        "source_system_identifier": source_snapshot["source_identity"][
            "system_identifier"
        ],
        "source_timeline_id": source_snapshot["source_identity"]["timeline_id"],
        "recovery_plan_sha256": admission.recovery_plan.plan_sha256,
        "admission_sha256": admission.admission_sha256,
    }
    output_artifact_id = uuid5(
        run.run_id, "gda.postgresql_cdc.resnapshot.output.v1"
    )
    quality_artifact_id = uuid5(
        run.run_id, "gda.postgresql_cdc.resnapshot.quality.v1"
    )
    quarantine_artifact_id = uuid5(
        run.run_id, "gda.postgresql_cdc.resnapshot.quarantine.v1"
    )
    lineage_event_id = uuid5(
        run.run_id, "gda.postgresql_cdc.resnapshot.lineage.v1"
    )
    output_manifest = {
        "schema": "gda.postgresql_cdc_resnapshot_output.v1",
        "provider": provider_ref,
        "rows": rows,
        "row_count": len(rows),
    }
    output_artifact = Artifact(
        tenant_id=definition.tenant_id,
        artifact_id=output_artifact_id,
        artifact_key=f"cdc-resnapshot-output-{target_content_sha256[:16]}",
        artifact_role=ArtifactRole.OUTPUT,
        storage_uri=(
            "postgresql://gda-control/resnapshot-targets/"
            f"{definition.tenant_id}/{target_content_sha256}"
        ),
        media_type="application/vnd.gda.postgresql-cdc-resnapshot+json",
        content_sha256=target_content_sha256,
        size_bytes=len(
            json.dumps(rows, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            .encode("utf-8")
        ),
        run_id=run.run_id,
        resource_version_id=target_version_id,
        manifest=output_manifest,
        created_by=WORKLOAD,
        created_at=created_at,
    )
    quality_evidence = Artifact(
        tenant_id=definition.tenant_id,
        artifact_id=quality_artifact_id,
        artifact_key=f"cdc-resnapshot-quality-{target_content_sha256[:16]}",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri=(
            "postgresql://gda-control/resnapshot-quality/"
            f"{definition.tenant_id}/{target_content_sha256}"
        ),
        media_type="application/vnd.gda.postgresql-cdc-quality+json",
        content_sha256=canonical_json_fingerprint(
            {
                "target_content_sha256": target_content_sha256,
                "row_count": len(rows),
                "violations": 0,
            }
        ),
        size_bytes=256,
        run_id=run.run_id,
        resource_version_id=target_version_id,
        manifest={
            "schema": "gda.postgresql_cdc_resnapshot_quality.v1",
            "target_content_sha256": target_content_sha256,
            "row_count": len(rows),
            "violations": 0,
        },
        created_by="workload:quality-evaluator",
        created_at=created_at + timedelta(seconds=1),
    )
    quarantine_artifact = Artifact(
        tenant_id=definition.tenant_id,
        artifact_id=quarantine_artifact_id,
        artifact_key=f"cdc-resnapshot-quarantine-{target_content_sha256[:16]}",
        artifact_role=ArtifactRole.QUARANTINE,
        storage_uri=(
            "postgresql://gda-control/resnapshot-quarantine/"
            f"{definition.tenant_id}/{target_content_sha256}"
        ),
        media_type="application/vnd.gda.source-sync-quarantine+json",
        content_sha256=quarantine_content_sha256,
        size_bytes=1,
        run_id=run.run_id,
        resource_version_id=quarantine_version_id,
        manifest={
            "schema": "gda.source_sync_quarantine.v1",
            "source_slice_sha256": source_snapshot_sha256,
            "sync_definition_version_id": str(
                definition.sync_definition_version_id
            ),
            "records_rejected": 0,
            "reason_counts": {},
            "target_content_sha256": target_content_sha256,
            "rejected_content_sha256": quarantine_content_sha256,
        },
        created_by=run_actor,
        created_at=created_at,
    )
    for artifact in (output_artifact, quality_evidence, quarantine_artifact):
        gateway.record_artifact(artifact)

    quality_metrics = {
        "records_read": len(rows),
        "records_output": len(rows),
        "rows_rejected": 0,
        "source_snapshot_sha256": source_snapshot_sha256,
        "target_content_sha256": target_content_sha256,
    }
    quality = QualityResult(
        tenant_id=definition.tenant_id,
        quality_result_id=uuid5(
            run.run_id, "gda.postgresql_cdc.resnapshot.quality-result.v1"
        ),
        run_id=run.run_id,
        resource_version_id=target_version_id,
        rule_version_ref="quality:cdc-changelog-integrity-v1",
        verdict="passed",
        metrics=quality_metrics,
        evidence_artifact_id=quality_artifact_id,
        result_sha256=quality_result_fingerprint(
            tenant_id=definition.tenant_id,
            run_id=run.run_id,
            resource_version_id=target_version_id,
            rule_version_ref="quality:cdc-changelog-integrity-v1",
            verdict="passed",
            metrics=quality_metrics,
            evidence_artifact_id=quality_artifact_id,
            evaluated_by="workload:quality-evaluator",
            evaluated_at=created_at + timedelta(seconds=1),
        ),
        evaluated_by="workload:quality-evaluator",
        evaluated_at=created_at + timedelta(seconds=1),
    )
    gateway.record_quality_result(quality)
    lineage_payload = {
        "schema": "gda.postgresql_cdc_resnapshot_lineage.v1",
        "source_resource_version_id": str(source_version_id),
        "target_resource_version_id": str(target_version_id),
        "run_id": str(run.run_id),
        "artifact_id": str(output_artifact_id),
        "source_snapshot_sha256": source_snapshot_sha256,
        "target_content_sha256": target_content_sha256,
    }
    lineage = LineageEvent(
        tenant_id=definition.tenant_id,
        lineage_event_id=lineage_event_id,
        event_type=LineageEventType.MATERIALIZE,
        source_resource_version_id=source_version_id,
        target_resource_version_id=target_version_id,
        producer=run_actor,
        event_sha256=canonical_json_fingerprint(lineage_payload),
        run_id=run.run_id,
        definition_version_id=definition.platform_definition_version_id,
        artifact_id=output_artifact_id,
        facets={"recovery_mode": "resnapshot_and_reconcile", **provider_ref},
        occurred_at=created_at + timedelta(seconds=1),
    )
    gateway.record_lineage(lineage)
    metadata_change_id = _metadata_change_id(
        gateway._engine or authority._engine,
        definition.tenant_id,
        lineage_event_id,
    )
    previous_cursor: dict[str, Any] = {}
    next_cursor = {
        "snapshot_sha256": target_content_sha256,
        "source_observation_lsn": source_snapshot["source_observation_lsn"],
    }
    committed_at = created_at + timedelta(seconds=2)
    commit_values = {
        "tenant_id": definition.tenant_id,
        "sync_commit_id": uuid5(
            run.run_id, "gda.postgresql_cdc.resnapshot.commit.v1"
        ),
        "sync_definition_version_id": definition.sync_definition_version_id,
        "run_id": run.run_id,
        "from_state_version": 0,
        "to_state_version": 1,
        "previous_cursor": previous_cursor,
        "next_cursor": next_cursor,
        "source_slice_sha256": source_snapshot_sha256,
        "target_commit_ref": provider_ref,
        "target_content_sha256": target_content_sha256,
        "records_read": len(rows),
        "records_inserted": len(rows),
        "records_updated": 0,
        "records_deleted": 0,
        "records_output": len(rows),
        "committed_by": run_actor,
        "committed_at": committed_at,
    }
    commit = SourceSyncCommit(
        **commit_values,
        previous_cursor_sha256=canonical_json_fingerprint(previous_cursor),
        next_cursor_sha256=canonical_json_fingerprint(next_cursor),
        commit_sha256=source_sync_commit_fingerprint(**commit_values),
    )
    governance_evidence = _commit_governance_evidence(
        tenant_id=definition.tenant_id,
        sync_commit_id=commit.sync_commit_id,
        target_resource_version_id=target_version_id,
        output_artifact_id=output_artifact_id,
        quality_result_ids=(quality.quality_result_id,),
        lineage_event_id=lineage_event_id,
        metadata_change_id=metadata_change_id,
    )
    quarantine_evidence = _quarantine_evidence(
        tenant_id=definition.tenant_id,
        sync_commit_id=commit.sync_commit_id,
        source_slice_sha256=source_snapshot_sha256,
        quarantine_resource_version_id=quarantine_version_id,
        quarantine_artifact_id=quarantine_artifact_id,
        records_rejected=0,
        reason_counts={},
    )
    commit_write = authority.commit(
        commit,
        governance_evidence=governance_evidence,
        quarantine_evidence=quarantine_evidence,
    )
    replay_write = authority.commit(
        commit,
        governance_evidence=governance_evidence,
        quarantine_evidence=quarantine_evidence,
    )
    observation_values = {
        "tenant_id": definition.tenant_id,
        "observation_id": uuid5(
            run.run_id, "gda.postgresql_cdc.resnapshot.attempt-observation.v1"
        ),
        "run_id": run.run_id,
        "attempt_no": 1,
        "framework_kind": FrameworkKind.POSTGIS.value,
        "external_namespace": "postgresql-full-resnapshot",
        "external_run_id": str(run.run_id),
        "external_attempt_id": "1",
        "observed_state": "SUCCESS",
        "evidence": {
            "source_snapshot_sha256": source_snapshot_sha256,
            "target_content_sha256": target_content_sha256,
            "source_observation_lsn": source_snapshot["source_observation_lsn"],
            "commit_id": str(commit.sync_commit_id),
        },
        "observed_at": committed_at,
    }
    observation_fingerprint_values = {
        **observation_values,
        "observation_id": str(observation_values["observation_id"]),
        "run_id": str(observation_values["run_id"]),
        "observed_at": committed_at.isoformat().replace("+00:00", "Z"),
    }
    observation = FrameworkAttemptObservation(
        **observation_values,
        observation_sha256=canonical_json_fingerprint(observation_fingerprint_values),
    )
    observation_write = gateway.record_attempt(observation)
    reconciliation_details = {
        "schema": "gda.postgresql_cdc_resnapshot_reconciliation.v1",
        "execution_status": "provider_commit_reconciled",
        "sync_commit_id": str(commit.sync_commit_id),
        "target_content_sha256": target_content_sha256,
        "attempt_observation_id": str(observation.observation_id),
        "dolphinscheduler_finalization": "pending",
    }
    reconciled_run = gateway.get_run(definition.tenant_id, run.run_id)
    for _attempt in range(5):
        if reconciled_run.status.value in {"reconciling", "succeeded"}:
            break
        if reconciled_run.status.value not in {"dispatching", "running"}:
            raise ValueError(
                "resnapshot provider commit requires a dispatching or running Run"
            )
        try:
            reconciled_run = gateway.transition_run(
                definition.tenant_id,
                run.run_id,
                reconciled_run.state_version,
                "reconciling",
                run_actor,
                "PostgreSQL failover resnapshot commit requires workflow finalization",
                details=reconciliation_details,
            )
            break
        except GatewayValidationError:
            reconciled_run = gateway.get_run(definition.tenant_id, run.run_id)
    else:
        raise GatewayValidationError("resnapshot Run could not converge to reconciling")
    checkpoint = authority.get_checkpoint(
        definition.tenant_id, definition.sync_definition_version_id
    )
    commits = authority.commits(
        definition.tenant_id, definition.sync_definition_version_id
    )
    return {
        "source_snapshot_sha256": source_snapshot_sha256,
        "target_content_sha256": target_content_sha256,
        "row_count": len(rows),
        "target_resource_version_id": str(target_version_id),
        "source_resource_version_id": str(source_version_id),
        "quarantine_resource_version_id": str(quarantine_version_id),
        "output_artifact": output_artifact.model_dump(mode="json"),
        "quality_result": quality.model_dump(mode="json"),
        "lineage_event": lineage.model_dump(mode="json"),
        "metadata_change_id": str(metadata_change_id),
        "commit": commit.model_dump(mode="json"),
        "commit_created": commit_write.created,
        "replay_created": replay_write.created,
        "observation": observation.model_dump(mode="json"),
        "observation_created": observation_write.created,
        "run": reconciled_run.model_dump(mode="json"),
        "checkpoint": checkpoint.model_dump(mode="json"),
        "commits": [item.model_dump(mode="json") for item in commits],
        "finalization_status": "pending_dolphinscheduler_execution",
    }


def _certify(
    engine,
    args: argparse.Namespace,
    *,
    namespace: str,
    token: str,
    work_dir: Path,
    connector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    now = datetime.now(UTC).replace(microsecond=0)
    plan = build_cdc_plan(args.source)
    platform_definition_id = uuid4()
    sync_definition_version_id = uuid4()
    run_id = uuid4()
    gateway = PlatformGateway(engine)
    authority = SourceSyncAuthority(engine)
    gateway.register_definition(
        _definition_registration(
            "local-dev", platform_definition_id, namespace, now
        )
    )
    failover_policy = {
        "schema": "gda.postgres_cdc_failover_admission_policy.v1",
        "require_same_system_identifier": True,
        "require_timeline_increment": True,
        "require_exact_mutation_replay": True,
        "require_primary_fencing": True,
        "require_logical_slot_continuity": True,
        "on_missing_continuity": "reject_fail_closed",
    }
    definition = _sync_definition(
        sync_definition_version_id=sync_definition_version_id,
        platform_definition_version_id=platform_definition_id,
        namespace=namespace,
        source_slice_sha256=plan["source_slice_sha256"],
        connector=connector,
        flink_image=args.flink_image,
        flink_image_id=docker_image_id(
            args.flink_image, timeout=args.timeout_seconds
        ),
        job_source_sha256=_sha256_file(JAVA_SOURCE),
        created_at=now,
        additional_config={"failover_admission_policy": failover_policy},
    )
    initial_cursor = {"change_set_sequence": 0, "source_slice_sha256": None}
    definition_write = authority.create_definition(
        definition,
        owner_ref="team:data-platform",
        initial_cursor=initial_cursor,
    )
    running = _submit_run(
        gateway,
        _run(
            "local-dev",
            run_id,
            platform_definition_id,
            now,
            sequence=f"{namespace}:physical-failover-negative",
        ),
    )
    preflight = authority.find_source_slice_commit(
        "local-dev",
        sync_definition_version_id,
        previous_cursor=initial_cursor,
        next_cursor={
            "change_set_sequence": 1,
            "source_slice_sha256": plan["source_slice_sha256"],
        },
        source_slice_sha256=plan["source_slice_sha256"],
    )
    provider, provider_cleanup = run_failover_provider(
        args=args,
        work_dir=work_dir,
        token=token,
        plan=plan,
        connector=connector,
    )
    admission = provider["failover"]["admission"]
    if provider["status"] != "passed" or admission["admitted"]:
        failed_provider_checks = sorted(
            name for name, passed in provider["checks"].items() if not passed
        )
        raise RuntimeError(
            "PostgreSQL failover provider did not produce expected rejection: "
            f"failed_checks={failed_provider_checks}, "
            f"reason_codes={admission['reason_codes']}"
        )
    failed_run = gateway.transition_run(
        "local-dev",
        run_id,
        running.state_version,
        "failed",
        WORKLOAD,
        "logical replication slot continuity missing after physical failover",
        details={
            "schema": admission["schema"],
            "disposition": admission["disposition"],
            "reason_codes": admission["reason_codes"],
            "system_identifier": admission["system_identifier"],
            "original_timeline_id": admission["original_timeline_id"],
            "promoted_timeline_id": admission["promoted_timeline_id"],
        },
    )
    checkpoint = authority.get_checkpoint(
        "local-dev", sync_definition_version_id
    )
    primary_slot = provider["failover"]["primary_slot"]
    promoted_slot = provider["failover"]["promoted_slot"]
    primary_identity = provider["failover"]["primary_identity"]
    controller_observation = build_slot_continuity_observation(
        tenant_id="local-dev",
        sync_definition_urn=definition.sync_definition_urn,
        sync_definition_version_id=sync_definition_version_id,
        checkpoint_state_version=checkpoint.state_version,
        checkpoint_cursor=checkpoint.cursor,
        original_slot=primary_slot,
        current_slot=promoted_slot,
        absence_witnessed=promoted_slot.get("exists") is not True,
        observed_at=now,
        original_creation_anchor_lsn=str(
            primary_slot.get("restart_lsn")
            or primary_identity.get("checkpoint_lsn")
            or "0/0"
        ),
    )
    controller_runtime = PostgresqlCdcRecoveryControllerRuntime(gateway)
    controller_decision = controller_runtime.evaluate(
        controller_observation,
        decided_at=now,
    )
    if controller_decision.disposition != "schedule_resnapshot":
        raise RuntimeError(
            "recovery controller did not authorize a governed resnapshot: "
            f"disposition={controller_decision.disposition}, "
            f"reason_codes={controller_decision.reason_codes}"
        )
    provider["failover"]["recovery_controller_observation"] = (
        controller_observation.model_dump(mode="json", by_alias=True)
    )
    provider["failover"]["recovery_controller_decision"] = (
        controller_decision.model_dump(mode="json", by_alias=True)
    )
    recovery_plan = build_postgresql_cdc_failover_recovery_plan(
        tenant_id="local-dev",
        sync_definition_urn=definition.sync_definition_urn,
        sync_definition_version_id=sync_definition_version_id,
        source_resource_urn=definition.source_resource_urn,
        target_resource_urn=definition.target_resource_urn,
        checkpoint_state_version=checkpoint.state_version,
        checkpoint_cursor=checkpoint.cursor,
        admission=admission,
        admission_evidence=provider["failover"],
        created_by=WORKLOAD,
        created_at=now,
    )
    commits = authority.commits("local-dev", sync_definition_version_id)
    success_counts = _success_evidence_counts(
        engine,
        run_id=run_id,
        sync_definition_version_id=sync_definition_version_id,
        target_urn=definition.target_resource_urn,
    )
    recovery_artifact = build_postgresql_cdc_failover_recovery_artifact(
        recovery_plan,
        run_id=run_id,
    )
    recovery_artifact_write = gateway.record_artifact(recovery_artifact)
    recovery_artifact_replay = gateway.record_artifact(recovery_artifact)
    recovery_controller_artifact_write = controller_runtime.record_evidence(
        controller_observation,
        controller_decision,
        recovery_plan_sha256=recovery_plan.plan_sha256,
        run_id=run_id,
    )
    recovery_controller_artifact_replay = controller_runtime.record_evidence(
        controller_observation,
        controller_decision,
        recovery_plan_sha256=recovery_plan.plan_sha256,
        run_id=run_id,
    )
    recovery_controller_artifact = recovery_controller_artifact_write.artifact
    recovery_controller_record = gateway.get_postgresql_cdc_recovery_observation(
        "local-dev", recovery_controller_artifact.artifact_id
    )
    resnapshot_platform_definition_id = uuid4()
    resnapshot_definition_version_id = uuid4()
    resnapshot_namespace = f"{namespace}-resnapshot"
    resnapshot_definition = build_postgresql_cdc_failover_resnapshot_definition(
        definition,
        recovery_plan,
        sync_definition_urn=(
            f"gda://local-dev/sync_definition/{resnapshot_namespace}"
        ),
        sync_definition_version_id=resnapshot_definition_version_id,
        platform_definition_version_id=resnapshot_platform_definition_id,
        created_by=WORKLOAD,
        created_at=now,
    )
    source_snapshot = provider["failover"]["resnapshot_source"]
    source_snapshot_sha256 = source_snapshot["source_snapshot_sha256"]
    source_resource_version_id = _resnapshot_source_version_id(
        resnapshot_definition, source_snapshot_sha256
    )
    _register_resource_version(
        gateway,
        tenant_id="local-dev",
        resource_urn=resnapshot_definition.source_resource_urn,
        resource_version_id=source_resource_version_id,
        content_sha256=source_snapshot_sha256,
        created_at=now,
    )
    profile_path = Path(args.dolphinscheduler_profile).resolve(strict=True)
    profile = _dolphinscheduler_profile(profile_path)
    executor_token_path = Path(args.dolphinscheduler_executor_token).resolve(strict=True)
    executor_token = executor_token_path.read_text(encoding="utf-8").strip()
    executor_context: dict[str, Any] = {}
    executor_server, executor_thread, executor_port = _start_resnapshot_executor(
        token=executor_token,
        context=executor_context,
    )
    try:
        with DolphinSchedulerClient(profile) as client:
            deployment = _deploy_resnapshot_dolphinscheduler_workflow(
                gateway=gateway,
                client=client,
                profile=profile,
                source_definition=resnapshot_definition,
                definition_version_id=resnapshot_platform_definition_id,
                source_resource_version_id=source_resource_version_id,
                source_snapshot_sha256=source_snapshot_sha256,
                target_content_sha256=source_snapshot_sha256,
                recovery_plan_sha256=recovery_plan.plan_sha256,
                namespace=resnapshot_namespace,
                executor_port=executor_port,
                created_at=now,
            )
            resnapshot_definition_write = authority.create_definition(
                resnapshot_definition,
                owner_ref="team:data-platform",
                initial_cursor={},
            )
            recovery_schedule_spec = _resnapshot_recovery_schedule_spec(
                definition_version_id=resnapshot_platform_definition_id,
                source_resource_version_id=source_resource_version_id,
                binding_artifact_id=deployment["binding_artifact"].artifact_id,
                compiled_sha256=deployment["compiled"].compiled_sha256,
                namespace=resnapshot_namespace,
                recovery_plan_sha256=recovery_plan.plan_sha256,
                created_at=now,
            )
            expected_run_id = dataops_schedule_run_id(recovery_schedule_spec)
            schedule = gateway.submit_schedule_window(recovery_schedule_spec)
            if schedule.run.run_id != expected_run_id:
                raise RuntimeError(
                    "automatic resnapshot Run id drifted from recovery schedule identity"
                )
            resnapshot_run_id = schedule.run.run_id
            resnapshot_admission = build_postgresql_cdc_failover_resnapshot_admission(
                recovery_plan,
                resnapshot_definition,
                new_run_id=resnapshot_run_id,
                admitted_by=DOLPHINSCHEDULER_WORKLOAD,
                admitted_at=schedule.admitted_at,
            )
            resnapshot_admission_artifact = (
                build_postgresql_cdc_failover_resnapshot_admission_artifact(
                    resnapshot_admission
                )
            )
            resnapshot_admission_artifact_write = gateway.record_artifact(
                resnapshot_admission_artifact
            )
            resnapshot_admission_artifact_replay = gateway.record_artifact(
                resnapshot_admission_artifact
            )
            executor_context.update(
                {
                    "gateway": gateway,
                    "authority": authority,
                    "definition": resnapshot_definition,
                    "admission": resnapshot_admission,
                    "run_id": resnapshot_run_id,
                    "source_snapshot": source_snapshot,
                    "source_resource_version_id": source_resource_version_id,
                    "source_snapshot_sha256": source_snapshot_sha256,
                    "target_content_sha256": source_snapshot_sha256,
                    "created_at": now,
                }
            )
            executor_probe = _probe_resnapshot_executor_from_dolphinscheduler(
                container=args.dolphinscheduler_container,
                port=executor_port,
            )
            resnapshot_provider = _dispatch_resnapshot_and_wait(
                gateway=gateway,
                client=client,
                profile=profile,
                run_id=resnapshot_run_id,
                binding_artifact_id=deployment["binding_artifact"].artifact_id,
                command_id=schedule.command.command_id,
                timeout_seconds=args.dolphinscheduler_timeout_seconds,
                executor_context=executor_context,
            )
            resnapshot_execution = executor_context.get("execution")
            if not isinstance(resnapshot_execution, dict):
                raise RuntimeError(
                    "DolphinScheduler reported success without a resnapshot executor result"
                )
            resnapshot_finalization = _finalize_resnapshot_run(
                gateway=gateway,
                run_id=resnapshot_run_id,
                success_observation_id=(
                    resnapshot_provider["success_observation"].observation_id
                ),
                execution=resnapshot_execution,
            )
    finally:
        _stop_resnapshot_executor(executor_server, executor_thread)
    resnapshot_running = schedule.run
    resnapshot_provider_run = resnapshot_execution["run"]
    resnapshot_final_run = resnapshot_finalization["run"].model_dump(mode="json")
    resnapshot_checkpoint = resnapshot_execution["checkpoint"]
    resnapshot_commits = resnapshot_execution["commits"]
    checks = {
        "failover_policy_bound_to_definition_and_checkpoint_zero": (
            definition_write.created
            and definition.config["failover_admission_policy"] == failover_policy
            and definition_write.checkpoint.state_version == 0
            and definition_write.checkpoint.cursor == initial_cursor
        ),
        "provider_preflight_was_empty": preflight is None,
        "physical_postgresql_failover_negative_provider_passed": all(
            provider["checks"].values()
        ),
        "missing_promoted_logical_slot_rejected_fail_closed": (
            not admission["admitted"]
            and admission["disposition"] == "rejected_fail_closed"
            and admission["reason_codes"]
            == ["logical_replication_slot_missing_after_promotion"]
        ),
        "primary_fencing_evidence_passed": provider["checks"][
            "primary_fencing_was_observed_before_promotion"
        ],
        "source_sync_checkpoint_remained_zero": (
            checkpoint.state_version == 0
            and checkpoint.cursor == initial_cursor
            and checkpoint.last_sync_commit_id is None
        ),
        "recovery_plan_preserved_rejected_boundary": (
            recovery_plan.recovery_mode == "resnapshot_and_reconcile"
            and recovery_plan.cursor_disposition == "do_not_advance"
            and recovery_plan.requires_new_run is True
            and recovery_plan.checkpoint_state_version == checkpoint.state_version
            and recovery_plan.checkpoint_cursor == checkpoint.cursor
            and recovery_plan.admission_reason_codes
            == tuple(admission["reason_codes"])
        ),
        "recovery_controller_decision_bound_before_schedule": (
            controller_decision.disposition == "schedule_resnapshot"
            and controller_decision.checkpoint_action == "preserve_and_resnapshot"
            and controller_decision.requires_new_run is True
            and controller_decision.observation_sha256
            == controller_observation.observation_sha256
            and controller_observation.checkpoint_state_version
            == recovery_plan.checkpoint_state_version
            and controller_observation.checkpoint_cursor
            == recovery_plan.checkpoint_cursor
            and provider["failover"]["recovery_controller_decision"][
                "decision_sha256"
            ]
            == controller_decision.decision_sha256
        ),
        "recovery_controller_evidence_recorded_idempotently": (
            recovery_controller_artifact_write.created is True
            and recovery_controller_artifact_replay.created is False
            and recovery_controller_artifact_write.ledger_created is True
            and recovery_controller_artifact_replay.ledger_created is False
            and recovery_controller_artifact_replay.artifact == recovery_controller_artifact
            and recovery_controller_artifact.artifact_role is ArtifactRole.EVIDENCE
            and recovery_controller_artifact.run_id == run_id
            and recovery_controller_artifact.resource_version_id
            == sync_definition_version_id
            and recovery_controller_artifact.manifest["recovery_plan_sha256"]
            == recovery_plan.plan_sha256
            and recovery_controller_artifact.manifest["decision"]["decision_sha256"]
            == controller_decision.decision_sha256
        ),
        "recovery_controller_observation_ledger_projection": (
            recovery_controller_record.artifact_id == recovery_controller_artifact.artifact_id
            and recovery_controller_record.observation_sha256
            == controller_observation.observation_sha256
            and recovery_controller_record.decision_sha256
            == controller_decision.decision_sha256
            and recovery_controller_record.recovery_plan_sha256
            == recovery_plan.plan_sha256
            and recovery_controller_record.checkpoint_state_version
            == controller_observation.checkpoint_state_version
            and recovery_controller_record.checkpoint_cursor
            == controller_observation.checkpoint_cursor
            and recovery_controller_record.disposition
            == controller_decision.disposition
        ),
        "recovery_plan_recorded_as_idempotent_evidence": (
            recovery_artifact_write.created is True
            and recovery_artifact_replay.created is False
            and recovery_artifact_replay.value == recovery_artifact
            and recovery_artifact.artifact_role is ArtifactRole.EVIDENCE
            and recovery_artifact.run_id == run_id
            and recovery_artifact.resource_version_id == sync_definition_version_id
        ),
        "resnapshot_admission_created_new_full_definition": (
            resnapshot_definition_write.created
            and resnapshot_definition.sync_definition_version_id
            != sync_definition_version_id
            and resnapshot_definition.mode.value == "full"
            and resnapshot_definition.write_disposition.value == "overwrite"
            and resnapshot_definition.cursor_kind.value == "none"
            and resnapshot_definition.delete_mode.value == "ignore"
            and resnapshot_definition.governance_contract is not None
            and resnapshot_definition.governance_contract.capture_kind.value == "batch"
        ),
        "resnapshot_admission_bound_new_run_without_old_cursor_advance": (
            resnapshot_admission.new_run_id == resnapshot_run_id
            and resnapshot_admission.previous_sync_definition_version_id
            == sync_definition_version_id
            and checkpoint.state_version == 0
            and checkpoint.cursor == initial_cursor
            and resnapshot_checkpoint["state_version"] == 1
            and resnapshot_checkpoint["cursor"]["snapshot_sha256"]
            == resnapshot_execution["target_content_sha256"]
        ),
        "resnapshot_run_source_binding_frozen_before_dispatch": (
            any(
                binding.binding_name == "source"
                and binding.resource_version_id == source_resource_version_id
                for binding in resnapshot_running.input_bindings
            )
            and UUID(resnapshot_execution["source_resource_version_id"])
            == source_resource_version_id
        ),
        "resnapshot_admission_recorded_as_idempotent_evidence": (
            resnapshot_admission_artifact_write.created is True
            and resnapshot_admission_artifact_replay.created is False
            and resnapshot_admission_artifact_replay.value
            == resnapshot_admission_artifact
            and resnapshot_admission_artifact.run_id == resnapshot_run_id
            and resnapshot_admission_artifact.resource_version_id
            == resnapshot_definition_version_id
        ),
        "resnapshot_recovery_schedule_triggered_automatically": (
            schedule.invocation.trigger_kind == "schedule"
            and schedule.invocation.requested_by == DOLPHINSCHEDULER_WORKLOAD
            and schedule.invocation.schedule_ref
            == (
                "gda://local-dev/recovery/postgresql-cdc-failover/"
                f"{resnapshot_namespace}/{recovery_plan.plan_sha256}"
            )
            and schedule.run.subject_context.delegated_by is None
            and schedule.command.actor_subject == DOLPHINSCHEDULER_WORKLOAD
            and schedule.run_created is True
            and schedule.command_created is True
        ),
        "resnapshot_provider_commit_reconciled": (
            resnapshot_provider_run["status"] == "reconciling"
            and resnapshot_execution["commit_created"] is True
            and resnapshot_execution["replay_created"] is False
            and len(resnapshot_commits) == 1
            and resnapshot_execution["observation_created"] is True
        ),
        "real_dolphinscheduler_dispatch_and_success_observed": (
            resnapshot_provider["provider_state"] == "SUCCESS"
            and resnapshot_provider["workflow_instance_id"] > 0
            and resnapshot_provider["success_observation"].framework_kind.value
            == "dolphinscheduler"
            and resnapshot_provider["success_observation"].observed_state == "success"
            and resnapshot_provider["outbox"].claimed == 1
            and resnapshot_provider["outbox"].completed == 1
        ),
        "resnapshot_run_finalized_with_success_evidence": (
            resnapshot_final_run["status"] == "succeeded"
            and resnapshot_finalization["before"].status.value == "reconciling"
            and resnapshot_finalization["evidence"].run_id == resnapshot_run_id
        ),
        "old_source_sync_commit_history_remained_empty": len(commits) == 0,
        "no_provider_success_evidence_fabricated": all(
            value == 0 for value in success_counts.values()
        ),
        "platform_run_failed_with_no_success_admission": (
            failed_run.status.value == "failed"
            and failed_run.state_version == running.state_version + 1
        ),
        "post_failover_physical_sink_remained_stable": provider["checks"][
            "post_promotion_probe_advanced_source_but_not_sink"
        ],
    }
    return (
        {
            "schema": (
                "gda.chongqing_osm_postgres_cdc_physical_failover."
                "negative_acceptance.v1"
            ),
            "status": "passed" if all(checks.values()) else "failed",
            "expected_outcome": "rejected_fail_closed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "source_slice_sha256": plan["source_slice_sha256"],
            },
            "provider": provider,
            "authority": {
                "sync_definition_version_id": str(sync_definition_version_id),
                "run": failed_run.model_dump(mode="json"),
                "checkpoint": checkpoint.model_dump(mode="json"),
                "recovery_controller": {
                    "observation": controller_observation.model_dump(
                        mode="json", by_alias=True
                    ),
                    "decision": controller_decision.model_dump(
                        mode="json", by_alias=True
                    ),
                    "artifact": {
                    "artifact": recovery_controller_artifact.model_dump(
                        mode="json"
                    ),
                        "created": recovery_controller_artifact_write.created,
                        "replay_created": recovery_controller_artifact_replay.created,
                        "ledger_created": recovery_controller_artifact_write.ledger_created,
                        "ledger_replay_created": recovery_controller_artifact_replay.ledger_created,
                    },
                    "ledger": recovery_controller_record.model_dump(mode="json"),
                },
                "recovery_plan": recovery_plan.model_dump(mode="json"),
                "recovery_artifact": {
                    "artifact": recovery_artifact.model_dump(mode="json"),
                    "created": recovery_artifact_write.created,
                    "replay_created": recovery_artifact_replay.created,
                },
                "resnapshot_admission": {
                    "definition": resnapshot_definition.model_dump(mode="json"),
                    "definition_write_created": resnapshot_definition_write.created,
                    "run": resnapshot_execution["run"],
                    "checkpoint": resnapshot_checkpoint,
                    "admission": resnapshot_admission.model_dump(mode="json"),
                    "artifact": resnapshot_admission_artifact.model_dump(mode="json"),
                    "artifact_created": resnapshot_admission_artifact_write.created,
                    "artifact_replay_created": resnapshot_admission_artifact_replay.created,
                    "automatic_trigger": {
                        "trigger_kind": schedule.invocation.trigger_kind,
                        "requested_by": schedule.invocation.requested_by,
                        "schedule_ref": schedule.invocation.schedule_ref,
                        "window_sha256": schedule.window_sha256,
                        "scheduled_for": schedule.invocation.schedule_times[
                            0
                        ].isoformat().replace("+00:00", "Z"),
                        "run_created": schedule.run_created,
                        "command_created": schedule.command_created,
                    },
                    "execution": resnapshot_execution,
                    "commits": resnapshot_commits,
                    "dolphinscheduler": {
                        "definition_version_id": str(
                            resnapshot_platform_definition_id
                        ),
                        "definition_sha256": deployment[
                            "definition"
                        ].definition_sha256,
                        "compiled_sha256": deployment["compiled"].compiled_sha256,
                        "workflow_definition_code": deployment[
                            "binding"
                        ].workflow_definition_code,
                        "workflow_definition_version": deployment[
                            "binding"
                        ].workflow_definition_version,
                        "binding_artifact_id": str(
                            deployment["binding_artifact"].artifact_id
                        ),
                        "workflow_created": deployment["workflow_created"],
                        "executor_probe": executor_probe,
                        "provider": {
                            "provider_state": resnapshot_provider["provider_state"],
                            "workflow_instance_id": resnapshot_provider[
                                "workflow_instance_id"
                            ],
                            "success_observation": resnapshot_provider[
                                "success_observation"
                            ].model_dump(mode="json"),
                            "observation_created": resnapshot_provider[
                                "observation_created"
                            ],
                            "outbox_claimed": resnapshot_provider["outbox"].claimed,
                            "outbox_completed": resnapshot_provider[
                                "outbox"
                            ].completed,
                        },
                        "finalization": {
                            "before": resnapshot_finalization[
                                "before"
                            ].model_dump(mode="json"),
                            "run": resnapshot_finalization["run"].model_dump(
                                mode="json"
                            ),
                            "evidence": resnapshot_finalization[
                                "evidence"
                            ].model_dump(mode="json"),
                        },
                    },
                },
                "commits": [],
                "success_evidence_counts": success_counts,
                "failover_admission_policy": failover_policy,
                "diagnostic_provider_invocations": 2,
                "successful_provider_admissions": 1,
            },
            "not_claimed": [
                "automatic logical replication slot synchronization or repair",
                "automatic CDC resume after PostgreSQL promotion",
                "production RPO, RTO, throughput, or freshness SLO",
                "multi-cluster high availability or Kubernetes recovery",
                "external durable event boundary or distributed exactly-once commit",
            ],
        },
        provider_cleanup,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postgres-url", default="postgresql://127.0.0.1:5433/gis_agent"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--connector", type=Path, default=DEFAULT_CONNECTOR)
    parser.add_argument("--flink-image", default=DEFAULT_FLINK_IMAGE)
    parser.add_argument("--jdk-image", default=DEFAULT_JDK_IMAGE)
    parser.add_argument("--java-home", default=DEFAULT_JAVA_HOME)
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--docker-network", default=DEFAULT_NETWORK)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--primary-stop-timeout-seconds", type=int, default=30)
    parser.add_argument("--promotion-timeout-seconds", type=int, default=60)
    parser.add_argument(
        "--post-failover-observation-seconds", type=float, default=2.0
    )
    parser.add_argument(
        "--dolphinscheduler-profile",
        type=Path,
        default=DEFAULT_DOLPHINSCHEDULER_PROFILE,
    )
    parser.add_argument(
        "--dolphinscheduler-executor-token",
        type=Path,
        default=DEFAULT_DOLPHINSCHEDULER_EXECUTOR_TOKEN,
    )
    parser.add_argument(
        "--dolphinscheduler-container", default=DOLPHINSCHEDULER_CONTAINER
    )
    parser.add_argument(
        "--dolphinscheduler-timeout-seconds", type=int, default=180
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if not 10 <= args.primary_stop_timeout_seconds <= 60:
        parser.error("--primary-stop-timeout-seconds must be between 10 and 60")
    if not 10 <= args.promotion_timeout_seconds <= 120:
        parser.error("--promotion-timeout-seconds must be between 10 and 120")
    if not 1.0 <= args.post_failover_observation_seconds <= 10.0:
        parser.error(
            "--post-failover-observation-seconds must be between 1 and 10"
        )
    if not 30 <= args.dolphinscheduler_timeout_seconds <= 900:
        parser.error("--dolphinscheduler-timeout-seconds must be between 30 and 900")

    connector = verify_connector_artifact(args.connector)
    settings = _settings()
    admin_auth = {
        "type": "basic",
        "username": settings.get("POSTGRES_USER", "postgres"),
        "password": settings.get(
            "POSTGRES_ADMIN_PASSWORD",
            settings.get("POSTGRES_PASSWORD", "postgres"),
        ),
    }
    admin_url = _connection_url(args.postgres_url, admin_auth)
    token = secrets.token_hex(5)
    namespace = f"chongqing_osm_cdc_failover_{token}"
    work_dir = REPO_ROOT / ".tmp/source-sync-certification" / namespace
    sandbox = _PostgresDatabaseSandbox(admin_url)
    report: dict[str, Any] | None = None
    error: str | None = None
    cleanup: dict[str, bool] = {}
    main_counts_before = main_sync_counts(admin_url)
    work_dir.mkdir(parents=True, exist_ok=False)
    try:
        sandbox.setup()
        if sandbox.engine is None:
            raise RuntimeError("certification control database engine was not created")
        with sandbox.engine.begin() as connection:
            connection.execute(
                text(RECOVERY_CONTROLLER_MIGRATION.read_text(encoding="utf-8"))
            )
        report, provider_cleanup = _certify(
            sandbox.engine,
            args,
            namespace=namespace,
            token=token,
            work_dir=work_dir,
            connector=connector,
        )
        cleanup.update(provider_cleanup)
        report["sandbox"] = {"database": sandbox.database, "persistent": False}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup.update(sandbox.cleanup())
        shutil.rmtree(work_dir)
        cleanup["work_directory_removed"] = not work_dir.exists()
        cleanup["primary_container_removed"] = _container_absent(
            f"gda-cdc-pg-{token}"
        )
        cleanup["flink_container_removed"] = _container_absent(
            f"gda-cdc-flink-{token}"
        )
        cleanup["standby_container_removed"] = _container_absent(
            f"gda-cdc-standby-{token}"
        )
        cleanup["standby_volume_removed"] = _docker_volume_absent(
            f"gda-cdc-standby-data-{token}"
        )
    main_counts_after = main_sync_counts(admin_url)
    cleanup["main_sync_tables_unchanged_empty"] = (
        main_counts_before == (0, 0, 0) and main_counts_after == (0, 0, 0)
    )
    if report is None:
        report = {
            "schema": (
                "gda.chongqing_osm_postgres_cdc_physical_failover."
                "negative_acceptance.v1"
            ),
            "status": "failed",
            "expected_outcome": "rejected_fail_closed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    if not cleanup or not all(cleanup.values()):
        report["status"] = "failed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "expected_outcome": report["expected_outcome"],
                "report": str(args.report),
                "checks": report["checks"],
                "cleanup": cleanup,
                "error": report.get("error"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
