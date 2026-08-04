#!/usr/bin/env python3
"""Certify approval-bound DataProduct release of an architecture successor."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from certify_postgis_architecture_reconciliation import (
    _docker,
    _start_postgis,
    _wait_for_host_connection,
)
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    REPO_ROOT
    / ".tmp"
    / "data-product-architecture-successor-release"
    / "acceptance-report.json"
)
POSTGIS_TEST = "data_agent/test_architecture_successor_data_product_release_postgis.py"


def _run_test(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["POSTGIS_ARCHITECTURE_RELEASE_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", POSTGIS_TEST],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _collect_evidence(engine) -> dict[str, object]:
    with engine.begin() as connection:
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM gda_control.data_product_version) AS versions, "
                "(SELECT count(*) FROM gda_control.data_product_architecture_release) "
                "AS releases, "
                "(SELECT count(*) FROM gda_control.approval_case) AS approvals, "
                "(SELECT count(*) FROM gda_control.approval_case "
                " WHERE status = 'approved') AS approved, "
                "(SELECT count(DISTINCT decided_by) FROM gda_control.approval_case) "
                "AS human_deciders, "
                "(SELECT count(*) FROM gda_control.data_product_event) AS events"
            )
        ).one()
        release = connection.execute(
            text(
                "SELECT release_plan_sha256, architecture_successor_plan_sha256, "
                "architecture_binding_sha256, distribution_artifact_ids, "
                "rollback_target_version_id, release_approval_case_ref "
                "FROM gda_control.data_product_architecture_release"
            )
        ).mappings().one()
        events = {
            row.event_type: int(row.total)
            for row in connection.execute(
                text(
                    "SELECT event_type, count(*) AS total "
                    "FROM gda_control.data_product_event GROUP BY event_type"
                )
            )
        }
        trigger = connection.execute(
            text(
                "SELECT tgdeferrable, tginitdeferred FROM pg_trigger "
                "WHERE tgname = 'trg_gda_product_architecture_release_required'"
            )
        ).one()
        relation = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = "
                "'gda_control.data_product_architecture_release'::regclass"
            )
        ).one()
        current = connection.execute(
            text(
                "SELECT v.version_key FROM gda_control.data_product p "
                "JOIN gda_control.data_product_version v "
                "ON v.tenant_id = p.tenant_id "
                "AND v.data_product_version_id = p.current_version_id"
            )
        ).scalar_one()
        postgres_version = connection.execute(text("SHOW server_version")).scalar_one()
        postgis_version = connection.execute(
            text("SELECT postgis_lib_version()")
        ).scalar_one()
    return {
        "counts": {
            "data_product_versions": int(counts.versions),
            "architecture_releases": int(counts.releases),
            "approval_cases": int(counts.approvals),
            "approved_cases": int(counts.approved),
            "human_deciders": int(counts.human_deciders),
            "data_product_events": int(counts.events),
        },
        "release": dict(release),
        "events": events,
        "release_constraint": {
            "deferrable": bool(trigger.tgdeferrable),
            "initially_deferred": bool(trigger.tginitdeferred),
        },
        "release_rls": {
            "enabled": bool(relation.relrowsecurity),
            "forced": bool(relation.relforcerowsecurity),
        },
        "current_version": current,
        "postgres_version": postgres_version,
        "postgis_version": postgis_version,
    }


def certify(image: str, report_path: Path) -> dict[str, object]:
    container = ""
    engine = None
    try:
        container, port = _start_postgis(image)
        database_url = f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres"
        engine = create_engine(database_url)
        _wait_for_host_connection(engine)
        result = _run_test(database_url)
        if result.returncode != 0:
            raise RuntimeError(
                "architecture successor DataProduct release failed:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        evidence = _collect_evidence(engine)
        checks = {
            "postgis_test_passed": "1 passed" in result.stdout,
            "exactly_one_approved_release_was_persisted": evidence["counts"]
            == {
                "data_product_versions": 2,
                "architecture_releases": 1,
                "approval_cases": 3,
                "approved_cases": 3,
                "human_deciders": 3,
                "data_product_events": 4,
            },
            "publish_rollback_and_promotion_are_audited": evidence["events"]
            == {"published": 1, "advanced": 1, "rolled_back": 1, "promoted": 1},
            "successor_was_restored_after_rehearsal": (
                evidence["current_version"] == "v2.0.0"
            ),
            "release_binding_is_complete": (
                len(evidence["release"]["release_plan_sha256"]) == 64
                and len(
                    evidence["release"]["architecture_successor_plan_sha256"]
                )
                == 64
                and len(evidence["release"]["architecture_binding_sha256"]) == 64
                and len(evidence["release"]["distribution_artifact_ids"]) == 1
                and evidence["release"]["rollback_target_version_id"] is not None
                and evidence["release"]["release_approval_case_ref"] is not None
            ),
            "direct_publish_bypass_is_deferred_and_fail_closed": (
                evidence["release_constraint"]
                == {"deferrable": True, "initially_deferred": True}
            ),
            "release_authority_is_tenant_scoped": evidence["release_rls"]
            == {"enabled": True, "forced": True},
        }
        report = {
            "schema_version": (
                "gda.architecture_successor_data_product_release.acceptance.v1"
            ),
            "postgis_image": image,
            "test": POSTGIS_TEST,
            "test_output": result.stdout.strip(),
            "evidence": evidence,
            "checks": checks,
            "passed": all(checks.values()),
        }
        if not report["passed"]:
            raise RuntimeError(f"architecture successor release checks failed: {checks}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=True, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        return report
    finally:
        if engine is not None:
            engine.dispose()
        if container:
            _docker("rm", "--force", container, check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="postgis/postgis:16-3.4")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    print(
        json.dumps(
            certify(args.image, args.report),
            ensure_ascii=True,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
