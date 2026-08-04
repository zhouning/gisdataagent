#!/usr/bin/env python3
"""Certify PostGIS schema compatibility and lineage-bound change review."""

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
    REPO_ROOT / ".tmp" / "data-architecture-change-assessment" / "acceptance-report.json"
)
POSTGIS_TEST = "data_agent/test_architecture_change_assessment_postgis.py"


def _run_test(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["POSTGIS_ASSESSMENT_DATABASE_URL"] = database_url
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
        artifact_summary = connection.execute(
            text(
                "SELECT count(*) AS artifacts, "
                "count(DISTINCT content_sha256) AS distinct_content, "
                "count(*) FILTER (WHERE media_type = "
                "'application/vnd.gda.postgis-schema-snapshot+json') "
                "AS correct_media_type, "
                "count(*) FILTER (WHERE artifact_role = 'evidence') "
                "AS evidence_role, "
                "count(*) FILTER (WHERE "
                "(SELECT count(*) FROM jsonb_object_keys(manifest)) = 4 "
                "AND manifest ?& ARRAY['schema','observation_id',"
                "'observation_sha256','snapshot_sha256']::text[]) "
                "AS bounded_manifests "
                "FROM gda_control.artifact"
            )
        ).one()
        case_status_counts = {
            row.status: int(row.count)
            for row in connection.execute(
                text(
                    "SELECT status, count(*) AS count "
                    "FROM gda_control.approval_case "
                    "WHERE action = 'data_architecture.assessed_change_review' "
                    "GROUP BY status ORDER BY status"
                )
            )
        }
        compatibility_counts = {
            row.verdict: int(row.count)
            for row in connection.execute(
                text(
                    "SELECT request_context->>'compatibility_verdict' AS verdict, "
                    "count(*) AS count FROM gda_control.approval_case "
                    "WHERE action = 'data_architecture.assessed_change_review' "
                    "GROUP BY request_context->>'compatibility_verdict' "
                    "ORDER BY verdict"
                )
            )
        }
        case_summary = connection.execute(
            text(
                "SELECT count(*) AS cases, "
                "count(DISTINCT target_fingerprint) AS fingerprints, "
                "count(DISTINCT request_context->>'compatibility_assessment_sha256') "
                "AS compatibility_assessments, "
                "count(DISTINCT request_context->>'lineage_impact_sha256') "
                "AS lineage_assessments, "
                "count(*) FILTER (WHERE request_context->'successor_blockers' = "
                '\'["new_content_snapshot_required",'
                '"successor_data_contract_required"]\'::jsonb) '
                "AS blocked_successors, "
                "count(*) FILTER (WHERE request_context::text ~ "
                "'(zoning_code|land_use|columns|constraints)') "
                "AS leaked_schema_details "
                "FROM gda_control.approval_case "
                "WHERE action = 'data_architecture.assessed_change_review'"
            )
        ).one()
        approval_event_count = int(
            connection.execute(
                text("SELECT count(*) FROM gda_control.approval_case_event")
            ).scalar_one()
        )
        lineage_count = int(
            connection.execute(text("SELECT count(*) FROM gda_control.lineage_event")).scalar_one()
        )
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
        original_version_count = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM gda_control.resource_version AS candidate "
                    "WHERE candidate.resource_urn = ("
                    "SELECT bound.resource_urn "
                    "FROM gda_control.resource_version_architecture_binding AS binding "
                    "JOIN gda_control.resource_version AS bound "
                    "ON bound.tenant_id = binding.tenant_id "
                    "AND bound.resource_version_id = binding.resource_version_id "
                    "LIMIT 1)"
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
                    "'gda_control.artifact'::regclass, "
                    "'gda_control.approval_case'::regclass, "
                    "'gda_control.approval_case_event'::regclass, "
                    "'gda_control.architecture_provider_observation'::regclass, "
                    "'gda_control.lineage_event'::regclass)"
                )
            )
        }
        postgis_version = connection.execute(text("SELECT postgis_lib_version()")).scalar_one()
    return {
        "observation_counts": observation_counts,
        "schema_artifacts": {
            "count": int(artifact_summary.artifacts),
            "distinct_content_count": int(artifact_summary.distinct_content),
            "correct_media_type_count": int(artifact_summary.correct_media_type),
            "evidence_role_count": int(artifact_summary.evidence_role),
            "bounded_manifest_count": int(artifact_summary.bounded_manifests),
        },
        "approval": {
            "status_counts": case_status_counts,
            "compatibility_counts": compatibility_counts,
            "case_count": int(case_summary.cases),
            "distinct_target_fingerprint_count": int(case_summary.fingerprints),
            "compatibility_assessment_count": int(case_summary.compatibility_assessments),
            "lineage_assessment_count": int(case_summary.lineage_assessments),
            "blocked_successor_count": int(case_summary.blocked_successors),
            "leaked_schema_detail_count": int(case_summary.leaked_schema_details),
            "event_count": approval_event_count,
        },
        "lineage_event_count": lineage_count,
        "authority_counts": {
            "schema_version": int(authority_counts.schemas),
            "data_contract_version": int(authority_counts.contracts),
            "physical_location": int(authority_counts.locations),
            "architecture_binding": int(authority_counts.bindings),
        },
        "original_resource_version_count": original_version_count,
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
                f"PostGIS architecture change assessment failed:\n{result.stdout}\n{result.stderr}"
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
            "three_schema_observations_recorded": (
                evidence["observation_counts"] == {"present": 3}
            ),
            "schema_evidence_is_external_and_bounded": all(
                evidence["schema_artifacts"][key] == 3
                for key in (
                    "count",
                    "distinct_content_count",
                    "correct_media_type_count",
                    "evidence_role_count",
                    "bounded_manifest_count",
                )
            ),
            "compatibility_classifies_additive_and_breaking": (
                evidence["approval"]["compatibility_counts"]
                == {"backward_compatible": 1, "breaking": 1}
                and evidence["approval"]["compatibility_assessment_count"] == 2
            ),
            "lineage_impact_is_bound": (
                evidence["lineage_event_count"] == 1
                and evidence["approval"]["lineage_assessment_count"] == 1
            ),
            "assessed_cases_require_human_lifecycle": (
                evidence["approval"]["status_counts"] == {"approved": 1, "pending": 1}
                and evidence["approval"]["case_count"] == 2
                and evidence["approval"]["distinct_target_fingerprint_count"] == 2
                and evidence["approval"]["event_count"] == 3
            ),
            "successor_creation_remains_blocked": (
                evidence["approval"]["blocked_successor_count"] == 2
                and evidence["original_resource_version_count"] == 1
                and all(count == 1 for count in evidence["authority_counts"].values())
            ),
            "approval_context_has_no_schema_details": (
                evidence["approval"]["leaked_schema_detail_count"] == 0
            ),
            "evidence_and_decisions_are_tenant_scoped": all(
                value["enabled"] and value["forced"] for value in evidence["rls"].values()
            ),
        }
        report = {
            "schema_version": "gda.architecture_change_assessment.acceptance.v1",
            "postgis_image": image,
            "postgres_version": postgres_version,
            "test": POSTGIS_TEST,
            "test_output": result.stdout.strip(),
            "evidence": evidence,
            "checks": checks,
            "passed": all(checks.values()),
        }
        if not report["passed"]:
            raise RuntimeError(f"architecture assessment checks failed: {checks}")
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
