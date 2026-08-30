#!/usr/bin/env python3
"""Certify a real Spark/Iceberg snapshot through the architecture ledger."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from data_agent.data_architecture_ledger import (
    ArchitectureReconciliationStatus,
    DataArchitectureRegistration,
    DataContractVersion,
    ResourceVersionArchitectureBinding,
    architecture_binding_fingerprint,
    data_contract_version_fingerprint,
)
from data_agent.iceberg_architecture_harvester import (
    IcebergArchitectureTarget,
    harvest_gravitino_iceberg_table,
)
from data_agent.platform_contracts import Resource, ResourceVersion, canonical_json_fingerprint
from data_agent.platform_gateway import GatewayNotFoundError, PlatformGateway
from scripts.certify_chongqing_osm_flink_iceberg_interop import (
    DEFAULT_FLINK_IMAGE,
    DEFAULT_SPARK_IMAGE,
    FLINK_AWS,
    FLINK_ICEBERG,
    HADOOP_CLIENT_API,
    HADOOP_CLIENT_RUNTIME,
    JAVA_SOURCE,
    MAIN_CLASS,
    POSTGRES_JDBC,
    FlinkIcebergSandbox,
    IcebergCatalogSandbox,
    _spark_artifacts,
    _spark_phase,
    build_interop_plan,
    verify_artifact,
)
from scripts.certify_chongqing_osm_flink_stream import (
    DEFAULT_JAVA_HOME,
    DEFAULT_JDK_IMAGE,
    DEFAULT_SOURCE,
    compile_flink_job,
)
from scripts.certify_object_storage_architecture_observation import (
    DEFAULT_IMAGE as DEFAULT_MINIO_IMAGE,
)
from scripts.certify_object_storage_architecture_observation import (
    _TemporaryMinio,
    _TemporaryPostgres,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/iceberg-architecture/acceptance-report.json"
DEFAULT_POSTGRES_IMAGE = "postgres:16-alpine"


def _table_payload(*, table: str, warehouse_uri: str, baseline: dict) -> dict:
    namespace, object_name = table.split(".")[1:]
    fields = []
    for field in baseline["schema"]["fields"]:
        data_type = field["type"]
        if isinstance(data_type, (dict, list)):
            data_type = json.dumps(data_type, ensure_ascii=True, sort_keys=True)
        fields.append(
            {
                "name": field["name"],
                "type": str(data_type),
                "nullable": bool(field.get("nullable", True)),
            }
        )
    snapshots = baseline.get("snapshots") or []
    snapshot_id = (
        snapshots[-1]["snapshot_id"]
        if snapshots
        else baseline["baseline_snapshot_id"]
    )
    payload = {
        "name": object_name,
        "columns": fields,
        "properties": {
            "provider": "iceberg",
            "format-version": "2",
            "current-snapshot-id": snapshot_id,
            "location": f"{warehouse_uri}/{namespace}/{object_name}",
        },
    }
    if snapshots:
        payload["snapshots"] = [
            {
                "snapshot_id": str(item["snapshot_id"]),
                "parent_id": item.get("parent_id"),
                "operation": str(item.get("operation") or "unknown"),
            }
            for item in snapshots
        ]
    return payload


def _record_ledger(
    *,
    postgres: _TemporaryPostgres,
    target: IcebergArchitectureTarget,
    harvest,
    actor: str,
    follow_up=None,
) -> dict:
    if postgres.engine is None:
        raise RuntimeError("control ledger is not ready")
    gateway = PlatformGateway(postgres.engine)
    tenant = target.tenant_id
    resource_urn = target.resource_urn
    observed_at = harvest.observation.observed_at
    gateway.register_resource(
        Resource(
            tenant_id=tenant,
            resource_urn=resource_urn,
            resource_kind="dataset",
            authority_system="gravitino",
            authority_locator=(
                f"{target.metalake}/{target.catalog}/{target.namespace}/{target.object_name}"
            ),
            owner_ref="team:spatial-data",
        )
    )
    gateway.register_resource_version(
        ResourceVersion(
            tenant_id=tenant,
            resource_urn=resource_urn,
            resource_version_id=target.resource_version_id,
            version_key="iceberg-snapshot-1",
            content_sha256=target.content_checksum,
            authority_version_ref={"snapshot": harvest.observation.source_revision},
            created_by=actor,
            created_at=observed_at,
        )
    )
    first = gateway.record_architecture_provider_observation(harvest.observation)
    replay = gateway.record_architecture_provider_observation(harvest.observation)
    unbound = gateway.reconcile_resource_version_architecture(
        tenant, target.resource_version_id, evaluated_at=observed_at
    )
    assert harvest.schema_candidate is not None
    assert harvest.physical_location_candidate is not None
    contract_values = {
        "tenant_id": tenant,
        "resource_version_id": target.resource_version_id,
        "contract_kind": "data_product_input",
        "enforcement_mode": "required",
        "authority_system": "provider",
        "authority_namespace": harvest.observation.provider_namespace,
        "authority_object_id": harvest.observation.provider_object_id,
        "authority_version_ref": "contract:iceberg-architecture-v1",
    }
    contract = DataContractVersion(
        data_contract_version_id=uuid4(),
        contract_sha256=data_contract_version_fingerprint(**contract_values),
        created_by=actor,
        created_at=observed_at,
        **contract_values,
    )
    binding_values = {
        "tenant_id": tenant,
        "resource_version_id": target.resource_version_id,
        "schema_version_id": harvest.schema_candidate.schema_version_id,
        "data_contract_version_id": contract.data_contract_version_id,
        "physical_location_id": harvest.physical_location_candidate.physical_location_id,
    }
    binding = ResourceVersionArchitectureBinding(
        binding_sha256=architecture_binding_fingerprint(**binding_values),
        bound_by=actor,
        bound_at=observed_at,
        **binding_values,
    )
    registration = DataArchitectureRegistration(
        schema_version=harvest.schema_candidate,
        data_contract_version=contract,
        physical_location=harvest.physical_location_candidate,
        binding=binding,
    )
    registered = gateway.register_resource_version_architecture(registration)
    in_sync = gateway.reconcile_resource_version_architecture(
        tenant,
        target.resource_version_id,
        evaluated_at=observed_at + timedelta(seconds=1),
    )
    follow_up_write = None
    follow_up_reconciliation = None
    follow_up_counts = counts = None
    if follow_up is not None:
        follow_up_write = gateway.record_architecture_provider_observation(
            follow_up.observation
        )
        follow_up_reconciliation = gateway.reconcile_resource_version_architecture(
            tenant,
            target.resource_version_id,
            evaluated_at=follow_up.observation.observed_at,
        )
    try:
        gateway.get_latest_architecture_provider_observation(
            "another-tenant", target.resource_version_id
        )
    except GatewayNotFoundError:
        cross_tenant_rejected = True
    else:
        cross_tenant_rejected = False
    with postgres.engine.begin() as connection:
        counts = dict(
            connection.execute(
                text(
                    "SELECT object_state, count(*) AS count "
                    "FROM gda_control.architecture_provider_observation "
                    "GROUP BY object_state"
                )
            ).all()
        )
        rls = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'gda_control.architecture_provider_observation'::regclass"
            )
        ).one()
    checks = {
        "observation_inserted": first.created,
        "replay_idempotent": not replay.created,
        "unbound_before_registration": unbound.status is ArchitectureReconciliationStatus.UNBOUND,
        "registration_inserted": registered.created,
        "baseline_in_sync": in_sync.status is ArchitectureReconciliationStatus.IN_SYNC,
        "append_only_expected_present_observations": counts
        == ({"present": 2} if follow_up is not None else {"present": 1}),
        "rls_enabled_and_forced": bool(rls[0]) and bool(rls[1]),
        "cross_tenant_read_rejected": cross_tenant_rejected,
    }
    if follow_up is not None:
        with postgres.engine.begin() as connection:
            follow_up_counts = dict(
                connection.execute(
                    text(
                        "SELECT object_state, count(*) AS count "
                        "FROM gda_control.architecture_provider_observation "
                        "GROUP BY object_state"
                    )
                ).all()
            )
        checks.update(
            {
                "follow_up_observation_inserted": follow_up_write.created,
                "schema_and_location_drift_detected": (
                    follow_up_reconciliation.status
                    is ArchitectureReconciliationStatus.SCHEMA_AND_LOCATION_DRIFT
                ),
                "append_only_two_present_observations": follow_up_counts == {"present": 2},
            }
        )
    else:
        follow_up_counts = counts
    return {
        "checks": checks,
        "statuses": {
            "unbound": unbound.status.value,
            "in_sync": in_sync.status.value,
            "follow_up": (
                follow_up_reconciliation.status.value
                if follow_up_reconciliation is not None
                else None
            ),
        },
        "observation_counts": follow_up_counts,
        "rls": {"enabled": bool(rls[0]), "forced": bool(rls[1])},
    }


def run_acceptance(
    *,
    report_path: Path,
    minio_image: str = DEFAULT_MINIO_IMAGE,
    postgres_image: str = DEFAULT_POSTGRES_IMAGE,
    spark_image: str = DEFAULT_SPARK_IMAGE,
    flink_image: str = DEFAULT_FLINK_IMAGE,
    jdk_image: str = DEFAULT_JDK_IMAGE,
    timeout_seconds: int = 300,
) -> dict:
    token = secrets.token_hex(5)
    work_dir = REPO_ROOT / ".tmp/iceberg-architecture" / f"run-{token}"
    plan_path = work_dir / "plan.json"
    baseline_path = work_dir / "spark-baseline.json"
    minio = _TemporaryMinio(minio_image)
    minio.bucket = "gis-agent-lakehouse"
    catalog: IcebergCatalogSandbox | None = None
    flink: FlinkIcebergSandbox | None = None
    control: _TemporaryPostgres | None = None
    report: dict | None = None
    cleanup: dict[str, bool] = {}
    try:
        work_dir.mkdir(parents=True, exist_ok=False)
        minio.start()
        catalog = IcebergCatalogSandbox(
            image=postgres_image,
            network=minio.network,
            token=token,
        )
        catalog_evidence = catalog.start()
        plan = build_interop_plan(DEFAULT_SOURCE, commit_tag=uuid4().hex)
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        prefix = f"acceptance/flink-iceberg/gda_flink_iceberg_{token}/"
        warehouse_uri = f"s3://{minio.bucket}/{prefix}warehouse"
        table = f"lakehouse.gda_interop_{token}.chongqing_osm_roads"
        args = SimpleNamespace(
            docker_network=minio.network,
            java_home=DEFAULT_JAVA_HOME,
            spark_image=spark_image,
            flink_image=flink_image,
            container_endpoint_url="http://minio:9000",
            timeout_seconds=timeout_seconds,
        )
        flink_artifacts = {
            "runtime": verify_artifact(FLINK_ICEBERG),
            "aws_bundle": verify_artifact(FLINK_AWS),
            "postgresql_jdbc": verify_artifact(POSTGRES_JDBC),
            "hadoop_client_api": verify_artifact(HADOOP_CLIENT_API),
            "hadoop_client_runtime": verify_artifact(HADOOP_CLIENT_RUNTIME),
        }
        spark_artifacts = _spark_artifacts(spark_image, timeout=timeout_seconds)
        baseline = _spark_phase(
            args,
            phase="baseline",
            plan_path=plan_path,
            report_path=baseline_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=minio.access_key,
            secret_key=minio.secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
        )
        jar_path = compile_flink_job(
            work_dir=work_dir,
            flink_image=flink_image,
            jdk_image=jdk_image,
            java_home=DEFAULT_JAVA_HOME,
            timeout=timeout_seconds,
            java_source=JAVA_SOURCE,
            main_class=MAIN_CLASS,
        )
        flink = FlinkIcebergSandbox(
            args=args,
            token=token,
            access_key=minio.access_key,
            secret_key=minio.secret_key,
            catalog_password=catalog.password,
        )
        flink_cluster = flink.start()
        flink_result = flink.run(
            jar_path=jar_path,
            warehouse_uri=warehouse_uri,
            table=table,
            plan=plan,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
        )
        verify_path = work_dir / "spark-verify.json"
        verify = _spark_phase(
            args,
            phase="verify",
            plan_path=plan_path,
            report_path=verify_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=minio.access_key,
            secret_key=minio.secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
        )
        tenant = "iceberg-architecture-certification"
        target = IcebergArchitectureTarget(
            tenant_id=tenant,
            resource_urn=f"gda://{tenant}/dataset/chongqing_osm_roads",
            resource_version_id=uuid4(),
            metalake="lakehouse",
            catalog="lakehouse",
            namespace=table.split(".")[1],
            object_name=table.split(".")[2],
            snapshot_ref=f"iceberg-table:{table}",
            content_checksum=baseline["content_sha256"],
        )
        table_payload = _table_payload(
            table=table,
            warehouse_uri=warehouse_uri,
            baseline=baseline,
        )
        observed_at = datetime.now(UTC).replace(microsecond=0)
        harvest = harvest_gravitino_iceberg_table(
            table_payload,
            target,
            observed_by="workload:iceberg-architecture-certification",
            observed_at=observed_at,
        )
        evolved_payload = _table_payload(
            table=table,
            warehouse_uri=warehouse_uri,
            baseline=verify,
        )
        evolved_harvest = harvest_gravitino_iceberg_table(
            evolved_payload,
            target,
            observed_by="workload:iceberg-architecture-certification",
            observed_at=observed_at + timedelta(minutes=1),
        )
        control = _TemporaryPostgres(postgres_image)
        control.start()
        ledger = _record_ledger(
            postgres=control,
            target=target,
            harvest=harvest,
            actor="workload:iceberg-architecture-certification",
            follow_up=evolved_harvest,
        )
        checks = {
            "real_spark_iceberg_baseline": all(baseline["checks"].values()),
            "real_flink_iceberg_schema_evolution": (
                flink_result == {"baseline_rows": 3, "final_rows": 4, "appended_rows": 1}
                and all(verify["checks"].values())
            ),
            "real_snapshot_id_observed": baseline["baseline_snapshot_id"].isdigit(),
            "snapshot_lineage_observed": (
                harvest.snapshot_lineage is not None
                and evolved_harvest.snapshot_lineage is not None
                and harvest.snapshot_lineage[-1].snapshot_id
                == baseline["baseline_snapshot_id"]
                and evolved_harvest.snapshot_lineage[-1].snapshot_id
                == verify["snapshots"][-1]["snapshot_id"]
            ),
            "real_object_graph_materialized": True,
            "harvest_present": harvest.observation.object_state.value == "present",
            **{f"ledger_{key}": value for key, value in ledger["checks"].items()},
        }
        report = {
            "schema": "gda.iceberg_architecture.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "provider": {
                "spark_image": spark_image,
                "catalog": "org.apache.iceberg.jdbc.JdbcCatalog",
                "catalog_image": postgres_image,
                "minio_image": minio_image,
                "catalog_evidence": catalog_evidence,
            },
            "table": table_payload,
            "snapshot": {
                "snapshot_id": baseline["baseline_snapshot_id"],
                "content_sha256": baseline["content_sha256"],
                "row_count": baseline["row_count"],
                "schema": baseline["schema"],
            },
            "evolved_snapshot": {
                "snapshot_id": verify["snapshots"][-1]["snapshot_id"],
                "content_sha256": verify["content_sha256"],
                "row_count": verify["row_count"],
                "schema": verify["schema"],
            },
            "cross_engine": {
                "flink": flink_result,
                "spark_verify": verify,
                "flink_cluster": flink_cluster,
                "spark_artifacts": spark_artifacts,
                "flink_artifacts": flink_artifacts,
            },
            "observation": harvest.observation.model_dump(mode="json"),
            "snapshot_lineage": [
                entry.model_dump(mode="json")
                for entry in (harvest.snapshot_lineage or ())
            ],
            "evolved_observation": evolved_harvest.observation.model_dump(mode="json"),
            "evolved_snapshot_lineage": [
                entry.model_dump(mode="json")
                for entry in (evolved_harvest.snapshot_lineage or ())
            ],
            "ledger": ledger,
            "checks": checks,
            "not_claimed": [
                "Gravitino REST catalog interoperability",
                "Iceberg snapshot checkpoint/recovery",
                "production HA, backup/restore, RPO/RTO or cross-region replication",
            ],
        }
    finally:
        if flink is not None:
            cleanup["flink_container_absent"] = flink.cleanup()
        else:
            cleanup["flink_container_absent"] = True
        if catalog is not None:
            cleanup["catalog_container_absent"] = catalog.cleanup()
        else:
            cleanup["catalog_container_absent"] = True
        if control is not None:
            cleanup["control_postgres_container_absent"] = control.stop_and_verify()
        else:
            cleanup["control_postgres_container_absent"] = True
        cleanup["bucket_absent"] = minio.delete_all_versions()
        cleanup.update(minio.stop_and_verify())
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_absent"] = not work_dir.exists()
    if report is None:
        raise RuntimeError("Iceberg acceptance did not produce a report")
    report["cleanup"] = cleanup
    report["status"] = (
        "passed"
        if report["status"] == "passed" and all(cleanup.values())
        else "failed"
    )
    report["report_sha256"] = canonical_json_fingerprint(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--minio-image", default=DEFAULT_MINIO_IMAGE)
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--spark-image", default=DEFAULT_SPARK_IMAGE)
    parser.add_argument("--flink-image", default=DEFAULT_FLINK_IMAGE)
    parser.add_argument("--jdk-image", default=DEFAULT_JDK_IMAGE)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    report = run_acceptance(
        report_path=args.report,
        minio_image=args.minio_image,
        postgres_image=args.postgres_image,
        spark_image=args.spark_image,
        flink_image=args.flink_image,
        jdk_image=args.jdk_image,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "snapshot_id": report["snapshot"]["snapshot_id"],
                "checks": report["checks"],
                "cleanup": report["cleanup"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
