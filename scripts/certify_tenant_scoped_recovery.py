#!/usr/bin/env python3
"""Certify tenant-preserving recovery of the platform control ledger.

The acceptance uses one disposable PostGIS container, creates a source database
with two tenants, restores a custom-format dump into a fresh database, and then
checks the restored graph through the least-privilege gateway role.  It is a
recovery evidence slice, not a production RPO/RTO claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.platform_contracts import (
    Artifact,
    ArtifactRole,
    FrameworkAttemptObservation,
    FrameworkKind,
    LineageEvent,
    LineageEventType,
    PlatformDefinitionVersion,
    PlatformRun,
    QualityResult,
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunSuccessEvidence,
    SubjectContext,
    SubjectType,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from data_agent.platform_gateway import (
    DefinitionRegistration,
    GatewayNotFoundError,
    PlatformGateway,
)
from data_agent.platform_runtime.tenant_recovery import (
    build_recovery_manifest,
    compare_recovery_manifests,
    fingerprint_tenant_rows,
    validate_tenant_visibility,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp" / "tenant-recovery" / "acceptance-report.json"
IMAGE = "postgis/postgis:16-3.4"
MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "096_platform_success_verdict.sql",
)
TENANTS = ("recovery-alpha", "recovery-beta")
TABLES = (
    "resource",
    "resource_version",
    "platform_definition_version",
    "platform_run",
    "platform_run_event",
    "framework_attempt_observation",
    "artifact",
    "lineage_event",
    "quality_result",
)
NAMESPACE = UUID("d4acb5a6-4939-5f2e-9b89-e7f5eab64a2a")


def _sql_file(filename: str) -> str:
    # psycopg2 treats percent signs in driver SQL as interpolation markers.
    return (
        (REPO_ROOT / "data_agent" / "migrations" / filename)
        .read_text(encoding="utf-8")
        .replace("%", "%%")
    )


def _docker(
    *args: str, input_bytes: bytes | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=input_bytes, capture_output=True, check=check)


def _wait_for_postgres(container: str) -> None:
    for _ in range(120):
        if _docker("exec", container, "pg_isready", "-U", "postgres", check=False).returncode == 0:
            return
        time.sleep(0.25)
    raise RuntimeError("disposable PostGIS did not become ready")


def _start() -> tuple[str, int]:
    container = f"gda-tenant-recovery-{secrets.token_hex(5)}"
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
        IMAGE,
    )
    _wait_for_postgres(container)
    port_output = _docker("port", container, "5432/tcp").stdout.decode().strip()
    return container, int(port_output.splitlines()[0].rsplit(":", 1)[1])


def _url(port: int, database: str) -> str:
    return f"postgresql://postgres@127.0.0.1:{port}/{database}"


def _create_database(port: int, database: str) -> None:
    admin = create_engine(_url(port, "postgres"))
    try:
        last_error: Exception | None = None
        for _ in range(120):
            try:
                with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                    connection.execute(text(f'CREATE DATABASE "{database}"'))
                return
            except Exception as exc:  # host port can lag container readiness
                last_error = exc
                time.sleep(0.25)
        raise RuntimeError("PostGIS host port did not become ready") from last_error
    finally:
        admin.dispose()


def _bootstrap(port: int, database: str) -> None:
    _create_database(port, database)
    engine = create_engine(_url(port, database))
    try:
        with engine.begin() as connection:
            for filename in MIGRATIONS:
                connection.exec_driver_sql(_sql_file(filename))
    finally:
        engine.dispose()


def _id(tenant: str, label: str) -> UUID:
    return uuid5(NAMESPACE, f"{tenant}:{label}")


def _seed_tenant(engine, tenant: str, ordinal: int) -> dict[str, object]:
    gateway = PlatformGateway(engine)
    now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC) + timedelta(minutes=ordinal)
    definition_id = _id(tenant, "definition")
    source_id = _id(tenant, "source-version")
    output_id = _id(tenant, "output-version")
    run_id = _id(tenant, "run")
    observation_id = _id(tenant, "observation")
    output_artifact_id = _id(tenant, "output-artifact")
    quality_artifact_id = _id(tenant, "quality-artifact")
    quality_id = _id(tenant, "quality")
    lineage_id = _id(tenant, "lineage")
    definition_urn = f"gda://{tenant}/definition/recovery-pipeline"
    source_urn = f"gda://{tenant}/dataset/recovery-source"
    output_urn = f"gda://{tenant}/dataset/recovery-output"
    definition_document = {"pipeline": "tenant-recovery", "ordinal": ordinal}
    input_contract = {"source": source_urn}
    output_contract = {"output": output_urn}
    definition_sha = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="recovery.certify",
        portability_class="portable",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    gateway.register_definition(
        DefinitionRegistration(
            resource=Resource(
                tenant_id=tenant,
                resource_urn=definition_urn,
                resource_kind="definition",
                authority_system="gda",
                authority_locator="recovery/definition",
                owner_ref="team:platform",
            ),
            resource_version=ResourceVersion(
                tenant_id=tenant,
                resource_urn=definition_urn,
                resource_version_id=definition_id,
                version_key="v1",
                content_sha256=definition_sha,
                authority_version_ref={"ordinal": ordinal},
                created_by="workload:recovery-certifier",
                created_at=now,
            ),
            definition=PlatformDefinitionVersion(
                tenant_id=tenant,
                definition_urn=definition_urn,
                definition_version_id=definition_id,
                orchestration_class="dataops",
                capability_id="recovery.certify",
                portability_class="portable",
                definition_document=definition_document,
                input_contract=input_contract,
                output_contract=output_contract,
                definition_sha256=definition_sha,
            ),
        )
    )
    for urn, locator in ((source_urn, "recovery/source"), (output_urn, "recovery/output")):
        gateway.register_resource(
            Resource(
                tenant_id=tenant,
                resource_urn=urn,
                resource_kind="dataset",
                authority_system="gda",
                authority_locator=locator,
                owner_ref="team:platform",
            )
        )
    gateway.register_resource_version(
        ResourceVersion(
            tenant_id=tenant,
            resource_urn=source_urn,
            resource_version_id=source_id,
            version_key="snapshot-1",
            content_sha256="1" * 64,
            authority_version_ref={"snapshot": 1},
            created_by="workload:recovery-certifier",
            created_at=now,
        )
    )
    gateway.register_resource_version(
        ResourceVersion(
            tenant_id=tenant,
            resource_urn=output_urn,
            resource_version_id=output_id,
            version_key="snapshot-1",
            content_sha256="2" * 64,
            authority_version_ref={"snapshot": 1},
            created_by="workload:recovery-certifier",
            created_at=now,
        )
    )
    run = PlatformRun(
        tenant_id=tenant,
        run_id=run_id,
        definition_version_id=definition_id,
        orchestration_class="dataops",
        subject_context=SubjectContext(
            tenant_id=tenant,
            subject_id="recovery-worker",
            subject_type=SubjectType.WORKLOAD,
            roles=("dataops",),
            purpose="recovery certification",
        ),
        input_bindings=(
            ResourceBinding(
                binding_name="source", resource_version_id=source_id, semantic_type="dataset"
            ),
        ),
        idempotency_key="recovery-certification",
        submitted_at=now,
    )
    gateway.submit_run(run)
    dispatched = gateway.transition_run(
        tenant, run_id, 0, "dispatching", "workload:recovery-worker", "provider accepted"
    )
    gateway.transition_run(
        tenant,
        run_id,
        dispatched.state_version,
        "running",
        "workload:recovery-worker",
        "provider started",
    )
    observation_evidence = {
        "schema": "gda.recovery.provider_observation.v1",
        "provider_state": "SUCCESS",
        "ordinal": ordinal,
    }
    observation = FrameworkAttemptObservation(
        tenant_id=tenant,
        observation_id=observation_id,
        run_id=run_id,
        attempt_no=1,
        framework_kind=FrameworkKind.DOLPHINSCHEDULER,
        external_namespace="recovery-certification",
        external_run_id=str(run_id),
        observed_state="success",
        observation_sha256=canonical_json_fingerprint(observation_evidence),
        evidence=observation_evidence,
        observed_at=now,
    )
    gateway.record_attempt(observation)
    output_artifact = Artifact(
        tenant_id=tenant,
        artifact_id=output_artifact_id,
        artifact_key="output",
        artifact_role=ArtifactRole.OUTPUT,
        storage_uri=f"s3://recovery/{tenant}/output.json",
        media_type="application/json",
        content_sha256="2" * 64,
        size_bytes=2,
        run_id=run_id,
        resource_version_id=output_id,
        manifest={"tenant_id": tenant},
        created_by="workload:recovery-worker",
        created_at=now,
    )
    evidence_artifact = Artifact(
        tenant_id=tenant,
        artifact_id=quality_artifact_id,
        artifact_key="quality-evidence",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri=f"s3://recovery/{tenant}/quality.json",
        media_type="application/json",
        content_sha256="3" * 64,
        size_bytes=3,
        run_id=run_id,
        resource_version_id=output_id,
        manifest={"tenant_id": tenant},
        created_by="workload:quality-worker",
        created_at=now,
    )
    gateway.record_artifact(output_artifact)
    gateway.record_artifact(evidence_artifact)
    metrics = {"rows": 1, "tenant": tenant}
    quality = QualityResult(
        tenant_id=tenant,
        quality_result_id=quality_id,
        run_id=run_id,
        resource_version_id=output_id,
        rule_version_ref="recovery-quality:v1",
        verdict="passed",
        metrics=metrics,
        evidence_artifact_id=quality_artifact_id,
        result_sha256=quality_result_fingerprint(
            tenant_id=tenant,
            run_id=run_id,
            resource_version_id=output_id,
            rule_version_ref="recovery-quality:v1",
            verdict="passed",
            metrics=metrics,
            evidence_artifact_id=quality_artifact_id,
            evaluated_by="workload:quality-worker",
            evaluated_at=now,
        ),
        evaluated_by="workload:quality-worker",
        evaluated_at=now,
    )
    gateway.record_quality_result(quality)
    lineage_values = {"tenant": tenant, "source": str(source_id), "target": str(output_id)}
    lineage = LineageEvent(
        tenant_id=tenant,
        lineage_event_id=lineage_id,
        event_type=LineageEventType.DERIVE,
        source_resource_version_id=source_id,
        target_resource_version_id=output_id,
        producer="workload:recovery-worker",
        event_sha256=canonical_json_fingerprint(lineage_values),
        run_id=run_id,
        definition_version_id=definition_id,
        artifact_id=output_artifact_id,
        facets={"schema": "gda.recovery.lineage.v1"},
        occurred_at=now,
    )
    gateway.record_lineage(lineage)
    gateway.finalize_run_success(
        RunSuccessEvidence(
            tenant_id=tenant,
            run_id=run_id,
            attempt_observation_id=observation_id,
            output_artifact_id=output_artifact_id,
            quality_result_id=quality_id,
            lineage_event_id=lineage_id,
            evidence_sha256=run_success_evidence_fingerprint(
                tenant_id=tenant,
                run_id=run_id,
                attempt_observation_id=observation_id,
                output_artifact_id=output_artifact_id,
                quality_result_id=quality_id,
                lineage_event_id=lineage_id,
            ),
        ),
        expected_state_version=2,
        actor_subject="workload:recovery-worker",
        reason="evidence complete",
    )
    return {"tenant_id": tenant, "resource_urn": source_urn, "definition_version_id": definition_id}


def _rows(engine, tenant: str, table: str) -> list[dict[str, object]]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(f"SELECT * FROM gda_control.{table} WHERE tenant_id = :tenant"),
                {"tenant": tenant},
            )
            .mappings()
            .all()
        ]


def _manifest(engine):
    digests = [
        fingerprint_tenant_rows(tenant, table, _rows(engine, tenant, table))
        for tenant in TENANTS
        for table in TABLES
    ]
    return build_recovery_manifest(TENANTS, digests)


def _visibility(engine) -> tuple[dict[str, dict[str, int]], int]:
    result: dict[str, dict[str, int]] = {}
    cross_tenant_rows = 0
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        for tenant in TENANTS:
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"), {"tenant": tenant}
            )
            result[tenant] = {
                table: int(
                    connection.execute(
                        text(f"SELECT count(*) FROM gda_control.{table}")
                    ).scalar_one()
                )
                for table in TABLES
            }
            other = TENANTS[1] if tenant == TENANTS[0] else TENANTS[0]
            cross_tenant_rows += int(
                connection.execute(
                    text("SELECT count(*) FROM gda_control.resource WHERE tenant_id = :other"),
                    {"other": other},
                ).scalar_one()
            )
    return result, cross_tenant_rows


def _cross_tenant_reference_rejected(engine, tenant: str, other: str, source_id: UUID) -> bool:
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"), {"tenant": tenant}
        )
        try:
            with connection.begin_nested():
                connection.execute(
                    text("""
                    INSERT INTO gda_control.resource_version
                        (tenant_id, resource_version_id, resource_urn, version_key,
                         predecessor_version_id, content_sha256, authority_version_ref, created_by)
                    VALUES (:tenant, :version_id, :urn, 'cross-tenant', :predecessor,
                            repeat('f', 64), jsonb_build_object('recovery', true),
                            'workload:recovery-certifier')
                """),
                    {
                        "tenant": tenant,
                        "version_id": _id(tenant, "cross-tenant"),
                        "urn": f"gda://{tenant}/dataset/recovery-source",
                        "predecessor": source_id,
                    },
                )
        except DBAPIError:
            return True
    return False


def certify() -> dict[str, object]:
    container, port = _start()
    source_db = f"gda_recovery_{secrets.token_hex(4)}"
    restored_db = f"gda_restored_{secrets.token_hex(4)}"
    dump_path = REPO_ROOT / ".tmp" / "tenant-recovery" / f"{source_db}.dump"
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _bootstrap(port, source_db)
        source_engine = create_engine(_url(port, source_db))
        try:
            seeded = [
                _seed_tenant(source_engine, tenant, index) for index, tenant in enumerate(TENANTS)
            ]
            source_manifest = _manifest(source_engine)
            source_visibility, source_cross = _visibility(source_engine)
            source_gateway = PlatformGateway(source_engine)
            replay_created = [
                source_gateway.register_resource(
                    Resource(
                        tenant_id=item["tenant_id"],
                        resource_urn=item["resource_urn"],
                        resource_kind="dataset",
                        authority_system="gda",
                        authority_locator="recovery/source",
                        owner_ref="team:platform",
                    )
                ).created
                for item in seeded
            ]
            source_manifest_after_replay = _manifest(source_engine)
            compare_recovery_manifests(source_manifest, source_manifest_after_replay)
            dump = _docker("exec", container, "pg_dump", "-U", "postgres", "-d", source_db, "-Fc")
            if dump.returncode != 0 or not dump.stdout:
                raise RuntimeError("pg_dump failed")
            dump_path.write_bytes(dump.stdout)
            dump_sha256 = hashlib.sha256(dump.stdout).hexdigest()
            _create_database(port, restored_db)
            restore = _docker(
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                restored_db,
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                input_bytes=dump.stdout,
            )
            if restore.returncode != 0:
                raise RuntimeError("pg_restore failed")
            restored_engine = create_engine(_url(port, restored_db))
            try:
                # pg_dump does not include cluster-global role grants.  Reapply
                # the already-versioned least-privilege role contract to the
                # fresh database before probing it through the gateway.
                with restored_engine.begin() as connection:
                    for filename in (
                        "094_platform_control_gateway.sql",
                        "096_platform_success_verdict.sql",
                    ):
                        connection.exec_driver_sql(_sql_file(filename))
                restored_manifest = _manifest(restored_engine)
                compare_recovery_manifests(source_manifest, restored_manifest)
                visibility, cross = _visibility(restored_engine)
                validate_tenant_visibility(restored_manifest, visibility)
                gateway = PlatformGateway(restored_engine)
                restored_replay_created = [
                    gateway.register_resource(
                        Resource(
                            tenant_id=item["tenant_id"],
                            resource_urn=item["resource_urn"],
                            resource_kind="dataset",
                            authority_system="gda",
                            authority_locator="recovery/source",
                            owner_ref="team:platform",
                        )
                    ).created
                    for item in seeded
                ]
                cross_reference_rejected = _cross_tenant_reference_rejected(
                    restored_engine, TENANTS[0], TENANTS[1], seeded[1]["definition_version_id"]
                )
                try:
                    gateway.get_resource(TENANTS[0], f"gda://{TENANTS[1]}/dataset/recovery-source")
                    cross_tenant_gateway_not_found = False
                except GatewayNotFoundError:
                    cross_tenant_gateway_not_found = True
            finally:
                restored_engine.dispose()
        finally:
            source_engine.dispose()
        report = {
            "schema": "gda.tenant_scoped_recovery_acceptance.v1",
            "status": "passed",
            "image": IMAGE,
            "databases": {"source": source_db, "restored": restored_db},
            "tenants": list(TENANTS),
            "dump": {"bytes": dump_path.stat().st_size, "sha256": dump_sha256, "retained": False},
            "manifest": {
                "source": source_manifest.as_dict(),
                "restored": restored_manifest.as_dict(),
            },
            "replay": {
                "source_manifest_unchanged": True,
                "source_gateway_created_flags": replay_created,
                "restored_gateway_created_flags": restored_replay_created,
            },
            "security": {
                "source_cross_tenant_rows": source_cross,
                "restored_cross_tenant_rows": cross,
                "source_visibility": source_visibility,
                "restored_visibility": visibility,
                "cross_tenant_gateway_not_found": cross_tenant_gateway_not_found,
                "cross_tenant_reference_rejected": cross_reference_rejected,
            },
            "scope": [
                "control_ledger_two_tenant_dump_restore",
                "gateway_rls_visibility",
                "immutable_graph_replay",
            ],
            "limitations": [
                "production_backup_encryption",
                "offsite_replication",
                "approved_rpo_rto",
                "cross_store_point_in_time",
            ],
        }
        report["report_sha256"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in report.items() if key != "report_sha256"},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return report
    finally:
        try:
            dump_path.unlink(missing_ok=True)
        except OSError:
            pass
        _docker("rm", "--force", "--volumes", container, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        report = certify()
    except Exception as exc:  # sparse failure output; do not expose DSNs or container logs
        report = {
            "schema": "gda.tenant_scoped_recovery_acceptance.v1",
            "status": "failed",
            "error_type": type(exc).__name__,
            "promotion_ready": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        )
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
