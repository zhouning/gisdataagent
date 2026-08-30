#!/usr/bin/env python3
"""Certify Flink/Iceberg cancellation and uncertain-commit reconciliation."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import boto3
from sqlalchemy import text

from data_agent.agentops_contracts import AgentSideEffect
from data_agent.agentops_flink_provider import FlinkProviderCancellationAdapter
from data_agent.agentops_temporal_contracts import (
    TemporalActivityRequest,
    TemporalProviderExecutionSpec,
    derive_temporal_activity_id,
    temporal_contract_fingerprint,
)
from data_agent.connectors.database import _connection_url
from data_agent.iceberg_commit_reconciliation import (
    IcebergCommitIntent,
    IcebergSnapshotEvidence,
    reconcile_iceberg_commit,
)
from data_agent.platform_contracts import (
    SourceSyncCommit,
    SourceSyncDefinitionVersion,
    SubjectContext,
    SubjectType,
    canonical_json_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_definition_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway
from data_agent.source_sync_authority import SourceSyncAuthority
from scripts.certify_chongqing_osm_flink_iceberg_interop import (
    BUCKET,
    DEFAULT_FLINK_IMAGE,
    DEFAULT_JAVA_HOME,
    DEFAULT_JDK_IMAGE,
    DEFAULT_NETWORK,
    DEFAULT_SOURCE,
    DEFAULT_SOURCE_PRODUCT_SHA256,
    DEFAULT_SPARK_IMAGE,
    FLINK_AWS,
    FLINK_ICEBERG,
    HADOOP_CLIENT_API,
    HADOOP_CLIENT_RUNTIME,
    POSTGRES_JDBC,
    FlinkIcebergSandbox,
    IcebergCatalogSandbox,
    _cleanup_prefix,
    _object_inventory,
    _run_command,
    _spark_artifacts,
    verify_artifact,
)
from scripts.certify_chongqing_osm_flink_iceberg_recovery import (
    build_recovery_plan,
    render_recovery_input,
)
from scripts.certify_chongqing_osm_flink_stream import (
    REPO_ROOT,
    _canonical_sha256,
    _sha256_file,
    compile_flink_job,
    docker_image_id,
)
from scripts.certify_chongqing_osm_incremental_sync import _main_sync_counts
from scripts.certify_source_sync_authority import (
    WORKLOAD,
    _definition_registration,
    _PostgresDatabaseSandbox,
    _run,
    _settings,
    _submit_run,
)

JAVA_SOURCE = REPO_ROOT / "scripts/flink/ChongqingOsmIcebergReconciliationJob.java"
MAIN_CLASS = "ChongqingOsmIcebergReconciliationJob"
SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_reconciliation"
DATA_PRODUCT_MIGRATION = REPO_ROOT / "data_agent/migrations/100_data_product_registry.sql"
DEFAULT_REPORT = (
    REPO_ROOT / ".tmp/source-sync-certification/"
    "chongqing-osm-flink-iceberg-reconciliation-report.json"
)
JOB_ID_RE = re.compile(r"Job has been submitted with JobID ([0-9a-f]{32})")
CHECKPOINT_RE = re.compile(
    r"GDA_ICEBERG_RECONCILE_CHECKPOINT_COMPLETED "
    r"token=([0-9a-f]{64}) id=(\d+) offset=(\d+)"
)


def _flink_cancellation_request(job_id: str) -> tuple[TemporalActivityRequest, str, str]:
    """Build the immutable AgentOps identity used by the live Flink adapter probe."""

    run_id = uuid5(NAMESPACE_URL, f"gda-flink-agentops-run:{job_id}")
    step_id = uuid5(NAMESPACE_URL, f"gda-flink-agentops-step:{job_id}")
    tool_call_id = uuid5(NAMESPACE_URL, f"gda-flink-agentops-tool:{job_id}")
    activity_id = derive_temporal_activity_id(
        run_id=run_id,
        tool_call_id=tool_call_id,
        attempt_no=1,
    )
    spec_values: dict[str, Any] = {
        "provider_ref": "provider:flink",
        "operation_ref": "flink.iceberg.reconciliation.v1",
        "parameters": {"job_id": job_id},
        "input_artifact_ids": (),
        "output_media_type": "application/json",
    }
    spec_values["spec_sha256"] = temporal_contract_fingerprint(
        TemporalProviderExecutionSpec.schema_id, spec_values, "spec_sha256"
    )
    spec = TemporalProviderExecutionSpec(**spec_values)
    workflow_id = f"flink-agentops-{job_id[:16]}"
    subject = SubjectContext(
        tenant_id="local-dev",
        subject_id="workload:agentops-flink-certifier",
        subject_type=SubjectType.WORKLOAD,
        purpose="agentops-flink-provider-cancellation-certification",
    )
    values: dict[str, Any] = {
        "tenant_id": "local-dev",
        "workflow_id": workflow_id,
        "run_id": run_id,
        "step_id": step_id,
        "tool_call_id": tool_call_id,
        "activity_id": activity_id,
        "attempt_no": 1,
        "tool_ref": "tool:flink.cancel.v1",
        "capability_ref": "capability:flink.provider_cancel.v1",
        "policy_decision_ref": "policy:local-dev:flink-provider-cancel",
        "subject_context": subject,
        "side_effect": AgentSideEffect.EXTERNAL_WRITE,
        "idempotency_key": f"agentops:flink-cancel:{job_id}",
        "input_artifact_ids": (),
        "provider_spec": spec,
    }
    values["request_sha256"] = temporal_contract_fingerprint(
        TemporalActivityRequest.schema_id, values, "request_sha256"
    )
    request = TemporalActivityRequest(**values)
    operation_ref = f"{spec.operation_ref}://{request.activity_id}"
    receipt_ref = f"flink://job/{job_id}"
    return request, operation_ref, receipt_ref


def build_reconciliation_plan(source_path: Path) -> dict[str, Any]:
    seed = build_recovery_plan(source_path, commit_tag="0" * 64)
    plan = build_recovery_plan(
        source_path,
        commit_tag=seed["source_slice_sha256"],
    )
    baseline = [
        {**row, "stream_event_id": None, "flink_commit_tag": None} for row in plan["baseline_rows"]
    ]
    return {
        **plan,
        "schema": "gda.chongqing_osm_flink_iceberg_reconciliation_plan.v1",
        "baseline_rows": baseline,
        "baseline_content_sha256": _canonical_sha256(baseline),
    }


def _spark_phase(
    args: argparse.Namespace,
    *,
    phase: str,
    plan_path: Path,
    report_path: Path,
    warehouse_uri: str,
    table: str,
    access_key: str,
    secret_key: str,
    catalog_uri: str,
    catalog_user: str,
    catalog_password: str,
    baseline_snapshot_id: str | None = None,
) -> dict[str, Any]:
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        args.docker_network,
        "-e",
        f"JAVA_HOME={args.java_home}",
        "-e",
        f"AWS_ACCESS_KEY_ID={access_key}",
        "-e",
        f"AWS_SECRET_ACCESS_KEY={secret_key}",
        "-e",
        "AWS_REGION=us-east-1",
        "-e",
        f"ICEBERG_CATALOG_URI={catalog_uri}",
        "-e",
        f"ICEBERG_CATALOG_USER={catalog_user}",
        "-e",
        f"ICEBERG_CATALOG_PASSWORD={catalog_password}",
        "-v",
        f"{REPO_ROOT}:/workspace",
        "-w",
        "/workspace",
        args.spark_image,
        "python",
        "-m",
        SPARK_MODULE,
        phase,
        "--plan",
        plan_path.relative_to(REPO_ROOT).as_posix(),
        "--report",
        report_path.relative_to(REPO_ROOT).as_posix(),
        "--warehouse-uri",
        warehouse_uri,
        "--table",
        table,
        "--endpoint-url",
        args.container_endpoint_url,
    ]
    if baseline_snapshot_id:
        command.extend(("--baseline-snapshot-id", baseline_snapshot_id))
    _run_command(
        command,
        stage=f"Spark Iceberg reconciliation {phase}",
        timeout=args.timeout_seconds,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("phase") != phase:
        raise RuntimeError(f"Spark Iceberg reconciliation {phase} failed")
    return report


def _flink_job_arguments(
    flink: FlinkIcebergSandbox,
    *,
    jar_path: Path,
    mode: str,
    warehouse_uri: str,
    table: str,
    input_path: Path,
    checkpoint_path: Path,
    catalog_uri: str,
    catalog_user: str,
    commit_token: str,
) -> list[str]:
    return [
        "docker",
        "exec",
        flink.container,
        "flink",
        "run",
        "-p",
        "1",
        f"/workspace/{jar_path.relative_to(REPO_ROOT).as_posix()}",
        "--mode",
        mode,
        "--warehouse-uri",
        warehouse_uri,
        "--endpoint-url",
        flink.args.container_endpoint_url,
        "--catalog-uri",
        catalog_uri,
        "--catalog-user",
        catalog_user,
        "--table",
        table,
        "--input",
        f"/workspace/{input_path.relative_to(REPO_ROOT).as_posix()}",
        "--checkpoints",
        f"file:///workspace/{checkpoint_path.relative_to(REPO_ROOT).as_posix()}",
        "--expected-records",
        "4",
        "--commit-token",
        commit_token,
    ]


def _task_output(flink: FlinkIcebergSandbox) -> str:
    try:
        return flink.task_output()
    except RuntimeError:
        return ""


def _container_state(flink: FlinkIcebergSandbox) -> dict[str, Any]:
    completed = _run_command(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .State}}",
            flink.container,
        ],
        stage="inspect Flink fault-injection container",
        timeout=30,
    )
    return json.loads(completed.stdout)


def _network_contains_container(flink: FlinkIcebergSandbox) -> bool:
    completed = _run_command(
        [
            "docker",
            "network",
            "inspect",
            "--format",
            "{{json .Containers}}",
            flink.args.docker_network,
        ],
        stage="inspect Flink fault-injection network",
        timeout=30,
    )
    containers = json.loads(completed.stdout)
    return any(item.get("Name") == flink.container for item in containers.values())


def _wait_for_marker(
    flink: FlinkIcebergSandbox,
    marker: str,
    *,
    timeout: int,
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        output = _task_output(flink)
        if marker in output:
            return output
        time.sleep(0.25)
    raise RuntimeError("Flink reconciliation marker was not observed")


def _job_state(flink: FlinkIcebergSandbox, job_id: str) -> str:
    completed = _run_command(
        [
            "docker",
            "exec",
            flink.container,
            "curl",
            "-fsS",
            f"http://localhost:8081/jobs/{job_id}",
        ],
        stage="read Flink reconciliation job state",
        timeout=30,
    )
    return str(json.loads(completed.stdout)["state"])


def _cancel_before_checkpoint(
    flink: FlinkIcebergSandbox,
    command: list[str],
    *,
    commit_token: str,
    timeout: int,
    cancellation_adapter: FlinkProviderCancellationAdapter | None = None,
) -> dict[str, Any]:
    detached = [*command[:5], "-d", *command[5:]]
    submitted = _run_command(
        detached,
        stage="submit cancellable Flink Iceberg job",
        timeout=timeout,
    )
    match = JOB_ID_RE.search(submitted.stdout)
    if not match:
        raise RuntimeError("Flink did not return a detached job identity")
    job_id = match.group(1)
    marker = f"GDA_ICEBERG_CANCEL_READY token={commit_token} offset=4"
    before_cancel = _wait_for_marker(flink, marker, timeout=timeout)
    completed_before_cancel = [
        item for item in CHECKPOINT_RE.findall(before_cancel) if item[0] == commit_token
    ]
    provider_cancellation: dict[str, Any] | None = None
    if cancellation_adapter is not None:
        request, operation_ref, receipt_ref = _flink_cancellation_request(job_id)
        observation = cancellation_adapter.request_cancellation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=receipt_ref,
        )
        deadline = time.monotonic() + 60
        while (
            observation.status.value != "confirmed"
            and time.monotonic() < deadline
        ):
            time.sleep(0.25)
            observation = cancellation_adapter.observe_cancellation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
            )
        provider_cancellation = observation.model_dump(mode="json")
        state = _job_state(flink, job_id)
    else:
        _run_command(
            ["docker", "exec", flink.container, "flink", "cancel", job_id],
            stage="cancel Flink Iceberg job",
            timeout=60,
        )
        state = ""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = _job_state(flink, job_id)
        if state in {"CANCELED", "FAILED", "FINISHED"}:
            break
        time.sleep(0.25)
    return {
        "job_id": job_id,
        "terminal_state": state,
        "source_ready_offset": 4,
        "completed_checkpoints_before_cancel": len(completed_before_cancel),
        "provider_cancellation": provider_cancellation,
        "checks": {
            "source_emitted_before_cancel": marker in before_cancel,
            "no_completed_checkpoint_before_cancel": not completed_before_cancel,
            "provider_confirmed_cancelled": state == "CANCELED",
        },
    }


def _run_uncertain_commit(
    flink: FlinkIcebergSandbox,
    command: list[str],
    *,
    commit_token: str,
    timeout: int,
) -> dict[str, Any]:
    completed = _run_command(
        command,
        stage="run unacknowledged Flink Iceberg commit",
        timeout=timeout,
    )
    expected = f"GDA_ICEBERG_RECONCILIATION_JOB_COMPLETED token={commit_token} records=4"
    output = _task_output(flink)
    checkpoints = [
        {"checkpoint_id": int(item[1]), "source_offset": int(item[2])}
        for item in CHECKPOINT_RE.findall(output)
        if item[0] == commit_token
    ]
    finished = f"GDA_ICEBERG_COMMIT_SOURCE_FINISHED token={commit_token} offset=4"
    checks = {
        "provider_process_completed": expected in completed.stdout,
        "terminal_source_checkpoint_completed": any(
            item["source_offset"] == 4 for item in checkpoints
        ),
        "source_finished_after_checkpoint": finished in output,
    }
    return {
        "acknowledgement_delivered_to_control_plane": False,
        "checkpoints": checkpoints,
        "checks": checks,
        "status": "passed" if all(checks.values()) else "failed",
    }


def _run_fault_injected_commit(
    flink: FlinkIcebergSandbox,
    command: list[str],
    *,
    commit_token: str,
    timeout: int,
    fault_mode: str,
) -> dict[str, Any]:
    """Inject a physical provider fault after the terminal checkpoint commits."""

    detached = [*command[:5], "-d", *command[5:]]
    submitted = _run_command(
        detached,
        stage=f"submit Flink Iceberg {fault_mode} fault job",
        timeout=timeout,
    )
    match = JOB_ID_RE.search(submitted.stdout)
    if not match:
        raise RuntimeError("Flink did not return a detached job identity")
    job_id = match.group(1)
    marker = f"GDA_ICEBERG_COMMIT_SOURCE_FINISHED token={commit_token} offset=4"
    before_fault = _wait_for_marker(flink, marker, timeout=timeout)
    checkpoints = [
        {"checkpoint_id": int(item[1]), "source_offset": int(item[2])}
        for item in CHECKPOINT_RE.findall(before_fault)
        if item[0] == commit_token
    ]
    terminal_checkpoint = any(item["source_offset"] == 4 for item in checkpoints)
    if not terminal_checkpoint:
        raise RuntimeError("fault injection window was reached without a terminal checkpoint")

    if fault_mode == "kill":
        _run_command(
            ["docker", "kill", "--signal", "KILL", flink.container],
            stage="inject Flink SIGKILL after Iceberg checkpoint",
            timeout=30,
        )
        state = _container_state(flink)
        fault = {
            "kind": "container_sigkill",
            "signal": "KILL",
            "container_running_after_fault": bool(state.get("Running")),
            "exit_code": int(state.get("ExitCode", -1)),
        }
        injected = not fault["container_running_after_fault"] and fault["exit_code"] == 137
    elif fault_mode == "network":
        _run_command(
            ["docker", "network", "disconnect", flink.args.docker_network, flink.container],
            stage="disconnect Flink from provider network after Iceberg checkpoint",
            timeout=30,
        )
        time.sleep(1)
        fault = {
            "kind": "docker_network_disconnect",
            "network": flink.args.docker_network,
            "container_attached_after_fault": _network_contains_container(flink),
        }
        injected = fault["container_attached_after_fault"] is False
    else:
        raise ValueError(f"unsupported fault mode: {fault_mode}")

    return {
        "job_id": job_id,
        "acknowledgement_delivered_to_control_plane": False,
        "fault_mode": fault_mode,
        "fault": fault,
        "checkpoints": checkpoints,
        "checks": {
            "provider_job_submitted": bool(match),
            "terminal_source_checkpoint_completed": terminal_checkpoint,
            "source_finished_before_fault": marker in before_fault,
            "physical_fault_injected": injected,
        },
        "status": "passed"
        if terminal_checkpoint and marker in before_fault and injected
        else "failed",
    }


def _sync_definition(
    sync_definition_version_id: UUID,
    platform_definition_version_id: UUID,
    namespace: str,
    plan: dict[str, Any],
    args: argparse.Namespace,
    flink_image_id: str,
    created_at: datetime,
) -> SourceSyncDefinitionVersion:
    values: dict[str, Any] = {
        "tenant_id": "local-dev",
        "sync_definition_urn": (
            f"gda://local-dev/sync_definition/flink-iceberg-reconcile-{namespace}"
        ),
        "sync_definition_version_id": sync_definition_version_id,
        "platform_definition_version_id": platform_definition_version_id,
        "source_resource_urn": "gda://local-dev/data_product/chongqing-osm-roads",
        "source_definition_fingerprint": DEFAULT_SOURCE_PRODUCT_SHA256,
        "target_resource_urn": f"gda://local-dev/table/{namespace}",
        "mode": "incremental",
        "write_disposition": "append",
        "cursor_kind": "provider_token",
        "cursor_field": None,
        "primary_keys": (),
        "delete_mode": "ignore",
        "config": {
            "provider": "flink-iceberg",
            "runtime": args.flink_image,
            "runtime_image_id": flink_image_id,
            "source_slice_sha256": plan["source_slice_sha256"],
            "commit_token": plan["commit_tag"],
            "acceptance_scope": "isolated",
        },
        "governance_contract": {
            "schema": "gda.source_sync_governance.v1",
            "target_layer": "ods",
            "data_kind": "vector",
            "capture_kind": "micro_batch",
            "source_adapter": {
                "adapter_id": "flink-iceberg",
                "adapter_version": "certification-v1",
                "adapter_fingerprint": canonical_json_fingerprint(
                    {
                        "runtime_image_id": flink_image_id,
                        "job_source_sha256": _sha256_file(JAVA_SOURCE),
                    }
                ),
            },
            "standard_mapping_contract_id": None,
            "standard_version_id": None,
            "data_model_version_id": None,
            "quality_rule_version_refs": ["quality:iceberg-commit-integrity-v1"],
            "classification_policy_version_ref": "classification:internal-v1",
            "retention_policy_version_ref": "retention:ods-v1",
            "schema_change_policy": "approval_required",
            "promotion_mode": "blocked",
            "quarantine_resource_urn": None,
            "event_time_field": None,
            "watermark_delay_seconds": None,
        },
    }
    return SourceSyncDefinitionVersion(
        **values,
        definition_sha256=source_sync_definition_fingerprint(**values),
        created_by=WORKLOAD,
        created_at=created_at,
    )


def _sync_commit(
    *,
    sync_definition_version_id: UUID,
    run_id: UUID,
    plan: dict[str, Any],
    target_commit_ref: dict[str, str],
    committed_at: datetime,
    sync_commit_id: UUID | None = None,
) -> SourceSyncCommit:
    previous_cursor = {"event_offset": 0, "source_slice_sha256": None}
    next_cursor = {
        "event_offset": len(plan["stream_rows"]),
        "source_slice_sha256": plan["source_slice_sha256"],
    }
    values: dict[str, Any] = {
        "tenant_id": "local-dev",
        "sync_commit_id": sync_commit_id or uuid4(),
        "sync_definition_version_id": sync_definition_version_id,
        "run_id": run_id,
        "from_state_version": 0,
        "to_state_version": 1,
        "previous_cursor": previous_cursor,
        "next_cursor": next_cursor,
        "source_slice_sha256": plan["source_slice_sha256"],
        "target_commit_ref": target_commit_ref,
        "target_content_sha256": plan["final_content_sha256"],
        "records_read": len(plan["stream_rows"]),
        "records_inserted": len(plan["stream_rows"]),
        "records_updated": 0,
        "records_deleted": 0,
        "records_output": len(plan["final_rows"]),
        "committed_by": WORKLOAD,
        "committed_at": committed_at,
    }
    return SourceSyncCommit(
        **values,
        previous_cursor_sha256=canonical_json_fingerprint(previous_cursor),
        next_cursor_sha256=canonical_json_fingerprint(next_cursor),
        commit_sha256=source_sync_commit_fingerprint(**values),
    )


def _control_counts(engine, sync_definition_version_id: UUID) -> dict[str, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM gda_control.source_sync_commit
                     WHERE sync_definition_version_id = :sync_definition_version_id),
                    (SELECT count(*) FROM gda_control.data_product_version)
                """
            ),
            {"sync_definition_version_id": sync_definition_version_id},
        ).one()
        connection.rollback()
    return {"source_sync_commits": int(row[0]), "data_product_versions": int(row[1])}


