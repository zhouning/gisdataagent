#!/usr/bin/env python3
"""Verify ApprovalCase recording rules and Grafana provisioning with real binaries."""

from __future__ import annotations

import argparse
import json
import secrets
import tempfile
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
PROMETHEUS_RULES = REPO_ROOT / "config/prometheus/approval-notification-rules.yaml"
GRAFANA_PROVISIONING = REPO_ROOT / "config/grafana/provisioning"
GRAFANA_DASHBOARD = (
    REPO_ROOT
    / "k8s/observability/approval-notifications/dashboards"
    / "approval-case-operations.json"
)
DASHBOARD_UID = "gda-approval-case-operations"
DATASOURCE_UID = "gda-prometheus"
RECORDING_RULE_GROUP = "gis-data-agent-approval-notification-sli"


def _get_json(
    url: str,
    *,
    auth: httpx.BasicAuth | None = None,
) -> dict[str, Any] | list[Any]:
    response = httpx.get(url, auth=auth, timeout=3.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise RuntimeError(f"API returned an unexpected payload: {url}")
    return payload


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _prometheus_rule_names(prometheus_url: str) -> set[str]:
    payload = _get_json(f"{prometheus_url}/api/v1/rules?type=record")
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise RuntimeError("Prometheus rule API did not return success")
    groups = payload.get("data", {}).get("groups", [])
    return {
        str(rule.get("name", ""))
        for group in groups
        if group.get("name") == RECORDING_RULE_GROUP
        for rule in group.get("rules", [])
    }


def rehearse(*, prometheus_image: str, grafana_image: str) -> dict[str, Any]:
    for image in (prometheus_image, grafana_image):
        _ensure_image(image)

    suffix = secrets.token_hex(5)
    network = f"gda-approval-grafana-{suffix}"
    prometheus_container = f"gda-approval-prom-{suffix}"
    grafana_container = f"gda-approval-grafana-{suffix}"
    containers = (grafana_container, prometheus_container)
    admin_user = "gda-rehearsal-admin"
    admin_password = secrets.token_urlsafe(24)
    report: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="gda-approval-grafana-") as temp_dir:
        prometheus_config = Path(temp_dir) / "prometheus.yml"
        prometheus_config.write_text(
            "global:\n"
            "  evaluation_interval: 5s\n"
            "rule_files:\n"
            "  - /etc/prometheus/rules/approval-notification-rules.yaml\n"
            "scrape_configs: []\n",
            encoding="utf-8",
        )
        try:
            _docker("network", "create", network)
            _docker(
                "run",
                "--detach",
                "--name",
                prometheus_container,
                "--network",
                network,
                "--publish",
                "127.0.0.1::9090",
                "--volume",
                f"{prometheus_config}:/etc/prometheus/prometheus.yml:ro",
                "--volume",
                f"{PROMETHEUS_RULES}:/etc/prometheus/rules/approval-notification-rules.yaml:ro",
                prometheus_image,
                "--config.file=/etc/prometheus/prometheus.yml",
                "--storage.tsdb.path=/prometheus",
            )
            prometheus_url = (
                f"http://127.0.0.1:{_container_port(prometheus_container, 9090)}"
            )
            _wait_for_http(f"{prometheus_url}/-/ready", "dashboard Prometheus")

            _docker(
                "run",
                "--detach",
                "--name",
                grafana_container,
                "--network",
                network,
                "--publish",
                "127.0.0.1::3000",
                "--env",
                f"GF_SECURITY_ADMIN_USER={admin_user}",
                "--env",
                f"GF_SECURITY_ADMIN_PASSWORD={admin_password}",
                "--env",
                "GF_USERS_ALLOW_SIGN_UP=false",
                "--env",
                "GF_AUTH_ANONYMOUS_ENABLED=false",
                "--env",
                (
                    "GDA_GRAFANA_PROMETHEUS_URL="
                    f"http://{prometheus_container}:9090"
                ),
                "--volume",
                f"{GRAFANA_PROVISIONING}:/etc/grafana/provisioning:ro",
                "--volume",
                f"{GRAFANA_DASHBOARD}:/var/lib/grafana/dashboards/approval-case-operations.json:ro",
                grafana_image,
            )
            grafana_url = f"http://127.0.0.1:{_container_port(grafana_container, 3000)}"
            _wait_for_http(f"{grafana_url}/api/health", "Grafana API")
            auth = httpx.BasicAuth(admin_user, admin_password)

            def dashboard_is_loaded() -> bool:
                response = httpx.get(
                    f"{grafana_url}/api/dashboards/uid/{DASHBOARD_UID}",
                    auth=auth,
                    timeout=3.0,
                )
                return response.status_code == 200

            _wait_until(
                dashboard_is_loaded,
                "provisioned ApprovalCase dashboard",
                timeout_seconds=30,
            )

            health = _get_json(f"{grafana_url}/api/health")
            datasource = _get_json(
                f"{grafana_url}/api/datasources/uid/{DATASOURCE_UID}",
                auth=auth,
            )
            datasource_health = _get_json(
                f"{grafana_url}/api/datasources/uid/{DATASOURCE_UID}/health",
                auth=auth,
            )
            search = _get_json(
                f"{grafana_url}/api/search?query=ApprovalCase%20Operations",
                auth=auth,
            )
            dashboard_payload = _get_json(
                f"{grafana_url}/api/dashboards/uid/{DASHBOARD_UID}",
                auth=auth,
            )
            rule_names = _prometheus_rule_names(prometheus_url)

            _require(isinstance(health, dict), "Grafana health payload is not an object")
            _require(
                health.get("database") == "ok",
                "Grafana database health is not ok",
            )
            _require(isinstance(datasource, dict), "datasource payload is not an object")
            _require(datasource.get("uid") == DATASOURCE_UID, "datasource UID drifted")
            _require(datasource.get("type") == "prometheus", "datasource is not Prometheus")
            _require(
                isinstance(datasource_health, dict)
                and str(datasource_health.get("status", "")).upper() == "OK",
                "Grafana could not query the provisioned Prometheus datasource",
            )
            _require(isinstance(search, list), "Grafana search payload is not a list")
            _require(
                any(item.get("uid") == DASHBOARD_UID for item in search),
                "Grafana search did not return the ApprovalCase dashboard",
            )
            _require(
                isinstance(dashboard_payload, dict),
                "Grafana dashboard payload is not an object",
            )
            dashboard = dashboard_payload.get("dashboard", {})
            metadata = dashboard_payload.get("meta", {})
            panels = dashboard.get("panels", [])
            _require(dashboard.get("uid") == DASHBOARD_UID, "dashboard UID drifted")
            _require(len(panels) == 10, "Grafana did not load all dashboard panels")
            _require(metadata.get("provisioned") is True, "dashboard is not provisioned")
            _require(
                metadata.get("folderUid") == "gda-approval-operations",
                "dashboard was loaded into an unexpected folder",
            )
            _require(
                {
                    "gda:approval_notification_worker_healthy_replicas",
                    "gda:approval_notification_worker_target_replicas",
                    "gda:approval_notification_cycle_success_age_seconds",
                    "gda:approval_notification_delivery_success:ratio_30m",
                    "gda:approval_notification_delivery_success:ratio_6h",
                    "gda:approval_notification_delivery_attempts:rate5m",
                    "gda:approval_notification_cycle_duration:p95_5m",
                }
                == rule_names,
                "Prometheus did not load the complete ApprovalCase recording-rule set",
            )

            report = {
                "schema": "gda.approval_grafana_provisioning_rehearsal.v1",
                "status": "verified",
                "images": {
                    "grafana": grafana_image,
                    "prometheus": prometheus_image,
                },
                "dashboard": {
                    "uid": DASHBOARD_UID,
                    "folder_uid": metadata.get("folderUid"),
                    "panel_count": len(panels),
                    "query_count": sum(
                        len(panel.get("targets", [])) for panel in panels
                    ),
                },
                "recording_rule_count": len(rule_names),
                "checks": {
                    "prometheus_recording_rules_loaded": True,
                    "grafana_database_healthy": True,
                    "prometheus_datasource_provisioned": True,
                    "prometheus_datasource_queryable": True,
                    "dashboard_searchable": True,
                    "dashboard_file_provisioned": True,
                    "dashboard_folder_bound": True,
                    "dashboard_panels_loaded": True,
                },
            }
        finally:
            for container in containers:
                _docker("rm", "--force", container, check=False)
            _docker("network", "rm", network, check=False)

    if report is None:
        raise RuntimeError("Grafana provisioning rehearsal ended without a report")
    if any(_docker("inspect", container, check=False).returncode == 0 for container in containers):
        raise AssertionError("a disposable dashboard container was not removed")
    if _docker("network", "inspect", network, check=False).returncode == 0:
        raise AssertionError("the disposable dashboard network was not removed")
    report["checks"]["disposable_resources_cleaned"] = True
    if not all(report["checks"].values()):
        report["status"] = "failed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-image", default="prom/prometheus:v3.5.0")
    parser.add_argument("--grafana-image", default="grafana/grafana:11.6.0")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = rehearse(
        prometheus_image=args.prometheus_image,
        grafana_image=args.grafana_image,
    )
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
