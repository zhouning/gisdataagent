#!/usr/bin/env python3
"""Verify ApprovalCase on-call routing and Prometheus rules with real binaries."""

from __future__ import annotations

import argparse
import json
import secrets
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from rehearse_approval_alertmanager_delivery import (
    _container_port,
    _docker,
    _ensure_image,
    _wait_for_http,
    _wait_until,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALERTMANAGER_CONFIG = (
    REPO_ROOT / "config/alertmanager/approval-notification-routing.yaml"
)
PROMETHEUS_CONFIG_DIR = REPO_ROOT / "config/prometheus"
PROMETHEUS_RULE_TEST = "tests/approval-notification-rules.test.yaml"


class _WebhookReceiver(ThreadingHTTPServer):
    received: list[dict[str, Any]]

    def __init__(self) -> None:
        super().__init__(("0.0.0.0", 0), _WebhookHandler)
        self.received = []


class _WebhookHandler(BaseHTTPRequestHandler):
    server: _WebhookReceiver

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/approval-notifications":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            self.send_error(400)
            return
        self.server.received.append(payload)
        self.send_response(200)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _post_alert(alertmanager_url: str, labels: dict[str, str]) -> None:
    now = datetime.now(UTC)
    response = httpx.post(
        f"{alertmanager_url}/api/v2/alerts",
        json=[
            {
                "labels": labels,
                "annotations": {"summary": f"routing rehearsal for {labels['alertname']}"},
                "startsAt": _rfc3339(now),
                "endsAt": _rfc3339(now + timedelta(minutes=10)),
            }
        ],
        timeout=3.0,
    )
    response.raise_for_status()


def rehearse(
    *,
    alertmanager_image: str,
    prometheus_image: str,
) -> dict[str, Any]:
    _ensure_image(alertmanager_image)
    _ensure_image(prometheus_image)
    suffix = secrets.token_hex(5)
    container = f"gda-approval-routing-{suffix}"
    receiver = _WebhookReceiver()
    receiver_thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    receiver_thread.start()
    report: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="gda-approval-routing-") as temp_dir:
        secret_path = Path(temp_dir) / "approval-oncall-webhook-url"
        secret_path.write_text(
            "http://host.docker.internal:"
            f"{receiver.server_port}/approval-notifications\n",
            encoding="utf-8",
        )
        try:
            amtool = _docker(
                "run",
                "--rm",
                "--volume",
                f"{ALERTMANAGER_CONFIG}:/etc/alertmanager/alertmanager.yml:ro",
                "--entrypoint",
                "amtool",
                alertmanager_image,
                "check-config",
                "/etc/alertmanager/alertmanager.yml",
            )
            promtool = _docker(
                "run",
                "--rm",
                "--volume",
                f"{PROMETHEUS_CONFIG_DIR}:/rules:ro",
                "--workdir",
                "/rules",
                "--entrypoint",
                "promtool",
                prometheus_image,
                "test",
                "rules",
                PROMETHEUS_RULE_TEST,
            )
            _docker(
                "run",
                "--detach",
                "--name",
                container,
                "--publish",
                "127.0.0.1::9093",
                "--add-host",
                "host.docker.internal:host-gateway",
                "--volume",
                f"{ALERTMANAGER_CONFIG}:/etc/alertmanager/alertmanager.yml:ro",
                "--volume",
                f"{temp_dir}:/etc/alertmanager/secrets:ro",
                alertmanager_image,
                "--config.file=/etc/alertmanager/alertmanager.yml",
                "--storage.path=/alertmanager",
            )
            alertmanager_url = f"http://127.0.0.1:{_container_port(container, 9093)}"
            _wait_for_http(f"{alertmanager_url}/-/ready", "routing Alertmanager readiness")

            _post_alert(
                alertmanager_url,
                {
                    "alertname": "GDAApprovalCase",
                    "namespace": "gis-agent",
                    "gda_tenant": "routing-rehearsal",
                    "gda_approval_action": "data_product.release",
                    "gda_approval_case": (
                        "gda://routing-rehearsal/approval_case/release-1"
                    ),
                    "severity": "warning",
                },
            )
            _post_alert(
                alertmanager_url,
                {
                    "alertname": "UnrelatedControlAlert",
                    "namespace": "gis-agent",
                    "severity": "warning",
                },
            )
            _wait_until(
                lambda: len(receiver.received) >= 1,
                "ApprovalCase on-call webhook delivery",
                timeout_seconds=20,
            )

            delivered_alertnames = sorted(
                {
                    alert.get("labels", {}).get("alertname", "")
                    for delivery in receiver.received
                    for alert in delivery.get("alerts", [])
                }
            )
            if delivered_alertnames != ["GDAApprovalCase"]:
                raise AssertionError(
                    "receiver route delivered an unexpected alert set: "
                    f"{delivered_alertnames}"
                )
            receiver_names = sorted(
                {str(delivery.get("receiver", "")) for delivery in receiver.received}
            )
            if receiver_names != ["approval-oncall"]:
                raise AssertionError(f"unexpected Alertmanager receivers: {receiver_names}")

            report = {
                "schema": "gda.approval_observability_routing_rehearsal.v1",
                "status": "verified",
                "images": {
                    "alertmanager": alertmanager_image,
                    "prometheus": prometheus_image,
                },
                "receiver_delivery_count": len(receiver.received),
                "receiver_names": receiver_names,
                "delivered_alertnames": delivered_alertnames,
                "checks": {
                    "alertmanager_config_valid": "SUCCESS" in amtool.stdout,
                    "prometheus_rule_tests_passed": "SUCCESS" in promtool.stdout,
                    "approval_alert_reached_oncall": True,
                    "unrelated_alert_was_not_delivered": True,
                    "receiver_url_loaded_from_file": True,
                },
            }
        finally:
            _docker("rm", "--force", container, check=False)
            receiver.shutdown()
            receiver.server_close()
            receiver_thread.join(timeout=5)

    if report is None:
        raise RuntimeError("routing rehearsal ended without an evidence report")
    if _docker("inspect", container, check=False).returncode == 0:
        raise AssertionError("disposable Alertmanager container was not removed")
    report["checks"]["disposable_resources_cleaned"] = True
    if not all(report["checks"].values()):
        report["status"] = "failed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alertmanager-image", default="prom/alertmanager:v0.28.1")
    parser.add_argument("--prometheus-image", default="prom/prometheus:v3.5.0")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = rehearse(
        alertmanager_image=args.alertmanager_image,
        prometheus_image=args.prometheus_image,
    )
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
