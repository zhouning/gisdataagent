#!/usr/bin/env python3
"""Certify a real OSM-derived Flink event stream and SourceSync replay."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import secrets
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pyarrow.parquet as pq

from data_agent.connectors.database import _connection_url
from data_agent.platform_contracts import (
    SourceSyncCommit,
    SourceSyncDefinitionVersion,
    canonical_json_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_definition_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway
from data_agent.source_sync_authority import SourceSyncAuthority
from scripts.certify_chongqing_osm_incremental_sync import _main_sync_counts
from scripts.certify_source_sync_authority import (
    WORKLOAD,
    _definition_registration,
    _PostgresDatabaseSandbox,
    _run,
    _settings,
    _submit_run,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
JAVA_SOURCE = REPO_ROOT / "scripts/flink/ChongqingOsmEventStreamJob.java"
DEFAULT_SOURCE = (
    REPO_ROOT
    / "data_agent/uploads/data_products/chongqing-osm-roads/v1.2.0/"
    "silver/chongqing-osm-roads-standardized.geoparquet"
)
DEFAULT_SOURCE_PRODUCT_SHA256 = (
    "c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164"
)
DEFAULT_REPORT = (
    REPO_ROOT / ".tmp/source-sync-certification/chongqing-osm-flink-report.json"
)
DEFAULT_FLINK_IMAGE = "flink:1.19.3-scala_2.12-java11"
DEFAULT_JDK_IMAGE = "gisdataagent/mmfe-spark-runtime:local"
DEFAULT_JAVA_HOME = "/usr/lib/jvm/java-17-openjdk-arm64"
EVENT_EPOCH_MS = 1_785_628_800_000
OUT_OF_ORDERNESS_MS = 10_000
FAIL_AFTER_OFFSET = 5
CHECKPOINT_RE = re.compile(r"GDA_CHECKPOINT_COMPLETED id=(\d+) offset=(\d+)")
FAILURE_RE = re.compile(r"GDA_INTENTIONAL_FAILURE checkpoint=(\d+) offset=(\d+)")
RESTORE_RE = re.compile(r"GDA_SOURCE_OPEN attempt=(\d+) restored=true offset=(\d+)")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _encoded_name(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _event(
    event_id: str,
    source: dict[str, Any],
    operation: str,
    offset_ms: int,
    *,
    suffix: str = "",
) -> dict[str, Any]:
    road_id = str(source["road_id"])
    label = str(source.get("road_name") or source.get("road_class") or road_id)
    geometry = bytes(source["geometry"])
    return {
        "event_id": event_id,
        "road_id": road_id,
        "operation": operation,
        "event_time_ms": EVENT_EPOCH_MS + offset_ms,
        "road_name_base64": _encoded_name(f"{label}{suffix}"),
        "geometry_sha256": _sha256_bytes(geometry),
    }


def build_event_slice(source_path: Path) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Build one deterministic insert/update/delete slice from real OSM rows."""

    table = pq.read_table(
        source_path,
        columns=["road_id", "road_name", "road_class", "geometry"],
    )
    rows = [row for row in table.slice(0, 4).to_pylist() if row["geometry"]]
    if len(rows) != 4 or len({str(row["road_id"]) for row in rows}) != 4:
        raise RuntimeError("OSM event source requires four deterministic unique road rows")
    road_a, road_b, road_c, road_d = rows
    delete_b = _event("cq-osm-e05", road_b, "delete", 6_000)
    events = (
        _event("cq-osm-e01", road_a, "insert", 1_000),
        _event("cq-osm-e02", road_b, "insert", 2_000),
        _event("cq-osm-e03", road_c, "insert", 12_000),
        _event("cq-osm-e04", road_a, "update", 5_000, suffix="|updated-on-time"),
        delete_b,
        dict(delete_b),
        _event("cq-osm-e06", road_d, "insert", 30_000),
        _event("cq-osm-e07", road_a, "update", 3_000, suffix="|too-late"),
        _event("cq-osm-e08", road_c, "update", 25_000, suffix="|updated"),
        _event("cq-osm-e09", road_d, "delete", 31_000),
    )
    metadata = {
        "source_path": str(source_path.relative_to(REPO_ROOT)),
        "source_parquet_sha256": _sha256_file(source_path),
        "source_product_sha256": DEFAULT_SOURCE_PRODUCT_SHA256,
        "source_feature_count": table.num_rows,
        "selected_road_ids": [str(row["road_id"]) for row in rows],
    }
    return events, metadata


