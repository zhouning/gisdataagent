#!/usr/bin/env python3
"""Certify managed Martin warmup delivery in a disposable PostgreSQL database."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from data_agent.gis_provider_runtime import (
    MartinMVTWarmupSample,
    MartinVectorTileProvider,
)
from data_agent.gis_service_endpoint_warmup import (
    GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE,
    GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
    GISServiceEndpointWarmupRunRequest,
)
from data_agent.gis_service_endpoint_warmup_consumer import (
    GISServiceEndpointWarmupConsumer,
    LocalWarmupReceiptStore,
)
from data_agent.platform_contracts import SubjectContext, SubjectType
from data_agent.platform_gateway import GatewayForbiddenError, PlatformGateway

try:  # Support package imports and direct script invocation.
    from scripts.certify_gis_service_consumer_migration_impact import (
        _bootstrap as _bootstrap_220,
    )
    from scripts.certify_gis_service_consumer_migration_impact import (
        _definition,
        _ready_endpoint_fixture,
        _register_warmup_definition,
        _release_bundle,
        _seed_authorities,
        _service_policy,
        _sql_file,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script invocation path.
    from certify_gis_service_consumer_migration_impact import (
        _bootstrap as _bootstrap_220,
    )
    from certify_gis_service_consumer_migration_impact import (
        _definition,
        _ready_endpoint_fixture,
        _register_warmup_definition,
        _release_bundle,
        _seed_authorities,
        _service_policy,
        _sql_file,
    )

MIGRATION = "221_gis_service_endpoint_warmup_command.sql"
COMMAND_OUTBOX_MIGRATION = "095_platform_command_outbox.sql"


def _bootstrap(engine: Engine, login_role: str) -> None:
    _bootstrap_220(engine, login_role)
    with engine.begin() as connection:
        connection.exec_driver_sql(_sql_file(COMMAND_OUTBOX_MIGRATION))
        connection.exec_driver_sql(_sql_file(MIGRATION))


def _register_release(
    gateway: PlatformGateway,
    seed: dict[str, object],
    now: datetime,
):
    definition = _definition(seed, now)
    gateway.register_gis_service_definition_version(definition)
    bundle = _release_bundle(seed, definition, now)
    for item, register in zip(
        bundle[:-1],
        (
            gateway.register_layer_definition_version,
            gateway.register_style_definition_version,
            gateway.register_tile_matrix_set_definition_version,
            gateway.register_cache_policy_version,
            gateway.register_mvt_serving_projection_version,
        ),
        strict=True,
    ):
        register(item)
    release = bundle[-1]
    gateway.register_service_release_binding(release)
    gateway.register_service_policy_binding(
        _service_policy(seed, definition, release, now)
    )
    return definition, bundle, release


def _admit(
    gateway: PlatformGateway,
    seed: dict[str, object],
    warmup_definition,
    endpoint,
    submitted_at: datetime,
    *,
    run_id=None,
    suffix: str = "success",
):
    request = GISServiceEndpointWarmupRunRequest(
        tenant_id=str(seed["tenant"]),
        run_id=run_id or uuid4(),
        definition_version_id=warmup_definition.definition_version_id,
        service_urn=str(seed["service_urn"]),
        endpoint_revision_id=endpoint.endpoint_revision_id,
        samples=(
            MartinMVTWarmupSample(z=0, x=0, y=0),
            MartinMVTWarmupSample(z=1, x=1, y=0),
            MartinMVTWarmupSample(z=2, x=3, y=1),
        ),
        idempotency_key=f"managed-martin-warmup-{suffix}",
        submitted_at=submitted_at,
    )
    subject = SubjectContext(
        tenant_id=str(seed["tenant"]),
        subject_id="gis-warmup-controller",
        subject_type=SubjectType.WORKLOAD,
        roles=("service_operator",),
        purpose=GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE,
    )
    return request, gateway.admit_gis_service_endpoint_warmup_run(
        request, subject_context=subject
    )


def certify(database_url: str, *, report_path: Path | None = None) -> dict[str, object]:
    source_url = make_url(database_url)
    admin = create_engine(
        source_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    database = f"gda_gis_warmup_worker_cert_{uuid4().hex[:10]}"
    login_role = f"gda_gis_warmup_login_{uuid4().hex[:10]}"
    password = uuid4().hex
    with admin.connect() as connection:
        connection.execute(
            text(f'CREATE ROLE "{login_role}" LOGIN PASSWORD :password'),
            {"password": password},
        )
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    owner_engine = create_engine(source_url.set(database=database))
    login_engine = create_engine(
        source_url.set(username=login_role, password=password, database=database)
    )
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        _bootstrap(owner_engine, login_role)
        seed = _seed_authorities(owner_engine, now - timedelta(hours=1))
        gateway = PlatformGateway(login_engine)
        warmup_definition = _register_warmup_definition(
            gateway, seed, now - timedelta(minutes=50)
        )
        definition, bundle, release = _register_release(
            gateway, seed, now - timedelta(minutes=45)
        )
        deployment, endpoint = _ready_endpoint_fixture(
            gateway,
            owner_engine,
            seed,
            definition,
            release,
            bundle[-2],
            now - timedelta(minutes=30),
            revision_key="r91",
            suffix="managed",
            provider_revision_ref="deployment:managed-warmup",
            provider_system="martin",
        )
        request, admission = _admit(
            gateway,
            seed,
            warmup_definition,
            endpoint,
            now - timedelta(seconds=1),
        )
        replay = gateway.admit_gis_service_endpoint_warmup_run(
            request,
            subject_context=admission.run.subject_context,
        )
        try:
            gateway.admit_gis_service_endpoint_warmup_run(
                request.model_copy(update={"run_id": uuid4()}),
                subject_context=SubjectContext(
                    tenant_id=str(seed["tenant"]),
                    subject_id="other-controller",
                    subject_type=SubjectType.WORKLOAD,
                    purpose=GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE,
                ),
            )
        except GatewayForbiddenError:
            wrong_workload_rejected = True
        else:
            wrong_workload_rejected = False

        requested_paths: list[str] = []

        def handler(http_request: httpx.Request) -> httpx.Response:
            requested_paths.append(http_request.url.path)
            if http_request.url.path == "/health":
                return httpx.Response(200, text="OK")
            if http_request.url.path == "/catalog":
                return httpx.Response(
                    200,
                    json={
                        "tiles": {
                            "gda_mvt_serving_projection": {
                                "content_type": "application/x-protobuf"
                            }
                        }
                    },
                )
            return httpx.Response(
                200,
                content=f"mvt:{http_request.url.path}".encode(),
                headers={
                    "content-type": "application/x-protobuf",
                    "etag": f'"{len(requested_paths)}"',
                },
            )

        with TemporaryDirectory(prefix="gda-gis-warmup-cert-") as temporary:
            receipt_root = Path(temporary) / "receipts"
            consumer = GISServiceEndpointWarmupConsumer(
                gateway,
                MartinVectorTileProvider(
                    "http://martin:3000",
                    transport=httpx.MockTransport(handler),
                ),
                LocalWarmupReceiptStore(receipt_root),
                retry_delay_seconds=0,
            )
            batch = consumer.run_once(
                str(seed["tenant"]),
                worker_id="worker:gis-warmup-cert",
                limit=1,
                lease_seconds=1200,
            )
            receipt_file = (
                receipt_root
                / str(seed["tenant"])
                / str(request.run_id)
                / "martin-origin-warmup-receipt.json"
            )
            receipt_file_sha256 = hashlib.sha256(
                receipt_file.read_bytes()
            ).hexdigest()

        settled_run = gateway.get_run(str(seed["tenant"]), request.run_id)
        receipts = gateway.list_gis_service_endpoint_warmups(
            str(seed["tenant"]),
            str(seed["service_urn"]),
            endpoint.endpoint_revision_id,
        )
        settled_command = gateway.get_command(
            str(seed["tenant"]), admission.command.command_id
        )

        failure_request, failure_admission = _admit(
            gateway,
            seed,
            warmup_definition,
            endpoint,
            now,
            suffix="terminal-failure",
        )
        failure_claim = gateway.claim_commands(
            str(seed["tenant"]),
            "worker:gis-warmup-cert",
            actor_subject=GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
            limit=1,
            lease_seconds=1200,
        )[0]
        failed_command = (
            gateway.fail_gis_service_endpoint_warmup_command_terminal(
                str(seed["tenant"]),
                failure_claim.command_id,
                worker_id="worker:gis-warmup-cert",
                error="certified endpoint contract drift",
            )
        )
        failed_run = gateway.get_run(
            str(seed["tenant"]), failure_request.run_id
        )

        with owner_engine.connect() as connection:
            security = connection.execute(
                text(
                    """
                    SELECT
                      has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.finalize_gis_service_endpoint_warmup_success(text,uuid,integer,text,text,jsonb)',
                        'EXECUTE'
                      ),
                      has_function_privilege(
                        'public',
                        'gda_control.finalize_gis_service_endpoint_warmup_success(text,uuid,integer,text,text,jsonb)',
                        'EXECUTE'
                      ),
                      has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.fail_gis_service_endpoint_warmup_command_terminal(text,uuid,text,text)',
                        'EXECUTE'
                      ),
                      has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.gis_service_endpoint_warmup',
                        'INSERT'
                      ),
                      relrowsecurity,
                      relforcerowsecurity
                    FROM pg_class
                    WHERE oid = 'gda_control.gis_service_endpoint_warmup'::regclass
                    """
                )
            ).one()
            evidence_counts = connection.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM gda_control.framework_attempt_observation
                        WHERE run_id = :run_id AND framework_kind = 'cloud'
                          AND external_namespace = 'martin'),
                      (SELECT count(*) FROM gda_control.artifact
                        WHERE run_id = :run_id AND artifact_role = 'evidence'),
                      (SELECT count(*) FROM gda_control.quality_result
                        WHERE run_id = :run_id AND verdict = 'passed'),
                      (SELECT count(*) FROM gda_control.lineage_event
                        WHERE run_id = :run_id),
                      (SELECT count(*) FROM gda_control.gis_service_endpoint_warmup
                        WHERE run_id = :run_id)
                    """
                ),
                {"run_id": request.run_id},
            ).one()

        receipt = receipts[0]
        report: dict[str, object] = {
            "schema": "gda.gis_service_endpoint_warmup_worker_certification.v1",
            "status": "passed",
            "database": database,
            "migration": MIGRATION.removesuffix(".sql"),
            "admission": {
                "run_created": admission.run_created,
                "plan_artifact_created": admission.artifact_created,
                "command_created": admission.command_created,
                "replay_run_created": replay.run_created,
                "replay_plan_created": replay.artifact_created,
                "replay_command_created": replay.command_created,
                "wrong_workload_rejected": wrong_workload_rejected,
                "plan_sha256": admission.execution_plan.plan_sha256,
                "sample_set_sha256": admission.execution_plan.sample_set_sha256,
            },
            "execution": {
                "batch": batch.__dict__,
                "http_paths": requested_paths,
                "run_status": settled_run.status.value,
                "command_status": settled_command.status.value,
                "receipt_count": len(receipts),
                "receipt_sha256": receipt.warmup_sha256,
                "provider_receipt_sha256": receipt.provider_receipt_sha256,
                "receipt_file_sha256": receipt_file_sha256,
                "receipt_file_content_bound": (
                    receipt_file_sha256 == receipt.provider_receipt_sha256
                ),
                "evidence_counts": [int(value) for value in evidence_counts],
            },
            "terminal_failure": {
                "admitted_command_id": str(failure_admission.command.command_id),
                "command_status": failed_command.status.value,
                "run_status": failed_run.status.value,
            },
            "security": {
                "success_finalizer_gateway_execute": bool(security[0]),
                "success_finalizer_public_execute": bool(security[1]),
                "terminal_failure_gateway_execute": bool(security[2]),
                "direct_receipt_insert": bool(security[3]),
                "rls_enabled": bool(security[4]),
                "rls_forced": bool(security[5]),
            },
            "bindings": {
                "deployment_revision_id": str(deployment.deployment_revision_id),
                "endpoint_revision_id": str(endpoint.endpoint_revision_id),
                "release_binding_id": str(release.service_release_binding_id),
            },
        }
        if (
            not admission.run_created
            or not admission.artifact_created
            or not admission.command_created
            or replay.run_created
            or replay.artifact_created
            or replay.command_created
            or not wrong_workload_rejected
            or batch.claimed != 1
            or batch.succeeded != 1
            or settled_run.status.value != "succeeded"
            or settled_command.status.value != "done"
            or len(receipts) != 1
            or receipt_file_sha256 != receipt.provider_receipt_sha256
            or tuple(int(value) for value in evidence_counts) != (1, 1, 1, 1, 1)
            or failed_command.status.value != "failed"
            or failed_run.status.value != "failed"
            or tuple(bool(value) for value in security)
            != (True, False, True, False, True, True)
        ):
            report["status"] = "failed"
            raise RuntimeError(f"managed GIS warmup certification failed: {report}")
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
        return report
    finally:
        owner_engine.dispose()
        login_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            connection.execute(text(f'DROP ROLE IF EXISTS "{login_role}"'))
        admin.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default="postgresql://postgres:postgres@127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            certify(args.database_url, report_path=args.report),
            indent=2,
            sort_keys=True,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
