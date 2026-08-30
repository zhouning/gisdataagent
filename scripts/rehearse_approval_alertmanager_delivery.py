#!/usr/bin/env python3
"""Rehearse ApprovalCase delivery against real PostgreSQL, Alertmanager, and Prometheus."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from prometheus_client import start_http_server
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.approval_case_notification_worker import (
    ApprovalCaseNotificationCycle,
    ApprovalCaseNotificationWorker,
    ApprovalCaseNotificationWorkerConfig,
)
from data_agent.platform_contracts import ApprovalCase

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = tuple(
    REPO_ROOT / "data_agent/migrations" / name
    for name in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "118_approval_case_sla_notification_outbox.sql",
        "119_approval_notification_governed_recovery.sql",
        "120_approval_case_assignment_authority.sql",
        "121_approval_principal_directory.sql",
    )
)
RUNTIME_ROLE = "gda_approval_delivery_runtime"
TENANT_ID = "approval-delivery-rehearsal"
WORKER_ID = "worker:approval-alertmanager:rehearsal"
APPROVER = "human:delivery-rehearsal-steward"


def _docker(
    *args: str,
    check: bool = True,
    timeout_seconds: float = 120,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["docker", *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        operation = " ".join(args[:2])
        raise RuntimeError(
            f"docker {operation} exceeded {timeout_seconds:g} seconds"
        ) from exc


def _ensure_image(image: str) -> None:
    inspected = _docker("image", "inspect", image, check=False)
    if inspected.returncode != 0:
        _docker("pull", image, timeout_seconds=300)


def _container_port(container: str, container_port: int) -> int:
    binding = _docker("port", container, f"{container_port}/tcp").stdout.strip()
    if not binding:
        raise RuntimeError(f"container {container} has no published port {container_port}")
    return int(binding.splitlines()[0].rsplit(":", 1)[1])


def _wait_until(
    predicate: Callable[[], bool],
    description: str,
    *,
    timeout_seconds: float = 30,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
        time.sleep(0.25)
    detail = f": {last_error}" if last_error is not None else ""
    raise RuntimeError(f"timed out waiting for {description}{detail}")


def _wait_for_http(url: str, description: str) -> None:
    def ready() -> bool:
        response = httpx.get(url, timeout=1.0)
        return 200 <= response.status_code < 300

    _wait_until(ready, description)


def _start_postgres(container: str, image: str) -> int:
    _docker(
        "run",
        "--detach",
        "--name",
        container,
        "--publish",
        "127.0.0.1::5432",
        "--env",
        "POSTGRES_HOST_AUTH_METHOD=trust",
        image,
    )

    def ready() -> bool:
        return (
            _docker("exec", container, "pg_isready", "-U", "postgres", check=False)
            .returncode
            == 0
        )

    _wait_until(ready, "disposable PostgreSQL")
    return _container_port(container, 5432)


def _start_alertmanager(container: str, image: str) -> tuple[int, str]:
    _docker(
        "run",
        "--detach",
        "--name",
        container,
        "--publish",
        "127.0.0.1::9093",
        image,
    )
    port = _container_port(container, 9093)
    base_url = f"http://127.0.0.1:{port}"
    _wait_for_http(f"{base_url}/-/ready", "Alertmanager readiness")
    return port, base_url


def _start_prometheus(
    container: str,
    image: str,
    config_path: Path,
) -> tuple[int, str]:
    _docker(
        "run",
        "--detach",
        "--name",
        container,
        "--publish",
        "127.0.0.1::9090",
        "--add-host",
        "host.docker.internal:host-gateway",
        "--volume",
        f"{config_path}:/etc/prometheus/prometheus.yml:ro",
        image,
        "--config.file=/etc/prometheus/prometheus.yml",
        "--storage.tsdb.path=/prometheus",
    )
    port = _container_port(container, 9090)
    base_url = f"http://127.0.0.1:{port}"
    _wait_for_http(f"{base_url}/-/ready", "Prometheus readiness")
    return port, base_url


def _wait_for_connection(engine) -> None:
    last_error = None
    for _ in range(120):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except DBAPIError as exc:
            last_error = exc
            engine.dispose()
            time.sleep(0.25)
    raise RuntimeError("PostgreSQL host port did not become ready") from last_error


def _bootstrap(admin_engine) -> str:
    with admin_engine.begin() as connection:
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))
        connection.exec_driver_sql(
            f"CREATE ROLE {RUNTIME_ROLE} LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS"
        )
        connection.exec_driver_sql(f"GRANT gda_control_gateway TO {RUNTIME_ROLE}")
        return str(connection.execute(text("SHOW server_version")).scalar_one())


def _approval_case(case_id: str, *, expires_in_seconds: float) -> ApprovalCase:
    requested_at = datetime.now(UTC)
    return ApprovalCase(
        tenant_id=TENANT_ID,
        approval_case_ref=f"gda://{TENANT_ID}/approval_case/{case_id}",
        target_resource_urn=f"gda://{TENANT_ID}/data_product/{case_id}",
        target_fingerprint=("a" if case_id == "approved-release" else "b") * 64,
        action="data_product.release",
        requester_subject="workload:release-controller",
        request_reason="rehearse durable ApprovalCase delivery",
        requested_at=requested_at,
        expires_at=requested_at + timedelta(seconds=expires_in_seconds),
    )


def _register_approver(authority: ApprovalCaseAuthority) -> None:
    now = datetime.now(UTC)
    authority.upsert_principal(
        tenant_id=TENANT_ID,
        principal_subject=APPROVER,
        expected_directory_version=0,
        principal_type="human",
        display_name="Delivery rehearsal steward",
        status="active",
        approval_eligible=True,
        availability_status="available",
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=1),
        actor_subject="human:platform-admin",
        reason="register disposable ApprovalCase rehearsal approver",
    )


def _notification_projection(
    authority: ApprovalCaseAuthority,
    approval_case: ApprovalCase,
) -> dict[str, dict[str, Any]]:
    return {
        notification.notification_kind.value: {
            "status": notification.status.value,
            "attempt_count": notification.attempt_count,
            "last_error": notification.last_error,
        }
        for notification in authority.notifications(
            TENANT_ID,
            approval_case.approval_case_ref,
        )
    }


def _prometheus_query_value(prometheus_url: str, query: str) -> float:
    response = httpx.get(
        f"{prometheus_url}/api/v1/query",
        params={"query": query},
        timeout=3.0,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {query}")
    result = payload.get("data", {}).get("result", [])
    if not isinstance(result, list) or not result:
        return 0.0
    return sum(float(sample["value"][1]) for sample in result)


def _prometheus_target_up(prometheus_url: str) -> bool:
    response = httpx.get(f"{prometheus_url}/api/v1/targets", timeout=3.0)
    response.raise_for_status()
    active = response.json().get("data", {}).get("activeTargets", [])
    return any(
        target.get("labels", {}).get("job") == "approval-notification-worker"
        and target.get("health") == "up"
        for target in active
    )


def _active_approval_alerts(alertmanager_url: str) -> list[dict[str, Any]]:
    response = httpx.get(f"{alertmanager_url}/api/v2/alerts", timeout=3.0)
    response.raise_for_status()
    alerts = response.json()
    if not isinstance(alerts, list):
        raise RuntimeError("Alertmanager returned a non-list alert response")
    return [
        alert
        for alert in alerts
        if alert.get("labels", {}).get("alertname") == "GDAApprovalCase"
        and alert.get("status", {}).get("state") == "active"
    ]


def _cycle_dict(cycle: ApprovalCaseNotificationCycle) -> dict[str, int]:
    return {
        "claimed": cycle.claimed,
        "delivered": cycle.delivered,
        "retrying": cycle.retrying,
        "dead_lettered": cycle.dead_lettered,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def rehearse(
    *,
    postgres_image: str,
    alertmanager_image: str,
    prometheus_image: str,
) -> dict[str, Any]:
    suffix = secrets.token_hex(5)
    postgres_container = f"gda-approval-pg-{suffix}"
    alertmanager_container = f"gda-approval-am-{suffix}"
    prometheus_container = f"gda-approval-prom-{suffix}"
    containers = (
        prometheus_container,
        alertmanager_container,
        postgres_container,
    )
    admin_engine = None
    runtime_engine = None
    metrics_server = None
    metrics_thread = None
    worker = None
    report: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="gda-approval-delivery-") as temp_dir:
        try:
            for image in (postgres_image, alertmanager_image, prometheus_image):
                _ensure_image(image)
            postgres_port = _start_postgres(postgres_container, postgres_image)
            admin_engine = create_engine(
                f"postgresql+psycopg2://postgres@127.0.0.1:{postgres_port}/postgres"
            )
            _wait_for_connection(admin_engine)
            postgres_version = _bootstrap(admin_engine)
            runtime_engine = create_engine(
                f"postgresql+psycopg2://{RUNTIME_ROLE}@127.0.0.1:"
                f"{postgres_port}/postgres"
            )
            _wait_for_connection(runtime_engine)

            _alertmanager_port, alertmanager_url = _start_alertmanager(
                alertmanager_container,
                alertmanager_image,
            )
            metrics_server, metrics_thread = start_http_server(0, addr="0.0.0.0")
            metrics_port = int(metrics_server.server_port)
            prometheus_config = Path(temp_dir) / "prometheus.yml"
            prometheus_config.write_text(
                "global:\n"
                "  scrape_interval: 1s\n"
                "  scrape_timeout: 1s\n"
                "scrape_configs:\n"
                "  - job_name: approval-notification-worker\n"
                "    static_configs:\n"
                f"      - targets: ['host.docker.internal:{metrics_port}']\n",
                encoding="utf-8",
            )
            _prometheus_port, prometheus_url = _start_prometheus(
                prometheus_container,
                prometheus_image,
                prometheus_config,
            )

            authority = ApprovalCaseAuthority(runtime_engine)
            _register_approver(authority)
            approved_case = _approval_case("approved-release", expires_in_seconds=120)
            expired_case = _approval_case("expired-release", expires_in_seconds=8)
            authority.create(approved_case, owner_ref="team:data-platform")
            authority.create(expired_case, owner_ref="team:data-platform")

            worker = ApprovalCaseNotificationWorker(
                ApprovalCaseNotificationWorkerConfig(
                    tenant_id=TENANT_ID,
                    worker_id=WORKER_ID,
                    alertmanager_url=alertmanager_url,
                    batch_size=10,
                    lease_seconds=30,
                    retry_delay_seconds=0,
                    poll_interval_seconds=0.1,
                    timeout_seconds=1.0,
                ),
                authority=authority,
            )

            _docker("pause", alertmanager_container)
            outage_cycle = worker.run_once()
            _require(
                outage_cycle.claimed == 2
                and outage_cycle.retrying == 2
                and outage_cycle.delivered == 0,
                "Alertmanager outage did not return both requested events to pending",
            )

            _docker("unpause", alertmanager_container)
            _wait_for_http(
                f"{alertmanager_url}/-/ready",
                "restarted Alertmanager readiness",
            )
            recovery_cycle = worker.run_once()
            _require(
                recovery_cycle.claimed == 2
                and recovery_cycle.delivered == 2
                and recovery_cycle.retrying == 0,
                "requested notifications were not recovered exactly once",
            )

            authority.decide(
                tenant_id=TENANT_ID,
                approval_case_ref=approved_case.approval_case_ref,
                expected_state_version=0,
                verdict="approved",
                actor_subject=APPROVER,
                reason="approve during real delivery rehearsal",
            )
            remaining = (expired_case.expires_at - datetime.now(UTC)).total_seconds()
            if remaining > 0:
                time.sleep(remaining + 0.25)

            lifecycle_cycle = worker.run_once()
            _require(
                lifecycle_cycle.claimed == 2
                and lifecycle_cycle.delivered == 2
                and lifecycle_cycle.retrying == 0,
                "decided and expired lifecycle facts were not delivered",
            )
            idle_cycle = worker.run_once()
            _require(idle_cycle.claimed == 0, "outbox was not idempotently drained")

            approved_projection = _notification_projection(authority, approved_case)
            expired_projection = _notification_projection(authority, expired_case)
            _require(
                {
                    kind: value["status"]
                    for kind, value in approved_projection.items()
                }
                == {"requested": "done", "expired": "suppressed", "decided": "done"},
                "approved case notification projection is inconsistent",
            )
            _require(
                {
                    kind: value["status"]
                    for kind, value in expired_projection.items()
                }
                == {"requested": "done", "expired": "done"},
                "expired case notification projection is inconsistent",
            )
            _require(
                authority.get(TENANT_ID, expired_case.approval_case_ref).status.value
                == "pending",
                "expiry manufactured an ApprovalCase verdict",
            )

            alert_snapshot: list[dict[str, Any]] = []

            def alert_state_converged() -> bool:
                nonlocal alert_snapshot
                alert_snapshot = _active_approval_alerts(alertmanager_url)
                by_case = {
                    alert.get("labels", {}).get("gda_approval_case"): alert
                    for alert in alert_snapshot
                }
                return (
                    approved_case.approval_case_ref not in by_case
                    and by_case.get(expired_case.approval_case_ref, {})
                    .get("annotations", {})
                    .get("gda_status")
                    == "expired"
                )

            _wait_until(alert_state_converged, "Alertmanager lifecycle convergence")

            delivered_metric = 0.0
            retrying_metric = 0.0
            cycle_count_metric = 0.0

            def metrics_converged() -> bool:
                nonlocal delivered_metric, retrying_metric, cycle_count_metric
                if not _prometheus_target_up(prometheus_url):
                    return False
                delivered_metric = _prometheus_query_value(
                    prometheus_url,
                    'sum(gda_approval_notification_operations_total{outcome="delivered"})',
                )
                retrying_metric = _prometheus_query_value(
                    prometheus_url,
                    'sum(gda_approval_notification_operations_total{outcome="retrying"})',
                )
                cycle_count_metric = _prometheus_query_value(
                    prometheus_url,
                    "sum(gda_approval_notification_cycle_duration_seconds_count)",
                )
                return (
                    delivered_metric >= 4
                    and retrying_metric >= 2
                    and cycle_count_metric >= 4
                )

            _wait_until(metrics_converged, "Prometheus ApprovalCase metrics scrape")

            active_by_case = {
                alert["labels"]["gda_approval_case"]: {
                    "status": alert["annotations"]["gda_status"],
                    "notification_kind": alert["annotations"][
                        "gda_notification_kind"
                    ],
                }
                for alert in alert_snapshot
            }
            report = {
                "schema": "gda.approval_alertmanager_delivery_rehearsal.v1",
                "status": "verified",
                "tenant_id": TENANT_ID,
                "images": {
                    "postgresql": postgres_image,
                    "alertmanager": alertmanager_image,
                    "prometheus": prometheus_image,
                },
                "postgresql_server_version": postgres_version,
                "cycles": {
                    "alertmanager_outage": _cycle_dict(outage_cycle),
                    "alertmanager_recovery": _cycle_dict(recovery_cycle),
                    "lifecycle_delivery": _cycle_dict(lifecycle_cycle),
                    "idempotent_drain": _cycle_dict(idle_cycle),
                },
                "notification_projection": {
                    "approved_case": approved_projection,
                    "expired_case": expired_projection,
                },
                "approval_case_status": {
                    "approved_case": authority.get(
                        TENANT_ID, approved_case.approval_case_ref
                    ).status.value,
                    "expired_case": authority.get(
                        TENANT_ID, expired_case.approval_case_ref
                    ).status.value,
                },
                "alertmanager_active_approval_alerts": active_by_case,
                "prometheus": {
                    "target_health": "up",
                    "delivered_operations": delivered_metric,
                    "retrying_operations": retrying_metric,
                    "observed_cycles": cycle_count_metric,
                },
                "checks": {
                    "outage_returns_requested_notifications_to_pending": True,
                    "receiver_recovery_delivers_requested_notifications": True,
                    "decision_closes_stable_alert_identity": True,
                    "expiry_remains_an_sla_fact": True,
                    "outbox_is_idempotently_drained": True,
                    "prometheus_scraped_worker_metrics": True,
                },
            }
        finally:
            if worker is not None:
                worker.client.close()
            if metrics_server is not None:
                metrics_server.shutdown()
                metrics_server.server_close()
            if metrics_thread is not None:
                metrics_thread.join(timeout=5)
            if runtime_engine is not None:
                runtime_engine.dispose()
            if admin_engine is not None:
                admin_engine.dispose()
            for container in containers:
                _docker("rm", "--force", container, check=False)

    if report is None:
        raise RuntimeError("rehearsal ended without an evidence report")
    resources_cleaned = all(
        _docker("inspect", container, check=False).returncode != 0
        for container in containers
    )
    _require(resources_cleaned, "one or more disposable containers were not removed")
    report["checks"]["disposable_resources_cleaned"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-image", default="postgres:16")
    parser.add_argument("--alertmanager-image", default="prom/alertmanager:v0.28.1")
    parser.add_argument("--prometheus-image", default="prom/prometheus:v3.5.0")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = rehearse(
        postgres_image=args.postgres_image,
        alertmanager_image=args.alertmanager_image,
        prometheus_image=args.prometheus_image,
    )
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
