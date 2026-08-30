#!/usr/bin/env python3
"""Certify fail-closed CDC admission when both PostgreSQL writers remain live."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.certify_chongqing_osm_flink_stream import (
    DEFAULT_SOURCE,
    REPO_ROOT,
)
from scripts.certify_chongqing_osm_postgres_cdc import (
    DEFAULT_NETWORK,
    DEFAULT_POSTGRES_IMAGE,
    CdcPostgresSandbox,
    _container_absent,
    _sql_literal,
    build_cdc_plan,
)
from scripts.certify_chongqing_osm_postgres_cdc_failover import (
    PhysicalStandbySandbox,
    _enable_isolated_physical_replication,
    _physical_replication_observation,
    assess_failover_continuity,
)

DEFAULT_REPORT = (
    REPO_ROOT
    / ".tmp/source-sync-certification/"
    "chongqing-osm-postgres-cdc-split-brain-report.json"
)


def _row(source: Any, road_id: int) -> dict[str, Any]:
    table = source.table if hasattr(source, "table") else source.source.table
    value = source._psql(  # noqa: SLF001 - certification needs source-side evidence
        "SELECT road_id::text || E'\\t' || revision::text || E'\\t' || "
        "road_name_base64 || E'\\t' || geometry_sha256 "
        f"FROM public.{table} WHERE road_id = {road_id};"
    ).strip()
    fields = value.split("\t") if value else []
    if len(fields) != 4:
        raise RuntimeError("split-brain source row is missing")
    return {
        "road_id": int(fields[0]),
        "revision": int(fields[1]),
        "road_name_base64": fields[2],
        "geometry_sha256": fields[3],
    }


def _write_divergent_revision(
    source: Any,
    *,
    road_id: int,
    revision: int,
    geometry_sha256: str,
) -> dict[str, Any]:
    table = source.table if hasattr(source, "table") else source.source.table
    source._psql(  # noqa: SLF001 - certification intentionally writes each side
        f"UPDATE public.{table} SET revision = {revision}, "
        f"geometry_sha256 = {_sql_literal(geometry_sha256)} "
        f"WHERE road_id = {road_id};"
    )
    return {
        "target_lsn": (
            source.current_lsn()
            if hasattr(source, "current_lsn")
            else source.replication_identity()["observation_lsn"]
        ),
        "row": _row(source, road_id),
    }


def _network_exists(network: str) -> bool:
    completed = subprocess.run(
        ["docker", "network", "inspect", network],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return completed.returncode == 0


def run_split_brain_provider(
    *,
    args: argparse.Namespace,
    plan: dict[str, Any],
    token: str,
) -> tuple[dict[str, Any], dict[str, bool]]:
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
    cleanup: dict[str, bool] = {}
    try:
        postgres_start = postgres.start(plan["initial"])
        physical_replication_access = _enable_isolated_physical_replication(postgres)
        # An inactive logical slot is enough to prove that fencing, rather than
        # slot absence alone, is what rejects this promotion.
        postgres._psql(  # noqa: SLF001
            "SELECT * FROM pg_create_logical_replication_slot("
            f"{_sql_literal(postgres.slot)}, 'pgoutput');"
        )
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
        primary_identity = postgres.replication_identity()
        standby_identity = standby.replication_identity()
        primary_slot = postgres.slot_observation()

        # Deliberately promote without stopping or detaching the old primary.
        promotion = standby.promote(timeout=args.promotion_timeout_seconds)
        promoted_identity = promotion["identity"]
        promoted_slot = standby.slot_observation()
        publication_present = standby.publication_present()
        old_primary_write = _write_divergent_revision(
            postgres,
            road_id=int(source_mutation["row"]["road_id"]),
            revision=3,
            geometry_sha256="b" * 64,
        )
        promoted_write = _write_divergent_revision(
            standby,
            road_id=int(source_mutation["row"]["road_id"]),
            revision=4,
            geometry_sha256="c" * 64,
        )
        primary_aliases = _optional_container_aliases(postgres.container, postgres.network)
        promoted_aliases = _optional_container_aliases(standby.container, standby.network)
        fencing = {
            "schema": "gda.postgresql_primary_fencing.v1",
            "mode": "none",
            "old_primary_stopped": False,
            "old_primary_network_detached": False,
            "old_primary_write_probe": {
                "attempted": True,
                "accepted": True,
                "target_lsn": old_primary_write["target_lsn"],
            },
        }
        admission_evidence = {
            "primary_identity": primary_identity,
            "standby_identity_before_promotion": standby_identity,
            "promoted_identity": promoted_identity,
            "primary_slot": primary_slot,
            "promoted_slot": promoted_slot,
            "mutation_replayed_before_promotion": True,
            "primary_stopped_before_promotion": False,
            "fencing": fencing,
            "publication_present_after_promotion": publication_present,
        }
        admission = assess_failover_continuity(admission_evidence)
        checks = {
            "same_physical_cluster_identifier": (
                primary_identity["system_identifier"]
                == standby_identity["system_identifier"]
                == promoted_identity["system_identifier"]
            ),
            "standby_replayed_exact_mutation_before_promotion": (
                standby_replay["row"] == source_mutation["row"]
                and standby_replay["replay_lsn"]
                and promoted_identity["timeline_id"]
                == primary_identity["timeline_id"] + 1
            ),
            "old_primary_remained_writable_after_promotion": (
                old_primary_write["row"]["revision"] == 3
                and old_primary_write["row"]["geometry_sha256"] == "b" * 64
            ),
            "promoted_primary_remained_writable_after_promotion": (
                promoted_write["row"]["revision"] == 4
                and promoted_write["row"]["geometry_sha256"] == "c" * 64
            ),
            "old_and_promoted_rows_diverged": (
                old_primary_write["row"] != promoted_write["row"]
            ),
            "old_primary_alias_remained_attached": (
                source_alias in primary_aliases
                and source_alias not in promoted_aliases
            ),
            "admission_rejected_fail_closed": (
                not admission["admitted"]
                and admission["disposition"] == "rejected_fail_closed"
            ),
            "fencing_reasons_were_present": all(
                reason in admission["reason_codes"]
                for reason in (
                    "postgresql_primary_stop_order_unproven",
                    "postgresql_primary_fencing_mode_unapproved",
                    "postgresql_primary_not_fenced_before_promotion",
                    "postgresql_primary_network_not_fenced_before_promotion",
                    "postgresql_primary_write_fence_probe_failed",
                )
            ),
            "no_alias_transfer_before_admission": source_alias in primary_aliases,
        }
        return (
            {
                "schema": "gda.postgres_cdc_split_brain_provider.negative.v1",
                "status": "passed" if all(checks.values()) else "failed",
                "expected_outcome": "rejected_fail_closed",
                "checks": checks,
                "admission": admission,
                "fencing": fencing,
                "postgres": {
                    **postgres_start,
                    "image": args.postgres_image,
                    "source_alias": source_alias,
                },
                "physical_replication_access": physical_replication_access,
                "basebackup": basebackup,
                "physical_replication": physical_replication,
                "source_mutation": source_mutation,
                "standby_replay": standby_replay,
                "primary_identity": primary_identity,
                "standby_identity_before_promotion": standby_identity,
                "promoted_identity": promoted_identity,
                "primary_slot": primary_slot,
                "promoted_slot": promoted_slot,
                "old_primary_write": old_primary_write,
                "promoted_write": promoted_write,
                "primary_aliases": primary_aliases,
                "promoted_aliases": promoted_aliases,
                "not_claimed": [
                    "automatic fencing or split-brain resolution",
                    "production RPO, RTO or freshness SLO",
                    "logical slot synchronization or automatic CDC resume",
                    "multi-zone or Kubernetes high availability",
                ],
            },
            cleanup,
        )
    finally:
        cleanup.update(standby.cleanup())
        cleanup.update(postgres.cleanup())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--docker-network", default=DEFAULT_NETWORK)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--promotion-timeout-seconds", type=int, default=60)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if not 10 <= args.promotion_timeout_seconds <= 120:
        parser.error("--promotion-timeout-seconds must be between 10 and 120")
    if not _network_exists(args.docker_network):
        parser.error(
            f"Docker network {args.docker_network!r} must exist; "
            "refusing to create a shared network"
        )

    token = secrets.token_hex(5)
    report: dict[str, Any] | None = None
    error: str | None = None
    cleanup: dict[str, bool] = {}
    try:
        report, provider_cleanup = run_split_brain_provider(
            args=args,
            plan=build_cdc_plan(args.source),
            token=token,
        )
        cleanup.update(provider_cleanup)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup["primary_container_removed"] = _container_absent(
            f"gda-cdc-pg-{token}"
        )
        cleanup["standby_container_removed"] = _container_absent(
            f"gda-cdc-standby-{token}"
        )
        cleanup["standby_volume_removed"] = not _volume_exists(
            f"gda-cdc-standby-data-{token}"
        )
    if report is None:
        report = {
            "schema": "gda.postgres_cdc_split_brain_provider.negative.v1",
            "status": "failed",
            "expected_outcome": "rejected_fail_closed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    if error or not cleanup or not all(cleanup.values()):
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


def _optional_container_aliases(name: str, network: str) -> list[str]:
    completed = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .NetworkSettings.Networks}}",
            name,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("split-brain PostgreSQL network metadata is missing")
    networks = json.loads(completed.stdout)
    attachment = networks.get(network)
    if not isinstance(attachment, dict):
        raise RuntimeError("split-brain PostgreSQL network attachment is missing")
    aliases = attachment.get("Aliases") or []
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) for alias in aliases
    ):
        raise RuntimeError("split-brain PostgreSQL network aliases are malformed")
    return sorted(set(aliases))


def _volume_exists(name: str) -> bool:
    completed = subprocess.run(
        ["docker", "volume", "inspect", name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return completed.returncode == 0


if __name__ == "__main__":
    raise SystemExit(main())
