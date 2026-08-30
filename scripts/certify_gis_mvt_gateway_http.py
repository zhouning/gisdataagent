#!/usr/bin/env python3
"""Certify signed HTTP MVT consumption against a disposable active Martin release.

The fixture reuses the existing active-release authority. After activation it
requests and independently approves an exact-release ServiceConsumerBinding,
then exercises three HTTP requests: unauthenticated,
authenticated-but-unbound, and authenticated-and-bound.
It then approves an append-only revocation and proves the same signed subject
is denied before the provider is invoked again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.testclient import TestClient

from data_agent.api import platform_gateway_routes as gateway_routes
from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.db_engine import reset_engine
from data_agent.gis_mvt_response_cache import reset_mvt_response_cache
from data_agent.platform_contracts import (
    ApprovalAvailabilityStatus,
    ApprovalCaseStatus,
    ApprovalPrincipalStatus,
    ApprovalPrincipalType,
)
from data_agent.platform_gateway import GatewayValidationError, PlatformGateway
from data_agent.security_event_ledger import SecurityEventLedger
from data_agent.service_consumer_binding import (
    ServiceConsumerBinding,
    service_consumer_binding_fingerprint,
)
from data_agent.service_consumer_binding_grant import (
    ServiceConsumerBindingGrantService,
    build_service_consumer_binding_grant_plan,
)
from data_agent.service_consumer_binding_revocation import (
    ServiceConsumerBindingRevocationService,
    build_service_consumer_binding_revoke_plan,
)

try:  # Support both ``python scripts/...`` and package imports in pytest.
    from scripts.certify_martin_active_release import (
        MARTIN_DATABASE_HOST,
        MARTIN_DATABASE_PORT,
        MARTIN_IMAGE,
        MARTIN_NETWORK,
    )
    from scripts.certify_martin_active_release import (
        certify as certify_active_release,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script invocation path.
    from certify_martin_active_release import (
        MARTIN_DATABASE_HOST,
        MARTIN_DATABASE_PORT,
        MARTIN_IMAGE,
        MARTIN_NETWORK,
    )
    from certify_martin_active_release import (
        certify as certify_active_release,
    )

TENANT_ID = "planning"
SERVICE_URN = "gda://planning/gis_service/district-features"
AUTH_SECRET = "gda-mvt-gateway-http-certification-secret-0123456789abcdef"
REDIS_IMAGE = "redis:7-alpine"


def _service_consumer_binding(
    gateway: PlatformGateway,
    *,
    subject: str,
) -> ServiceConsumerBinding:
    projection = gateway.get_gis_service_control_projection(TENANT_ID, SERVICE_URN)
    definition = projection.active_service_definition_version
    release = projection.active_release_binding
    if definition is None or release is None:
        raise RuntimeError("active fixture is missing its GIS service release")
    now = datetime.now(UTC)
    values = {
        "tenant_id": TENANT_ID,
        "service_consumer_binding_id": uuid4(),
        "service_urn": SERVICE_URN,
        "service_definition_version_id": definition.service_definition_version_id,
        "service_release_binding_id": release.service_release_binding_id,
        "consumer_ref": subject,
        "action": "mvt.read",
        "purpose": "gis_mvt_read",
        "scope": {"operations": ["read"]},
        "credential_ref": "credential:fixture-mvt-reader",
        "expires_at": now + timedelta(hours=1),
        "compatibility_fingerprint": hashlib.sha256(
            b"gda-mvt-gateway-http-fixture"
        ).hexdigest(),
        "compatibility_evidence": {
            "schema": "gda.gis_mvt_http_service_compatibility.v1",
            "release_key": release.release_key,
            "service_release_sha256": release.binding_sha256,
        },
        "created_by": "workload:gateway-http-certifier",
        "created_at": now,
    }
    binding = ServiceConsumerBinding(
        **values,
        binding_sha256=service_consumer_binding_fingerprint(values),
    )
    approvals = ApprovalCaseAuthority(gateway._get_engine())
    approvals.upsert_principal(
        tenant_id=TENANT_ID,
        principal_subject="human:service-owner",
        expected_directory_version=0,
        principal_type=ApprovalPrincipalType.HUMAN,
        display_name="Fixture Service Owner",
        status=ApprovalPrincipalStatus.ACTIVE,
        approval_eligible=True,
        availability_status=ApprovalAvailabilityStatus.AVAILABLE,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=2),
        actor_subject="human:service-owner",
        reason="register fixture service grant approver",
    )
    grants = ServiceConsumerBindingGrantService(gateway, approvals)
    plan = build_service_consumer_binding_grant_plan(binding)
    requested = grants.request_grant(
        plan,
        requester_subject="workload:gateway-http-certifier",
        request_reason="authorize fixture MVT reader for the active release",
        owner_ref="team:spatial-data",
        requested_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    approvals.decide(
        tenant_id=TENANT_ID,
        approval_case_ref=requested.approval_case.approval_case_ref,
        expected_state_version=0,
        verdict=ApprovalCaseStatus.APPROVED,
        actor_subject="human:service-owner",
        reason="fixture MVT consumer grant approved",
    )
    result = grants.issue(
        plan,
        approval_case_ref=requested.approval_case.approval_case_ref,
    )
    if not result.created:
        raise RuntimeError("HTTP fixture ServiceConsumerBinding was unexpectedly replayed")
    return binding


def _signed_cookie(identifier: str) -> str:
    from chainlit.auth.jwt import create_jwt
    from chainlit.user import User

    return create_jwt(
        User(
            identifier=identifier,
            metadata={
                "role": "analyst",
                "tenant_id": TENANT_ID,
                "subject_type": "human",
            },
        )
    )


def _reserve_host_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _start_redis_cache() -> tuple[str, str, int]:
    """Start a disposable Redis endpoint for the real Gateway cache proof."""
    container = f"gda-mvt-cache-cert-{uuid4().hex[:10]}"
    port = _reserve_host_port()
    result = subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container,
            "--publish",
            f"127.0.0.1:{port}:6379",
            REDIS_IMAGE,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Redis fixture failed to start: {detail}")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        probe = subprocess.run(
            ["docker", "exec", container, "redis-cli", "ping"],
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0 and probe.stdout.strip() == "PONG":
            return container, f"redis://127.0.0.1:{port}/0", port
        time.sleep(0.2)
    subprocess.run(["docker", "rm", "--force", container], check=False)
    raise RuntimeError("Redis fixture did not become ready")


def _stop_redis_cache(container: str) -> None:
    subprocess.run(
        ["docker", "rm", "--force", container],
        check=False,
        capture_output=True,
        text=True,
    )


def _event_summary(gateway: PlatformGateway) -> list[dict[str, object]]:
    with gateway._transaction(TENANT_ID) as connection:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT phase, outcome, actor_subject, resource_ref, details
                      FROM gda_control.security_event
                     WHERE tenant_id = :tenant_id
                       AND action = 'mvt.read'
                     ORDER BY sequence_no
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
            .mappings()
            .all()
        )
    return [
        {
            "phase": row["phase"],
            "outcome": row["outcome"],
            "actor_subject": row["actor_subject"],
            "resource_ref": row["resource_ref"],
            "decision_sha256": row["details"].get("decision_sha256"),
            "denial_code": row["details"].get("denial_code"),
            "provider_invocations": row["details"].get("provider_invocations"),
            "delivery_source": row["details"].get("delivery_source"),
        }
        for row in rows
    ]


def _sqlstate(error: DBAPIError) -> str | None:
    original = getattr(error, "orig", None)
    return getattr(original, "pgcode", None)


def _binding_security_evidence(
    gateway: PlatformGateway, binding: ServiceConsumerBinding
) -> dict[str, object]:
    """Prove the binding is readable only through the gateway's controlled path."""

    engine = gateway._get_engine()
    values = binding.model_dump(mode="json")
    with engine.connect() as connection:
        with connection.begin():
            connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": binding.tenant_id},
            )
            direct_insert_sqlstate = None
            try:
                with connection.begin_nested():
                    connection.execute(
                        text(
                            """
                            INSERT INTO gda_control.service_consumer_binding (
                                tenant_id, service_consumer_binding_id, service_urn,
                                service_definition_version_id,
                                service_release_binding_id, consumer_ref, action,
                                purpose, scope, credential_ref, expires_at,
                                compatibility_fingerprint, compatibility_evidence,
                                binding_sha256, created_by, created_at
                            ) VALUES (
                                :tenant_id,
                                CAST(:service_consumer_binding_id AS uuid),
                                :service_urn,
                                CAST(:service_definition_version_id AS uuid),
                                CAST(:service_release_binding_id AS uuid),
                                :consumer_ref, :action, :purpose,
                                CAST(:scope AS jsonb), :credential_ref, :expires_at,
                                CAST(:compatibility_fingerprint AS char(64)),
                                CAST(:compatibility_evidence AS jsonb),
                                CAST(:binding_sha256 AS char(64)),
                                :created_by, :created_at
                            )
                            """
                        ),
                        {
                            **values,
                            "scope": json.dumps(values["scope"], separators=(",", ":")),
                            "compatibility_evidence": json.dumps(
                                values["compatibility_evidence"],
                                separators=(",", ":"),
                            ),
                        },
                    )
            except DBAPIError as error:
                direct_insert_sqlstate = _sqlstate(error)

            rls_enabled, rls_forced = connection.execute(
                text(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                      FROM pg_class
                     WHERE oid = 'gda_control.service_consumer_binding'::regclass
                    """
                )
            ).one()
            table_insert, recorder_execute = connection.execute(
                text(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_consumer_binding', 'INSERT'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_service_consumer_binding('
                            'text,uuid,text,char(64),text,uuid,uuid,text,text,text,'
                            'jsonb,text,timestamptz,char(64),jsonb,char(64),'
                            'text,timestamptz)',
                            'EXECUTE'
                        )
                    """
                )
            ).one()

    evidence = {
        "rls_enabled": bool(rls_enabled),
        "rls_forced": bool(rls_forced),
        "gateway_table_insert": bool(table_insert),
        "gateway_recorder_execute": bool(recorder_execute),
        "direct_insert_sqlstate": direct_insert_sqlstate,
    }
    if evidence != {
        "rls_enabled": True,
        "rls_forced": True,
        "gateway_table_insert": False,
        "gateway_recorder_execute": True,
        "direct_insert_sqlstate": "42501",
    }:
        raise RuntimeError(f"service consumer binding security contract failed: {evidence}")
    return evidence


