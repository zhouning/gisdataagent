#!/usr/bin/env python3
"""Certify fail-closed SourceSync handling of PostgreSQL slot WAL loss."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from scripts.certify_chongqing_osm_postgres_cdc_slot_invalidation import (
    TERMINAL_FLINK_STATES,
    _exception_summary,
    _slot_incarnation,
    _success_evidence_counts,
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
    "chongqing-osm-postgres-cdc-wal-capacity-report.json"
)


def assess_slot_wal_capacity(evidence: dict[str, Any]) -> dict[str, Any]:
    """Admit only a reserved slot with a usable restart LSN and safety margin."""

    slot = evidence.get("slot")
    policy = evidence.get("policy")
    reasons: list[str] = []
    if not isinstance(policy, dict):
        reasons.append("replication_slot_wal_capacity_policy_missing")
        minimum_safe_wal_bytes = None
    else:
        maximum = policy.get("max_slot_wal_keep_size_bytes")
        minimum_safe_wal_bytes = policy.get("minimum_safe_wal_bytes")
        if not isinstance(maximum, int) or maximum <= 0:
            reasons.append("replication_slot_wal_capacity_limit_missing")
        if not isinstance(minimum_safe_wal_bytes, int) or minimum_safe_wal_bytes < 0:
            reasons.append("replication_slot_wal_safety_margin_missing")

    if not isinstance(slot, dict):
        reasons.append("replication_slot_wal_capacity_evidence_missing")
        wal_status = None
        safe_wal_size = None
        restart_lsn = None
    else:
        wal_status = slot.get("wal_status")
        safe_wal_size = slot.get("safe_wal_size")
        restart_lsn = slot.get("restart_lsn")
        if slot.get("exists") is not True:
            reasons.append("replication_slot_missing")
        if wal_status != "reserved":
            reasons.append(
                "replication_slot_wal_status_"
                + (str(wal_status) if wal_status else "missing")
            )
        if not restart_lsn:
            reasons.append("replication_slot_restart_lsn_missing")
        if (
            not isinstance(safe_wal_size, int)
            or not isinstance(minimum_safe_wal_bytes, int)
            or safe_wal_size < minimum_safe_wal_bytes
        ):
            reasons.append("replication_slot_safe_wal_size_exhausted")

    admitted = not reasons
    return {
        "schema": "gda.postgres_cdc_slot_wal_capacity_admission.v1",
        "admitted": admitted,
        "disposition": "admitted" if admitted else "rejected_fail_closed",
        "reason_codes": sorted(set(reasons)),
        "wal_status": wal_status,
        "restart_lsn": restart_lsn,
        "safe_wal_size": safe_wal_size,
    }


def _wal_capacity_fault_checks(evidence: dict[str, Any]) -> dict[str, bool]:
    configuration = evidence["configuration"]
    baseline = evidence["baseline"]
    final_slot = evidence["final_slot"]
    cycles = evidence["pressure_cycles"]
    identity = evidence["slot_incarnation"]
    pressure = evidence["pressure_policy"]
    admission_policy = evidence["admission_policy"]
    storage_samples = [baseline["storage"], *(cycle["storage"] for cycle in cycles)]
    return {
        "finite_slot_wal_limit_was_applied": (
            configuration["max_slot_wal_keep_size_bytes"]
            == pressure["max_slot_wal_keep_size_bytes"]
            == admission_policy["max_slot_wal_keep_size_bytes"]
            and configuration["max_slot_wal_keep_size"] != "-1"
            and configuration["wal_segment_size_bytes"] > 0
            and admission_policy["minimum_safe_wal_bytes"] >= 0
        ),
        "physical_disconnect_and_backend_termination_preceded_pressure": (
            evidence["event_sequence"]["network_disconnected"]
            < evidence["event_sequence"]["slot_backend_terminated"]
            < evidence["event_sequence"]["wal_pressure_started"]
            and evidence["disconnect"]["disconnected"]
            and evidence["backend_termination"]["terminated"]
            and baseline["slot"]["exists"]
            and not baseline["slot"]["active"]
        ),
        "one_slot_incarnation_remained_continuously_present": (
            final_slot["exists"]
            and final_slot["slot_name"] == identity["slot_name"]
            and final_slot["system_identifier"] == identity["system_identifier"]
            and all(
                cycle["slot"]["exists"]
                and cycle["slot"]["slot_name"] == identity["slot_name"]
                and cycle["slot"]["system_identifier"]
                == identity["system_identifier"]
                for cycle in cycles
            )
        ),
        "wal_pressure_was_bounded_and_checkpointed": (
            1 <= len(cycles) <= pressure["maximum_cycles"]
            and sum(cycle["requested_payload_bytes"] for cycle in cycles)
            <= pressure["maximum_requested_payload_bytes"]
            and evidence["observed_wal_bytes_total"]
            <= pressure["maximum_observed_wal_budget_bytes"]
            and all(cycle["observed_wal_bytes"] > 0 for cycle in cycles)
            and all(
                _lsn_value(cycle["start_lsn"])
                <= _lsn_value(cycle["emitted_lsn"])
                <= _lsn_value(cycle["checkpoint_lsn"])
                for cycle in cycles
            )
        ),
        "configured_retention_was_physically_exceeded": (
            evidence["observed_wal_bytes_total"]
            > pressure["max_slot_wal_keep_size_bytes"]
            and len(cycles) >= 1
        ),
        "slot_transitioned_to_lost_with_no_restart_lsn": (
            baseline["slot"]["wal_status"] in {"reserved", "extended"}
            and final_slot["wal_status"] == "lost"
            and not final_slot["restart_lsn"]
            and final_slot["safe_wal_size"] is None
        ),
        "source_filesystem_safety_floor_was_preserved": (
            baseline["storage"]["filesystem_available_bytes"]
            >= pressure["filesystem_safety_floor_bytes"]
            + pressure["maximum_observed_wal_budget_bytes"]
            and all(
                sample["filesystem_available_bytes"]
                >= pressure["filesystem_safety_floor_bytes"]
                for sample in storage_samples
            )
            and all(sample["filesystem_capacity_percent"] != "100%" for sample in storage_samples)
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
            == "controller_cancel_after_wal_capacity_rejection"
        ),
        "post_fault_physical_sink_did_not_advance": (
            evidence["sink"]["accepted_after"]
            == evidence["sink"]["accepted_before"]
            and evidence["sink"]["rejected_after"]
            == evidence["sink"]["rejected_before"]
            and evidence["sink"]["post_fault_accepted_delta"] == 0
            and evidence["sink"]["post_fault_rejected_delta"] == 0
        ),
        "lost_slot_remained_inactive_after_observation_reconnect": (
            evidence["slot_after_reconnect"]["exists"]
            and not evidence["slot_after_reconnect"]["active"]
            and evidence["slot_after_reconnect"]["wal_status"] == "lost"
            and not evidence["slot_after_reconnect"]["restart_lsn"]
        ),
    }


def run_wal_capacity_provider(
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
        max_slot_wal_keep_size_mb=args.max_slot_wal_keep_size_mb,
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
        configuration = postgres.wal_capacity_configuration()
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
        slot_incarnation = _slot_incarnation(
            original_inactive,
            ordinal=1,
            creation_anchor_lsn=original_inactive["restart_lsn"],
            established_by="connector_initial_slot_observation",
        )
        accepted_before, _ = _committed_lines(work_dir / "silver/v1/changelog")
        rejected_before, _ = _committed_lines(work_dir / "quarantine/v1/rejected")
        baseline_storage = postgres.wal_storage_evidence()
        maximum_requested_payload_bytes = (
            args.wal_pressure_cycles
            * args.wal_pressure_message_count
            * args.wal_pressure_message_bytes
        )
        maximum_observed_wal_budget_bytes = (
            maximum_requested_payload_bytes
            + args.wal_pressure_cycles
            * configuration["wal_segment_size_bytes"]
            * 2
        )
        if baseline_storage["filesystem_available_bytes"] < (
            args.filesystem_safety_floor_bytes
            + maximum_observed_wal_budget_bytes
        ):
            raise RuntimeError("bounded WAL pressure lacks filesystem safety headroom")

        pressure_cycles: list[dict[str, Any]] = []
        for cycle_number in range(1, args.wal_pressure_cycles + 1):
            pressure = postgres.generate_wal_pressure(
                cycle=cycle_number,
                message_count=args.wal_pressure_message_count,
                message_bytes=args.wal_pressure_message_bytes,
            )
            observation = postgres.slot_observation()
            storage = postgres.wal_storage_evidence()
            pressure_cycles.append(
                {**pressure, "slot": observation, "storage": storage}
            )
            if observation["wal_status"] == "lost":
                break
        final_slot = postgres.slot_observation()
        if final_slot["wal_status"] != "lost":
            raise RuntimeError(
                "bounded WAL pressure did not invalidate the replication slot: "
                f"cycles={pressure_cycles}"
            )

        policy = {
            "max_slot_wal_keep_size_bytes": configuration[
                "max_slot_wal_keep_size_bytes"
            ],
            "minimum_safe_wal_bytes": args.minimum_safe_wal_bytes,
        }
        admission = assess_slot_wal_capacity({"slot": final_slot, "policy": policy})
        if admission["admitted"]:
            raise RuntimeError("controller admitted a replication slot with lost WAL")

        exceptions_before_cancel = _exception_summary(flink.job_exceptions(job_id))
        status_before_cancel = flink.job_status(job_id)
        final_status = flink.cancel(job_id, timeout=args.timeout_seconds)
        exceptions_after_cancel = _exception_summary(flink.job_exceptions(job_id))
        reconnect = postgres.reconnect_network()
        time.sleep(args.post_termination_observation_seconds)
        accepted_after, accepted_files = _committed_lines(
            work_dir / "silver/v1/changelog"
        )
        rejected_after, rejected_files = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        slot_after_reconnect = postgres.slot_observation()
        observed_wal_bytes_total = sum(
            cycle["observed_wal_bytes"] for cycle in pressure_cycles
        )
        capacity_fault = {
            "event_sequence": {
                "network_disconnected": 1,
                "slot_backend_terminated": 2,
                "wal_pressure_started": 3,
                "slot_wal_lost": 4,
                "admission_rejected": 5,
                "runtime_terminated": 6,
                "network_reconnected_for_observation": 7,
            },
            "configuration": configuration,
            "pressure_policy": {
                "max_slot_wal_keep_size_bytes": configuration[
                    "max_slot_wal_keep_size_bytes"
                ],
                "maximum_cycles": args.wal_pressure_cycles,
                "message_count_per_cycle": args.wal_pressure_message_count,
                "message_bytes": args.wal_pressure_message_bytes,
                "maximum_requested_payload_bytes": maximum_requested_payload_bytes,
                "maximum_observed_wal_budget_bytes": (
                    maximum_observed_wal_budget_bytes
                ),
                "filesystem_safety_floor_bytes": args.filesystem_safety_floor_bytes,
            },
            "disconnect": disconnect,
            "reconnect": reconnect,
            "backend_termination": backend_termination,
            "original_active_observation": original_active,
            "slot_incarnation": slot_incarnation,
            "baseline": {
                "slot": original_inactive,
                "storage": baseline_storage,
            },
            "pressure_cycles": pressure_cycles,
            "observed_wal_bytes_total": observed_wal_bytes_total,
            "final_slot": final_slot,
            "admission_policy": policy,
            "admission": admission,
            "runtime_termination": {
                "status_before_controller_cancel": status_before_cancel,
                "final_job_status": final_status,
                "origin": "controller_cancel_after_wal_capacity_rejection",
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
                "accepted_files": accepted_files,
                "rejected_files": rejected_files,
            },
            "slot_after_reconnect": slot_after_reconnect,
        }
        checks = _wal_capacity_fault_checks(capacity_fault)
        return (
            {
                "schema": "gda.postgres_cdc_slot_wal_capacity_provider.negative.v1",
                "status": "passed" if all(checks.values()) else "failed",
                "expected_outcome": "rejected_fail_closed",
                "checks": checks,
                "capacity_fault": capacity_fault,
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
    capacity_policy = {
        "schema": "gda.postgres_cdc_slot_wal_capacity_policy.v1",
        "max_slot_wal_keep_size_bytes": args.max_slot_wal_keep_size_mb * 1_048_576,
        "minimum_safe_wal_bytes": args.minimum_safe_wal_bytes,
        "filesystem_safety_floor_bytes": args.filesystem_safety_floor_bytes,
        "on_unsafe_or_lost": "reject_fail_closed",
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
        additional_config={"slot_wal_capacity_policy": capacity_policy},
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
            sequence=f"{namespace}:wal-capacity-negative",
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
    provider, provider_cleanup = run_wal_capacity_provider(
        args=args,
        work_dir=work_dir,
        token=token,
        plan=plan,
        connector=connector,
    )
    admission = provider["capacity_fault"]["admission"]
    if provider["status"] != "passed" or admission["admitted"]:
        raise RuntimeError("WAL capacity provider did not produce the expected rejection")
    failed_run = gateway.transition_run(
        "local-dev",
        run_id,
        running.state_version,
        "failed",
        WORKLOAD,
        "replication slot lost required WAL",
        details={
            "schema": admission["schema"],
            "disposition": admission["disposition"],
            "reason_codes": admission["reason_codes"],
            "wal_status": admission["wal_status"],
            "safe_wal_size": admission["safe_wal_size"],
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
        "capacity_policy_bound_to_definition_and_checkpoint_zero": (
            definition_write.created
            and definition.config["slot_wal_capacity_policy"] == capacity_policy
            and definition_write.checkpoint.state_version == 0
            and definition_write.checkpoint.cursor == initial_cursor
        ),
        "provider_preflight_was_empty": preflight is None,
        "physical_slot_wal_capacity_negative_provider_passed": all(
            provider["checks"].values()
        ),
        "lost_slot_was_rejected_fail_closed": (
            not admission["admitted"]
            and admission["disposition"] == "rejected_fail_closed"
            and "replication_slot_wal_status_lost" in admission["reason_codes"]
            and "replication_slot_restart_lsn_missing" in admission["reason_codes"]
            and "replication_slot_safe_wal_size_exhausted"
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
        "source_filesystem_safety_floor_preserved": provider["checks"][
            "source_filesystem_safety_floor_was_preserved"
        ],
    }
    return (
        {
            "schema": (
                "gda.chongqing_osm_postgres_cdc_slot_wal_capacity."
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
                "slot_wal_capacity_policy": capacity_policy,
                "diagnostic_provider_invocations": 1,
                "successful_provider_admissions": 0,
            },
            "not_claimed": [
                "physical filesystem exhaustion",
                "automatic slot repair, resnapshot, or resume",
                "connector retry or backoff exhaustion",
                "PostgreSQL failover or timeline continuity",
                "production WAL generation rate, RPO, RTO, or high availability",
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
    parser.add_argument("--max-slot-wal-keep-size-mb", type=int, default=1)
    parser.add_argument("--minimum-safe-wal-bytes", type=int, default=65_536)
    parser.add_argument("--wal-pressure-cycles", type=int, default=4)
    parser.add_argument("--wal-pressure-message-count", type=int, default=16)
    parser.add_argument("--wal-pressure-message-bytes", type=int, default=524_288)
    parser.add_argument(
        "--filesystem-safety-floor-bytes", type=int, default=536_870_912
    )
    parser.add_argument("--post-termination-observation-seconds", type=float, default=1.0)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if not 1 <= args.max_slot_wal_keep_size_mb <= 16:
        parser.error("--max-slot-wal-keep-size-mb must be between 1 and 16")
    if not 0 <= args.minimum_safe_wal_bytes <= 16_777_216:
        parser.error("--minimum-safe-wal-bytes must be between 0 and 16777216")
    if not 2 <= args.wal_pressure_cycles <= 8:
        parser.error("--wal-pressure-cycles must be between 2 and 8")
    if not 1 <= args.wal_pressure_message_count <= 32:
        parser.error("--wal-pressure-message-count must be between 1 and 32")
    if not 65_536 <= args.wal_pressure_message_bytes <= 524_288:
        parser.error(
            "--wal-pressure-message-bytes must be between 65536 and 524288"
        )
    if args.wal_pressure_message_bytes % 16:
        parser.error("--wal-pressure-message-bytes must be a 16-byte multiple")
    maximum_requested_payload_bytes = (
        args.wal_pressure_cycles
        * args.wal_pressure_message_count
        * args.wal_pressure_message_bytes
    )
    if maximum_requested_payload_bytes > 134_217_728:
        parser.error("bounded WAL pressure may request at most 128 MiB")
    if not 268_435_456 <= args.filesystem_safety_floor_bytes <= 4_294_967_296:
        parser.error(
            "--filesystem-safety-floor-bytes must be between 256 MiB and 4 GiB"
        )
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
    namespace = f"chongqing_osm_cdc_wal_capacity_{token}"
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
                "gda.chongqing_osm_postgres_cdc_slot_wal_capacity."
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
