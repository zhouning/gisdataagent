#!/usr/bin/env python3
"""Certify approval-bound, atomic architecture successor adoption."""

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
    / "data-architecture-successor-adoption"
    / "acceptance-report.json"
)
POSTGIS_TEST = "data_agent/test_architecture_successor_adoption_postgis.py"


def _run_test(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["POSTGIS_SUCCESSOR_DATABASE_URL"] = database_url
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
        versions = connection.execute(
            text(
                "SELECT count(*) AS total, "
                "count(*) FILTER (WHERE predecessor_version_id IS NULL) AS roots, "
                "count(*) FILTER (WHERE predecessor_version_id IS NOT NULL) "
                "AS successors, count(DISTINCT content_sha256) AS content_snapshots, "
                "count(DISTINCT version_key) AS version_keys "
                "FROM gda_control.resource_version"
            )
        ).one()
        authority = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM gda_control.schema_version) AS schemas, "
                "(SELECT count(*) FROM gda_control.data_contract_version) "
                "AS contracts, "
                "(SELECT count(*) FROM gda_control.physical_location) "
                "AS locations, "
                "(SELECT count(*) FROM "
                "gda_control.resource_version_architecture_binding) AS bindings"
            )
        ).one()
        approval = connection.execute(
            text(
                "SELECT count(*) AS cases, "
                "count(*) FILTER (WHERE status = 'approved') AS approved, "
                "count(DISTINCT decided_by) AS human_deciders, "
                "count(*) FILTER (WHERE requester_subject = decided_by) "
                "AS self_approvals, "
                "count(*) FILTER (WHERE action = "
                "'data_architecture.assessed_change_review' AND "
                "request_context->'successor_blockers' = "
                "'[\"new_content_snapshot_required\","
                "\"successor_data_contract_required\"]'::jsonb) "
                "AS assessed_with_blockers, "
                "count(*) FILTER (WHERE action = "
                "'data_architecture.create_successor_version' AND "
                "target_fingerprint = request_context->>'plan_sha256' AND "
                "request_context->'cleared_blockers' = "
                "'[\"new_content_snapshot_required\","
                "\"successor_data_contract_required\"]'::jsonb) "
                "AS adoption_with_cleared_blockers "
                "FROM gda_control.approval_case"
            )
        ).one()
        approval_events = int(
            connection.execute(
                text("SELECT count(*) FROM gda_control.approval_case_event")
            ).scalar_one()
        )
        lineage = connection.execute(
            text(
                "SELECT count(*) AS events, "
                "count(*) FILTER (WHERE event_type = 'derive' AND "
                "facets->>'operation' = 'create_successor_version' AND "
                "facets ? 'architecture_successor_plan_sha256') "
                "AS successor_events "
                "FROM gda_control.lineage_event"
            )
        ).one()
        observations = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM "
                    "gda_control.architecture_provider_observation"
                )
            ).scalar_one()
        )
        schema_artifacts = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM gda_control.artifact WHERE media_type = "
                    "'application/vnd.gda.postgis-schema-snapshot+json'"
                )
            ).scalar_one()
        )
        adoption_lock_triggers = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal "
                    "AND tgname IN ("
                    "'trg_gda_architecture_observation_adoption_lock', "
                    "'trg_gda_architecture_successor_adoption_lock')"
                )
            ).scalar_one()
        )
        rls = {
            row.relname: {
                "enabled": bool(row.relrowsecurity),
                "forced": bool(row.relforcerowsecurity),
            }
            for row in connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE oid IN ("
                    "'gda_control.resource_version'::regclass, "
                    "'gda_control.schema_version'::regclass, "
                    "'gda_control.data_contract_version'::regclass, "
                    "'gda_control.physical_location'::regclass, "
                    "'gda_control.resource_version_architecture_binding'::regclass, "
                    "'gda_control.architecture_provider_observation'::regclass, "
                    "'gda_control.approval_case'::regclass, "
                    "'gda_control.lineage_event'::regclass)"
                )
            )
        }
        postgis_version = connection.execute(
            text("SELECT postgis_lib_version()")
        ).scalar_one()
    return {
        "resource_versions": {
            "total": int(versions.total),
            "root_count": int(versions.roots),
            "successor_count": int(versions.successors),
            "distinct_content_snapshot_count": int(versions.content_snapshots),
            "distinct_version_key_count": int(versions.version_keys),
        },
        "architecture_authority": {
            "schema_version": int(authority.schemas),
            "data_contract_version": int(authority.contracts),
            "physical_location": int(authority.locations),
            "architecture_binding": int(authority.bindings),
        },
        "approval": {
            "case_count": int(approval.cases),
            "approved_count": int(approval.approved),
            "human_decider_count": int(approval.human_deciders),
            "self_approval_count": int(approval.self_approvals),
            "assessed_with_blockers_count": int(approval.assessed_with_blockers),
            "adoption_with_cleared_blockers_count": int(
                approval.adoption_with_cleared_blockers
            ),
            "event_count": approval_events,
        },
        "lineage": {
            "event_count": int(lineage.events),
            "successor_event_count": int(lineage.successor_events),
        },
        "provider_observation_count": observations,
        "schema_artifact_count": schema_artifacts,
        "adoption_lock_trigger_count": adoption_lock_triggers,
        "rls": rls,
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
                f"PostGIS architecture successor adoption failed:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        evidence = _collect_evidence(engine)
        postgres_version = _docker(
            "exec",
            container,
            "psql",
            "-U",
            "postgres",
            "-Atc",
            "SHOW server_version",
        ).stdout.strip()
        checks = {
            "postgis_test_passed": "1 passed" in result.stdout,
            "one_successor_was_created": evidence["resource_versions"]
            == {
                "total": 2,
                "root_count": 1,
                "successor_count": 1,
                "distinct_content_snapshot_count": 2,
                "distinct_version_key_count": 2,
            },
            "successor_architecture_is_complete": all(
                count == 2 for count in evidence["architecture_authority"].values()
            ),
            "assessment_and_adoption_are_separate_human_decisions": (
                evidence["approval"]
                == {
                    "case_count": 2,
                    "approved_count": 2,
                    "human_decider_count": 2,
                    "self_approval_count": 0,
                    "assessed_with_blockers_count": 1,
                    "adoption_with_cleared_blockers_count": 1,
                    "event_count": 4,
                }
            ),
            "predecessor_successor_lineage_is_immutable": (
                evidence["lineage"]
                == {"event_count": 1, "successor_event_count": 1}
            ),
            "latest_observation_is_serialized_with_adoption": (
                evidence["provider_observation_count"] == 3
                and evidence["adoption_lock_trigger_count"] == 2
            ),
            "schema_evidence_remains_external": (
                evidence["schema_artifact_count"] == 2
            ),
            "authority_is_tenant_scoped": all(
                value["enabled"] and value["forced"]
                for value in evidence["rls"].values()
            ),
        }
        report = {
            "schema_version": "gda.architecture_successor_adoption.acceptance.v1",
            "postgis_image": image,
            "postgres_version": postgres_version,
            "test": POSTGIS_TEST,
            "test_output": result.stdout.strip(),
            "evidence": evidence,
            "checks": checks,
            "passed": all(checks.values()),
        }
        if not report["passed"]:
            raise RuntimeError(f"architecture successor checks failed: {checks}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=True, indent=2) + "\n",
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
    report = certify(args.image, args.report)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