def _certify_active_gateway_http(
    gateway: PlatformGateway,
    expected_active_release: dict[str, str],
    martin_origin: str,
) -> dict[str, object]:
    """Run real signed-cookie requests through normal Gateway dependencies."""

    engine = gateway._get_engine()
    import data_agent.db_engine as db_engine

    previous_engine = db_engine._engine
    previous_read_engine = db_engine._read_engine
    db_engine._engine = engine
    db_engine._read_engine = None
    app = FastAPI()
    app.router.routes.extend(gateway_routes.get_platform_gateway_routes())
    redis_container, redis_url, _ = _start_redis_cache()
    client: TestClient | None = None
    try:
        reset_mvt_response_cache()
        with patch.dict(
            os.environ,
            {
                "CHAINLIT_AUTH_SECRET": AUTH_SECRET,
                "MARTIN_URL": martin_origin,
                "GDA_GIS_MVT_CACHE_REDIS_URL": redis_url,
                "GDA_GIS_MVT_CACHE_KEY_PREFIX": "gda:mvt:certification:v1",
                "GDA_GIS_MVT_CACHE_TIMEOUT_SECONDS": "0.5",
            },
        ):
            client = TestClient(app)
            client.__enter__()
            route = "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf"
            unauthenticated = client.get(route, params={"service_urn": SERVICE_URN})

            client.cookies.set("access_token", _signed_cookie("unbound-01"))
            unbound = client.get(
                route,
                params={"service_urn": SERVICE_URN},
                headers={"x-request-id": "mvt-http-unbound-01"},
            )

            binding = _service_consumer_binding(gateway, subject="human:analyst-01")
            binding_security = _binding_security_evidence(gateway, binding)
            client.cookies.set("access_token", _signed_cookie("analyst-01"))
            bound = client.get(
                route,
                params={"service_urn": SERVICE_URN},
                headers={"x-request-id": "mvt-http-bound-01"},
            )
            bound_replay = client.get(
                route,
                params={"service_urn": SERVICE_URN},
                headers={"x-request-id": "mvt-http-bound-replay-01"},
            )
            _stop_redis_cache(redis_container)
            bound_cache_fallback = client.get(
                route,
                params={"service_urn": SERVICE_URN},
                headers={"x-request-id": "mvt-http-bound-fallback-01"},
            )
            revoke_approvals = ApprovalCaseAuthority(gateway._get_engine())
            revoke_plan = build_service_consumer_binding_revoke_plan(
                binding,
                reason="HTTP certification revokes the disposable reader",
                context={"certificate": "gis-mvt-gateway-http", "ticket": "CERT-214"},
            )
            revoke_service = ServiceConsumerBindingRevocationService(
                gateway, revoke_approvals
            )
            revoke_now = datetime.now(UTC)
            revoke_request = revoke_service.request_revoke(
                revoke_plan,
                requester_subject="workload:gateway-http-certifier",
                request_reason="revoke disposable HTTP certification reader",
                owner_ref="team:spatial-data",
                requested_at=revoke_now,
                expires_at=revoke_now + timedelta(minutes=30),
            )
            pending_revoke_rejected = False
            try:
                revoke_service.revoke(
                    revoke_plan,
                    approval_case_ref=revoke_request.approval_case.approval_case_ref,
                )
            except GatewayValidationError:
                pending_revoke_rejected = True
            revoke_approvals.decide(
                tenant_id=TENANT_ID,
                approval_case_ref=revoke_request.approval_case.approval_case_ref,
                expected_state_version=0,
                verdict=ApprovalCaseStatus.APPROVED,
                actor_subject="human:service-owner",
                reason="HTTP certification revoke approved",
            )
            revoke_write = revoke_service.revoke(
                revoke_plan,
                approval_case_ref=revoke_request.approval_case.approval_case_ref,
            )
            revoked = client.get(
                route,
                params={"service_urn": SERVICE_URN},
                headers={"x-request-id": "mvt-http-revoked-01"},
            )
    finally:
        if client is not None:
            client.__exit__(None, None, None)
        _stop_redis_cache(redis_container)
        reset_mvt_response_cache()
        db_engine._engine = previous_engine
        db_engine._read_engine = previous_read_engine

    events = _event_summary(gateway)
    if unauthenticated.status_code != 401:
        raise RuntimeError("unauthenticated MVT HTTP request was not rejected")
    if (
        unbound.status_code != 403
        or unbound.json().get("error", {}).get("code")
        != "service_consumer_binding_required"
    ):
        raise RuntimeError("unbound MVT HTTP request was not rejected by ServiceConsumerBinding")
    if bound.status_code != 200 or not bound.content:
        raise RuntimeError("bound MVT HTTP request did not return a non-empty tile")
    if bound.headers.get("x-gda-service-release") != "v1.0.0":
        raise RuntimeError("bound MVT HTTP response omitted the active release")
    if "private" not in bound.headers.get("cache-control", ""):
        raise RuntimeError("bound MVT HTTP response did not preserve private caching")
    generation = bound.headers.get("x-gda-cache-generation", "")
    if len(generation) != 64 or any(
        character not in "0123456789abcdef" for character in generation
    ):
        raise RuntimeError("bound MVT HTTP response omitted the full cache generation")
    if bound_replay.status_code != 200 or bound_replay.content != bound.content:
        raise RuntimeError("replayed MVT HTTP request did not return the cached tile")
    if bound.headers.get("x-gda-shared-cache") != "miss":
        raise RuntimeError("first bound MVT request did not record a cache miss")
    if bound_replay.headers.get("x-gda-shared-cache") != "hit":
        raise RuntimeError("replayed bound MVT request did not hit Redis")
    if bound_cache_fallback.status_code != 200 or not bound_cache_fallback.content:
        raise RuntimeError("MVT request did not fall back after Redis outage")
    if bound_cache_fallback.headers.get("x-gda-shared-cache") != "miss":
        raise RuntimeError("Redis outage was not recorded as a cache miss")
    if not SecurityEventLedger(engine).verify_chain(TENANT_ID):
        raise RuntimeError("MVT HTTP security event chain did not verify")
    if [event["phase"] for event in events] != [
        "denied",
        "admitted",
        "outcome",
        "admitted",
        "outcome",
        "admitted",
        "outcome",
        "denied",
    ]:
        raise RuntimeError(f"MVT HTTP audit phases were incomplete: {events}")
    if events[0]["denial_code"] != "service_consumer_binding_required":
        raise RuntimeError("MVT HTTP denial audit did not retain its reason code")
    if events[1]["decision_sha256"] != events[2]["decision_sha256"]:
        raise RuntimeError("MVT HTTP admission and outcome did not share one decision")
    if [event["provider_invocations"] for event in events[1:8]] != [
        0,
        1,
        0,
        0,
        0,
        1,
        None,
    ]:
        raise RuntimeError(f"MVT HTTP audit did not prove cache/provider sources: {events}")
    if (
        not pending_revoke_rejected
        or not revoke_write.revocation.created
        or revoked.status_code != 403
        or revoked.json().get("error", {}).get("code")
        != "service_consumer_binding_required"
        or events[7]["denial_code"] != "service_consumer_binding_required"
        or events[7]["provider_invocations"] not in (None, 0)
    ):
        raise RuntimeError("revoked MVT binding was still admitted or provider was called")

    return {
        "schema": "gda.gis_mvt_gateway_http_certification.v3",
        "status": "passed",
        "transport": "fastapi_http_contract",
        "active_release": expected_active_release,
        "service_consumer_binding_id": str(binding.service_consumer_binding_id),
        "service_consumer_binding_security": binding_security,
        "requests": {
            "unauthenticated_status": unauthenticated.status_code,
            "unbound_status": unbound.status_code,
            "unbound_error_code": unbound.json()["error"]["code"],
            "bound_status": bound.status_code,
            "bound_content_bytes": len(bound.content),
            "bound_cache_control": bound.headers["cache-control"],
            "bound_cache_miss_source": bound.headers["x-gda-shared-cache"],
            "bound_replay_source": bound_replay.headers["x-gda-shared-cache"],
            "bound_replay_provider_invocations": events[4]["provider_invocations"],
            "bound_fallback_source": bound_cache_fallback.headers["x-gda-shared-cache"],
            "bound_release_key": bound.headers["x-gda-service-release"],
            "bound_cache_generation": generation,
            "revoked_status": revoked.status_code,
            "revoked_error_code": revoked.json()["error"]["code"],
        },
        "security_event_chain_valid": True,
        "security_events": events,
        "revocation": {
            "pending_rejected": pending_revoke_rejected,
            "created": revoke_write.revocation.created,
            "active_lookup_denied": revoked.status_code == 403,
        },
    }