def render_event_slice(events: tuple[dict[str, Any], ...]) -> bytes:
    lines = [
        "\t".join(
            (
                event["event_id"],
                event["road_id"],
                event["operation"],
                str(event["event_time_ms"]),
                event["road_name_base64"],
                event["geometry_sha256"],
            )
        )
        for event in events
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def _run_command(
    command: list[str],
    *,
    timeout: int,
    stage: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout)[-6_000:]
        raise RuntimeError(f"{stage} failed: {details}")
    return completed


def _container_path(path: Path) -> str:
    return f"/workspace/{path.relative_to(REPO_ROOT).as_posix()}"


def docker_image_id(image: str, *, timeout: int) -> str:
    completed = _run_command(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        timeout=timeout,
        stage="inspect Docker image identity",
    )
    image_id = completed.stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError("Docker returned an invalid image identity")
    return image_id


def compile_flink_job(
    *,
    work_dir: Path,
    flink_image: str,
    jdk_image: str,
    java_home: str,
    timeout: int,
    java_source: Path = JAVA_SOURCE,
    main_class: str = "ChongqingOsmEventStreamJob",
    extra_compile_classpath: tuple[Path, ...] = (),
) -> Path:
    """Compile against the exact runtime libraries without a permanent build image."""

    lib_dir = work_dir / "flink-lib"
    classes_dir = work_dir / "classes"
    jar_path = work_dir / f"{main_class}.jar"
    lib_dir.mkdir(parents=True, exist_ok=False)
    classes_dir.mkdir(parents=True, exist_ok=False)
    created = _run_command(
        ["docker", "create", flink_image],
        timeout=timeout,
        stage="create Flink library container",
    )
    container_id = created.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        raise RuntimeError("Docker returned an invalid temporary container identity")
    try:
        _run_command(
            ["docker", "cp", f"{container_id}:/opt/flink/lib/.", str(lib_dir)],
            timeout=timeout,
            stage="extract Flink compile libraries",
        )
    finally:
        _run_command(
            ["docker", "rm", container_id],
            timeout=timeout,
            stage="remove Flink library container",
        )

    mount = f"{REPO_ROOT}:/workspace"
    compile_classpath = [f"{_container_path(lib_dir)}/*"]
    for artifact in extra_compile_classpath:
        if not artifact.is_file():
            raise RuntimeError(f"missing Flink compile artifact: {artifact.name}")
        compile_classpath.append(_container_path(artifact))
    _run_command(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            f"JAVA_HOME={java_home}",
            "-v",
            mount,
            "-w",
            "/workspace",
            jdk_image,
            "javac",
            "--release",
            "11",
            "-cp",
            ":".join(compile_classpath),
            "-d",
            _container_path(classes_dir),
            _container_path(java_source),
        ],
        timeout=timeout,
        stage="compile Flink acceptance job",
    )
    _run_command(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            f"JAVA_HOME={java_home}",
            "-v",
            mount,
            "-w",
            "/workspace",
            jdk_image,
            "jar",
            "--create",
            "--file",
            _container_path(jar_path),
            "--main-class",
            main_class,
            "-C",
            _container_path(classes_dir),
            ".",
        ],
        timeout=timeout,
        stage="package Flink acceptance job",
    )
    return jar_path


