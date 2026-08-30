#!/usr/bin/env python3
"""Certify real Chongqing OSM baseline, Iceberg merge, and sync replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import boto3
from sqlalchemy import create_engine, text

from data_agent.connectors.database import _connection_url
from data_agent.lakehouse_materialization import (
    LakehouseMaterializationContract,
    LakehouseMaterializationEvidence,
    LakehouseMaterializationRecorder,
)
from data_agent.platform_contracts import (
    SourceSyncCommit,
    SourceSyncDefinitionVersion,
    canonical_json_bytes,
    canonical_json_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_definition_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway
from data_agent.source_sync_authority import SourceSyncAuthority
from data_agent.source_sync_quarantine import (
    ProviderQuarantineReceipt,
    SourceSyncQuarantineContract,
    SourceSyncQuarantineRecorder,
)
from scripts.certify_source_sync_authority import (
    WORKLOAD,
    _commit_governance_evidence,
    _definition_registration,
    _metadata_change_id,
    _PostgresDatabaseSandbox,
    _register_resource_version,
    _run,
    _settings,
    _submit_run,
)
from scripts.smoke_chongqing_osm_incremental_sync import (
    DEFAULT_INPUT,
    DEFAULT_SOURCE_SHA256,
    baseline_next_cursor,
    baseline_previous_cursor,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/source-sync-certification/chongqing-osm-report.json"
DEFAULT_IMAGE = "gisdataagent/mmfe-spark-runtime:local"
DEFAULT_NETWORK = "gisdataagent_agent-net"
DEFAULT_JAVA_HOME = "/usr/lib/jvm/java-17-openjdk-arm64"
BUCKET = "gis-agent-lakehouse"


def _sync_definition(
    sync_definition_version_id: UUID,
    platform_definition_version_id: UUID,
    namespace: str,
    created_at: datetime,
) -> SourceSyncDefinitionVersion:
    values: dict[str, Any] = {
        "tenant_id": "local-dev",
        "sync_definition_urn": (
            f"gda://local-dev/sync_definition/chongqing-osm-{namespace}"
        ),
        "sync_definition_version_id": sync_definition_version_id,
        "platform_definition_version_id": platform_definition_version_id,
        "source_resource_urn": "gda://local-dev/data_product/chongqing-osm-roads",
        "source_definition_fingerprint": DEFAULT_SOURCE_SHA256,
        "target_resource_urn": f"gda://local-dev/table/{namespace}",
        "mode": "incremental",
        "write_disposition": "merge",
        "cursor_kind": "provider_token",
        "cursor_field": None,
        "primary_keys": ("road_id",),
        "delete_mode": "hard_delete",
        "config": {
            "bootstrap_mode": "full_snapshot",
            "input_uri": DEFAULT_INPUT,
            "provider": "spark-iceberg",
            "acceptance_scope": "isolated",
        },
        "governance_contract": {
            "schema": "gda.source_sync_governance.v1",
            "target_layer": "silver",
            "data_kind": "vector",
            "capture_kind": "micro_batch",
            "source_adapter": {
                "adapter_id": "spark-iceberg",
                "adapter_version": "certification-v1",
                "adapter_fingerprint": canonical_json_fingerprint(
                    {
                        "provider": "spark-iceberg",
                        "source_sha256": DEFAULT_SOURCE_SHA256,
                    }
                ),
            },
            "standard_mapping_contract_id": uuid4(),
            "standard_version_id": uuid4(),
            "data_model_version_id": uuid4(),
            "quality_rule_version_refs": ["quality:osm-road-integrity-v1"],
            "classification_policy_version_ref": "classification:internal-v1",
            "retention_policy_version_ref": "retention:silver-v1",
            "schema_change_policy": "approval_required",
            "promotion_mode": "quality_gated",
            "quarantine_resource_urn": (
                f"gda://local-dev/table/{namespace}-quarantine"
            ),
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


def _commit_from_provider(
    *,
    sync_commit_id: UUID,
    sync_definition_version_id: UUID,
    run_id: UUID,
    from_state_version: int,
    provider_report: dict[str, Any],
    committed_at: datetime,
) -> SourceSyncCommit:
    values: dict[str, Any] = {
        "tenant_id": "local-dev",
        "sync_commit_id": sync_commit_id,
        "sync_definition_version_id": sync_definition_version_id,
        "run_id": run_id,
        "from_state_version": from_state_version,
        "to_state_version": from_state_version + 1,
        "previous_cursor": provider_report["previous_cursor"],
        "next_cursor": provider_report["next_cursor"],
        "source_slice_sha256": provider_report["source_slice_sha256"],
        "target_commit_ref": provider_report["target_commit_ref"],
        "target_content_sha256": provider_report["target_content_sha256"],
        "records_read": provider_report["records_read"],
        "records_inserted": provider_report["records_inserted"],
        "records_updated": provider_report["records_updated"],
        "records_deleted": provider_report["records_deleted"],
        "records_output": provider_report["records_output"],
        "committed_by": WORKLOAD,
        "committed_at": committed_at,
    }
    return SourceSyncCommit(
        **values,
        previous_cursor_sha256=canonical_json_fingerprint(values["previous_cursor"]),
        next_cursor_sha256=canonical_json_fingerprint(values["next_cursor"]),
        commit_sha256=source_sync_commit_fingerprint(**values),
    )


def _materialization_provider_report(
    provider_report: dict[str, Any],
    *,
    warehouse_uri: str,
) -> dict[str, Any]:
    return {
        **provider_report,
        "content_fingerprint": provider_report["target_content_sha256"],
        "row_count": provider_report["records_output"],
        "semantic_sha256": provider_report["source_slice_sha256"],
        "warehouse_uri": warehouse_uri,
    }


def _record_governed_phase(
    *,
    engine,
    authority: SourceSyncAuthority,
    definition: SourceSyncDefinitionVersion,
    run,
    phase: str,
    from_state_version: int,
    provider_report: dict[str, Any],
    provider_report_path: Path,
    warehouse_uri: str,
    materialization_recorder: LakehouseMaterializationRecorder,
    quarantine_recorder: SourceSyncQuarantineRecorder,
) -> dict[str, Any]:
    materialization_report = _materialization_provider_report(
        provider_report,
        warehouse_uri=warehouse_uri,
    )
    materialization = materialization_recorder.record(
        run=run,
        provider_report=materialization_report,
        provider_report_path=provider_report_path,
        evidence=LakehouseMaterializationEvidence(
            evidence_document={
                "schema": "gda.source_sync_spark_quality.v1",
                "phase": phase,
                "provider_checks": provider_report["checks"],
                "records_read": provider_report["records_read"],
                "records_output": provider_report["records_output"],
                "source_slice_sha256": provider_report["source_slice_sha256"],
                "target_content_sha256": provider_report[
                    "target_content_sha256"
                ],
            },
            output_manifest={
                "schema": "gda.source_sync_iceberg_output.v1",
                "phase": phase,
                "iceberg_table": materialization_recorder.contract.iceberg_table,
                "snapshot_id": provider_report["snapshot_id"],
                "feature_count": provider_report["records_output"],
                "target_commit_ref": provider_report["target_commit_ref"],
            },
            lineage_facets={
                "schema": "gda.source_sync_iceberg_lineage.v1",
                "capture_kind": "micro_batch",
                "phase": phase,
                "snapshot_id": provider_report["snapshot_id"],
                "source_slice_sha256": provider_report["source_slice_sha256"],
                "target_layer": "silver",
            },
            quality_metrics={
                "checked": provider_report["records_read"],
                "records_output": provider_report["records_output"],
                "violations": 0,
            },
        ),
    )
    metadata_change_id = _metadata_change_id(
        engine,
        definition.tenant_id,
        materialization.lineage_event_id,
    )

    receipt_time = datetime.now(UTC)
    commit = _commit_from_provider(
        sync_commit_id=uuid4(),
        sync_definition_version_id=definition.sync_definition_version_id,
        run_id=run.run_id,
        from_state_version=from_state_version,
        provider_report=provider_report,
        committed_at=receipt_time + timedelta(seconds=1),
    )
    quarantine_document = {
        "schema": "gda.spark_iceberg_quarantine_output.v1",
        "phase": phase,
        "provider": "spark-iceberg",
        "snapshot_id": provider_report["snapshot_id"],
        "records_rejected": 0,
        "reason_counts": {},
        "source_slice_sha256": provider_report["source_slice_sha256"],
        "target_content_sha256": provider_report["target_content_sha256"],
    }
    quarantine_path = provider_report_path.with_name("quarantine-receipt.json")
    quarantine_payload = canonical_json_bytes(quarantine_document)
    quarantine_path.write_bytes(quarantine_payload)
    quarantine_content_sha256 = hashlib.sha256(quarantine_payload).hexdigest()
    quarantine = quarantine_recorder.record(
        definition=definition,
        commit=commit,
        receipt=ProviderQuarantineReceipt(
            storage_uri=quarantine_path.resolve().as_uri(),
            media_type="application/json",
            content_sha256=quarantine_content_sha256,
            size_bytes=len(quarantine_payload),
            records_rejected=0,
            reason_counts={},
            manifest_facets={
                "phase": phase,
                "provider": "spark-iceberg",
                "provider_output_schema": quarantine_document["schema"],
                "snapshot_id": provider_report["snapshot_id"],
            },
        ),
        recorded_at=receipt_time,
    )
    governance_evidence = _commit_governance_evidence(
        tenant_id=definition.tenant_id,
        sync_commit_id=commit.sync_commit_id,
        target_resource_version_id=materialization.output_resource_version_id,
        output_artifact_id=materialization.output_artifact_id,
        quality_result_ids=(materialization.quality_result_id,),
        lineage_event_id=materialization.lineage_event_id,
        metadata_change_id=metadata_change_id,
    )
    write = authority.commit(commit, governance_evidence, quarantine.evidence)
    return {
        "commit": commit,
        "write": write,
        "materialization": materialization,
        "governance_evidence": governance_evidence,
        "quarantine": quarantine,
        "quarantine_path": quarantine_path,
        "quarantine_content_sha256": quarantine_content_sha256,
    }


def _spark_phase(
    args: argparse.Namespace,
    *,
    phase: str,
    namespace: str,
    warehouse_uri: str,
    table: str,
    report_path: Path,
    extra: tuple[str, ...] = (),
) -> dict[str, Any]:
    relative_report = report_path.relative_to(REPO_ROOT)
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        args.docker_network,
        "-e",
        f"JAVA_HOME={args.java_home}",
        "-v",
        f"{REPO_ROOT}:/workspace",
        "-w",
        "/workspace",
        args.runtime_image,
        "python",
        "-m",
        "scripts.smoke_chongqing_osm_incremental_sync",
        phase,
        "--warehouse-uri",
        warehouse_uri,
        "--table",
        table,
        "--insert-road-id",
        f"gda-source-sync-{namespace}",
        "--report-path",
        str(relative_report),
        *extra,
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=args.timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout)[-4000:]
        raise RuntimeError(f"Spark phase {phase} failed: {details}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("phase") != phase.replace("-", "_"):
        raise RuntimeError(f"Spark phase {phase} returned invalid evidence")
    return report


def _main_sync_counts(admin_url: str) -> tuple[int, int, int]:
    engine = create_engine(admin_url, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.source_sync_definition),
                        (SELECT count(*) FROM gda_control.source_sync_checkpoint),
                        (SELECT count(*) FROM gda_control.source_sync_commit)
                    """
                )
            ).one()
            connection.rollback()
        return tuple(int(value) for value in row)
    finally:
        engine.dispose()


