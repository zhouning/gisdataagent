#!/usr/bin/env python3
"""Certify the approval-bound JQDLTB candidate-to-product release gate."""

from __future__ import annotations

import argparse
import hashlib
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
from sqlalchemy.exc import DBAPIError

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    REPO_ROOT / ".tmp" / "jqdltb-data-product-release" / "acceptance-report.json"
)
POSTGRES_TEST = "data_agent/test_jqdltb_data_product_release_postgres.py"


def _run_test(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["JQDLTB_RELEASE_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", POSTGRES_TEST],
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
                "(SELECT count(*) FROM gda_control.platform_run) AS runs, "
                "(SELECT count(*) FROM gda_control.artifact) AS artifacts, "
                "(SELECT count(*) FROM gda_control.quality_result) AS quality_results, "
                "(SELECT count(*) FROM gda_control.lineage_event) AS lineage_events, "
                "(SELECT count(*) FROM gda_control.approval_case) AS approvals, "
                "(SELECT count(*) FROM gda_control.approval_case "
                " WHERE status = 'approved') AS approved, "
                "(SELECT count(*) FROM gda_control.data_product_version) AS versions, "
                "(SELECT count(*) FROM gda_control.jqdltb_data_product_release) "
                "AS releases, "
                "(SELECT count(*) FROM gda_control.data_product_event) AS product_events"
            )
        ).one()
        release = connection.execute(
            text(
                """
                SELECT tenant_id, release_plan_sha256, decision_packet_sha256,
                       operating_contract,
                       output_artifact_id, quality_result_id,
                       quality_evidence_artifact_id, lineage_event_id,
                       transformation_approval_case_ref,
                       release_approval_case_ref
                  FROM gda_control.jqdltb_data_product_release
                """
            )
        ).mappings().one()
        graph = connection.execute(
            text(
                """
                SELECT
                    run.status = 'succeeded' AS run_succeeded,
                    output.run_id = release.run_id AS output_same_run,
                    output.resource_version_id = release.output_resource_version_id
                        AS output_same_version,
                    quality.run_id = release.run_id AS quality_same_run,
                    quality.resource_version_id = release.output_resource_version_id
                        AS quality_same_version,
                    quality.verdict = 'passed' AS quality_passed,
                    quality.evidence_artifact_id = release.quality_evidence_artifact_id
                        AS quality_evidence_bound,
                    lineage.run_id = release.run_id AS lineage_same_run,
                    lineage.source_resource_version_id =
                        release.source_resource_version_id AS lineage_same_source,
                    lineage.target_resource_version_id =
                        release.output_resource_version_id AS lineage_same_output,
                    lineage.artifact_id = release.output_artifact_id
                        AS lineage_same_artifact,
                    transform_case.status = 'approved'
                        AND transform_case.action = 'jqdltb.transform'
                        AS transformation_approved,
                    release_case.status = 'approved'
                        AND release_case.action = 'data_product.publish_jqdltb'
                        AND release_case.target_fingerprint = release.release_plan_sha256
                        AS release_approved,
                    version.mapping_contract->>'schema' =
                        'gda.jqdltb_mapping_binding.v1' AS typed_mapping_bound,
                    version.mapping_contract->>'transformation_approval_case_ref' =
                        release.transformation_approval_case_ref
                        AS version_transformation_case_bound,
                    version.distribution_manifest->>'release_approval_case_ref' =
                        release.release_approval_case_ref
                        AS version_release_case_bound,
                    release.decision_packet_sha256 IS NOT NULL
                        AS decision_packet_present,
                    version.mapping_contract->>'decision_packet_sha256' =
                        release.decision_packet_sha256
                        AS mapping_packet_bound,
                    version.distribution_manifest->>'decision_packet_sha256' =
                        release.decision_packet_sha256
                        AS distribution_packet_bound,
                    release_case.request_context->>'decision_packet_sha256' =
                        release.decision_packet_sha256
                        AS approval_packet_bound,
                    product.current_version_id = release.data_product_version_id
                        AS release_is_current
                FROM gda_control.jqdltb_data_product_release release
                JOIN gda_control.platform_run run
                  ON run.tenant_id = release.tenant_id
                 AND run.run_id = release.run_id
                JOIN gda_control.artifact output
                  ON output.tenant_id = release.tenant_id
                 AND output.artifact_id = release.output_artifact_id
                JOIN gda_control.quality_result quality
                  ON quality.tenant_id = release.tenant_id
                 AND quality.quality_result_id = release.quality_result_id
                JOIN gda_control.lineage_event lineage
                  ON lineage.tenant_id = release.tenant_id
                 AND lineage.lineage_event_id = release.lineage_event_id
                JOIN gda_control.approval_case transform_case
                  ON transform_case.tenant_id = release.tenant_id
                 AND transform_case.approval_case_ref =
                     release.transformation_approval_case_ref
                JOIN gda_control.approval_case release_case
                  ON release_case.tenant_id = release.tenant_id
                 AND release_case.approval_case_ref = release.release_approval_case_ref
                JOIN gda_control.data_product_version version
                  ON version.tenant_id = release.tenant_id
                 AND version.data_product_version_id =
                     release.data_product_version_id
                JOIN gda_control.data_product product
                  ON product.tenant_id = release.tenant_id
                 AND product.product_urn = release.product_urn
                """
            )
        ).mappings().one()
        approval_actions = {
            row.action: int(row.total)
            for row in connection.execute(
                text(
                    "SELECT action, count(*) AS total "
                    "FROM gda_control.approval_case "
                    "WHERE status = 'approved' GROUP BY action ORDER BY action"
                )
            )
        }
        trigger = connection.execute(
            text(
                "SELECT tgdeferrable, tginitdeferred FROM pg_trigger "
                "WHERE tgname = 'trg_gda_jqdltb_product_release_required'"
            )
        ).one()
        packet_trigger = connection.execute(
            text(
                "SELECT tgdeferrable, tginitdeferred FROM pg_trigger "
                "WHERE tgname = "
                "'trg_gda_jqdltb_decision_packet_release_binding'"
            )
        ).one()
        immutable_trigger_count = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE NOT tgisinternal "
                    "AND tgname = 'trg_gda_jqdltb_release_immutable' "
                    "AND tgrelid = "
                    "'gda_control.jqdltb_data_product_release'::regclass"
                )
            ).scalar_one()
        )
        relation = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'gda_control.jqdltb_data_product_release'::regclass"
            )
        ).one()
        privileges = connection.execute(
            text(
                "SELECT "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.jqdltb_data_product_release', 'SELECT,INSERT'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.jqdltb_data_product_release', 'UPDATE'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.jqdltb_data_product_release', 'DELETE')"
            )
        ).one()
        current_version = connection.execute(
            text(
                "SELECT version.version_key FROM gda_control.data_product product "
                "JOIN gda_control.data_product_version version "
                "ON version.tenant_id = product.tenant_id "
                "AND version.data_product_version_id = product.current_version_id"
            )
        ).scalar_one()
        postgres_version = connection.execute(text("SHOW server_version")).scalar_one()
        postgis_version = connection.execute(
            text("SELECT postgis_lib_version()")
        ).scalar_one()
        try:
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE gda_control.jqdltb_data_product_release "
                        "SET bound_by = 'workload:tampered'"
                    )
                )
            immutable_update_rejected = False
        except DBAPIError:
            immutable_update_rejected = True

        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": "other-tenant"},
        )
        cross_tenant_count = int(
            connection.execute(
                text("SELECT count(*) FROM gda_control.jqdltb_data_product_release")
            ).scalar_one()
        )
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": release["tenant_id"]},
        )
        own_tenant_count = int(
            connection.execute(
                text("SELECT count(*) FROM gda_control.jqdltb_data_product_release")
            ).scalar_one()
        )
        try:
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE gda_control.jqdltb_data_product_release "
                        "SET bound_by = 'workload:tampered'"
                    )
                )
            gateway_update_rejected = False
        except DBAPIError:
            gateway_update_rejected = True
    return {
        "counts": {
            "platform_runs": int(counts.runs),
            "artifacts": int(counts.artifacts),
            "quality_results": int(counts.quality_results),
            "lineage_events": int(counts.lineage_events),
            "approval_cases": int(counts.approvals),
            "approved_cases": int(counts.approved),
            "data_product_versions": int(counts.versions),
            "jqdltb_releases": int(counts.releases),
            "data_product_events": int(counts.product_events),
        },
        "release": dict(release),
        "evidence_graph": dict(graph),
        "approval_actions": approval_actions,
        "release_constraint": {
            "deferrable": bool(trigger.tgdeferrable),
            "initially_deferred": bool(trigger.tginitdeferred),
        },
        "decision_packet_constraint": {
            "deferrable": bool(packet_trigger.tgdeferrable),
            "initially_deferred": bool(packet_trigger.tginitdeferred),
        },
        "release_rls": {
            "enabled": bool(relation.relrowsecurity),
            "forced": bool(relation.relforcerowsecurity),
        },
        "immutable_trigger_count": immutable_trigger_count,
        "gateway_privileges": {
            "select_insert": bool(privileges[0]),
            "update": bool(privileges[1]),
            "delete": bool(privileges[2]),
        },
        "execution_probes": {
            "immutable_update_rejected": immutable_update_rejected,
            "gateway_update_rejected": gateway_update_rejected,
            "own_tenant_release_count": own_tenant_count,
            "cross_tenant_release_count": cross_tenant_count,
        },
        "current_version": current_version,
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
                "JQDLTB DataProduct release certification failed:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        evidence = _collect_evidence(engine)
        operating_contract = evidence["release"]["operating_contract"]
        checks = {
            "postgres_test_passed": "1 passed" in result.stdout,
            "negative_replay_and_concurrency_paths_passed": "1 passed" in result.stdout,
            "one_atomic_release_was_persisted": evidence["counts"]
            == {
                "platform_runs": 1,
                "artifacts": 3,
                "quality_results": 1,
                "lineage_events": 1,
                "approval_cases": 2,
                "approved_cases": 2,
                "data_product_versions": 1,
                "jqdltb_releases": 1,
                "data_product_events": 1,
            },
            "evidence_graph_is_exact": all(evidence["evidence_graph"].values()),
            "two_independent_approval_actions_are_bound": evidence[
                "approval_actions"
            ]
            == {"data_product.publish_jqdltb": 1, "jqdltb.transform": 1},
            "release_plan_and_operating_contract_are_bound": (
                len(evidence["release"]["release_plan_sha256"]) == 64
                and all(
                    operating_contract.get(key)
                    for key in (
                        "business_steward_ref",
                        "license_id",
                        "data_slo_ref",
                        "service_slo_ref",
                        "on_call_ref",
                        "environment_owner_ref",
                        "deployment_profile_ref",
                        "backup_restore_evidence_artifact_id",
                    )
                )
            ),
            "decision_packet_is_bound_across_release_surfaces": (
                len(evidence["release"]["decision_packet_sha256"]) == 64
                and evidence["decision_packet_constraint"]
                == {"deferrable": True, "initially_deferred": True}
                and all(
                    evidence["evidence_graph"][key]
                    for key in (
                        "decision_packet_present",
                        "mapping_packet_bound",
                        "distribution_packet_bound",
                        "approval_packet_bound",
                    )
                )
            ),
            "direct_registry_bypass_is_deferred_and_fail_closed": evidence[
                "release_constraint"
            ]
            == {"deferrable": True, "initially_deferred": True},
            "release_binding_is_tenant_scoped_and_immutable": (
                evidence["release_rls"] == {"enabled": True, "forced": True}
                and evidence["immutable_trigger_count"] == 1
            ),
            "gateway_has_append_only_release_access": evidence[
                "gateway_privileges"
            ]
            == {"select_insert": True, "update": False, "delete": False},
            "rls_and_immutability_are_enforced": evidence["execution_probes"]
            == {
                "immutable_update_rejected": True,
                "gateway_update_rejected": True,
                "own_tenant_release_count": 1,
                "cross_tenant_release_count": 0,
            },
            "released_version_is_current": evidence["current_version"] == "v1.0.0",
        }
        report = {
            "schema_version": "gda.jqdltb_data_product_release.acceptance.v1",
            "scope": "disposable_postgis_contract_certification",
            "production_claim": False,
            "real_business_approval_claim": False,
            "postgis_image": image,
            "test": POSTGRES_TEST,
            "test_output": result.stdout.strip(),
            "evidence": evidence,
            "checks": checks,
            "passed": all(checks.values()),
        }
        if not report["passed"]:
            raise RuntimeError(f"JQDLTB release checks failed: {checks}")
        payload = (
            json.dumps(report, ensure_ascii=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes(payload)
        report_sha256 = hashlib.sha256(payload).hexdigest()
        sha_path = report_path.with_suffix(report_path.suffix + ".sha256")
        sha_path.write_text(
            f"{report_sha256}  {report_path.name}\n",
            encoding="ascii",
        )
        return report | {
            "report_path": str(report_path),
            "report_sha256": report_sha256,
            "report_sha256_path": str(sha_path),
        }
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