def _committed_lines(root: Path) -> tuple[list[str], list[dict[str, Any]]]:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not path.name.startswith(".") and not path.name.endswith(".crc")
    )
    inventory = [
        {
            "name": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in files
    ]
    lines: list[str] = []
    for path in files:
        lines.extend(line for line in path.read_text(encoding="utf-8").splitlines() if line)
    return lines, inventory


def _parse_event_line(line: str, *, rejected: bool = False) -> dict[str, Any]:
    fields = line.split("\t")
    reason = None
    if rejected:
        if len(fields) != 7:
            raise RuntimeError("rejected Flink output has an invalid field count")
        reason, fields = fields[0], fields[1:]
    if len(fields) != 6:
        raise RuntimeError("accepted Flink output has an invalid field count")
    result = {
        "event_id": fields[0],
        "road_id": fields[1],
        "operation": fields[2],
        "event_time_ms": int(fields[3]),
        "road_name_base64": fields[4],
        "geometry_sha256": fields[5],
    }
    if reason is not None:
        result["reason"] = reason
    return result


def verify_flink_output(
    *,
    events: tuple[dict[str, Any], ...],
    accepted_root: Path,
    rejected_root: Path,
    runtime_log: str,
) -> dict[str, Any]:
    accepted_lines, accepted_inventory = _committed_lines(accepted_root)
    rejected_lines, rejected_inventory = _committed_lines(rejected_root)
    accepted = [_parse_event_line(line) for line in accepted_lines]
    rejected = [_parse_event_line(line, rejected=True) for line in rejected_lines]
    accepted_ids = [event["event_id"] for event in accepted]
    rejected_pairs = {(event["reason"], event["event_id"]) for event in rejected}
    final_state: dict[str, dict[str, Any]] = {}
    for event in sorted(
        accepted,
        key=lambda item: (item["event_time_ms"], item["event_id"]),
    ):
        if event["operation"] == "delete":
            final_state.pop(event["road_id"], None)
        else:
            final_state[event["road_id"]] = event

    checkpoints = [
        {"checkpoint_id": int(match[0]), "source_offset": int(match[1])}
        for match in CHECKPOINT_RE.findall(runtime_log)
    ]
    failure = FAILURE_RE.search(runtime_log)
    restore = RESTORE_RE.search(runtime_log)
    selected_road_ids = tuple(dict.fromkeys(event["road_id"] for event in events))
    expected_active = {selected_road_ids[0], selected_road_ids[2]}
    checks = {
        "checkpoint_completed_before_failure": bool(
            checkpoints and failure and int(failure.group(1)) >= checkpoints[0]["checkpoint_id"]
        ),
        "source_restored_from_checkpoint": bool(
            failure
            and restore
            and int(restore.group(1)) >= 1
            and 0 < int(restore.group(2)) <= int(failure.group(2))
        ),
        "job_completed_after_restart": "GDA_JOB_COMPLETED status=success" in runtime_log,
        "exactly_once_accepted_event_ids": (
            len(accepted_ids) == 8
            and len(set(accepted_ids)) == 8
            and set(accepted_ids)
            == {
                "cq-osm-e01",
                "cq-osm-e02",
                "cq-osm-e03",
                "cq-osm-e04",
                "cq-osm-e05",
                "cq-osm-e06",
                "cq-osm-e08",
                "cq-osm-e09",
            }
        ),
        "duplicate_and_late_events_audited": rejected_pairs
        == {("duplicate", "cq-osm-e05"), ("late", "cq-osm-e07")},
        "out_of_order_within_watermark_accepted": "cq-osm-e04" in accepted_ids,
        "source_deletes_applied": set(final_state) == expected_active,
        "final_state_uses_on_time_updates": all(
            base64.b64decode(item["road_name_base64"]).decode("utf-8").endswith(
                ("|updated-on-time", "|updated")
            )
            for item in final_state.values()
        ),
        "all_input_events_reconciled": len(accepted) + len(rejected) == len(events),
        "accepted_files_committed": bool(accepted_inventory),
        "rejected_files_committed": bool(rejected_inventory),
    }
    final_rows = [
        {
            "road_id": road_id,
            "event_id": event["event_id"],
            "event_time_ms": event["event_time_ms"],
            "road_name_base64": event["road_name_base64"],
            "geometry_sha256": event["geometry_sha256"],
        }
        for road_id, event in sorted(final_state.items())
    ]
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "checkpoints": checkpoints,
        "failure": (
            {"checkpoint_id": int(failure.group(1)), "source_offset": int(failure.group(2))}
            if failure
            else None
        ),
        "restore": (
            {"attempt": int(restore.group(1)), "source_offset": int(restore.group(2))}
            if restore
            else None
        ),
        "accepted_event_count": len(accepted),
        "rejected_event_count": len(rejected),
        "accepted_manifest_sha256": _canonical_sha256(accepted_inventory),
        "rejected_manifest_sha256": _canonical_sha256(rejected_inventory),
        "final_state_sha256": _canonical_sha256(final_rows),
        "final_state_rows": len(final_rows),
        "records_inserted": 4,
        "records_updated": 2,
        "records_deleted": 2,
    }


