"""Rehearse M3-4 OpenLineage delivery over a real local HTTP boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, text

from . import metadata_fabric_ingestion as ingestion
from . import metadata_fabric_binding_ledger as binding_ledger
from .metadata_fabric_binding_contract import (
    parse_metadata_fabric_execution_plan_artifact,
)
from .metadata_fabric_lineage_delivery_contract import (
    DEFAULT_TARGET_NAME,
    MetadataFabricLineageDelivery,
    build_metadata_fabric_lineage_delivery,
)
from .metadata_fabric_lineage_emitter import (
    LineageEmitterProfile,
    MetadataFabricLineageConsumer,
    OpenLineageHttpEmitter,
)
from .platform_contracts import canonical_json_bytes, canonical_json_fingerprint
from .platform_gateway import (
    DefinitionRegistration,
    GatewayNotFoundError,
    PlatformGateway,
)

CONTRACT_SCHEMA = "gda.metadata_fabric_openlineage_delivery_contract.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_openlineage_delivery_evidence.v1"
EMITTER_ACTOR = "workload:gda-lineage-emitter-local"
WORKER_ID = "worker:gda-lineage-emitter-local-1"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_EVIDENCE = (
    REPO_ROOT / "docs/evidence/metadata-fabric-binding-ledger-2026-07-28.json"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-openlineage-delivery-2026-07-28.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-openlineage-delivery.sh"
)
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "095_platform_command_outbox.sql",
        "096_platform_success_verdict.sql",
        "097_metadata_fabric_binding_ledger.sql",
        "098_metadata_fabric_openlineage_delivery.sql",
    )
)


class MetadataFabricLineageDeliveryError(RuntimeError):
    """The bounded local OpenLineage delivery rehearsal failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


class LineageDeliveryBundle(_FrozenModel):
    binding_bundle: binding_ledger.BindingLedgerBundle
    source_plan: ingestion.MetadataFabricIngestionPlan
    delivery: MetadataFabricLineageDelivery
    source_evidence_sha256: str


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricLineageDeliveryError(
            f"{path.name} must contain an object"
        )
    return payload


def _build_source_plan() -> ingestion.MetadataFabricIngestionPlan:
    values = ingestion._load_contract_inputs(
        ingestion.DEFAULT_PLATFORM_FIXTURE,
        ingestion.DEFAULT_METADATA_FIXTURE,
    )
    return ingestion.build_ingestion_plan(
        metadata_resource=values[2],
        target=values[3],
        binding=values[4],
        definition=values[5],
        run=values[6],
        source=values[7],
        artifact=values[8],
        quality=values[9],
        lineage=values[10],
        success=values[11],
        openmetadata=values[12],
        gravitino=values[13],
    )


def build_lineage_delivery_bundle(
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE,
) -> LineageDeliveryBundle:
    source_evidence = _load_json_object(source_evidence_path.resolve())
    errors = binding_ledger.validate_rehearsal_evidence(source_evidence)
    if errors:
        raise MetadataFabricLineageDeliveryError(
            "M3-3 binding evidence is invalid: " + ", ".join(errors)
        )
    binding_bundle = binding_ledger.build_binding_ledger_bundle()
    if (
        source_evidence.get("binding_id")
        != str(binding_bundle.record.binding_id)
        or source_evidence.get("record_sha256")
        != binding_bundle.record.record_sha256
    ):
        raise MetadataFabricLineageDeliveryError(
            "M3-3 evidence does not match the deterministic binding"
        )
    source_plan = _build_source_plan()
    apply_plan = parse_metadata_fabric_execution_plan_artifact(
        binding_bundle.artifacts[0]
    )
    delivery = build_metadata_fabric_lineage_delivery(
        binding=binding_bundle.record,
        source_plan=source_plan,
        apply_plan=apply_plan,
        actor_subject=EMITTER_ACTOR,
        created_at=binding_bundle.record.recorded_at + timedelta(seconds=1),
        target_name=DEFAULT_TARGET_NAME,
    )
    return LineageDeliveryBundle(
        binding_bundle=binding_bundle,
        source_plan=source_plan,
        delivery=delivery,
        source_evidence_sha256=source_evidence["evidence_sha256"],
    )


