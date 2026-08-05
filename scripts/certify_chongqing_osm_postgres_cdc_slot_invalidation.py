#!/usr/bin/env python3
"""Certify fail-closed SourceSync handling of PostgreSQL CDC slot loss."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from data_agent.platform_contracts import (
    canonical_json_bytes,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway
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
    _lsn_value,
    _sync_definition,
    build_cdc_plan,
    verify_connector_artifact,
)
from scripts.certify_source_sync_authority import (
    WORKLOAD,
    _definition_registration,
    _PostgresDatabaseSandbox,
    _run,
    _settings,
    _submit_run,
)
from scripts.source_sync_certification_support import connection_url as _connection_url
from scripts.source_sync_certification_support import main_sync_counts

DEFAULT_REPORT = (
    REPO_ROOT
    / ".tmp/source-sync-certification/"
    "chongqing-osm-postgres-cdc-slot-invalidation-report.json"
)
TERMINAL_FLINK_STATES = {"FAILED", "CANCELED", "FINISHED"}


def _slot_incarnation(
    observation: dict[str, Any],
    *,
    ordinal: int,
    creation_anchor_lsn: str,
    established_by: str,
) -> dict[str, Any]:
    if not observation.get("exists"):
        raise ValueError("slot incarnation requires an existing slot observation")
    identity = {
        "system_identifier": observation["system_identifier"],
        "database_identity": observation["database_identity"],
        "slot_name": observation["slot_name"],
        "plugin": observation["plugin"],
        "slot_type": observation["slot_type"],
        "creation_anchor_lsn": creation_anchor_lsn,
        "incarnation_ordinal": ordinal,
        "established_by": established_by,
    }
    return {
        **identity,
        "incarnation_fingerprint": canonical_json_fingerprint(identity),
    }


def assess_slot_continuity(evidence: dict[str, Any]) -> dict[str, Any]:
    """Admit only a continuously observed slot incarnation; missing proof fails closed."""

    original = evidence.get("original_incarnation")
    current = evidence.get("current_incarnation")
    absence_witnessed = evidence.get("absence_witnessed") is True
    reasons: list[str] = []
    if not isinstance(original, dict) or not isinstance(current, dict):
        reasons.append("replication_slot_continuity_evidence_missing")
    else:
        required = {
            "system_identifier",
            "database_identity",
            "slot_name",
            "plugin",
            "slot_type",
            "incarnation_fingerprint",
        }
        if not required.issubset(original) or not required.issubset(current):
            reasons.append("replication_slot_continuity_evidence_incomplete")
        elif any(original[key] != current[key] for key in required - {"incarnation_fingerprint"}):
            reasons.append("replication_slot_identity_changed")
        elif original["incarnation_fingerprint"] != current["incarnation_fingerprint"]:
            reasons.append("replication_slot_incarnation_changed")
    if absence_witnessed:
        reasons.append("replication_slot_absence_witnessed")
    if evidence.get("current_slot_exists") is not True:
        reasons.append("replication_slot_current_observation_missing")
    admitted = not reasons
    return {
        "schema": "gda.postgres_cdc_slot_continuity_admission.v1",
        "admitted": admitted,
        "disposition": "admitted" if admitted else "rejected_fail_closed",
        "reason_codes": sorted(set(reasons)),
        "original_incarnation_fingerprint": (
            original.get("incarnation_fingerprint")
            if isinstance(original, dict)
            else None
        ),
        "current_incarnation_fingerprint": (
            current.get("incarnation_fingerprint")
            if isinstance(current, dict)
            else None
        ),
    }


def _slot_fault_checks(evidence: dict[str, Any]) -> dict[str, bool]:
    original = evidence["original_incarnation"]
    recreated = evidence["current_incarnation"]
    drop = evidence["teardown"]
    recreation = evidence["recreation"]
    return {
        "physical_disconnect_preceded_slot_teardown": (
            evidence["event_sequence"]["network_disconnected"]
            < evidence["event_sequence"]["slot_backend_terminated"]
            < evidence["event_sequence"]["slot_dropped"]
            and evidence["disconnect"]["disconnected"]
            and evidence["backend_termination"]["terminated"]
        ),
        "original_slot_was_observed_inactive_before_drop": (
            drop["slot_before"]["exists"]
            and not drop["slot_before"]["active"]
            and drop["slot_before"]["slot_name"] == original["slot_name"]
        ),
        "slot_absence_was_physically_witnessed": (
            drop["absence_witnessed"]
            and not drop["slot_after"]["exists"]
            and evidence["absence_witnessed"]
        ),
        "mutation_occured_between_drop_and_recreation": (
            evidence["event_sequence"]["slot_dropped"]
            < evidence["event_sequence"]["source_mutated"]
            < evidence["event_sequence"]["slot_recreated"]
            and _lsn_value(drop["drop_command_lsn"])
            <= _lsn_value(evidence["mutation_target_lsn"])
            <= _lsn_value(recreation["consistent_lsn"])
        ),
        "same_name_recreation_is_a_new_incarnation": (
            original["slot_name"] == recreated["slot_name"]
            and original["incarnation_fingerprint"]
            != recreated["incarnation_fingerprint"]
            and original["incarnation_ordinal"] == 1
            and recreated["incarnation_ordinal"] == 2
        ),
        "controller_rejected_before_runtime_termination": (
            evidence["event_sequence"]["admission_rejected"]
            < evidence["event_sequence"]["runtime_terminated"]
            and not evidence["admission"]["admitted"]
            and evidence["admission"]["disposition"] == "rejected_fail_closed"
        ),
        "runtime_terminal_state_is_separate_evidence": (
            evidence["runtime_termination"]["final_job_status"]
            in TERMINAL_FLINK_STATES
            and evidence["runtime_termination"]["origin"]
            == "controller_cancel_after_admission_rejection"
        ),
        "post_fault_physical_sink_did_not_advance": (
            evidence["sink"]["accepted_after"]
            == evidence["sink"]["accepted_before"]
            and evidence["sink"]["rejected_after"]
            == evidence["sink"]["rejected_before"]
            and evidence["sink"]["post_fault_accepted_delta"] == 0
            and evidence["sink"]["post_fault_rejected_delta"] == 0
        ),
        "recreated_slot_remained_inactive_after_reconnect": (
            evidence["recreated_slot_after_reconnect"]["exists"]
            and not evidence["recreated_slot_after_reconnect"]["active"]
            and evidence["recreated_slot_after_reconnect"]["slot_name"]
            == recreated["slot_name"]
        ),
    }


def _exception_summary(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = canonical_json_bytes(payload)
    text_value = encoded.decode("utf-8", errors="replace")
    exception_types = sorted(
        set(
            re.findall(
                r"(?:[A-Za-z_$][A-Za-z0-9_$]*\.)*"
                r"[A-Za-z_$][A-Za-z0-9_$]*(?:Exception|Error)",
                text_value,
            )
        )
    )
    return {
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "exception_type_count": len(exception_types),
        "exception_types": exception_types,
        "contains_connection_failure_signal": any(
            marker in text_value.lower()
            for marker in ("connection", "connectexception", "timeout")
        ),
        "contains_slot_failure_signal": "slot" in text_value.lower(),
    }


def run_slot_invalidation_provider(
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
    postgres = CdcPostgresSandbox(
        image=args.postgres_image,
        network=args.docker_network,
        token=token,
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
        flink_cluster = flink.start()
        job_id = flink.submit(jar_path=jar_path, source=postgres)
        initial_lines = flink.wait_for_output(
            expected=plan["milestone_counts"]["initial_snapshot_accepted"],
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        checkpoint_output = flink.wait_for_marker(
            "GDA_CDC_CHECKPOINT_COMPLETED",
            timeout=args.timeout_seconds,
        )
        completed_counts = [int(count) for _, count in CHECKPOINT_RE.findall(checkpoint_output)]
        if not completed_counts or max(completed_counts) < len(initial_lines):
            raise RuntimeError("initial CDC snapshot was not protected by a checkpoint")

        original_active = postgres.wait_for_slot_active(
            timeout=args.slot_inactive_timeout_seconds
        )
        disconnect = postgres.disconnect_network()
        backend_termination = postgres.terminate_slot_backend()
        original_inactive = postgres.wait_for_slot_inactive(
            timeout=args.slot_inactive_timeout_seconds
        )
        accepted_before, _ = _committed_lines(work_dir / "silver/v1/changelog")
        rejected_before, _ = _committed_lines(work_dir / "quarantine/v1/rejected")
        teardown = postgres.drop_replication_slot()
        mutation_target_lsn = postgres.mutate_after_slot_loss(plan)
        recreation = postgres.recreate_replication_slot()

        original_incarnation = _slot_incarnation(
            original_inactive,
            ordinal=1,
            creation_anchor_lsn=original_inactive["restart_lsn"],
            established_by="connector_initial_slot_observation",
        )
        current_incarnation = _slot_incarnation(
            recreation["observation"],
            ordinal=2,
            creation_anchor_lsn=recreation["consistent_lsn"],
            established_by="same_name_recreation_after_absence",
        )
        admission_evidence = {
            "original_incarnation": original_incarnation,
            "current_incarnation": current_incarnation,
            "absence_witnessed": teardown["absence_witnessed"],
            "current_slot_exists": recreation["observation"]["exists"],
        }
        admission = assess_slot_continuity(admission_evidence)
        if admission["admitted"]:
            raise RuntimeError("controller admitted a recreated replication slot")

        exceptions_before_cancel = _exception_summary(flink.job_exceptions(job_id))
        status_before_cancel = flink.job_status(job_id)
        final_status = flink.cancel(job_id, timeout=args.timeout_seconds)
        exceptions_after_cancel = _exception_summary(flink.job_exceptions(job_id))
        reconnect = postgres.reconnect_network()
        time.sleep(args.post_termination_observation_seconds)
        accepted_after, accepted_manifest = _committed_lines(
            work_dir / "silver/v1/changelog"
        )
        rejected_after, rejected_manifest = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        recreated_after_reconnect = postgres.slot_observation()

        slot_fault = {
            "event_sequence": {
                "network_disconnected": 1,
                "slot_backend_terminated": 2,
                "slot_dropped": 3,
                "source_mutated": 4,
                "slot_recreated": 5,
                "admission_rejected": 6,
                "runtime_terminated": 7,
                "network_reconnected_for_observation": 8,
            },
            "disconnect": disconnect,
            "reconnect": reconnect,
            "backend_termination": backend_termination,
            "original_active_observation": original_active,
            "original_inactive_observation": original_inactive,
            "teardown": teardown,
            "mutation_target_lsn": mutation_target_lsn,
            "recreation": recreation,
            "original_incarnation": original_incarnation,
            "current_incarnation": current_incarnation,
            "absence_witnessed": teardown["absence_witnessed"],
            "current_slot_exists": recreation["observation"]["exists"],
            "admission": admission,
            "runtime_termination": {
                "status_before_controller_cancel": status_before_cancel,
                "final_job_status": final_status,
                "origin": "controller_cancel_after_admission_rejection",
                "exceptions_before_cancel": exceptions_before_cancel,
                "exceptions_after_cancel": exceptions_after_cancel,
            },
            "sink": {
                "accepted_before": len(accepted_before),
                "accepted_after": len(accepted_after),
                "rejected_before": len(rejected_before),
                "rejected_after": len(rejected_after),
                "post_fault_accepted_delta": len(accepted_after) - len(accepted_before),
                "post_fault_rejected_delta": len(rejected_after) - len(rejected_before),
                "accepted_files": accepted_manifest,
                "accepted_manifest_sha256": canonical_json_fingerprint(
                    accepted_manifest
                ),
                "rejected_files": rejected_manifest,
                "rejected_manifest_sha256": canonical_json_fingerprint(
                    rejected_manifest
                ),
            },
            "recreated_slot_after_reconnect": recreated_after_reconnect,
        }
        checks = _slot_fault_checks(slot_fault)
        return (
            {
                "schema": "gda.postgres_cdc_slot_invalidation_provider.negative.v1",
                "status": "passed" if all(checks.values()) else "failed",
                "expected_outcome": "rejected_fail_closed",
                "checks": checks,
                "slot_fault": slot_fault,
                "postgres": {
                    **postgres_start,
                    "image": args.postgres_image,
                    "image_id": docker_image_id(
                        args.postgres_image, timeout=args.timeout_seconds
                    ),
                    "publication": postgres.publication,
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
        cleanup.update(postgres.cleanup())


def _success_evidence_counts(engine, *, run_id, sync_definition_version_id, target_urn):
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM gda_control.source_sync_commit
                     WHERE sync_definition_version_id = :sync_definition_version_id)
                        AS commits,
                    (SELECT count(*) FROM gda_control.artifact
                     WHERE run_id = :run_id) AS artifacts,
                    (SELECT count(*) FROM gda_control.quality_result
                     WHERE run_id = :run_id) AS quality_results,
                    (SELECT count(*) FROM gda_control.lineage_event
                     WHERE run_id = :run_id) AS lineage_events,
                    (SELECT count(*) FROM gda_control.resource_version
                     WHERE resource_urn = :target_urn) AS target_resource_versions
                """
            ),
            {
                "run_id": run_id,
                "sync_definition_version_id": sync_definition_version_id,
                "target_urn": target_urn,
            },
        ).mappings().one()
    return {key: int(value) for key, value in row.items()}


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
            sequence=f"{namespace}:slot-invalidation-negative",
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
    provider, provider_cleanup = run_slot_invalidation_provider(
        args=args,
        work_dir=work_dir,
        token=token,
        plan=plan,
        connector=connector,
    )
    admission = provider["slot_fault"]["admission"]
    if provider["status"] != "passed" or admission["admitted"]:
        raise RuntimeError(
            "slot invalidation provider did not produce the expected rejection"
        )
    failed_run = gateway.transition_run(
        "local-dev",
        run_id,
        running.state_version,
        "failed",
        WORKLOAD,
        "replication slot incarnation changed",
        details={
            "schema": admission["schema"],
            "disposition": admission["disposition"],
            "reason_codes": admission["reason_codes"],
            "original_incarnation_fingerprint": admission[
                "original_incarnation_fingerprint"
            ],
            "current_incarnation_fingerprint": admission[
                "current_incarnation_fingerprint"
            ],
        },
    )
    checkpoint = authority.get_checkpoint(
        "local-dev", sync_definition_version_id
    )
    commits = authority.commits("local-dev", sync_definition_version_id)
    success_counts = _success_evidence_counts(
        engine,
        run_id=run_id,
        sync_definition_version_id=sync_definition_version_id,
        target_urn=definition.target_resource_urn,
    )
    checks = {
        "definition_and_initial_checkpoint_created": (
            definition_write.created
            and definition_write.checkpoint.state_version == 0
            and definition_write.checkpoint.cursor == initial_cursor
        ),
        "provider_preflight_was_empty": preflight is None,
        "physical_slot_invalidation_negative_provider_passed": all(
            provider["checks"].values()
        ),
        "same_name_slot_recreation_rejected": (
            not admission["admitted"]
            and admission["disposition"] == "rejected_fail_closed"
            and "replication_slot_absence_witnessed"
            in admission["reason_codes"]
            and "replication_slot_incarnation_changed"
            in admission["reason_codes"]
        ),
        "source_sync_checkpoint_remained_zero": (
            checkpoint.state_version == 0
            and checkpoint.cursor == initial_cursor
            and checkpoint.last_sync_commit_id is None
        ),
        "source_sync_commit_history_remained_empty": len(commits) == 0,
        "no_provider_success_evidence_fabricated": all(
            value == 0 for value in success_counts.values()
        ),
        "platform_run_failed_with_no_success_admission": (
            failed_run.status.value == "failed"
            and failed_run.state_version == running.state_version + 1
        ),
        "post_fault_physical_sink_remained_stable": provider["checks"][
            "post_fault_physical_sink_did_not_advance"
        ],
    }
    return (
        {
            "schema": (
                "gda.chongqing_osm_postgres_cdc_slot_invalidation."
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
                "commits": [],
                "success_evidence_counts": success_counts,
                "diagnostic_provider_invocations": 1,
                "successful_provider_admissions": 0,
            },
            "not_claimed": [
                "automatic replication-slot repair or resume",
                "reconnect-backoff exhaustion without controller cancellation",
                "production WAL capacity safety",
                "PostgreSQL failover or timeline continuity",
                "production throughput, freshness SLO, or high availability",
            ],
        },
        provider_cleanup,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-url", default="postgresql://127.0.0.1:5433/gis_agent")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--connector", type=Path, default=DEFAULT_CONNECTOR)
    parser.add_argument("--flink-image", default=DEFAULT_FLINK_IMAGE)
    parser.add_argument("--jdk-image", default=DEFAULT_JDK_IMAGE)
    parser.add_argument("--java-home", default=DEFAULT_JAVA_HOME)
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--docker-network", default=DEFAULT_NETWORK)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--slot-inactive-timeout-seconds", type=int, default=30)
    parser.add_argument("--post-termination-observation-seconds", type=float, default=1.0)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if not 5 <= args.slot_inactive_timeout_seconds <= 120:
        parser.error("--slot-inactive-timeout-seconds must be between 5 and 120")
    if not 0.5 <= args.post_termination_observation_seconds <= 5.0:
        parser.error(
            "--post-termination-observation-seconds must be between 0.5 and 5"
        )

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
    namespace = f"chongqing_osm_cdc_slot_loss_{token}"
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
        for prefix in ("gda-cdc-pg-", "gda-cdc-flink-"):
            cleanup[f"no_runtime_container_with_prefix_{prefix.rstrip('-')}"] = (
                _container_absent(f"{prefix}{token}")
            )
    main_counts_after = main_sync_counts(admin_url)
    cleanup["main_sync_tables_unchanged_empty"] = (
        main_counts_before == (0, 0, 0) and main_counts_after == (0, 0, 0)
    )
    if report is None:
        report = {
            "schema": (
                "gda.chongqing_osm_postgres_cdc_slot_invalidation."
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
