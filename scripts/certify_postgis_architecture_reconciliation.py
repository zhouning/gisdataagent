#!/usr/bin/env python3
"""Certify PostGIS architecture harvesting and reconciliation in isolation."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    REPO_ROOT / ".tmp" / "data-architecture-provider-reconciliation" / "acceptance-report.json"
)
POSTGIS_TEST = "data_agent/test_data_architecture_reconciliation_postgis.py"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _start_postgis(image: str) -> tuple[str, int]:
    container = f"gda-architecture-postgis-{secrets.token_hex(5)}"
    _docker(
        "run",
        "--rm",
        "--detach",
        "--name",
        container,
        "--publish",
        "127.0.0.1::5432",
        "--env",
        "POSTGRES_HOST_AUTH_METHOD=trust",
        image,
    )
    for _ in range(120):
        ready = _docker(
            "exec",
            container,
            "pg_isready",
            "-U",
            "postgres",
            check=False,
        )
        if ready.returncode == 0:
            binding = _docker("port", container, "5432/tcp").stdout.strip()
            return container, int(binding.splitlines()[0].rsplit(":", 1)[1])
        time.sleep(0.25)
    raise RuntimeError("disposable PostGIS did not become ready")


def _wait_for_host_connection(engine) -> None:
    last_error = None
    for _ in range(120):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except DBAPIError as error:
            last_error = error
            engine.dispose()
            time.sleep(0.25)
    raise RuntimeError("PostGIS host port did not become ready") from last_error


def _run_postgis_test(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["POSTGIS_DATABASE_URL"] = database_url
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
        observation_counts = {
            row.object_state: int(row.count)
            for row in connection.execute(
                text(
                    "SELECT object_state, count(*) AS count "
                    "FROM gda_control.architecture_provider_observation "
                    "GROUP BY object_state ORDER BY object_state"
                )
            )
        }
        authority_counts = connection.execute(
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
        rls = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE oid = "
                "'gda_control.architecture_provider_observation'::regclass"
            )
        ).one()
        trigger_count = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE NOT tgisinternal "
                    "AND tgname = 'trg_gda_architecture_observation_immutable' "
                    "AND tgrelid = "
                    "'gda_control.architecture_provider_observation'::regclass"
                )
            ).scalar_one()
        )
        privileges = connection.execute(
            text(
                "SELECT "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.architecture_provider_observation', "
                "'SELECT,INSERT'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.architecture_provider_observation', 'UPDATE'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.architecture_provider_observation', 'DELETE')"
            )
        ).one()
        approval_status_counts = {
            row.status: int(row.count)
            for row in connection.execute(
                text(
                    "SELECT status, count(*) AS count "
                    "FROM gda_control.approval_case "
                    "GROUP BY status ORDER BY status"
                )
            )
        }
        approval_review_counts = {
            row.reconciliation_status: int(row.count)
            for row in connection.execute(
                text(
                    "SELECT request_context->>'reconciliation_status' "
                    "AS reconciliation_status, count(*) AS count "
                    "FROM gda_control.approval_case "
                    "WHERE action = 'data_architecture.change_review' "
                    "GROUP BY request_context->>'reconciliation_status' "
                    "ORDER BY reconciliation_status"
                )
            )
        }
        approval_summary = connection.execute(
            text(
                "SELECT count(*) AS cases, "
                "count(DISTINCT approval_case_ref) AS distinct_cases, "
                "count(DISTINCT target_resource_urn) AS distinct_targets, "
                "count(*) FILTER (WHERE action <> "
                "'data_architecture.change_review') AS wrong_actions, "
                "count(*) FILTER (WHERE status = 'approved' "
                "AND decided_by LIKE 'human:%') AS human_approved, "
                "count(*) FILTER (WHERE "
                "(SELECT count(*) FROM "
                "jsonb_object_keys(request_context)) = 8 "
                "AND request_context ?& ARRAY["
                "'resource_version_id','observation_id','observation_sha256',"
                "'binding_sha256','reconciliation_status',"
                "'candidate_schema_sha256','candidate_location_sha256',"
                "'required_actions']::text[]) AS bounded_contexts, "
                "count(*) FILTER (WHERE split_part(approval_case_ref, '/', 5) = "
                "'architecture-change-' || "
                "replace(request_context->>'observation_id', '-', '')) "
                "AS deterministic_case_refs "
                "FROM gda_control.approval_case"
            )
        ).one()
        approval_event_count = int(
            connection.execute(
                text("SELECT count(*) FROM gda_control.approval_case_event")
            ).scalar_one()
        )
        approval_rls = {
            row.relname: {
                "enabled": bool(row.relrowsecurity),
                "forced": bool(row.relforcerowsecurity),
            }
            for row in connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE oid IN ("
                    "'gda_control.approval_case'::regclass, "
                    "'gda_control.approval_case_event'::regclass)"
                )
            )
        }
        approval_trigger_count = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE NOT tgisinternal AND tgrelid IN ("
                    "'gda_control.approval_case'::regclass, "
                    "'gda_control.approval_case_event'::regclass) "
                    "AND tgname IN ("
                    "'trg_gda_approval_case_update_guard',"
                    "'trg_gda_approval_case_delete_guard',"
                    "'trg_gda_approval_case_event_immutable')"
                )
            ).scalar_one()
        )
        approval_privileges = connection.execute(
            text(
                "SELECT "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.approval_case', 'SELECT,INSERT'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.approval_case', 'UPDATE'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.approval_case', 'DELETE'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.approval_case_event', 'SELECT'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.approval_case_event', 'INSERT,UPDATE,DELETE')"
            )
        ).one()
        provider_table_exists = bool(
            connection.execute(
                text("SELECT to_regclass('provider_geo.parcels') IS NOT NULL")
            ).scalar_one()
        )
        postgis_version = connection.execute(text("SELECT postgis_lib_version()")).scalar_one()
    return {
        "observation_counts": observation_counts,
        "authority_counts": {
            "schema_version": int(authority_counts.schemas),
            "data_contract_version": int(authority_counts.contracts),
            "physical_location": int(authority_counts.locations),
            "architecture_binding": int(authority_counts.bindings),
        },
        "rls": {"enabled": rls[0], "forced": rls[1]},
        "immutable_trigger_count": trigger_count,
        "gateway_privileges": {
            "select_insert": privileges[0],
            "update": privileges[1],
            "delete": privileges[2],
        },
        "approval": {
            "status_counts": approval_status_counts,
            "review_counts": approval_review_counts,
            "case_count": int(approval_summary.cases),
            "distinct_case_count": int(approval_summary.distinct_cases),
            "distinct_target_count": int(approval_summary.distinct_targets),
            "wrong_action_count": int(approval_summary.wrong_actions),
            "human_approved_count": int(approval_summary.human_approved),
            "bounded_context_count": int(approval_summary.bounded_contexts),
            "deterministic_case_ref_count": int(approval_summary.deterministic_case_refs),
            "event_count": approval_event_count,
            "rls": approval_rls,
            "immutable_trigger_count": approval_trigger_count,
            "gateway_privileges": {
                "case_select_insert": approval_privileges[0],
                "case_update": approval_privileges[1],
                "case_delete": approval_privileges[2],
                "event_select": approval_privileges[3],
                "event_mutation": approval_privileges[4],
            },
        },
        "provider_table_exists_after_tombstone": provider_table_exists,
        "postgis_version": postgis_version,
    }


def certify(
    image: str,
    report_path: Path,
    *,
    report_schema: str = "gda.postgis_architecture_reconciliation.acceptance.v1",
) -> dict[str, object]:
    container = ""
    engine = None
    try:
        container, port = _start_postgis(image)
        database_url = f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres"
        engine = create_engine(database_url)
        _wait_for_host_connection(engine)
        result = _run_postgis_test(database_url)
        if result.returncode != 0:
            raise RuntimeError(
                "PostGIS architecture reconciliation test failed:\n"
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
            "present_drifts_and_tombstone_recorded": (
                evidence["observation_counts"] == {"present": 3, "tombstoned": 1}
            ),
            "drift_did_not_mutate_authority": all(
                count == 1 for count in evidence["authority_counts"].values()
            ),
            "rls_enabled_and_forced": all(evidence["rls"].values()),
            "observation_is_immutable": evidence["immutable_trigger_count"] == 1,
            "gateway_is_append_only": (
                evidence["gateway_privileges"]["select_insert"]
                and not evidence["gateway_privileges"]["update"]
                and not evidence["gateway_privileges"]["delete"]
            ),
            "provider_tombstone_is_real": not evidence["provider_table_exists_after_tombstone"],
            "three_reviewable_changes_admitted": (
                evidence["approval"]["review_counts"]
                == {
                    "location_drift": 1,
                    "schema_drift": 1,
                    "tombstoned": 1,
                }
                and evidence["approval"]["case_count"] == 3
                and evidence["approval"]["distinct_case_count"] == 3
                and evidence["approval"]["deterministic_case_ref_count"] == 3
            ),
            "approval_state_requires_human_verdict": (
                evidence["approval"]["status_counts"] == {"approved": 1, "pending": 2}
                and evidence["approval"]["human_approved_count"] == 1
                and evidence["approval"]["event_count"] == 4
            ),
            "approval_scope_is_bounded": (
                evidence["approval"]["distinct_target_count"] == 1
                and evidence["approval"]["wrong_action_count"] == 0
                and evidence["approval"]["bounded_context_count"] == 3
            ),
            "approval_rls_enabled_and_forced": all(
                value["enabled"] and value["forced"]
                for value in evidence["approval"]["rls"].values()
            ),
            "approval_ledger_is_immutable": (evidence["approval"]["immutable_trigger_count"] == 3),
            "approval_gateway_is_least_privilege": (
                evidence["approval"]["gateway_privileges"]["case_select_insert"]
                and not evidence["approval"]["gateway_privileges"]["case_update"]
                and not evidence["approval"]["gateway_privileges"]["case_delete"]
                and evidence["approval"]["gateway_privileges"]["event_select"]
                and not evidence["approval"]["gateway_privileges"]["event_mutation"]
            ),
        }
        report = {
            "schema_version": report_schema,
            "postgis_image": image,
            "postgres_version": postgres_version,
            "test": POSTGIS_TEST,
            "test_output": result.stdout.strip(),
            "evidence": evidence,
            "checks": checks,
            "passed": all(checks.values()),
        }
        if not report["passed"]:
            raise RuntimeError(f"PostGIS architecture checks failed: {checks}")
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