def run_flink_job(
    *,
    events: tuple[dict[str, Any], ...],
    work_dir: Path,
    jar_path: Path,
    flink_image: str,
    flink_image_id: str,
    timeout: int,
) -> tuple[dict[str, Any], str]:
    relative = work_dir.relative_to(REPO_ROOT)
    input_path = work_dir / "events.tsv"
    checkpoints = work_dir / "checkpoints"
    accepted = work_dir / "bronze/v1/accepted"
    rejected = work_dir / "bronze/v1/rejected"
    checkpoints.mkdir(parents=True, exist_ok=True)
    mount = f"{REPO_ROOT}:/workspace"
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        mount,
        "-w",
        "/workspace",
        flink_image,
        "flink",
        "run",
        "-t",
        "local",
        "-Dparallelism.default=1",
        "-Dtaskmanager.numberOfTaskSlots=1",
        _container_path(jar_path),
        "--input",
        _container_path(input_path),
        "--checkpoints",
        f"file://{_container_path(checkpoints)}",
        "--accepted-output",
        f"file://{_container_path(accepted)}",
        "--rejected-output",
        f"file://{_container_path(rejected)}",
        "--out-of-orderness-ms",
        str(OUT_OF_ORDERNESS_MS),
        "--fail-after-offset",
        str(FAIL_AFTER_OFFSET),
    ]
    completed = _run_command(command, timeout=timeout, stage="run Flink stream job")
    runtime_log = f"{completed.stdout}\n{completed.stderr}"
    verification = verify_flink_output(
        events=events,
        accepted_root=accepted,
        rejected_root=rejected,
        runtime_log=runtime_log,
    )
    verification["runtime_image"] = flink_image
    verification["runtime_image_id"] = flink_image_id
    verification["job_source_sha256"] = _sha256_file(JAVA_SOURCE)
    verification["job_jar_sha256"] = _sha256_file(jar_path)
    verification["target_version"] = f"bronze/v1/{relative.name}"
    return verification, runtime_log


def _sync_definition(
    sync_definition_version_id: UUID,
    platform_definition_version_id: UUID,
    namespace: str,
    source_slice_sha256: str,
    runtime_image: str,
    runtime_image_id: str,
    job_source_sha256: str,
    created_at: datetime,
) -> SourceSyncDefinitionVersion:
    values: dict[str, Any] = {
        "tenant_id": "local-dev",
        "sync_definition_urn": (
            f"gda://local-dev/sync_definition/chongqing-osm-flink-{namespace}"
        ),
        "sync_definition_version_id": sync_definition_version_id,
        "platform_definition_version_id": platform_definition_version_id,
        "source_resource_urn": "gda://local-dev/data_product/chongqing-osm-roads",
        "source_definition_fingerprint": DEFAULT_SOURCE_PRODUCT_SHA256,
        "target_resource_urn": f"gda://local-dev/table/{namespace}",
        "mode": "incremental",
        "write_disposition": "merge",
        "cursor_kind": "provider_token",
        "cursor_field": None,
        "primary_keys": ("road_id",),
        "delete_mode": "hard_delete",
        "config": {
            "provider": "flink-filesystem",
            "runtime": runtime_image,
            "runtime_image_id": runtime_image_id,
            "job_source_sha256": job_source_sha256,
            "event_time_field": "event_time_ms",
            "watermark_out_of_orderness_ms": OUT_OF_ORDERNESS_MS,
            "checkpoint_interval_ms": 300,
            "source_slice_sha256": source_slice_sha256,
            "acceptance_scope": "isolated",
        },
    }
    return SourceSyncDefinitionVersion(
        **values,
        definition_sha256=source_sync_definition_fingerprint(**values),
        created_by=WORKLOAD,
        created_at=created_at,
    )


