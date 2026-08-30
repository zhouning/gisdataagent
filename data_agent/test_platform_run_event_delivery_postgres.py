from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from data_agent.platform_gateway import GatewayConflictError, PlatformGateway
from data_agent.platform_run_event_worker import (
    PlatformRunEventWorker,
    PlatformRunEventWorkerConfig,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
MIGRATIONS = Path(__file__).resolve().parent / "migrations"
BASE_MIGRATIONS = tuple(
    MIGRATIONS / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
    )
)
DELIVERY_MIGRATION = MIGRATIONS / "129_platform_run_event_delivery_outbox.sql"


class _CloudEventReceiver(ThreadingHTTPServer):
    received: list[dict[str, Any]]
    content_types: list[str]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _CloudEventHandler)
        self.received = []
        self.content_types = []


class _CloudEventHandler(BaseHTTPRequestHandler):
    server: _CloudEventReceiver

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/platform-runs":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            self.send_error(400)
            return
        self.server.received.append(payload)
        self.server.content_types.append(self.headers.get("content-type", ""))
        self.send_response(202)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _set_gateway_tenant(connection, tenant_id: str) -> None:
    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
    connection.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


def _register_definition(
    connection,
    *,
    tenant_id: str,
    definition_id: UUID,
    suffix: str,
) -> None:
    definition_urn = f"gda://{tenant_id}/definition/{suffix}"
    connection.execute(
        text(
            """
            INSERT INTO gda_control.resource (
                tenant_id, resource_urn, resource_kind,
                authority_system, authority_locator, owner_ref
            ) VALUES (
                :tenant_id, :definition_urn, 'definition',
                'gda', :authority_locator, 'dataops'
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "definition_urn": definition_urn,
            "authority_locator": f"definition/{suffix}",
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO gda_control.resource_version (
                tenant_id, resource_version_id, resource_urn,
                version_key, content_sha256, authority_version_ref, created_by
            ) VALUES (
                :tenant_id, :definition_id, :definition_urn,
                'v1', :sha256, CAST(:authority_version_ref AS jsonb), 'dataops'
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "definition_id": definition_id,
            "definition_urn": definition_urn,
            "sha256": "d" * 64,
            "authority_version_ref": json.dumps({"revision": 1}),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO gda_control.platform_definition_version (
                tenant_id, definition_version_id, definition_urn,
                orchestration_class, capability_id, portability_class,
                definition_document, input_contract, output_contract,
                definition_sha256
            ) VALUES (
                :tenant_id, :definition_id, :definition_urn,
                'dataops', 'dataops.run.submit-manual', 'portable',
                '{"tasks":["publish"]}', '{}', '{}', :sha256
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "definition_id": definition_id,
            "definition_urn": definition_urn,
            "sha256": "d" * 64,
        },
    )


def _insert_run(
    connection,
    *,
    tenant_id: str,
    definition_id: UUID,
    run_id: UUID,
    idempotency_key: str,
) -> UUID:
    connection.execute(
        text(
            """
            INSERT INTO gda_control.platform_run (
                tenant_id, run_id, definition_version_id,
                orchestration_class, subject_context,
                idempotency_key, submitted_by
            ) VALUES (
                :tenant_id, :run_id, :definition_id, 'dataops',
                CAST(:subject_context AS jsonb), :idempotency_key,
                'workload:run-event-certifier'
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "definition_id": definition_id,
            "subject_context": json.dumps(
                {
                    "tenant_id": tenant_id,
                    "subject_id": "run-event-certifier",
                    "subject_type": "workload",
                    "roles": ["platform_operator"],
                    "purpose": "certify CloudEvents delivery",
                }
            ),
            "idempotency_key": idempotency_key,
        },
    )
    return connection.execute(
        text(
            """
            SELECT event_id
            FROM gda_control.platform_run_event
            WHERE tenant_id = :tenant_id AND run_id = :run_id
              AND sequence_no = 0
            """
        ),
        {"tenant_id": tenant_id, "run_id": run_id},
    ).scalar_one()


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_outbox_to_real_http_cloudevents_delivery(
    isolated_postgres_url: str,
) -> None:
    engine = create_engine(isolated_postgres_url)
    suffix = uuid4().hex[:12]
    tenant_a = f"run-events-a-{suffix}"
    tenant_b = f"run-events-b-{suffix}"
    definition_a = uuid4()
    definition_b = uuid4()
    historical_run = uuid4()
    current_run = uuid4()
    tenant_b_run = uuid4()

    with engine.begin() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            pytest.skip("delivery migration acceptance requires a PostgreSQL superuser")
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_app_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL
            )
            """
        )
        for migration in BASE_MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))
        delivery_preexisting = connection.exec_driver_sql(
            "SELECT to_regclass('gda_control.platform_run_event_delivery_outbox')"
        ).scalar_one() is not None

    with engine.begin() as connection:
        _set_gateway_tenant(connection, tenant_a)
        _register_definition(
            connection,
            tenant_id=tenant_a,
            definition_id=definition_a,
            suffix=f"delivery-{suffix}",
        )
        if not delivery_preexisting:
            _insert_run(
                connection,
                tenant_id=tenant_a,
                definition_id=definition_a,
                run_id=historical_run,
                idempotency_key=f"historical-{suffix}",
            )

    with engine.begin() as connection:
        connection.execute(text(DELIVERY_MIGRATION.read_text(encoding="utf-8")))
        if not delivery_preexisting:
            historical_delivery_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM gda_control.platform_run_event_delivery_outbox
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    """
                ),
                {"tenant_id": tenant_a, "run_id": historical_run},
            ).scalar_one()
            assert historical_delivery_count == 0

    with engine.begin() as connection:
        _set_gateway_tenant(connection, tenant_a)
        current_event_id = _insert_run(
            connection,
            tenant_id=tenant_a,
            definition_id=definition_a,
            run_id=current_run,
            idempotency_key=f"current-{suffix}",
        )
        atomic_delivery = connection.execute(
            text(
                """
                SELECT run_event_id, run_sequence_no, status
                FROM gda_control.platform_run_event_delivery_outbox
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                """
            ),
            {"tenant_id": tenant_a, "run_id": current_run},
        ).one()
        assert atomic_delivery == (current_event_id, 0, "pending")

    with engine.begin() as connection:
        _set_gateway_tenant(connection, tenant_b)
        _register_definition(
            connection,
            tenant_id=tenant_b,
            definition_id=definition_b,
            suffix=f"delivery-{suffix}",
        )
        _insert_run(
            connection,
            tenant_id=tenant_b,
            definition_id=definition_b,
            run_id=tenant_b_run,
            idempotency_key=f"tenant-b-{suffix}",
        )

    receiver = _CloudEventReceiver()
    receiver_thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    receiver_thread.start()
    worker = PlatformRunEventWorker(
        PlatformRunEventWorkerConfig(
            tenant_id=tenant_a,
            worker_id="worker:run-event-certifier",
            receiver_url=(
                f"http://127.0.0.1:{receiver.server_port}/platform-runs"
            ),
            retry_delay_seconds=0,
        ),
        gateway=PlatformGateway(engine),
    )
    try:
        cycle = worker.run_once()
    finally:
        worker.client.close()
        receiver.shutdown()
        receiver.server_close()
        receiver_thread.join(timeout=5)

    assert (cycle.claimed, cycle.delivered, cycle.retrying) == (1, 1, 0)
    assert receiver.content_types == ["application/cloudevents+json"]
    assert len(receiver.received) == 1
    assert receiver.received[0]["id"] == str(current_event_id)
    assert receiver.received[0]["data"] == {
        "tenant_id": tenant_a,
        "run_id": str(current_run),
        "status": "accepted",
        "state_version": 0,
    }

    gateway = PlatformGateway(engine)
    tenant_b_claim = gateway.claim_platform_run_event_deliveries(
        tenant_b,
        "worker:tenant-b-first",
        limit=10,
        lease_seconds=5,
    )
    assert len(tenant_b_claim) == 1
    assert tenant_b_claim[0].event.tenant_id == tenant_b
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE gda_control.platform_run_event_delivery_outbox
                   SET claimed_until = clock_timestamp() - interval '1 second'
                 WHERE tenant_id = :tenant_id AND delivery_id = :delivery_id
                """
            ),
            {
                "tenant_id": tenant_b,
                "delivery_id": tenant_b_claim[0].delivery.delivery_id,
            },
        )
    reclaimed = gateway.claim_platform_run_event_deliveries(
        tenant_b,
        "worker:tenant-b-replacement",
        limit=10,
        lease_seconds=5,
    )
    assert len(reclaimed) == 1
    assert reclaimed[0].delivery.attempt_count == 2
    with pytest.raises(GatewayConflictError):
        gateway.complete_platform_run_event_delivery(
            tenant_b,
            reclaimed[0].delivery.delivery_id,
            worker_id="worker:tenant-b-first",
        )
    gateway.complete_platform_run_event_delivery(
        tenant_b,
        reclaimed[0].delivery.delivery_id,
        worker_id="worker:tenant-b-replacement",
    )

    gateway.transition_run(
        tenant_a,
        current_run,
        0,
        "dispatching",
        "workload:run-event-certifier",
        "provider accepted dispatch",
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE gda_control.platform_run_event_delivery_outbox
                   SET max_attempts = 1
                 WHERE tenant_id = :tenant_id AND run_id = :run_id
                   AND run_sequence_no = 1
                """
            ),
            {"tenant_id": tenant_a, "run_id": current_run},
        )
    dispatching_claim = gateway.claim_platform_run_event_deliveries(
        tenant_a,
        "worker:dead-letter",
        limit=10,
        lease_seconds=5,
    )
    assert len(dispatching_claim) == 1
    dead_letter = gateway.fail_platform_run_event_delivery(
        tenant_a,
        dispatching_claim[0].delivery.delivery_id,
        worker_id="worker:dead-letter",
        error="receiver rejected the event",
        retry_delay_seconds=0,
    )
    assert dead_letter.status.value == "failed"

    gateway.transition_run(
        tenant_a,
        current_run,
        1,
        "running",
        "workload:run-event-certifier",
        "provider started execution",
    )
    assert gateway.claim_platform_run_event_deliveries(
        tenant_a,
        "worker:blocked-sequence",
        limit=10,
        lease_seconds=5,
    ) == ()

    engine.dispose()