def _write_report(report: dict[str, object], report_path: Path | None) -> str | None:
    if report_path is None:
        return None
    report_path.parent.mkdir(parents=True, exist_ok=True)
    contents = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_path.write_text(contents, encoding="utf-8")
    return hashlib.sha256(contents.encode("utf-8")).hexdigest()


def certify(
    database_url: str,
    *,
    docker_network: str = MARTIN_NETWORK,
    docker_database_host: str = MARTIN_DATABASE_HOST,
    docker_database_port: int = MARTIN_DATABASE_PORT,
    martin_image: str = MARTIN_IMAGE,
    report_path: Path | None = None,
) -> dict[str, object]:
    """Run the active Martin fixture and its signed Gateway MVT HTTP proof."""

    reset_engine()
    try:
        fixture = certify_active_release(
            database_url,
            docker_network=docker_network,
            docker_database_host=docker_database_host,
            docker_database_port=docker_database_port,
            martin_image=martin_image,
            after_activation=_certify_active_gateway_http,
        )
    finally:
        reset_engine()
    proof = fixture.get("post_activation")
    if not isinstance(proof, dict) or proof.get("status") != "passed":
        raise RuntimeError("active Martin fixture did not produce a Gateway HTTP proof")
    report = {
        "schema": "gda.gis_mvt_gateway_http_certification.v3",
        "status": "passed",
        "fixture": {
            "ephemeral": fixture["fixture"]["ephemeral"],
            "cleanup": fixture["fixture"]["cleanup"],
            "martin_image": fixture["fixture"]["martin_image"],
        },
        "gateway_http": proof,
    }
    _write_report(report, report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default="postgresql://postgres:postgres@127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--docker-network", default=MARTIN_NETWORK)
    parser.add_argument("--docker-database-host", default=MARTIN_DATABASE_HOST)
    parser.add_argument("--docker-database-port", type=int, default=MARTIN_DATABASE_PORT)
    parser.add_argument("--martin-image", default=MARTIN_IMAGE)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = certify(
        args.database_url,
        docker_network=args.docker_network,
        docker_database_host=args.docker_database_host,
        docker_database_port=args.docker_database_port,
        martin_image=args.martin_image,
        report_path=args.report,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.report is not None:
        print(f"report_sha256={hashlib.sha256(args.report.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