def build_contract_report(
    *,
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    bundle: LineageDeliveryBundle | None = None
    try:
        bundle = build_lineage_delivery_bundle(source_evidence_path)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(f"lineage delivery contract is invalid: {type(exc).__name__}")
    try:
        wrapper = wrapper_path.read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_lineage_delivery",
            "docker run",
        ):
            if marker not in wrapper:
                errors.append(f"lineage wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"lineage wrapper is invalid: {type(exc).__name__}")
    files: dict[str, dict[str, str | None]] = {}
    for path in (
        Path(__file__).resolve(),
        source_evidence_path.resolve(),
        wrapper_path.resolve(),
        *MIGRATIONS,
    ):
        files[path.name] = {
            "path": (
                path.resolve().relative_to(REPO_ROOT).as_posix()
                if path.resolve().is_relative_to(REPO_ROOT)
                else path.resolve().as_posix()
            ),
            "sha256": (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file()
                else None
            ),
        }
    stable = {
        "schema": CONTRACT_SCHEMA,
        "source_evidence_sha256": (
            bundle.source_evidence_sha256 if bundle is not None else None
        ),
        "delivery_id": (
            str(bundle.delivery.delivery_id) if bundle is not None else None
        ),
        "event_sha256": (
            bundle.delivery.event_sha256 if bundle is not None else None
        ),
        "idempotency_key": (
            bundle.delivery.idempotency_key if bundle is not None else None
        ),
        "files": files,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        "local_wire_openlineage_delivery_verified": False,
        "production_ready": False,
    }


class _SinkState:
    def __init__(self, expected: MetadataFabricLineageDelivery) -> None:
        self.expected = expected
        self.requests: list[dict[str, Any]] = []
        self.accepted: dict[str, str] = {}
        self.errors: list[str] = []


def _sink_handler(state: _SinkState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            key = self.headers.get("Idempotency-Key", "")
            delivery_id = self.headers.get("X-GDA-Delivery-ID", "")
            event_sha = self.headers.get("X-GDA-Event-SHA256", "")
            body_sha = hashlib.sha256(body).hexdigest()
            expected_body = canonical_json_bytes(
                state.expected.event.model_dump(mode="json", by_alias=True)
            )
            request_errors: list[str] = []
            if self.path != "/api/v1/lineage":
                request_errors.append("path_mismatch")
            if self.headers.get("Content-Type") != "application/json":
                request_errors.append("content_type_mismatch")
            if key != state.expected.idempotency_key:
                request_errors.append("idempotency_key_mismatch")
            if delivery_id != str(state.expected.delivery_id):
                request_errors.append("delivery_id_mismatch")
            if event_sha != state.expected.event_sha256:
                request_errors.append("event_sha_mismatch")
            if body != expected_body:
                request_errors.append("body_mismatch")
            state.errors.extend(request_errors)
            duplicate = key in state.accepted
            if duplicate and state.accepted[key] != body_sha:
                request_errors.append("idempotency_content_conflict")
                state.errors.append("idempotency_content_conflict")
            if not request_errors and not duplicate:
                state.accepted[key] = body_sha
            state.requests.append(
                {
                    "body_sha256": body_sha,
                    "idempotency_key": key,
                    "delivery_id": delivery_id,
                    "event_sha256": event_sha,
                    "duplicate": duplicate,
                }
            )
            if request_errors:
                status = 409
                response = {"accepted": False}
            elif duplicate:
                status = 200
                response = {"accepted": True, "duplicate": True}
            else:
                # Simulate receiver commit followed by a lost/failed acknowledgement.
                status = 503
                response = {"accepted": True, "acknowledged": False}
            payload = canonical_json_bytes(response)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def _apply_migrations(engine) -> None:
    with engine.begin() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            raise MetadataFabricLineageDeliveryError(
                "local lineage rehearsal requires a fresh superuser database"
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


def _register_binding(gateway: PlatformGateway, bundle: LineageDeliveryBundle) -> None:
    binding = bundle.binding_bundle
    by_urn = {item.resource_urn: item for item in binding.resources}
    definition_version = next(
        item
        for item in binding.resource_versions
        if item.resource_version_id == binding.definition.definition_version_id
    )
    gateway.register_definition(
        DefinitionRegistration(
            resource=by_urn[definition_version.resource_urn],
            resource_version=definition_version,
            definition=binding.definition,
        )
    )
    for resource in binding.resources:
        if resource.resource_urn != definition_version.resource_urn:
            gateway.register_resource(resource)
    for version in binding.resource_versions:
        if version.resource_version_id != definition_version.resource_version_id:
            gateway.register_resource_version(version)
    for artifact in binding.artifacts:
        gateway.record_artifact(artifact)
    gateway.commit_metadata_fabric_binding(binding.record)


def run_local_rehearsal(
    database_url: str,
    *,
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE,
) -> dict[str, Any]:
    if not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
    ):
        raise MetadataFabricLineageDeliveryError(
            "lineage rehearsal requires a PostgreSQL database URL"
        )
    bundle = build_lineage_delivery_bundle(source_evidence_path)
    engine = create_engine(database_url)
    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    try:
        _apply_migrations(engine)
        gateway = PlatformGateway(engine)
        _register_binding(gateway, bundle)
        first_enqueue = gateway.enqueue_metadata_fabric_lineage(
            bundle.delivery,
            source_plan=bundle.source_plan,
        )
        replay_enqueue = gateway.enqueue_metadata_fabric_lineage(
            bundle.delivery,
            source_plan=bundle.source_plan,
        )

        state = _SinkState(bundle.delivery)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _sink_handler(state))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}/api/v1/lineage"
        profile = LineageEmitterProfile(
            target_name=bundle.delivery.target_name,
            endpoint_url=endpoint,
            actor_subject=bundle.delivery.actor_subject,
        )
        with OpenLineageHttpEmitter(profile) as emitter:
            consumer = MetadataFabricLineageConsumer(
                emitter,
                gateway=gateway,
                retry_delay_seconds=0,
            )
            first_batch = consumer.run_once(
                bundle.delivery.tenant_id,
                worker_id=WORKER_ID,
            )
            after_first = gateway.get_metadata_fabric_lineage_delivery(
                bundle.delivery.tenant_id,
                bundle.delivery.delivery_id,
            )
            second_batch = consumer.run_once(
                bundle.delivery.tenant_id,
                worker_id=WORKER_ID,
            )
            third_batch = consumer.run_once(
                bundle.delivery.tenant_id,
                worker_id=WORKER_ID,
            )
        stored = gateway.get_metadata_fabric_lineage_delivery(
            bundle.delivery.tenant_id,
            bundle.delivery.delivery_id,
        )
        cross_tenant_visible = True
        try:
            gateway.get_metadata_fabric_lineage_delivery(
                "ar0-golden-isolated",
                bundle.delivery.delivery_id,
            )
        except GatewayNotFoundError:
            cross_tenant_visible = False
        with engine.connect() as connection:
            restricted_mutation = connection.exec_driver_sql(
                """
                SELECT NOT has_table_privilege(
                           'gda_control_gateway',
                           'gda_control.metadata_fabric_lineage_outbox', 'UPDATE'
                       )
                       AND NOT has_table_privilege(
                           'gda_control_gateway',
                           'gda_control.metadata_fabric_lineage_outbox', 'DELETE'
                       )
                """
            ).scalar_one()
            force_rls = connection.exec_driver_sql(
                """
                SELECT relforcerowsecurity
                FROM pg_class
                WHERE oid = 'gda_control.metadata_fabric_lineage_outbox'::regclass
                """
            ).scalar_one()
            connection.rollback()
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        engine.dispose()

    expected_body_sha = hashlib.sha256(
        canonical_json_bytes(
            bundle.delivery.event.model_dump(mode="json", by_alias=True)
        )
    ).hexdigest()
    request_count = len(state.requests)
    duplicate_count = sum(item["duplicate"] for item in state.requests)
    verified = (
        first_enqueue.created
        and not replay_enqueue.created
        and first_batch.claimed == 1
        and first_batch.retry_pending == 1
        and after_first.status.value == "pending"
        and after_first.attempt_count == 1
        and after_first.last_error_code == "http_5xx"
        and after_first.response_status == 503
        and second_batch.delivered == 1
        and third_batch.claimed == 0
        and stored.status.value == "delivered"
        and stored.attempt_count == 2
        and stored.receipt_sha256 is not None
        and request_count == 2
        and len(state.accepted) == 1
        and duplicate_count == 1
        and all(item["body_sha256"] == expected_body_sha for item in state.requests)
        and not state.errors
        and not cross_tenant_visible
        and restricted_mutation
        and force_rls
    )
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "status": (
            "local_wire_openlineage_delivery_verified" if verified else "blocked"
        ),
        "source_evidence_sha256": bundle.source_evidence_sha256,
        "binding_id": str(bundle.delivery.binding_id),
        "delivery_id": str(bundle.delivery.delivery_id),
        "source_plan_sha256": bundle.delivery.source_plan_sha256,
        "event_sha256": bundle.delivery.event_sha256,
        "idempotency_key": bundle.delivery.idempotency_key,
        "target_name": bundle.delivery.target_name,
        "first_enqueue_created": first_enqueue.created,
        "replay_enqueue_created": replay_enqueue.created,
        "first_attempt_response_status": after_first.response_status,
        "first_attempt_retry_pending": first_batch.retry_pending == 1,
        "final_response_status": stored.response_status,
        "final_attempt_count": stored.attempt_count,
        "receipt_sha256": stored.receipt_sha256,
        "wire_request_count": request_count,
        "receiver_unique_accept_count": len(state.accepted),
        "receiver_duplicate_count": duplicate_count,
        "wire_body_sha256": expected_body_sha,
        "wire_body_matched": all(
            item["body_sha256"] == expected_body_sha for item in state.requests
        ),
        "stable_idempotency_header_verified": all(
            item["idempotency_key"] == bundle.delivery.idempotency_key
            for item in state.requests
        ),
        "receiver_commit_then_failed_ack_recovered": (
            first_batch.retry_pending == 1
            and second_batch.delivered == 1
            and duplicate_count == 1
        ),
        "completed_delivery_not_reclaimed": third_batch.claimed == 0,
        "cross_tenant_read_blocked": not cross_tenant_visible,
        "gateway_direct_update_delete_blocked": bool(restricted_mutation),
        "force_rls_verified": bool(force_rls),
        "transport_semantics": "at_least_once_with_receiver_idempotency",
        "local_loopback_receiver": True,
        "receiver_credentials_used": False,
        "local_wire_openlineage_delivery_verified": verified,
        "live_openlineage_emission_verified": verified,
        "provider_mutations_executed": False,
        "writes_to_legacy": False,
        "provider_minimum_privilege_verified": False,
        "oidc_verified": False,
        "durable_catalog_verified": False,
        "production_receiver_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "errors": [] if verified else ["local OpenLineage delivery did not verify"],
    }
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def validate_rehearsal_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("lineage delivery evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("lineage delivery evidence SHA-256 does not match")
    for claim in (
        "provider_minimum_privilege_verified",
        "oidc_verified",
        "durable_catalog_verified",
        "production_receiver_verified",
        "production_ingestion_verified",
        "production_ready",
    ):
        if evidence.get(claim) is not False:
            errors.append(f"local lineage evidence may not claim {claim}")
    for claim in (
        "local_wire_openlineage_delivery_verified",
        "live_openlineage_emission_verified",
        "wire_body_matched",
        "stable_idempotency_header_verified",
        "receiver_commit_then_failed_ack_recovered",
        "completed_delivery_not_reclaimed",
        "cross_tenant_read_blocked",
        "gateway_direct_update_delete_blocked",
        "force_rls_verified",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"local lineage evidence did not verify {claim}")
    if evidence.get("transport_semantics") != (
        "at_least_once_with_receiver_idempotency"
    ):
        errors.append("lineage transport semantics are invalid")
    if evidence.get("receiver_credentials_used") is not False:
        errors.append("local lineage receiver must not use credentials")
    if evidence.get("provider_mutations_executed") is not False:
        errors.append("M3-4 must not mutate metadata providers")
    if evidence.get("writes_to_legacy") is not False:
        errors.append("M3-4 must not write legacy tables")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument(
        "--source-evidence", type=Path, default=DEFAULT_SOURCE_EVIDENCE
    )
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--database-url", required=True)
    rehearse.add_argument(
        "--source-evidence", type=Path, default=DEFAULT_SOURCE_EVIDENCE
    )
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_contract_report(source_evidence_path=args.source_evidence)
        try:
            evidence = _load_json_object(args.evidence)
            report["errors"].extend(validate_rehearsal_evidence(evidence))
        except (OSError, ValueError) as exc:
            report["errors"].append(
                f"lineage delivery evidence is invalid: {type(exc).__name__}"
            )
        report["status"] = "valid" if not report["errors"] else "invalid"
        report["local_wire_openlineage_delivery_verified"] = not report["errors"]
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report["errors"] else 1

    evidence = run_local_rehearsal(
        args.database_url,
        source_evidence_path=args.source_evidence,
    )
    args.evidence_out.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if not evidence["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