def _commit_from_verification(
    *,
    sync_definition_version_id: UUID,
    run_id: UUID,
    source_slice_sha256: str,
    verification: dict[str, Any],
    committed_at: datetime,
) -> SourceSyncCommit:
    previous_cursor = {"event_offset": 0, "watermark_ms": None}
    next_cursor = {
        "event_offset": 10,
        "watermark_ms": EVENT_EPOCH_MS + 31_000,
        "source_slice_sha256": source_slice_sha256,
    }
    values: dict[str, Any] = {
        "tenant_id": "local-dev",
        "sync_commit_id": uuid4(),
        "sync_definition_version_id": sync_definition_version_id,
        "run_id": run_id,
        "from_state_version": 0,
        "to_state_version": 1,
        "previous_cursor": previous_cursor,
        "next_cursor": next_cursor,
        "source_slice_sha256": source_slice_sha256,
        "target_commit_ref": {
            "provider": "flink-filesystem",
            "runtime_image": verification["runtime_image"],
            "runtime_image_id": verification["runtime_image_id"],
            "job_source_sha256": verification["job_source_sha256"],
            "job_jar_sha256": verification["job_jar_sha256"],
            "target_version": verification["target_version"],
            "completed_checkpoint_ids": [
                item["checkpoint_id"] for item in verification["checkpoints"]
            ],
            "accepted_manifest_sha256": verification["accepted_manifest_sha256"],
            "rejected_manifest_sha256": verification["rejected_manifest_sha256"],
        },
        "target_content_sha256": verification["final_state_sha256"],
        "records_read": 10,
        "records_inserted": verification["records_inserted"],
        "records_updated": verification["records_updated"],
        "records_deleted": verification["records_deleted"],
        "records_output": verification["final_state_rows"],
        "committed_by": WORKLOAD,
        "committed_at": committed_at,
    }
    return SourceSyncCommit(
        **values,
        previous_cursor_sha256=canonical_json_fingerprint(previous_cursor),
        next_cursor_sha256=canonical_json_fingerprint(next_cursor),
        commit_sha256=source_sync_commit_fingerprint(**values),
    )


