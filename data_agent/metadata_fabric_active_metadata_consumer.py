"""Validate and rehearse inert Active Metadata activation request staging."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from .active_metadata_change_contract import (
    MetadataActivationRequest,
    build_active_metadata_registration,
    build_metadata_activation_intent,
    build_metadata_activation_request,
)
from .active_metadata_consumer import ActiveMetadataConsumer
from .active_metadata_consumer_deployment import build_deployment_report
from .metadata_fabric_active_metadata_outbox import (
    CONSUMER_SUBJECT,
    ISOLATED_TENANT,
    TENANT,
    WORKER_1,
    WORKER_2,
    build_active_metadata_bundle,
)
from .platform_contracts import canonical_json_fingerprint
from .platform_gateway import (
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
)

CONTRACT_SCHEMA = "gda.active_metadata_consumer_contract.v1"
EVIDENCE_SCHEMA = "gda.active_metadata_consumer_evidence.v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-active-metadata-consumer-2026-07-30.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-active-metadata-consumer.sh"
)
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "095_platform_command_outbox.sql",
        "099_active_metadata_change_outbox.sql",
        "100_active_metadata_activation_request.sql",
    )
)


class ActiveMetadataConsumerEvidenceError(RuntimeError):
    """The consumer contract or local rehearsal failed closed."""


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ActiveMetadataConsumerEvidenceError(
            f"{path.name} must contain an object"
        )
    return value


def build_contract_report() -> dict[str, Any]:
    errors: list[str] = []
    paths = {
        "contract": Path(__file__).resolve().parent
        / "active_metadata_change_contract.py",
        "consumer": Path(__file__).resolve().parent
        / "active_metadata_consumer.py",
        "worker": Path(__file__).resolve().parent
        / "active_metadata_consumer_worker.py",
        "deployment_validator": Path(__file__).resolve().parent
        / "active_metadata_consumer_deployment.py",
        "gateway": Path(__file__).resolve().parent / "platform_gateway.py",
        "migration": Path(__file__).resolve().parent
        / "migrations/100_active_metadata_activation_request.sql",
        "manifest": REPO_ROOT / "k8s/base/active-metadata-consumer.yaml",
        "kustomization": REPO_ROOT / "k8s/base/kustomization.yaml",
        "network_policy": REPO_ROOT / "k8s/base/networkpolicy.yaml",
        "wrapper": DEFAULT_WRAPPER_PATH,
    }
    required = {
        "contract": (
            "class MetadataActivationRequest",
            "status: Literal[\"awaiting_authorization\"]",
            "production_scheduler_submission_verified: Literal[False]",
            "production_ready: Literal[False]",
        ),
        "consumer": (
            "class ActiveMetadataConsumer",
            "self.gateway.stage_metadata_activation_request(",
            "self.gateway.fail_metadata_change(",
        ),
        "worker": (
            "class ActiveMetadataConsumerWorker",
            "ACTIVE_METADATA_CONSUMER_ENABLED",
            "provider_credentials_configured\": False",
            "scheduler_credentials_configured\": False",
        ),
        "deployment_validator": (
            "expected_replicas: int = 0",
            "consumer must not receive provider or scheduler secrets",
            "consumer must disable Kubernetes API token mounting",
        ),
        "gateway": (
            "def stage_metadata_activation_request(",
            "def get_metadata_activation_request(",
        ),
        "migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.metadata_activation_request",
            "stage_metadata_activation_request",
            "durable activation request is required before completion",
            "FORCE ROW LEVEL SECURITY",
            "status = 'awaiting_authorization'",
        ),
        "manifest": (
            "replicas: 0",
            "automountServiceAccountToken: false",
            "data_agent.active_metadata_consumer_worker run",
        ),
        "kustomization": ("active-metadata-consumer.yaml",),
        "network_policy": ("gis-agent-active-metadata-consumer",),
        "wrapper": (
            "data_agent.metadata_fabric_active_metadata_consumer",
            '"$@"',
        ),
    }
    files: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"{name} is missing")
            files[name] = {
                "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
                "sha256": None,
            }
            continue
        raw = path.read_bytes()
        source = raw.decode("utf-8")
        files[name] = {
            "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        missing = [marker for marker in required[name] if marker not in source]
        if missing:
            errors.append(f"{name} is missing required consumer markers")

    deployment = build_deployment_report()
    if deployment["status"] != "valid":
        errors.append("Active Metadata consumer deployment contract is invalid")
    stable = {
        "schema": CONTRACT_SCHEMA,
        "activation_route": "metadata_fabric.projection_plan",
        "activation_boundary": "durable_request_awaiting_authorization",
        "consumer_subject": CONSUMER_SUBJECT,
        "deployment_expected_replicas": deployment["expected_replicas"],
        "files": files,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "production_scheduler_submission_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }


def _apply_migrations(engine: Any) -> None:
    with engine.begin() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            raise ActiveMetadataConsumerEvidenceError(
                "local consumer rehearsal requires a fresh superuser database"
            )
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_app_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL
            )
            """
        )
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))