def _cleanup_object_prefix(
    *,
    endpoint_url: str,
    access_key_id: str,
    secret_access_key: str,
    prefix: str,
) -> dict[str, Any]:
    if not prefix.startswith("acceptance/source-sync/gda_sync_cert_"):
        raise RuntimeError("refusing to clean a non-certification object prefix")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="us-east-1",
    )
    removed = 0
    while True:
        response = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
        objects = [{"Key": item["Key"]} for item in response.get("Contents", ())]
        if not objects:
            break
        client.delete_objects(Bucket=BUCKET, Delete={"Objects": objects, "Quiet": True})
        removed += len(objects)
    remaining = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix).get("KeyCount", 0)
    return {"prefix": prefix, "objects_removed": removed, "prefix_empty": remaining == 0}


def _certify(
    engine,
    args: argparse.Namespace,
    *,
    namespace: str,
    warehouse_uri: str,
    table: str,
    work_dir: Path,
) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    platform_definition_id = uuid4()
    sync_definition_version_id = uuid4()
    source_resource_version_id = uuid4()
    gateway = PlatformGateway(engine)
    authority = SourceSyncAuthority(engine)
    gateway.register_definition(
        _definition_registration(
            "local-dev",
            platform_definition_id,
            f"chongqing-osm-{namespace}",
            now,
        )
    )
    definition = _sync_definition(
        sync_definition_version_id,
        platform_definition_id,
        namespace,
        now,
    )
    _register_resource_version(
        gateway,
        tenant_id=definition.tenant_id,
        resource_urn=definition.source_resource_urn,
        resource_version_id=source_resource_version_id,
        content_sha256=DEFAULT_SOURCE_SHA256,
        created_at=now,
    )
    initial_cursor = baseline_previous_cursor(DEFAULT_SOURCE_SHA256)
    definition_write = authority.create_definition(
        definition,
        owner_ref="team:data-platform",
        initial_cursor=initial_cursor,
    )

    run_ids = {phase: uuid4() for phase in ("baseline", "incremental", "replay")}
    runs = {}
    for index, phase in enumerate(run_ids, start=1):
        runs[phase] = _submit_run(
            gateway,
            _run(
                "local-dev",
                run_ids[phase],
                platform_definition_id,
                now + timedelta(seconds=index),
                sequence=f"{namespace}:{phase}",
            ),
        )

    materialization_recorder = LakehouseMaterializationRecorder(
        LakehouseMaterializationContract(
            output_resource_urn=definition.target_resource_urn,
            iceberg_table=table,
            iceberg_storage_uri=warehouse_uri.replace("s3a://", "s3://", 1),
            source_resource_version_id=source_resource_version_id,
            workload_subject=WORKLOAD,
            quality_evaluator="workload:quality-evaluator",
            quality_rule_version="quality:osm-road-integrity-v1",
            governance_ref={
                "classification": "internal",
                "logical_stage": "silver",
            },
            technical_refs=(
                {
                    "provider": "spark-iceberg",
                    "table": table,
                    "warehouse_uri": warehouse_uri,
                },
            ),
            output_artifact_identity="source-sync:iceberg-output",
            evidence_artifact_identity="source-sync:quality-evidence",
            lineage_event_identity="source-sync:materialize-lineage",
            output_artifact_key_prefix=f"{namespace}_output",
            evidence_artifact_key_prefix=f"{namespace}_quality",
        ),
        gateway=gateway,
    )
    quarantine_urn = definition.governance_contract.quarantine_resource_urn
    if quarantine_urn is None:
        raise RuntimeError("Silver micro-batch definition lacks quarantine Resource")
    quarantine_recorder = SourceSyncQuarantineRecorder(
        SourceSyncQuarantineContract(
            quarantine_resource_urn=quarantine_urn,
            authority_system="spark-iceberg",
            authority_locator=f"{table}:quarantine",
            owner_ref="team:data-platform",
            artifact_key_prefix=f"{namespace}_quarantine",
            governance_ref={"retention_policy": "retention:silver-v1"},
        ),
        gateway=gateway,
    )

    baseline_preflight = authority.find_source_slice_commit(
        "local-dev",
        sync_definition_version_id,
        previous_cursor=initial_cursor,
        next_cursor=baseline_next_cursor(DEFAULT_SOURCE_SHA256),
        source_slice_sha256=DEFAULT_SOURCE_SHA256,
    )
    baseline_dir = work_dir / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=False)
    baseline_report_path = baseline_dir / "provider-report.json"
    baseline_report = _spark_phase(
        args,
        phase="baseline",
        namespace=namespace,
        warehouse_uri=warehouse_uri,
        table=table,
        report_path=baseline_report_path,
    )
    baseline_phase = _record_governed_phase(
        engine=engine,
        authority=authority,
        definition=definition,
        run=runs["baseline"],
        phase="baseline",
        from_state_version=0,
        provider_report=baseline_report,
        provider_report_path=baseline_report_path,
        warehouse_uri=warehouse_uri,
        materialization_recorder=materialization_recorder,
        quarantine_recorder=quarantine_recorder,
    )

    incremental_dir = work_dir / "incremental"
    incremental_dir.mkdir(parents=True, exist_ok=False)
    incremental_report_path = incremental_dir / "provider-report.json"
    incremental_report = _spark_phase(
        args,
        phase="incremental",
        namespace=namespace,
        warehouse_uri=warehouse_uri,
        table=table,
        report_path=incremental_report_path,
    )
    incremental_phase = _record_governed_phase(
        engine=engine,
        authority=authority,
        definition=definition,
        run=runs["incremental"],
        phase="incremental",
        from_state_version=1,
        provider_report=incremental_report,
        provider_report_path=incremental_report_path,
        warehouse_uri=warehouse_uri,
        materialization_recorder=materialization_recorder,
        quarantine_recorder=quarantine_recorder,
    )
    baseline_write = baseline_phase["write"]
    incremental_commit = incremental_phase["commit"]
    incremental_write = incremental_phase["write"]

    replay_preflight = authority.find_source_slice_commit(
        "local-dev",
        sync_definition_version_id,
        previous_cursor=incremental_commit.previous_cursor,
        next_cursor=incremental_commit.next_cursor,
        source_slice_sha256=incremental_commit.source_slice_sha256,
    )
    replay_commit = _commit_from_provider(
        sync_commit_id=uuid4(),
        sync_definition_version_id=sync_definition_version_id,
        run_id=run_ids["replay"],
        from_state_version=1,
        provider_report=incremental_report,
        committed_at=datetime.now(UTC),
    )
    replay_write = authority.commit(replay_commit)
    verification_report = _spark_phase(
        args,
        phase="verify-cleanup",
        namespace=namespace,
        warehouse_uri=warehouse_uri,
        table=table,
        report_path=work_dir / "verification-cleanup-report.json",
        extra=(
            "--baseline-snapshot-id",
            str(baseline_report["snapshot_id"]),
            "--incremental-snapshot-id",
            str(incremental_report["snapshot_id"]),
            "--expected-history-count",
            "2",
            "--delete-road-id",
            incremental_report["delete_road_id"],
            "--update-road-id",
            incremental_report["update_road_id"],
        ),
    )

    checkpoint = authority.get_checkpoint("local-dev", sync_definition_version_id)
    commits = authority.commits("local-dev", sync_definition_version_id)
    checks = {
        "real_chongqing_osm_source_bound": (
            baseline_report["input_uri"] == DEFAULT_INPUT
            and baseline_report["source_slice_sha256"] == DEFAULT_SOURCE_SHA256
            and baseline_report["records_read"] == 50366
        ),
        "definition_and_initial_checkpoint_created": (
            definition_write.created
            and definition_write.checkpoint.state_version == 0
            and definition_write.checkpoint.cursor == initial_cursor
        ),
        "baseline_preflight_was_empty": baseline_preflight is None,
        "full_baseline_committed": (
            baseline_write.created
            and baseline_write.checkpoint.state_version == 1
            and baseline_report["history_count"] == 1
        ),
        "baseline_governance_and_zero_quarantine_bound": (
            baseline_write.governance_evidence
            == baseline_phase["governance_evidence"]
            and baseline_write.quarantine_evidence
            == baseline_phase["quarantine"].evidence
            and baseline_phase["quarantine"].evidence.records_rejected == 0
            and baseline_phase["quarantine"].evidence.reason_counts == {}
            and hashlib.sha256(
                baseline_phase["quarantine_path"].read_bytes()
            ).hexdigest()
            == baseline_phase["quarantine_content_sha256"]
        ),
        "incremental_merge_committed": (
            incremental_write.created
            and incremental_write.checkpoint.state_version == 2
            and incremental_report["history_count"] == 2
            and incremental_report["records_inserted"] == 1
            and incremental_report["records_updated"] == 1
            and incremental_report["records_deleted"] == 1
        ),
        "incremental_governance_and_zero_quarantine_bound": (
            incremental_write.governance_evidence
            == incremental_phase["governance_evidence"]
            and incremental_write.quarantine_evidence
            == incremental_phase["quarantine"].evidence
            and incremental_phase["quarantine"].evidence.records_rejected == 0
            and incremental_phase["quarantine"].evidence.reason_counts == {}
            and hashlib.sha256(
                incremental_phase["quarantine_path"].read_bytes()
            ).hexdigest()
            == incremental_phase["quarantine_content_sha256"]
        ),
        "pre_and_post_time_travel_verified": (
            incremental_report["checks"]["baseline_time_travel_preserved"]
            and incremental_report["checks"]["incremental_time_travel_preserved"]
            and verification_report["checks"]["baseline_time_travel_rows"]
            and verification_report["checks"]["incremental_time_travel_rows"]
        ),
        "replay_preflight_skipped_provider_write": (
            replay_preflight == incremental_commit
            and verification_report["checks"]["replay_created_no_snapshot"]
        ),
        "cross_run_replay_recovered_commit": (
            not replay_write.created
            and replay_write.commit == incremental_commit
            and replay_write.replayed_commit_id == incremental_commit.sync_commit_id
            and replay_write.checkpoint.state_version == 2
            and replay_write.governance_evidence
            == incremental_phase["governance_evidence"]
            and replay_write.quarantine_evidence
            == incremental_phase["quarantine"].evidence
        ),
        "checkpoint_and_commit_history_exact": (
            checkpoint.state_version == 2
            and checkpoint.last_sync_commit_id == incremental_commit.sync_commit_id
            and len(commits) == 2
        ),
        "isolated_iceberg_cleanup_passed": all(
            verification_report["cleanup"].values()
        ),
    }
    return {
        "schema": "gda.chongqing_osm_incremental_source_sync.acceptance.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "source": {
            "product": "chongqing-osm-roads",
            "version": "v1.2.0",
            "input_uri": DEFAULT_INPUT,
            "content_sha256": DEFAULT_SOURCE_SHA256,
            "feature_count": 50366,
        },
        "authority": {
            "sync_definition_version_id": str(sync_definition_version_id),
            "checkpoint": checkpoint.model_dump(mode="json"),
            "commits": [commit.model_dump(mode="json") for commit in commits],
            "governed_phases": {
                phase: {
                    "governance_evidence": record[
                        "governance_evidence"
                    ].model_dump(mode="json"),
                    "quarantine_evidence": record[
                        "quarantine"
                    ].evidence.model_dump(mode="json"),
                    "quarantine_artifact": record[
                        "quarantine"
                    ].artifact.model_dump(mode="json"),
                    "target_resource_version_id": str(
                        record["materialization"].output_resource_version_id
                    ),
                }
                for phase, record in (
                    ("baseline", baseline_phase),
                    ("incremental", incremental_phase),
                )
            },
            "replay_run_id": str(run_ids["replay"]),
            "provider_write_invocations": 2,
        },
        "iceberg": {
            "warehouse_uri": warehouse_uri,
            "table": table,
            "baseline": baseline_report,
            "incremental": incremental_report,
            "verification_cleanup": verification_report,
        },
        "not_claimed": [
            "Flink checkpoint or streaming CDC",
            "late or out-of-order event handling",
            "production concurrency or throughput SLO",
            "persistent acceptance data product",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postgres-url",
        default="postgresql://127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--runtime-image", default=DEFAULT_IMAGE)
    parser.add_argument("--docker-network", default=DEFAULT_NETWORK)
    parser.add_argument("--java-home", default=DEFAULT_JAVA_HOME)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
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
    namespace = f"gda_sync_cert_{token}"
    warehouse_uri = (
        f"s3a://{BUCKET}/acceptance/source-sync/{namespace}/warehouse"
    )
    object_prefix = f"acceptance/source-sync/{namespace}/"
    table = f"lakehouse.{namespace}.osm_roads_incremental"
    work_dir = REPO_ROOT / ".tmp/source-sync-certification" / namespace
    sandbox = _PostgresDatabaseSandbox(admin_url)
    report: dict[str, Any] | None = None
    error: str | None = None
    database_cleanup: dict[str, bool] = {}
    work_directory_removed = False
    main_counts_before = _main_sync_counts(admin_url)
    try:
        sandbox.setup()
        if sandbox.engine is None:
            raise RuntimeError("certification database engine was not created")
        report = _certify(
            sandbox.engine,
            args,
            namespace=namespace,
            warehouse_uri=warehouse_uri,
            table=table,
            work_dir=work_dir,
        )
        report["sandbox"] = {"database": sandbox.database, "persistent": False}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            object_cleanup = _cleanup_object_prefix(
                endpoint_url=settings.get(
                    "AWS_ENDPOINT_URL", "http://127.0.0.1:9000"
                ),
                access_key_id=settings.get("AWS_ACCESS_KEY_ID", "minio_admin"),
                secret_access_key=settings.get(
                    "AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"
                ),
                prefix=object_prefix,
            )
        except Exception as cleanup_exc:
            object_cleanup = {
                "prefix": object_prefix,
                "objects_removed": 0,
                "prefix_empty": False,
                "error": f"{type(cleanup_exc).__name__}: {cleanup_exc}",
            }
        finally:
            database_cleanup = sandbox.cleanup()
            if work_dir.parent != REPO_ROOT / ".tmp/source-sync-certification":
                raise RuntimeError("refusing to clean an unexpected work directory")
            if work_dir.exists():
                shutil.rmtree(work_dir)
            work_directory_removed = not work_dir.exists()
    main_counts_after = _main_sync_counts(admin_url)
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_incremental_source_sync.acceptance.v1",
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = {
        **database_cleanup,
        **object_cleanup,
        "main_sync_tables_unchanged_empty": (
            main_counts_before == (0, 0, 0) and main_counts_after == (0, 0, 0)
        ),
        "work_directory_removed": work_directory_removed,
    }
    if not (
        report["cleanup"].get("database_removed") is True
        and report["cleanup"].get("prefix_empty") is True
        and report["cleanup"].get("main_sync_tables_unchanged_empty") is True
        and report["cleanup"].get("work_directory_removed") is True
    ):
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
                "cleanup": report["cleanup"],
                "error": report.get("error"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