def _certify(
    engine,
    args: argparse.Namespace,
    *,
    namespace: str,
    work_dir: Path,
) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    events, source = build_event_slice(args.source)
    event_payload = render_event_slice(events)
    source_slice_sha256 = _sha256_bytes(event_payload)
    (work_dir / "events.tsv").write_bytes(event_payload)
    jar_path = compile_flink_job(
        work_dir=work_dir,
        flink_image=args.flink_image,
        jdk_image=args.jdk_image,
        java_home=args.java_home,
        timeout=args.timeout_seconds,
    )
    flink_image_id = docker_image_id(args.flink_image, timeout=args.timeout_seconds)
    job_source_sha256 = _sha256_file(JAVA_SOURCE)

    platform_definition_id = uuid4()
    sync_definition_version_id = uuid4()
    gateway = PlatformGateway(engine)
    authority = SourceSyncAuthority(engine)
    gateway.register_definition(
        _definition_registration(
            "local-dev",
            platform_definition_id,
            f"chongqing-osm-flink-{namespace}",
            now,
        )
    )
    definition = _sync_definition(
        sync_definition_version_id,
        platform_definition_id,
        namespace,
        source_slice_sha256,
        args.flink_image,
        flink_image_id,
        job_source_sha256,
        now,
    )
    initial_cursor = {"event_offset": 0, "watermark_ms": None}
    definition_write = authority.create_definition(
        definition,
        owner_ref="team:data-platform",
        initial_cursor=initial_cursor,
    )
    primary_run_id = uuid4()
    replay_run_id = uuid4()
    for index, (phase, run_id) in enumerate(
        (("primary", primary_run_id), ("replay", replay_run_id)),
        start=1,
    ):
        _submit_run(
            gateway,
            _run(
                "local-dev",
                run_id,
                platform_definition_id,
                now + timedelta(seconds=index),
                sequence=f"{namespace}:{phase}",
            ),
        )

    next_cursor = {
        "event_offset": len(events),
        "watermark_ms": EVENT_EPOCH_MS + 31_000,
        "source_slice_sha256": source_slice_sha256,
    }
    preflight = authority.find_source_slice_commit(
        "local-dev",
        sync_definition_version_id,
        previous_cursor=initial_cursor,
        next_cursor=next_cursor,
        source_slice_sha256=source_slice_sha256,
    )
    verification, _runtime_log = run_flink_job(
        events=events,
        work_dir=work_dir,
        jar_path=jar_path,
        flink_image=args.flink_image,
        flink_image_id=flink_image_id,
        timeout=args.timeout_seconds,
    )
    if verification["status"] != "passed":
        raise RuntimeError(f"Flink output verification failed: {verification['checks']}")
    commit = _commit_from_verification(
        sync_definition_version_id=sync_definition_version_id,
        run_id=primary_run_id,
        source_slice_sha256=source_slice_sha256,
        verification=verification,
        committed_at=datetime.now(UTC),
    )
    commit_write = authority.commit(commit)
    replay_preflight = authority.find_source_slice_commit(
        "local-dev",
        sync_definition_version_id,
        previous_cursor=initial_cursor,
        next_cursor=next_cursor,
        source_slice_sha256=source_slice_sha256,
    )
    replay_values = commit.model_dump(mode="python")
    replay_values.update(
        {
            "sync_commit_id": uuid4(),
            "run_id": replay_run_id,
            "committed_at": datetime.now(UTC),
        }
    )
    replay_values["commit_sha256"] = source_sync_commit_fingerprint(
        **{
            key: value
            for key, value in replay_values.items()
            if key
            not in {
                "previous_cursor_sha256",
                "next_cursor_sha256",
                "commit_sha256",
            }
        }
    )
    replay_write = authority.commit(SourceSyncCommit(**replay_values))
    checkpoint = authority.get_checkpoint("local-dev", sync_definition_version_id)
    commits = authority.commits("local-dev", sync_definition_version_id)
    checks = {
        "real_chongqing_osm_rows_bound": (
            source["source_feature_count"] == 50_366
            and source["source_product_sha256"] == DEFAULT_SOURCE_PRODUCT_SHA256
            and len(source["selected_road_ids"]) == 4
        ),
        "event_slice_is_immutable": source_slice_sha256 == _sha256_bytes(event_payload),
        "definition_and_initial_checkpoint_created": (
            definition_write.created
            and definition_write.checkpoint.state_version == 0
            and definition_write.checkpoint.cursor == initial_cursor
        ),
        "provider_preflight_was_empty": preflight is None,
        "flink_checkpoint_restart_and_event_time_passed": all(
            verification["checks"].values()
        ),
        "source_sync_commit_advanced_once": (
            commit_write.created
            and commit_write.checkpoint.state_version == 1
            and commit_write.commit == commit
        ),
        "replay_preflight_skipped_second_flink_write": replay_preflight == commit,
        "cross_run_replay_recovered_commit": (
            not replay_write.created
            and replay_write.commit == commit
            and replay_write.replayed_commit_id == commit.sync_commit_id
        ),
        "checkpoint_and_commit_history_exact": (
            checkpoint.state_version == 1
            and checkpoint.last_sync_commit_id == commit.sync_commit_id
            and len(commits) == 1
        ),
    }
    return {
        "schema": "gda.chongqing_osm_flink_source_sync.acceptance.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "source": {
            **source,
            "event_slice_sha256": source_slice_sha256,
            "events_read": len(events),
        },
        "flink": verification,
        "authority": {
            "sync_definition_version_id": str(sync_definition_version_id),
            "checkpoint": checkpoint.model_dump(mode="json"),
            "commits": [item.model_dump(mode="json") for item in commits],
            "replay_run_id": str(replay_run_id),
            "provider_write_invocations": 1,
        },
        "not_claimed": [
            "PostgreSQL log-based CDC connector",
            "Flink to Iceberg interoperability",
            "production throughput or freshness SLO",
            "multi-cluster high availability",
            "cross-system exactly-once sink",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-url", default="postgresql://127.0.0.1:5433/gis_agent")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--flink-image", default=DEFAULT_FLINK_IMAGE)
    parser.add_argument("--jdk-image", default=DEFAULT_JDK_IMAGE)
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
    namespace = f"gda_flink_cert_{secrets.token_hex(5)}"
    work_dir = REPO_ROOT / ".tmp/source-sync-certification" / namespace
    sandbox = _PostgresDatabaseSandbox(admin_url)
    report: dict[str, Any] | None = None
    error: str | None = None
    cleanup: dict[str, bool] = {}
    main_counts_before = _main_sync_counts(admin_url)
    work_dir.mkdir(parents=True, exist_ok=False)
    try:
        sandbox.setup()
        if sandbox.engine is None:
            raise RuntimeError("certification database engine was not created")
        report = _certify(
            sandbox.engine,
            args,
            namespace=namespace,
            work_dir=work_dir,
        )
        report["sandbox"] = {"database": sandbox.database, "persistent": False}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup.update(sandbox.cleanup())
        shutil.rmtree(work_dir)
        cleanup["work_directory_removed"] = not work_dir.exists()
    main_counts_after = _main_sync_counts(admin_url)
    cleanup["main_sync_tables_unchanged_empty"] = (
        main_counts_before == (0, 0, 0) and main_counts_after == (0, 0, 0)
    )
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_flink_source_sync.acceptance.v1",
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    if not all(cleanup.values()):
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