def _request_is_inert(request: MetadataActivationRequest) -> bool:
    return (
        request.status == "awaiting_authorization"
        and request.provider_apply_authorized is False
        and request.provider_mutations_executed is False
        and request.production_scheduler_submission_verified is False
        and request.production_ingestion_verified is False
        and request.production_ready is False
    )


def run_local_rehearsal(database_url: str) -> dict[str, Any]:
    if not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
    ):
        raise ActiveMetadataConsumerEvidenceError(
            "Active Metadata consumer rehearsal requires PostgreSQL"
        )
    bundle = build_active_metadata_bundle()
    engine = create_engine(database_url)
    try:
        _apply_migrations(engine)
        gateway = PlatformGateway(engine)
        gateway.register_resource(bundle.resource)
        registration = gateway.register_resource_version_with_metadata_event(
            bundle.registration,
            max_attempts=3,
        )
        claimed = gateway.claim_metadata_changes(
            TENANT,
            WORKER_1,
            consumer_subject=CONSUMER_SUBJECT,
            lease_seconds=60,
        )
        intent = build_metadata_activation_intent(
            claimed[0].event,
            routed_by=CONSUMER_SUBJECT,
        )
        request = build_metadata_activation_request(intent)

        legacy_completion_blocked = False
        try:
            gateway.complete_metadata_change(
                TENANT,
                claimed[0].event.event_id,
                worker_id=WORKER_1,
                activation_intent=intent,
            )
        except GatewayValidationError:
            legacy_completion_blocked = True
        after_block = gateway.get_metadata_change_delivery(
            TENANT,
            claimed[0].event.event_id,
        )
        request_absent_before_stage = False
        try:
            gateway.get_metadata_activation_request(TENANT, request.request_id)
        except GatewayNotFoundError:
            request_absent_before_stage = True

        first_stage = gateway.stage_metadata_activation_request(
            TENANT,
            claimed[0].event.event_id,
            worker_id=WORKER_1,
            request=request,
        )
        replay_stage = gateway.stage_metadata_activation_request(
            TENANT,
            claimed[0].event.event_id,
            worker_id=WORKER_1,
            request=request,
        )

        next_version = bundle.registration.resource_version.model_copy(
            update={
                "resource_version_id": UUID(
                    "a4000000-0000-4000-8000-000000000003"
                ),
                "version_key": "snapshot-2",
                "predecessor_version_id": (
                    bundle.registration.resource_version.resource_version_id
                ),
                "content_sha256": "c" * 64,
                "authority_version_ref": {"snapshot_id": 2},
            }
        )
        next_registration = build_active_metadata_registration(
            next_version,
            consumer_subject=CONSUMER_SUBJECT,
        )
        gateway.register_resource_version_with_metadata_event(
            next_registration,
            max_attempts=3,
        )
        consumer_result = ActiveMetadataConsumer(
            gateway,
            consumer_subject=CONSUMER_SUBJECT,
        ).run_once(
            TENANT,
            worker_id=WORKER_2,
            limit=1,
            lease_seconds=60,
        )
        stored_requests = [
            gateway.get_metadata_activation_request(TENANT, request.request_id),
            gateway.get_metadata_activation_request(
                TENANT,
                consumer_result.request_ids[0],
            ),
        ]

        cross_tenant_read_blocked = False
        try:
            gateway.get_metadata_activation_request(
                ISOLATED_TENANT,
                request.request_id,
            )
        except GatewayNotFoundError:
            cross_tenant_read_blocked = True

        direct_mutation_blocked = True
        with gateway._transaction(TENANT) as connection:
            for statement in (
                """
                UPDATE gda_control.metadata_activation_request
                SET status = 'awaiting_authorization'
                WHERE request_id = :request_id
                """,
                """
                DELETE FROM gda_control.metadata_activation_request
                WHERE request_id = :request_id
                """,
            ):
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(statement),
                            {"request_id": request.request_id},
                        )
                except DBAPIError:
                    continue
                direct_mutation_blocked = False

        with engine.connect() as connection:
            privileges = connection.exec_driver_sql(
                """
                SELECT
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_request',
                        'SELECT,INSERT'
                    ),
                    NOT has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_request', 'UPDATE'
                    ),
                    NOT has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_request', 'DELETE'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.stage_metadata_activation_request(text,uuid,text,jsonb)',
                        'EXECUTE'
                    )
                """
            ).one()
            force_rls = connection.exec_driver_sql(
                """
                SELECT bool_and(relforcerowsecurity)
                FROM pg_class
                WHERE oid IN (
                    'gda_control.metadata_change_outbox'::regclass,
                    'gda_control.metadata_activation_request'::regclass
                )
                """
            ).scalar_one()
            counts = connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*)
                            FROM gda_control.metadata_change_outbox
                            WHERE tenant_id = :tenant_id
                              AND status = 'processed'
                        ) AS processed_events,
                        (
                            SELECT count(*)
                            FROM gda_control.metadata_activation_request
                            WHERE tenant_id = :tenant_id
                              AND status = 'awaiting_authorization'
                        ) AS activation_requests,
                        (
                            SELECT count(*)
                            FROM gda_control.platform_command_outbox
                            WHERE tenant_id = :tenant_id
                        ) AS platform_commands
                    """
                ),
                {"tenant_id": TENANT},
            ).one()

        deployment = build_deployment_report()
    finally:
        engine.dispose()

    requests_inert = all(_request_is_inert(item) for item in stored_requests)
    atomic_completion_guard_verified = (
        legacy_completion_blocked
        and request_absent_before_stage
        and after_block.status.value == "in_flight"
    )
    verified = (
        registration.created
        and len(claimed) == 1
        and atomic_completion_guard_verified
        and first_stage.created
        and not replay_stage.created
        and replay_stage.value == request
        and consumer_result.claimed == consumer_result.staged == 1
        and consumer_result.replayed == 0
        and consumer_result.retry_pending == 0
        and consumer_result.failed == 0
        and len(consumer_result.request_ids) == 1
        and requests_inert
        and cross_tenant_read_blocked
        and direct_mutation_blocked
        and privileges == (True, True, True, True)
        and bool(force_rls)
        and counts.processed_events == counts.activation_requests == 2
        and counts.platform_commands == 0
        and deployment["status"] == "valid"
        and deployment["expected_replicas"] == 0
    )
    contract = build_contract_report()
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "status": (
            "local_postgresql_activation_request_staging_verified"
            if verified
            else "blocked"
        ),
        "contract_sha256": contract["contract_sha256"],
        "activation_route": intent.route,
        "event_ids": sorted(str(item.intent.event_id) for item in stored_requests),
        "request_ids": sorted(str(item.request_id) for item in stored_requests),
        "request_sha256": sorted(item.request_sha256 for item in stored_requests),
        "request_statuses": sorted(item.status for item in stored_requests),
        "processed_event_count": counts.processed_events,
        "activation_request_count": counts.activation_requests,
        "platform_command_count": counts.platform_commands,
        "legacy_completion_without_request_blocked": legacy_completion_blocked,
        "request_absent_before_atomic_stage": request_absent_before_stage,
        "atomic_completion_guard_verified": atomic_completion_guard_verified,
        "exact_request_replay_created": replay_stage.created,
        "managed_consumer_staged": consumer_result.staged == 1,
        "requests_inert": requests_inert,
        "cross_tenant_read_blocked": cross_tenant_read_blocked,
        "gateway_select_insert_only_verified": privileges
        == (True, True, True, True),
        "direct_request_mutation_blocked": direct_mutation_blocked,
        "force_rls_verified": bool(force_rls),
        "deployment_contract_verified": deployment["status"] == "valid",
        "deployment_expected_replicas": deployment["expected_replicas"],
        "local_postgresql_activation_request_staging_verified": verified,
        "deployment_applied": False,
        "production_workload_identity_verified": False,
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "production_scheduler_submission_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "errors": [] if verified else ["local consumer rehearsal did not verify"],
    }
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def validate_rehearsal_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("Active Metadata consumer evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("Active Metadata consumer evidence SHA-256 does not match")
    contract = build_contract_report()
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("Active Metadata consumer contract fingerprint is stale")
    for claim in (
        "deployment_applied",
        "production_workload_identity_verified",
        "provider_apply_authorized",
        "provider_mutations_executed",
        "production_scheduler_submission_verified",
        "production_ingestion_verified",
        "production_ready",
    ):
        if evidence.get(claim) is not False:
            errors.append(
                f"local Active Metadata consumer evidence may not claim {claim}"
            )
    for claim in (
        "legacy_completion_without_request_blocked",
        "request_absent_before_atomic_stage",
        "atomic_completion_guard_verified",
        "managed_consumer_staged",
        "requests_inert",
        "cross_tenant_read_blocked",
        "gateway_select_insert_only_verified",
        "direct_request_mutation_blocked",
        "force_rls_verified",
        "deployment_contract_verified",
        "local_postgresql_activation_request_staging_verified",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"Active Metadata consumer evidence did not verify {claim}")
    if evidence.get("activation_route") != "metadata_fabric.projection_plan":
        errors.append("Active Metadata consumer activation route is invalid")
    if evidence.get("processed_event_count") != 2:
        errors.append("Active Metadata consumer evidence must contain two events")
    if evidence.get("activation_request_count") != 2:
        errors.append("Active Metadata consumer evidence must contain two requests")
    if evidence.get("platform_command_count") != 0:
        errors.append("Active Metadata consumer must not create platform commands")
    if evidence.get("exact_request_replay_created") is not False:
        errors.append("Active Metadata request replay must not create a row")
    if evidence.get("request_statuses") != [
        "awaiting_authorization",
        "awaiting_authorization",
    ]:
        errors.append("Active Metadata requests must await authorization")
    if evidence.get("deployment_expected_replicas") != 0:
        errors.append("Active Metadata consumer base must remain inert")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--database-url", required=True)
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_contract_report()
        try:
            evidence = _load_json_object(args.evidence)
            report["errors"].extend(validate_rehearsal_evidence(evidence))
        except (OSError, ValueError) as exc:
            report["errors"].append(
                f"Active Metadata consumer evidence is invalid: {type(exc).__name__}"
            )
        report["status"] = "valid" if not report["errors"] else "invalid"
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report["errors"] else 1

    evidence = run_local_rehearsal(args.database_url)
    args.evidence_out.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if not evidence["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
