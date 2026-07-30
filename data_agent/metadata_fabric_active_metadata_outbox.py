"""Validate and rehearse the local Active Metadata transactional outbox."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, text

from .active_metadata_change_contract import (
    ActiveMetadataRegistration,
    build_active_metadata_registration,
    build_metadata_activation_intent,
)
from .platform_contracts import (
    Resource,
    ResourceVersion,
    canonical_json_fingerprint,
)
from .platform_gateway import (
    GatewayConflictError,
    GatewayNotFoundError,
    PlatformGateway,
)


CONTRACT_SCHEMA = "gda.active_metadata_outbox_contract.v1"
EVIDENCE_SCHEMA = "gda.active_metadata_outbox_evidence.v1"
TENANT = "active-metadata-local"
ISOLATED_TENANT = "active-metadata-isolated"
RESOURCE_URN = f"gda://{TENANT}/dataset/parcels"
RESOURCE_VERSION_ID = UUID("a4000000-0000-4000-8000-000000000001")
LEGACY_VERSION_ID = UUID("a4000000-0000-4000-8000-000000000002")
OCCURRED_AT = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)
PRODUCER_SUBJECT = "workload:metadata-registrar"
CONSUMER_SUBJECT = "workload:metadata-router"
WORKER_1 = "worker:metadata-router-1"
WORKER_2 = "worker:metadata-router-2"
WORKER_3 = "worker:metadata-router-3"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT / "docs/evidence/metadata-fabric-active-metadata-outbox-2026-07-30.json"
)
DEFAULT_WRAPPER_PATH = REPO_ROOT / "scripts/metadata-fabric-active-metadata-outbox.sh"
CONTRACT_PATH = Path(__file__).resolve().parent / "active_metadata_change_contract.py"
GATEWAY_PATH = Path(__file__).resolve().parent / "platform_gateway.py"
MIGRATION_PATH = (
    Path(__file__).resolve().parent
    / "migrations"
    / "099_active_metadata_change_outbox.sql"
)
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "099_active_metadata_change_outbox.sql",
    )
)


class ActiveMetadataOutboxError(RuntimeError):
    """The Active Metadata contract or local rehearsal failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActiveMetadataBundle(_FrozenModel):
    resource: Resource
    registration: ActiveMetadataRegistration
    legacy_version: ResourceVersion


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ActiveMetadataOutboxError(f"{path.name} must contain an object")
    return value


def build_active_metadata_bundle() -> ActiveMetadataBundle:
    resource = Resource(
        tenant_id=TENANT,
        resource_urn=RESOURCE_URN,
        resource_kind="dataset",
        authority_system="iceberg",
        authority_locator="geo.parcels",
        owner_ref="team:data-platform",
    )
    version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=RESOURCE_URN,
        resource_version_id=RESOURCE_VERSION_ID,
        version_key="snapshot-1",
        content_sha256="a" * 64,
        authority_version_ref={"snapshot_id": 1},
        created_by=PRODUCER_SUBJECT,
        created_at=OCCURRED_AT,
    )
    legacy_version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=RESOURCE_URN,
        resource_version_id=LEGACY_VERSION_ID,
        version_key="legacy-snapshot",
        content_sha256="b" * 64,
        authority_version_ref={"snapshot_id": 0},
        created_by=PRODUCER_SUBJECT,
        created_at=OCCURRED_AT,
    )
    return ActiveMetadataBundle(
        resource=resource,
        registration=build_active_metadata_registration(
            version,
            consumer_subject=CONSUMER_SUBJECT,
        ),
        legacy_version=legacy_version,
    )