def _snapshot_evidence(report: dict[str, Any]) -> tuple[IcebergSnapshotEvidence, ...]:
    return tuple(
        IcebergSnapshotEvidence.model_validate(item) for item in report["snapshot_evidence"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--spark-image", default=DEFAULT_SPARK_IMAGE)
    parser.add_argument("--flink-image", default=DEFAULT_FLINK_IMAGE)
    parser.add_argument("--jdk-image", default=DEFAULT_JDK_IMAGE)
    parser.add_argument("--java-home", default=DEFAULT_JAVA_HOME)
    parser.add_argument("--docker-network", default=DEFAULT_NETWORK)
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--postgres-url", default="postgresql://127.0.0.1:5433/gis_agent")
    parser.add_argument("--container-endpoint-url", default="http://minio:9000")
    parser.add_argument("--host-endpoint-url", default="http://127.0.0.1:9000")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--fault-mode",
        choices=("ack-loss", "kill", "network"),
        default="ack-loss",
        help="provider uncertainty profile to certify",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    settings = _settings()
    access_key = settings.get("MINIO_ROOT_USER", "minio_admin")
    secret_key = settings.get("MINIO_ROOT_PASSWORD", "local_dev_minio_secret")
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
    namespace = f"gda_reconcile_{token}"
    prefix = f"acceptance/flink-iceberg/gda_flink_iceberg_{token}/"
    warehouse_uri = f"s3://{BUCKET}/{prefix}warehouse"
    table = f"lakehouse.gda_interop_{token}.chongqing_osm_roads"
    work_dir = REPO_ROOT / ".tmp/source-sync-certification" / f"flink_iceberg_reconcile_{token}"
    plan_path = work_dir / "plan.json"
    input_path = work_dir / "events.tsv"
    baseline_path = work_dir / "spark-baseline.json"
    cancel_probe_path = work_dir / "spark-cancel-probe.json"
    commit_probe_path = work_dir / "spark-commit-probe.json"
    replay_probe_path = work_dir / "spark-replay-probe.json"
    checkpoint_cancel = work_dir / "checkpoints-cancel"
    checkpoint_commit = work_dir / "checkpoints-commit"
    client = boto3.client(
        "s3",
        endpoint_url=args.host_endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    catalog: IcebergCatalogSandbox | None = None
    flink: FlinkIcebergSandbox | None = None
    control = _PostgresDatabaseSandbox(admin_url)
    report: dict[str, Any] | None = None
    error: str | None = None
    cancellation_adapter: FlinkProviderCancellationAdapter | None = None
    cleanup: dict[str, Any] = {}
    main_counts_before = _main_sync_counts(admin_url)
    work_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_cancel.mkdir()
    checkpoint_commit.mkdir()
    try:
        flink_artifacts = {
            "runtime": verify_artifact(FLINK_ICEBERG),
            "aws_bundle": verify_artifact(FLINK_AWS),
            "postgresql_jdbc": verify_artifact(POSTGRES_JDBC),
            "hadoop_client_api": verify_artifact(HADOOP_CLIENT_API),
            "hadoop_client_runtime": verify_artifact(HADOOP_CLIENT_RUNTIME),
        }
        spark_artifacts = _spark_artifacts(args.spark_image, timeout=args.timeout_seconds)
        plan = build_reconciliation_plan(args.source)
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        input_path.write_text(render_recovery_input(plan), encoding="utf-8")

        control.setup()
        if control.engine is None:
            raise RuntimeError("control-plane sandbox database was not created")
        with control.engine.begin() as connection:
            connection.execute(text(DATA_PRODUCT_MIGRATION.read_text(encoding="utf-8")))
        gateway = PlatformGateway(control.engine)
        authority = SourceSyncAuthority(control.engine)
        now = datetime.now(UTC).replace(microsecond=0)
        platform_definition_id = uuid4()
        sync_definition_version_id = uuid4()
        gateway.register_definition(
            _definition_registration(
                "local-dev",
                platform_definition_id,
                f"flink-iceberg-reconcile-{token}",
                now,
            )
        )
        flink_image_id = docker_image_id(args.flink_image, timeout=args.timeout_seconds)
        definition = _sync_definition(
            sync_definition_version_id,
            platform_definition_id,
            namespace,
            plan,
            args,
            flink_image_id,
            now,
        )
        initial_cursor = {"event_offset": 0, "source_slice_sha256": None}
        definition_write = authority.create_definition(
            definition,
            owner_ref="team:data-platform",
            initial_cursor=initial_cursor,
        )
        run_ids = {name: uuid4() for name in ("cancel", "uncertain", "retry")}
        runs = {}
        for index, name in enumerate(run_ids, start=1):
            runs[name] = _submit_run(
                gateway,
                _run(
                    "local-dev",
                    run_ids[name],
                    platform_definition_id,
                    now + timedelta(seconds=index),
                    sequence=f"{token}:{name}",
                ),
            )

        catalog = IcebergCatalogSandbox(
            image=args.postgres_image,
            network=args.docker_network,
            token=token,
        )
        catalog_evidence = catalog.start()
        baseline = _spark_phase(
            args,
            phase="baseline",
            plan_path=plan_path,
            report_path=baseline_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
        )
        jar_path = compile_flink_job(
            work_dir=work_dir,
            flink_image=args.flink_image,
            jdk_image=args.jdk_image,
            java_home=args.java_home,
            timeout=args.timeout_seconds,
            java_source=JAVA_SOURCE,
            main_class=MAIN_CLASS,
        )
        flink = FlinkIcebergSandbox(
            args=args,
            token=token,
            access_key=access_key,
            secret_key=secret_key,
            catalog_password=catalog.password,
        )
        cluster = flink.start()
        if flink.rest_url is None:
            raise RuntimeError("Flink REST endpoint was not published")
        cancellation_adapter = FlinkProviderCancellationAdapter(flink.rest_url)
        cancel_command = _flink_job_arguments(
            flink,
            jar_path=jar_path,
            mode="cancel",
            warehouse_uri=warehouse_uri,
            table=table,
            input_path=input_path,
            checkpoint_path=checkpoint_cancel,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            commit_token=plan["commit_tag"],
        )
        cancellation = _cancel_before_checkpoint(
            flink,
            cancel_command,
            commit_token=plan["commit_tag"],
            timeout=args.timeout_seconds,
            cancellation_adapter=cancellation_adapter,
        )
        cancelling = gateway.transition_run(
            "local-dev",
            run_ids["cancel"],
            runs["cancel"].state_version,
            "cancelling",
            WORKLOAD,
            "provider cancellation requested",
        )
        cancelled_run = gateway.transition_run(
            "local-dev",
            run_ids["cancel"],
            cancelling.state_version,
            "cancelled",
            WORKLOAD,
            "Flink provider confirmed CANCELED",
        )
        cancel_probe = _spark_phase(
            args,
            phase="cancel-probe",
            plan_path=plan_path,
            report_path=cancel_probe_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
        )
        intent = IcebergCommitIntent(
            source_slice_sha256=plan["source_slice_sha256"],
            commit_token=plan["commit_tag"],
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
            expected_record_count=len(plan["final_rows"]),
            expected_matching_records=len(plan["stream_rows"]),
            expected_content_sha256=plan["final_content_sha256"],
        )
        cancel_decision = reconcile_iceberg_commit(
            intent,
            _snapshot_evidence(cancel_probe),
            cancel_confirmed=True,
        )
        after_cancel_checkpoint = authority.get_checkpoint("local-dev", sync_definition_version_id)
        after_cancel_counts = _control_counts(control.engine, sync_definition_version_id)

        commit_command = _flink_job_arguments(
            flink,
            jar_path=jar_path,
            mode="commit",
            warehouse_uri=warehouse_uri,
            table=table,
            input_path=input_path,
            checkpoint_path=checkpoint_commit,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            commit_token=plan["commit_tag"],
        )
        if args.fault_mode == "ack-loss":
            uncertain_runtime = _run_uncertain_commit(
                flink,
                commit_command,
                commit_token=plan["commit_tag"],
                timeout=args.timeout_seconds,
            )
        else:
            uncertain_runtime = _run_fault_injected_commit(
                flink,
                commit_command,
                commit_token=plan["commit_tag"],
                timeout=args.timeout_seconds,
                fault_mode=args.fault_mode,
            )
        before_reconcile_checkpoint = authority.get_checkpoint(
            "local-dev", sync_definition_version_id
        )
        before_reconcile_counts = _control_counts(control.engine, sync_definition_version_id)
        commit_probe = _spark_phase(
            args,
            phase="commit-probe",
            plan_path=plan_path,
            report_path=commit_probe_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
        )
        uncertain_decision = reconcile_iceberg_commit(
            intent,
            _snapshot_evidence(commit_probe),
            cancel_confirmed=False,
        )
        if (
            not uncertain_decision.advance_source_sync
            or uncertain_decision.target_commit_ref is None
        ):
            raise RuntimeError("exact Iceberg commit was not eligible for reconciliation")
        gateway.transition_run(
            "local-dev",
            run_ids["uncertain"],
            runs["uncertain"].state_version,
            "reconciling",
            WORKLOAD,
            "provider committed but acknowledgement was lost",
        )
        commit = _sync_commit(
            sync_definition_version_id=sync_definition_version_id,
            run_id=run_ids["uncertain"],
            plan=plan,
            target_commit_ref=uncertain_decision.target_commit_ref,
            committed_at=datetime.now(UTC),
        )
        commit_write = authority.commit(commit)
        retry_preflight = authority.find_source_slice_commit(
            "local-dev",
            sync_definition_version_id,
            previous_cursor=commit.previous_cursor,
            next_cursor=commit.next_cursor,
            source_slice_sha256=commit.source_slice_sha256,
        )
        replay_commit = _sync_commit(
            sync_definition_version_id=sync_definition_version_id,
            run_id=run_ids["retry"],
            plan=plan,
            target_commit_ref=uncertain_decision.target_commit_ref,
            committed_at=datetime.now(UTC),
        )
        replay_write = authority.commit(replay_commit)
        recorded_decision = reconcile_iceberg_commit(
            intent,
            _snapshot_evidence(commit_probe),
            cancel_confirmed=False,
            recorded_snapshot_id=commit_write.commit.target_commit_ref["snapshot_id"],
        )
        replay_probe = _spark_phase(
            args,
            phase="commit-probe",
            plan_path=plan_path,
            report_path=replay_probe_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
        )
        final_checkpoint = authority.get_checkpoint("local-dev", sync_definition_version_id)
        commits = authority.commits("local-dev", sync_definition_version_id)
        final_counts = _control_counts(control.engine, sync_definition_version_id)
        inventory = _object_inventory(client, prefix)

        checks = {
            "real_chongqing_osm_source_bound": (
                plan["source"]["source_feature_count"] == 50_366
                and plan["source"]["source_product_sha256"] == DEFAULT_SOURCE_PRODUCT_SHA256
            ),
            "supply_chain_artifacts_verified": True,
            "definition_and_initial_checkpoint_created": (
                definition_write.created and definition_write.checkpoint.state_version == 0
            ),
            "pre_checkpoint_cancel_confirmed": all(cancellation["checks"].values()),
            "cancel_left_iceberg_uncommitted": all(cancel_probe["checks"].values()),
            "cancel_did_not_advance_control_plane": (
                cancel_decision.status == "cancelled_uncommitted"
                and cancelled_run.status.value == "cancelled"
                and after_cancel_checkpoint.state_version == 0
                and after_cancel_counts
                == {
                    "source_sync_commits": 0,
                    "data_product_versions": 0,
                }
            ),
            "uncertain_provider_commit_boundary_observed": all(
                uncertain_runtime["checks"].values()
            ),
            "lost_ack_left_control_plane_unadvanced": (
                uncertain_runtime["acknowledgement_delivered_to_control_plane"] is False
                and before_reconcile_checkpoint.state_version == 0
                and before_reconcile_counts
                == {
                    "source_sync_commits": 0,
                    "data_product_versions": 0,
                }
            ),
            "independent_snapshot_reconciliation_exact": (
                all(commit_probe["checks"].values())
                and uncertain_decision.status == "committed_unacknowledged"
                and uncertain_decision.snapshot_id == commit_probe["terminal_snapshot_id"]
            ),
            "source_sync_advanced_exactly_once": (
                commit_write.created
                and final_checkpoint.state_version == 1
                and final_checkpoint.last_sync_commit_id == commit.sync_commit_id
                and len(commits) == 1
                and final_counts["source_sync_commits"] == 1
            ),
            "retry_preflight_skipped_provider_and_reused_commit": (
                retry_preflight == commit
                and not replay_write.created
                and replay_write.commit == commit
                and replay_write.replayed_commit_id == commit.sync_commit_id
                and recorded_decision.status == "already_recorded"
            ),
            "retry_created_no_duplicate_snapshot": (
                commit_probe["snapshots"] == replay_probe["snapshots"]
                and commit_probe["content_sha256"] == replay_probe["content_sha256"]
            ),
            "data_product_version_never_published": (
                after_cancel_counts["data_product_versions"] == 0
                and before_reconcile_counts["data_product_versions"] == 0
                and final_counts["data_product_versions"] == 0
            ),
            "iceberg_object_graph_materialized": (
                inventory["metadata_json_count"] == len(commit_probe["snapshots"])
                and inventory["manifest_avro_count"] >= 4
                and inventory["data_parquet_count"] >= 2
                and inventory["object_count"]
                == inventory["metadata_json_count"]
                + inventory["manifest_avro_count"]
                + inventory["data_parquet_count"]
            ),
        }
        report = {
            "schema": "gda.chongqing_osm_flink_iceberg_reconciliation.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "source_slice_sha256": plan["source_slice_sha256"],
                "baseline_content_sha256": plan["baseline_content_sha256"],
                "final_content_sha256": plan["final_content_sha256"],
                "commit_token": plan["commit_tag"],
            },
            "runtime": {
                "spark_image": args.spark_image,
                "spark_image_id": docker_image_id(args.spark_image, timeout=args.timeout_seconds),
                "flink_image": args.flink_image,
                "flink_image_id": flink_image_id,
                "spark_artifacts": spark_artifacts,
                "flink_artifacts": flink_artifacts,
                "flink_job_source_sha256": _sha256_file(JAVA_SOURCE),
                "flink_job_jar_sha256": _sha256_file(jar_path),
                "flink_cluster": cluster,
                "catalog": {
                    **catalog_evidence,
                    "provider": "org.apache.iceberg.jdbc.JdbcCatalog",
                    "image": args.postgres_image,
                    "image_id": docker_image_id(args.postgres_image, timeout=args.timeout_seconds),
                },
            },
            "cancellation": {
                **cancellation,
                "decision": cancel_decision.model_dump(mode="json"),
                "spark_probe": cancel_probe,
            },
            "uncertain_commit": {
                "fault_mode": args.fault_mode,
                "runtime": uncertain_runtime,
                "decision": uncertain_decision.model_dump(mode="json"),
                "recorded_decision": recorded_decision.model_dump(mode="json"),
                "spark_probe": commit_probe,
            },
            "control_plane": {
                "checkpoint": final_checkpoint.model_dump(mode="json"),
                "commit": commit_write.commit.model_dump(mode="json"),
                "commit_count": len(commits),
                "data_product_version_count": final_counts["data_product_versions"],
                "retry_provider_write_executed": False,
            },
            "table": {
                "catalog": "jdbc",
                "file_io": "org.apache.iceberg.aws.s3.S3FileIO",
                "baseline": baseline,
                "replay_probe": replay_probe,
                "object_inventory": inventory,
            },
            "not_claimed": [
                "cross-engine concurrent write isolation",
                "cross-system exactly-once transaction",
                "automatic DataProductVersion publication",
                "REST or Gravitino catalog interoperability",
                "production throughput, freshness, HA, or Kubernetes runtime",
            ],
        }
        if args.fault_mode == "ack-loss":
            report["not_claimed"].append("physical kill -9 or network-partition commit uncertainty")
        elif args.fault_mode == "kill":
            report["not_claimed"].extend(
                [
                    "network-partition commit uncertainty",
                    "automatic Flink HA restart, fencing, RPO/RTO, or Kubernetes recovery",
                ]
            )
        else:
            report["not_claimed"].extend(
                [
                    "container kill -9 commit uncertainty",
                    "automatic Flink HA restart, fencing, RPO/RTO, or Kubernetes recovery",
                ]
            )
        if report["status"] != "passed":
            raise RuntimeError(f"Flink Iceberg reconciliation checks failed: {checks}")
    except Exception as exc:
        safe = f"{type(exc).__name__}: {exc}"
        catalog_password = catalog.password if catalog is not None else ""
        for value in (access_key, secret_key, catalog_password):
            if value:
                safe = safe.replace(value, "<redacted>")
        error = safe
    finally:
        if cancellation_adapter is not None:
            cancellation_adapter.close()
        cleanup["flink_container_removed"] = flink.cleanup() if flink is not None else True
        cleanup["catalog_container_removed"] = catalog.cleanup() if catalog is not None else True
        try:
            cleanup.update(_cleanup_prefix(client, prefix))
        except Exception as exc:
            cleanup["object_prefix_empty"] = False
            cleanup["object_storage_cleanup_error"] = f"{type(exc).__name__}: {exc}"
        try:
            cleanup.update(control.cleanup())
        except Exception as exc:
            cleanup["database_removed"] = False
            cleanup["database_cleanup_error"] = f"{type(exc).__name__}: {exc}"
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_removed"] = not work_dir.exists()
        try:
            main_counts_after = _main_sync_counts(admin_url)
            cleanup["main_source_sync_unchanged"] = main_counts_after == main_counts_before
            cleanup["main_source_sync_counts"] = list(main_counts_after)
        except Exception as exc:
            cleanup["main_source_sync_unchanged"] = False
            cleanup["main_source_sync_error"] = f"{type(exc).__name__}: {exc}"
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_flink_iceberg_reconciliation.acceptance.v1",
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    cleanup_passed = (
        cleanup.get("flink_container_removed") is True
        and cleanup.get("catalog_container_removed") is True
        and cleanup.get("object_prefix_empty") is True
        and cleanup.get("database_removed") is True
        and cleanup.get("work_directory_removed") is True
        and cleanup.get("main_source_sync_unchanged") is True
    )
    if not cleanup_passed:
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
