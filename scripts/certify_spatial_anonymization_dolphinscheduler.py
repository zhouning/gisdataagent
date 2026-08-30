#!/usr/bin/env python3
"""Certify a spatial anonymization Run through real DolphinScheduler 3.4.2."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerCorrelationNotFoundError,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerProfile,
    DolphinSchedulerProtocolError,
    compile_dolphinscheduler_workflow,
)
from data_agent.dolphinscheduler_command_consumer import (
    DolphinSchedulerCommandConsumer,
)
from data_agent.platform_contracts import Resource, ResourceVersion
from data_agent.platform_gateway import DefinitionRegistration, PlatformGateway
from data_agent.security_event_ledger import SecurityEventLedger
from data_agent.spatial_anonymization_dolphinscheduler import (
    SPATIAL_ANONYMIZATION_DEFINITION_SCHEMA,
    build_spatial_anonymization_definition,
)
from data_agent.spatial_anonymization_run import (
    SpatialAnonymizationRequest,
    SpatialAnonymizationRunSpec,
)
from data_agent.spatial_anonymization_worker import (
    spatial_anonymization_attempt_id,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = tuple(
    REPO_ROOT / "data_agent/migrations" / name
    for name in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "095_platform_command_outbox.sql",
        "110_immutable_security_event_ledger.sql",
        "111_security_operation_receipt.sql",
    )
)
TENANT_ID = "spatial-run-ds-cert"
DEFINITION_URN = f"gda://{TENANT_ID}/definition/spatial-anonymization-v1"
DEFINITION_VERSION_ID = uuid5(NAMESPACE_URL, f"{DEFINITION_URN}:v1")
WORKFLOW_NAME = "gda_spatial_anonymization_worker_cert_v1"
WORKLOAD_SUBJECT = "workload:dolphinscheduler-gda-dataops"
POLICY_EVALUATOR_SUBJECT = "workload:gda-policy-evaluator"
EXECUTOR_PORT = 18091
EXECUTOR_BASE_URL = f"http://host.docker.internal:{EXECUTOR_PORT}"
EXECUTOR_HOST_URL = f"http://127.0.0.1:{EXECUTOR_PORT}"
DOLPHINSCHEDULER_CONTAINER = (
    "gisdataagent-dolphinscheduler-sandbox-dolphinscheduler-1"
)


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _start_postgis(image: str) -> tuple[str, int]:
    container = f"gda-spatial-ds-cert-{secrets.token_hex(5)}"
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
    for _ in range(180):
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
    for _ in range(180):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except DBAPIError as error:
            last_error = error
            engine.dispose()
            time.sleep(0.25)
    raise RuntimeError("PostGIS host port did not become ready") from last_error


def _bootstrap(admin_engine) -> None:
    with admin_engine.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS postgis")
        connection.exec_driver_sql(
            "CREATE ROLE spatial_worker_runtime "
            "LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS"
        )
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))
        connection.exec_driver_sql(
            "GRANT gda_control_gateway TO spatial_worker_runtime"
        )
        connection.exec_driver_sql("GRANT CREATE ON SCHEMA public TO spatial_worker_runtime")
        connection.exec_driver_sql("CREATE SCHEMA geo")
        connection.exec_driver_sql(
            "CREATE TABLE geo.restricted_parcels ("
            "source_id bigint PRIMARY KEY, land_use text, area_m2 numeric, "
            "geom geometry(Polygon, 4326) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO geo.restricted_parcels "
            "SELECT value, CASE WHEN mod(value, 2) = 0 "
            "THEN 'residential' ELSE 'commercial' END, value * 100, "
            "ST_GeomFromText('POLYGON((106.50 29.50,106.51 29.50,"
            "106.51 29.51,106.50 29.51,106.50 29.50))', 4326) "
            "FROM generate_series(1, 6) AS value"
        )
        connection.exec_driver_sql(
            "GRANT USAGE ON SCHEMA geo TO spatial_worker_runtime"
        )
        connection.exec_driver_sql(
            "GRANT SELECT ON geo.restricted_parcels TO spatial_worker_runtime"
        )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _profile(profile_path: Path) -> DolphinSchedulerProfile:
    value = _read_json(profile_path)
    token = Path(str(value["token_file"])).read_text(encoding="utf-8").strip()
    return DolphinSchedulerProfile(
        base_url=str(value["base_url"]),
        access_token=token,
        project_code=int(value["project_code"]),
        workload_subject=str(value["workload_subject"]),
        policy_evaluator_subject=str(value["policy_evaluator_subject"]),
        tenant_code=str(value["tenant_code"]),
        worker_group=str(value["worker_group"]),
        timezone_name="Asia/Tokyo",
    )


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _start_executor(
    *,
    token_file: Path,
    postgres_port: int,
    log_path: Path,
    dolphinscheduler_container: str,
) -> tuple[subprocess.Popen[str], TextIO]:
    if not _port_available(EXECUTOR_PORT):
        raise RuntimeError(f"executor port {EXECUTOR_PORT} is already in use")
    environment = os.environ.copy()
    environment.update(
        {
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": str(postgres_port),
            "POSTGRES_DATABASE": "postgres",
            "POSTGRES_USER": "spatial_worker_runtime",
            "POSTGRES_PASSWORD": "unused",
            "PYTHONUNBUFFERED": "1",
        }
    )
    log_stream = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "data_agent.spatial_anonymization_executor",
            "--host",
            "0.0.0.0",
            "--port",
            str(EXECUTOR_PORT),
            "--token-file",
            str(token_file),
        ],
        cwd=REPO_ROOT,
        env=environment,
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for _ in range(120):
        if process.poll() is not None:
            log_stream.close()
            raise RuntimeError(
                "spatial executor exited before readiness: "
                f"{log_path.read_text(encoding='utf-8')[-2000:]}"
            )
        try:
            response = httpx.get(f"{EXECUTOR_HOST_URL}/health", timeout=1.0)
            if response.status_code == 200:
                provider_probe = _docker(
                    "exec",
                    dolphinscheduler_container,
                    "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    f"{EXECUTOR_BASE_URL}/health",
                    check=False,
                )
                if provider_probe.returncode == 0:
                    return process, log_stream
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    process.terminate()
    process.wait(timeout=10)
    log_stream.close()
    raise RuntimeError("spatial executor did not become ready")


def _definition_and_binding(
    *,
    gateway: PlatformGateway,
    client: DolphinSchedulerClient,
    profile: DolphinSchedulerProfile,
    state_path: Path,
):
    existing = [
        item
        for item in client.list_workflows(search_value=WORKFLOW_NAME)
        if item.get("name") == WORKFLOW_NAME
    ]
    if len(existing) > 1:
        raise RuntimeError("multiple certification workflows share the same name")
    state = _read_json(state_path) if state_path.exists() else None
    if state is None and existing:
        raise RuntimeError("certification workflow exists without local definition state")
    task_code = (
        int(state["task_code"])
        if state is not None
        else client.generate_task_codes(1)[0]
    )
    definition = build_spatial_anonymization_definition(
        tenant_id=TENANT_ID,
        definition_urn=DEFINITION_URN,
        definition_version_id=DEFINITION_VERSION_ID,
        task_code=task_code,
        worker_group=profile.worker_group,
        executor_base_url=EXECUTOR_BASE_URL,
        workflow_name=WORKFLOW_NAME,
    )
    spec = compile_dolphinscheduler_workflow(definition)
    if state is not None and (
        state.get("definition_sha256") != definition.definition_sha256
        or state.get("compiled_sha256") != spec.compiled_sha256
    ):
        raise RuntimeError("persisted certification workflow state has drifted")
    created_at = datetime.now(UTC)
    registration = gateway.register_definition(
        DefinitionRegistration(
            resource=Resource(
                tenant_id=TENANT_ID,
                resource_urn=DEFINITION_URN,
                resource_kind="definition",
                authority_system="gda-control",
                authority_locator="definitions/spatial-anonymization/v1",
                owner_ref="team:data-governance",
            ),
            resource_version=ResourceVersion(
                tenant_id=TENANT_ID,
                resource_urn=DEFINITION_URN,
                resource_version_id=DEFINITION_VERSION_ID,
                version_key="v1",
                content_sha256=definition.definition_sha256,
                authority_version_ref={
                    "schema": SPATIAL_ANONYMIZATION_DEFINITION_SCHEMA
                },
                created_by=WORKLOAD_SUBJECT,
                created_at=created_at,
            ),
            definition=definition,
        )
    )
    if existing:
        item = existing[0]
        binding = DolphinSchedulerDefinitionBinding(
            tenant_id=TENANT_ID,
            definition_version_id=DEFINITION_VERSION_ID,
            project_code=profile.project_code,
            workflow_definition_code=int(item["code"]),
            workflow_definition_version=int(item["version"]),
            compiled_sha256=spec.compiled_sha256,
        )
        client.release_workflow(binding.workflow_definition_code)
        workflow_created = False
    else:
        binding = client.create_workflow(spec)
        workflow_created = True
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "schema": "gda.spatial_anonymization_ds_definition_state.v1",
                    "task_code": task_code,
                    "definition_sha256": definition.definition_sha256,
                    "compiled_sha256": spec.compiled_sha256,
                    "workflow_definition_code": binding.workflow_definition_code,
                },
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        state_path.chmod(0o600)
    adapter = DolphinSchedulerAdapter(profile, gateway=gateway, client=client)
    binding_result = adapter.persist_binding(
        binding,
        actor_subject=WORKLOAD_SUBJECT,
        created_at=created_at,
    )
    return (
        definition,
        binding,
        binding_result.value,
        registration.created,
        workflow_created,
        binding_result.created,
    )


def _submit_run(gateway: PlatformGateway, binding_artifact_id: UUID):
    request = SpatialAnonymizationRequest(
        tenant_id=TENANT_ID,
        client_request_id="dolphinscheduler-certification-001",
        requester_subject="human:security-certifier",
        source_asset_ref="agent_data_assets:certified-restricted-parcels",
        source_schema="geo",
        source_table="restricted_parcels",
        output_schema="public",
        output_table="restricted_parcels_l3_ds",
        data_type="polygon",
        level="L3",
        k_anonymity=5,
        keep_attrs=("land_use", "area_m2"),
        agg_strategy="area_weighted",
        dp_epsilon=1.0,
        dp_numeric_fields=("area_m2",),
        register_lineage=False,
    )
    return gateway.submit_spatial_anonymization_run(
        SpatialAnonymizationRunSpec(
            request=request,
            definition_version_id=DEFINITION_VERSION_ID,
            execution_plan_artifact_id=binding_artifact_id,
            workload_subject_id=WORKLOAD_SUBJECT.removeprefix("workload:"),
            purpose="certify real provider spatial anonymization execution",
            policy_version_ref=(
                f"gda://{TENANT_ID}/policy/spatial-anonymization-cert:v1"
            ),
            policy_evaluator_subject=POLICY_EVALUATOR_SUBJECT,
        )
    )


def _wait_for_provider(
    *,
    adapter: DolphinSchedulerAdapter,
    binding_artifact_id: UUID,
    run_id: UUID,
    timeout_seconds: int,
):
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = adapter.reconcile(
                TENANT_ID,
                run_id,
                binding_artifact_id,
                actor_subject=WORKLOAD_SUBJECT,
            )
        except DolphinSchedulerCorrelationNotFoundError as error:
            last_error = error
            time.sleep(0.5)
            continue
        except DolphinSchedulerProtocolError as error:
            if "missing required correlation variables" not in str(error):
                raise
            last_error = error
            time.sleep(0.5)
            continue
        if result.provider_state in {"SUCCESS", "FAILURE", "STOP", "PAUSE"}:
            return result
        time.sleep(0.5)
    raise RuntimeError("DolphinScheduler instance did not become terminal") from last_error


def _certify(
    *,
    admin_engine,
    runtime_engine,
    profile: DolphinSchedulerProfile,
    profile_path: Path,
    state_path: Path,
    timeout_seconds: int,
    dolphinscheduler_container: str,
) -> dict[str, Any]:
    gateway = PlatformGateway(runtime_engine)
    ledger = SecurityEventLedger(runtime_engine)
    token_file = profile_path.parent / "executor-token"
    if not token_file.is_file():
        raise RuntimeError("DolphinScheduler executor token file is missing")
    with tempfile.TemporaryDirectory(prefix="gda-spatial-ds-cert-") as temporary:
        log_path = Path(temporary) / "executor.log"
        executor, log_stream = _start_executor(
            token_file=token_file,
            postgres_port=int(runtime_engine.url.port or 5432),
            log_path=log_path,
            dolphinscheduler_container=dolphinscheduler_container,
        )
        try:
            with DolphinSchedulerClient(profile) as client:
                (
                    definition,
                    binding,
                    binding_artifact,
                    definition_created,
                    workflow_created,
                    binding_created,
                ) = _definition_and_binding(
                    gateway=gateway,
                    client=client,
                    profile=profile,
                    state_path=state_path,
                )
                submission = _submit_run(gateway, binding_artifact.artifact_id)
                adapter = DolphinSchedulerAdapter(
                    profile,
                    gateway=gateway,
                    client=client,
                )
                batch = DolphinSchedulerCommandConsumer(
                    adapter,
                    gateway=gateway,
                ).run_once(
                    TENANT_ID,
                    worker_id="worker:spatial-ds-cert",
                    limit=1,
                    lease_seconds=60,
                )
                if batch.claimed != 1 or batch.completed != 1:
                    command = gateway.get_command(
                        TENANT_ID,
                        submission.command.command_id,
                    )
                    raise RuntimeError(
                        "DolphinScheduler dispatch command did not complete: "
                        f"status={command.status.value}, error={command.last_error}"
                    )
                reconciliation = _wait_for_provider(
                    adapter=adapter,
                    binding_artifact_id=binding_artifact.artifact_id,
                    run_id=submission.run.run_id,
                    timeout_seconds=timeout_seconds,
                )
                variables = client.get_instance_variables(
                    reconciliation.workflow_instance_id
                )

            token = token_file.read_text(encoding="utf-8").strip()
            replay_response = httpx.post(
                f"{EXECUTOR_HOST_URL}/v1/execute/spatial-anonymization-run",
                headers={"Authorization": f"Bearer {token}"},
                json={"tenant_id": TENANT_ID, "run_id": str(submission.run.run_id)},
                timeout=30.0,
            )
            replay_response.raise_for_status()
            replay = replay_response.json()
            attempt_id = spatial_anonymization_attempt_id(submission.run.run_id)
            receipt = ledger.get_operation_receipt(TENANT_ID, attempt_id)
            events = sorted(
                ledger.list_events(TENANT_ID, attempt_id=attempt_id, limit=10),
                key=lambda event: event.sequence_no,
            )
            with admin_engine.connect() as connection:
                output = connection.execute(
                    text(
                        """
                        SELECT to_regclass('public.restricted_parcels_l3_ds')
                                   IS NOT NULL,
                               (SELECT count(*)
                                FROM public.restricted_parcels_l3_ds),
                               EXISTS (
                                   SELECT 1 FROM pg_indexes
                                   WHERE schemaname = 'public'
                                     AND tablename = 'restricted_parcels_l3_ds'
                                     AND indexdef ILIKE '%USING gist%'
                               ),
                               (SELECT status
                                FROM gda_control.platform_command_outbox
                                WHERE tenant_id = :tenant_id),
                               (SELECT count(*)
                                FROM gda_control.framework_attempt_observation
                                WHERE tenant_id = :tenant_id
                                  AND run_id = :run_id
                                  AND framework_kind = 'dolphinscheduler')
                        """
                    ),
                    {"tenant_id": TENANT_ID, "run_id": submission.run.run_id},
                ).one()
            final_run = gateway.get_run(TENANT_ID, submission.run.run_id)
            forbidden_variables = {
                "source_schema",
                "source_table",
                "output_table",
                "k_anonymity",
                "dp_epsilon",
                "keep_attrs",
            }
            expected_variables = {
                "gda_tenant_id": TENANT_ID,
                "gda_run_id": str(submission.run.run_id),
                "gda_definition_version_id": str(DEFINITION_VERSION_ID),
            }
            checks = {
                "definition_registered": definition_created,
                "workflow_available": (
                    binding.workflow_definition_code > 0
                    and binding.workflow_definition_version >= 1
                ),
                "binding_persisted": binding_created,
                "dispatch_command_completed": (
                    batch.claimed == 1
                    and batch.completed == 1
                    and str(output[3]) == "done"
                ),
                "provider_instance_success": (
                    reconciliation.provider_state == "SUCCESS"
                    and reconciliation.workflow_instance_id > 0
                ),
                "provider_correlation_exact": all(
                    variables.get(key) == value
                    for key, value in expected_variables.items()
                ),
                "provider_has_no_business_parameters": not (
                    forbidden_variables & set(variables)
                ),
                "provider_observation_recorded": (
                    int(output[4]) >= 2
                    and reconciliation.observation.observed_state == "success"
                    and reconciliation.observation.external_run_id
                    == str(reconciliation.workflow_instance_id)
                ),
                "run_waits_at_evidence_gate": final_run.status.value == "reconciling",
                "output_table_committed": bool(output[0]),
                "output_has_rows": int(output[1]) > 0,
                "output_has_gist": bool(output[2]),
                "security_receipt_committed": receipt is not None,
                "security_lifecycle_complete": (
                    [(event.phase, event.outcome) for event in events]
                    == [("admitted", "admitted"), ("outcome", "success")]
                    and ledger.verify_chain(TENANT_ID)
                    and ledger.verify_operation_receipts(TENANT_ID)
                ),
                "executor_replay_skips_operation": (
                    replay.get("status") == "already_completed"
                    and replay.get("recovered_from_receipt") is True
                    and replay.get("attempt_id") == str(attempt_id)
                ),
                "definition_fingerprint_bound": (
                    binding.compiled_sha256
                    == compile_dolphinscheduler_workflow(definition).compiled_sha256
                ),
            }
            return {
                "schema": "gda.spatial_anonymization_dolphinscheduler_certification.v1",
                "tenant_id": TENANT_ID,
                "definition_version_id": str(DEFINITION_VERSION_ID),
                "workflow_definition_code": binding.workflow_definition_code,
                "workflow_definition_version": binding.workflow_definition_version,
                "workflow_created": workflow_created,
                "workflow_instance_id": reconciliation.workflow_instance_id,
                "run_id": str(submission.run.run_id),
                "request_version_id": str(submission.request_version.resource_version_id),
                "attempt_id": str(attempt_id),
                "provider_state": reconciliation.provider_state,
                "platform_run_status": final_run.status.value,
                "checks": checks,
                "passed": sum(checks.values()),
                "total": len(checks),
                "certified": all(checks.values()),
            }
        finally:
            executor.terminate()
            try:
                executor.wait(timeout=10)
            except subprocess.TimeoutExpired:
                executor.kill()
                executor.wait(timeout=5)
            log_stream.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="postgis/postgis:16-3.4")
    parser.add_argument(
        "--profile",
        type=Path,
        default=REPO_ROOT / ".tmp/dolphinscheduler-sandbox/profile.json",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=(
            REPO_ROOT
            / ".tmp/dolphinscheduler-sandbox/"
            "spatial-anonymization-definition-state.json"
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--dolphinscheduler-container",
        default=DOLPHINSCHEDULER_CONTAINER,
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    container = None
    engines = []
    try:
        profile_path = args.profile.resolve(strict=True)
        profile = _profile(profile_path)
        container, port = _start_postgis(args.image)
        base = f"127.0.0.1:{port}/postgres"
        admin_engine = create_engine(f"postgresql+psycopg2://postgres@{base}")
        runtime_engine = create_engine(
            f"postgresql+psycopg2://spatial_worker_runtime@{base}"
        )
        engines.extend((admin_engine, runtime_engine))
        _wait_for_host_connection(admin_engine)
        _bootstrap(admin_engine)
        report = _certify(
            admin_engine=admin_engine,
            runtime_engine=runtime_engine,
            profile=profile,
            profile_path=profile_path,
            state_path=args.state.resolve(),
            timeout_seconds=args.timeout_seconds,
            dolphinscheduler_container=args.dolphinscheduler_container,
        )
        rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
        print(rendered)
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered + "\n", encoding="utf-8")
        return 0 if report["certified"] else 1
    finally:
        for engine in engines:
            engine.dispose()
        if container is not None:
            _docker("stop", container, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