def build_contract_report() -> dict[str, Any]:
    errors: list[str] = []
    paths = {
        "contract": CONTRACT_PATH,
        "migration": MIGRATION_PATH,
        "gateway": GATEWAY_PATH,
        "wrapper": DEFAULT_WRAPPER_PATH,
    }
    required = {
        "contract": (
            "class MetadataChangeEvent",
            "class MetadataActivationIntent",
            "provider_apply_authorized: Literal[False]",
            "provider_mutations_executed: Literal[False]",
            "production_ingestion_verified: Literal[False]",
        ),
        "migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.metadata_change_outbox",
            "FOR UPDATE SKIP LOCKED",
            "FORCE ROW LEVEL SECURITY",
            "claim_metadata_changes",
            "complete_metadata_change",
            "fail_metadata_change",
            "GRANT SELECT, INSERT ON gda_control.metadata_change_outbox",
        ),
        "gateway": (
            "def register_resource_version_with_metadata_event(",
            "version_result.created != event_result.created",
            "def claim_metadata_changes(",
            "def complete_metadata_change(",
            "activation_intent != expected",
        ),
        "wrapper": (
            "data_agent.metadata_fabric_active_metadata_outbox",
            '"$@"',
        ),
    }
    files: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"{name} is missing")
            files[name] = {"path": path.resolve().as_posix(), "sha256": None}
            continue
        raw = path.read_bytes()
        source = raw.decode("utf-8")
        files[name] = {
            "path": path.resolve().as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        missing = [marker for marker in required[name] if marker not in source]
        if missing:
            errors.append(f"{name} is missing required Active Metadata markers")

    bundle = build_active_metadata_bundle()
    stable = {
        "schema": CONTRACT_SCHEMA,
        "event_id": str(bundle.registration.event.event_id),
        "event_sha256": bundle.registration.event.event_sha256,
        "consumer_subject": bundle.registration.event.consumer_subject,
        "activation_route": "metadata_fabric.projection_plan",
        "files": files,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        "local_postgresql_active_metadata_loop_verified": False,
        "production_ready": False,
    }


def _apply_migrations(engine) -> None:
    with engine.begin() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            raise ActiveMetadataOutboxError(
                "local Active Metadata rehearsal requires a fresh superuser database"
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


def run_local_rehearsal(database_url: str) -> dict[str, Any]:
    if not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
    ):
        raise ActiveMetadataOutboxError(
            "Active Metadata rehearsal requires a PostgreSQL database URL"
        )
    bundle = build_active_metadata_bundle()
    engine = create_engine(database_url)
    try:
        _apply_migrations(engine)
        gateway = PlatformGateway(engine)
        gateway.register_resource(bundle.resource)
        first = gateway.register_resource_version_with_metadata_event(
            bundle.registration,
            max_attempts=3,
        )
        replay = gateway.register_resource_version_with_metadata_event(
            bundle.registration,
            max_attempts=3,
        )
        wrong_consumer_claim = gateway.claim_metadata_changes(
            TENANT,
            WORKER_1,
            consumer_subject="workload:other-router",
        )
        first_claim = gateway.claim_metadata_changes(
            TENANT,
            WORKER_1,
            consumer_subject=CONSUMER_SUBJECT,
            lease_seconds=60,
        )
        intent = build_metadata_activation_intent(
            first_claim[0].event,
            routed_by=CONSUMER_SUBJECT,
        )
        wrong_worker_blocked = False
        try:
            gateway.complete_metadata_change(
                TENANT,
                bundle.registration.event.event_id,
                worker_id=WORKER_2,
                activation_intent=intent,
            )
        except GatewayConflictError:
            wrong_worker_blocked = True
        after_retry = gateway.fail_metadata_change(
            TENANT,
            bundle.registration.event.event_id,
            worker_id=WORKER_1,
            error_code="router_unavailable",
            retryable=True,
            retry_delay_seconds=0,
        )
        second_claim = gateway.claim_metadata_changes(
            TENANT,
            WORKER_2,
            consumer_subject=CONSUMER_SUBJECT,
            lease_seconds=60,
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE gda_control.metadata_change_outbox
                    SET claimed_until = clock_timestamp() - interval '1 second'
                    WHERE tenant_id = :tenant_id AND event_id = :event_id
                    """
                ),
                {
                    "tenant_id": TENANT,
                    "event_id": bundle.registration.event.event_id,
                },
            )
        third_claim = gateway.claim_metadata_changes(
            TENANT,
            WORKER_3,
            consumer_subject=CONSUMER_SUBJECT,
            lease_seconds=60,
        )
        completed = gateway.complete_metadata_change(
            TENANT,
            bundle.registration.event.event_id,
            worker_id=WORKER_3,
            activation_intent=intent,
        )
        final_claim = gateway.claim_metadata_changes(
            TENANT,
            WORKER_3,
            consumer_subject=CONSUMER_SUBJECT,
        )
        final_replay = gateway.register_resource_version_with_metadata_event(
            bundle.registration,
            max_attempts=3,
        )

        cross_tenant_blocked = False
        try:
            gateway.get_metadata_change_delivery(
                ISOLATED_TENANT,
                bundle.registration.event.event_id,
            )
        except GatewayNotFoundError:
            cross_tenant_blocked = True

        gateway.register_resource_version(bundle.legacy_version)
        legacy_registration = build_active_metadata_registration(
            bundle.legacy_version,
            consumer_subject=CONSUMER_SUBJECT,
        )
        legacy_backfill_blocked = False
        try:
            gateway.register_resource_version_with_metadata_event(
                legacy_registration
            )
        except GatewayConflictError:
            legacy_backfill_blocked = True
        legacy_event_rolled_back = False
        try:
            gateway.get_metadata_change_delivery(
                TENANT,
                legacy_registration.event.event_id,
            )
        except GatewayNotFoundError:
            legacy_event_rolled_back = True

        with engine.connect() as connection:
            privileges = connection.exec_driver_sql(
                """
                SELECT
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_change_outbox', 'SELECT,INSERT'
                    ),
                    NOT has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_change_outbox', 'UPDATE'
                    ),
                    NOT has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_change_outbox', 'DELETE'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.claim_metadata_changes(text,text,text,integer,integer)',
                        'EXECUTE'
                    )
                """
            ).one()
            force_rls = connection.exec_driver_sql(
                """
                SELECT relforcerowsecurity
                FROM pg_class
                WHERE oid = 'gda_control.metadata_change_outbox'::regclass
                """
            ).scalar_one()
            event_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM gda_control.metadata_change_outbox
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": TENANT},
            ).scalar_one()
            connection.rollback()
    finally:
        engine.dispose()

    verified = (
        first.created
        and not replay.created
        and not wrong_consumer_claim
        and len(first_claim) == len(second_claim) == len(third_claim) == 1
        and first_claim[0].attempt_count == 1
        and after_retry.status.value == "pending"
        and after_retry.attempt_count == 1
        and second_claim[0].attempt_count == 2
        and third_claim[0].attempt_count == 3
        and wrong_worker_blocked
        and completed.status.value == "processed"
        and completed.activation_intent_sha256 == intent.intent_sha256
        and not final_claim
        and not final_replay.created
        and cross_tenant_blocked
        and legacy_backfill_blocked
        and legacy_event_rolled_back
        and privileges == (True, True, True, True)
        and force_rls
        and event_count == 1
    )
    contract = build_contract_report()
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "status": (
            "local_postgresql_active_metadata_loop_verified"
            if verified
            else "blocked"
        ),
        "contract_sha256": contract["contract_sha256"],
        "event_id": str(bundle.registration.event.event_id),
        "event_sha256": bundle.registration.event.event_sha256,
        "activation_intent_sha256": intent.intent_sha256,
        "activation_route": intent.route,
        "first_registration_created": first.created,
        "exact_replay_created": replay.created,
        "processed_replay_created": final_replay.created,
        "wrong_consumer_claim_blocked": not wrong_consumer_claim,
        "wrong_worker_completion_blocked": wrong_worker_blocked,
        "retry_pending_verified": after_retry.status.value == "pending",
        "lease_expiry_reclaim_verified": (
            len(third_claim) == 1 and third_claim[0].attempt_count == 3
        ),
        "final_attempt_count": completed.attempt_count,
        "processed_delivery_not_reclaimed": not final_claim,
        "legacy_backfill_blocked": legacy_backfill_blocked,
        "legacy_event_transaction_rolled_back": legacy_event_rolled_back,
        "cross_tenant_read_blocked": cross_tenant_blocked,
        "gateway_select_insert_only_verified": privileges == (True, True, True, True),
        "force_rls_verified": bool(force_rls),
        "authoritative_event_count": event_count,
        "local_postgresql_active_metadata_loop_verified": verified,
        "transactional_outbox_verified": verified,
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "production_ingestion_verified": False,
        "production_scheduler_submission_verified": False,
        "production_ready": False,
        "errors": [] if verified else ["local Active Metadata loop did not verify"],
    }
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def validate_rehearsal_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("Active Metadata evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("Active Metadata evidence SHA-256 does not match")
    contract = build_contract_report()
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("Active Metadata evidence contract fingerprint is stale")
    for claim in (
        "provider_apply_authorized",
        "provider_mutations_executed",
        "production_ingestion_verified",
        "production_scheduler_submission_verified",
        "production_ready",
    ):
        if evidence.get(claim) is not False:
            errors.append(f"local Active Metadata evidence may not claim {claim}")
    for claim in (
        "wrong_consumer_claim_blocked",
        "wrong_worker_completion_blocked",
        "retry_pending_verified",
        "lease_expiry_reclaim_verified",
        "processed_delivery_not_reclaimed",
        "legacy_backfill_blocked",
        "legacy_event_transaction_rolled_back",
        "cross_tenant_read_blocked",
        "gateway_select_insert_only_verified",
        "force_rls_verified",
        "local_postgresql_active_metadata_loop_verified",
        "transactional_outbox_verified",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"local Active Metadata evidence did not verify {claim}")
    if evidence.get("activation_route") != "metadata_fabric.projection_plan":
        errors.append("Active Metadata activation route is invalid")
    if evidence.get("authoritative_event_count") != 1:
        errors.append("Active Metadata evidence must contain exactly one event")
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
                f"Active Metadata evidence is invalid: {type(exc).__name__}"
            )
        report["status"] = "valid" if not report["errors"] else "invalid"
        report["local_postgresql_active_metadata_loop_verified"] = not report[
            "errors"
        ]
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
