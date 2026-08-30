from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "k8s/observability/approval-notifications"
DASHBOARD = K8S / "dashboards/approval-case-operations.json"
GRAFANA_PROVISIONING = ROOT / "config/grafana/provisioning"


def _documents(filename: str) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all((K8S / filename).read_text(encoding="utf-8"))
        if document is not None
    ]


def _document(filename: str, kind: str) -> dict:
    return next(item for item in _documents(filename) if item["kind"] == kind)


def test_worker_is_ha_and_uses_a_dedicated_runtime_secret() -> None:
    deployment = _document("worker.yaml", "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    environment = {item["name"]: item for item in container["env"]}

    assert deployment["spec"]["replicas"] == 2
    assert deployment["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert pod["automountServiceAccountToken"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert environment["GDA_ALERTMANAGER_URL"]["valueFrom"]["secretKeyRef"] == {
        "name": "gis-agent-approval-notification-runtime",
        "key": "alertmanager-url",
    }
    assert environment["POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == (
        "gis-agent-approval-notification-runtime"
    )
    assert environment["GDA_APPROVAL_NOTIFICATION_ROUTE_NAMESPACE"]["valueFrom"][
        "fieldRef"
    ]["fieldPath"] == "metadata.namespace"
    assert environment["GDA_ALERTMANAGER_BEARER_TOKEN_FILE"]["value"].endswith(
        "/token"
    )
    token_volume = next(
        volume for volume in pod["volumes"] if volume["name"] == "alertmanager-token"
    )
    assert token_volume["secret"]["defaultMode"] == 0o440
    assert "gis-agent-secret" not in str(deployment)


def test_service_monitor_scrapes_each_worker_pod_via_the_metrics_service() -> None:
    monitor = _document("service-monitor.yaml", "ServiceMonitor")
    endpoint = monitor["spec"]["endpoints"][0]

    assert monitor["spec"]["jobLabel"] == "app.kubernetes.io/name"
    assert monitor["spec"]["namespaceSelector"]["matchNames"] == ["gis-agent"]
    assert endpoint == {
        "port": "metrics",
        "path": "/metrics",
        "scheme": "http",
        "interval": "30s",
        "scrapeTimeout": "10s",
    }


def test_prometheus_rule_crd_matches_the_promtool_source() -> None:
    canonical = yaml.safe_load(
        (ROOT / "config/prometheus/approval-notification-rules.yaml").read_text(
            encoding="utf-8"
        )
    )
    custom_resource = _document("prometheus-rule.yaml", "PrometheusRule")

    assert custom_resource["spec"]["groups"] == canonical["groups"]
    alert_names = {
        rule["alert"]
        for group in canonical["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }
    assert alert_names == {
        "GDAApprovalNotificationWorkerUnavailable",
        "GDAApprovalNotificationWorkerStalled",
        "GDAApprovalNotificationCycleErrors",
        "GDAApprovalNotificationDeadLettered",
        "GDAApprovalNotificationRetrySurge",
    }
    recording_names = {
        rule["record"]
        for group in canonical["groups"]
        for rule in group["rules"]
        if "record" in rule
    }
    assert recording_names == {
        "gda:approval_notification_worker_healthy_replicas",
        "gda:approval_notification_worker_target_replicas",
        "gda:approval_notification_cycle_success_age_seconds",
        "gda:approval_notification_delivery_success:ratio_30m",
        "gda:approval_notification_delivery_success:ratio_6h",
        "gda:approval_notification_delivery_attempts:rate5m",
        "gda:approval_notification_cycle_duration:p95_5m",
    }


def test_grafana_dashboard_has_stable_identity_and_actionable_panels() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    panels = dashboard["panels"]
    panel_titles = {panel["title"] for panel in panels}

    assert dashboard["uid"] == "gda-approval-case-operations"
    assert dashboard["title"] == "GIS Data Agent / ApprovalCase Operations"
    assert dashboard["refresh"] == "30s"
    assert dashboard["schemaVersion"] >= 40
    assert {"gis-data-agent", "approval-case", "operations"} <= set(
        dashboard["tags"]
    )
    assert dashboard["templating"]["list"] == [
        {
            "current": {
                "selected": True,
                "text": "GDA Prometheus",
                "value": "gda-prometheus",
            },
            "hide": 0,
            "includeAll": False,
            "label": "Prometheus",
            "multi": False,
            "name": "datasource",
            "options": [],
            "query": "prometheus",
            "refresh": 1,
            "regex": "",
            "skipUrlSync": False,
            "type": "datasource",
        }
    ]
    assert len(panels) == 10
    assert len({panel["id"] for panel in panels}) == len(panels)
    assert {
        "Healthy worker replicas",
        "Delivery success SLI (30m)",
        "Successful cycle age",
        "Dead letters (24h)",
        "Delivery attempt rate by outcome",
        "Delivery success SLI",
        "Notification cycle latency P95",
        "Worker scrape health",
        "Operation outcomes (24h)",
        "Firing ApprovalCase alerts",
    } == panel_titles
    for panel in panels:
        assert panel["datasource"] == {
            "type": "prometheus",
            "uid": "${datasource}",
        }
        assert panel["gridPos"]["h"] > 0
        assert panel["gridPos"]["w"] > 0
        assert all(target["expr"].strip() for target in panel["targets"])


def test_grafana_provisioning_binds_dashboard_to_prometheus_without_secrets() -> None:
    datasource_text = (
        GRAFANA_PROVISIONING / "datasources/approval-prometheus.yaml"
    ).read_text(encoding="utf-8")
    datasource = yaml.safe_load(datasource_text)["datasources"][0]
    provider = yaml.safe_load(
        (GRAFANA_PROVISIONING / "dashboards/approval-case.yaml").read_text(
            encoding="utf-8"
        )
    )["providers"][0]

    assert datasource["uid"] == "gda-prometheus"
    assert datasource["url"] == "$GDA_GRAFANA_PROMETHEUS_URL"
    assert datasource["editable"] is False
    assert datasource["jsonData"]["timeInterval"] == "30s"
    assert provider["folderUid"] == "gda-approval-operations"
    assert provider["editable"] is False
    assert provider["options"]["path"] == "/var/lib/grafana/dashboards"
    assert "password" not in datasource_text.lower()
    assert "http://" not in datasource_text and "https://" not in datasource_text


def test_kustomize_generates_a_sidecar_discoverable_dashboard_configmap() -> None:
    kustomization = yaml.safe_load(
        (K8S / "kustomization.yaml").read_text(encoding="utf-8")
    )
    generator = kustomization["configMapGenerator"][0]

    assert generator["name"] == "gis-agent-approval-notification-dashboard"
    assert generator["files"] == [
        "approval-case-operations.json=dashboards/approval-case-operations.json"
    ]
    assert generator["options"]["labels"]["grafana_dashboard"] == "1"
    assert generator["options"]["annotations"]["grafana_folder"] == (
        "ApprovalCase Operations"
    )
    assert kustomization["generatorOptions"]["disableNameSuffixHash"] is True


def test_alertmanager_routes_use_secret_references_not_embedded_urls() -> None:
    canonical_text = (
        ROOT / "config/alertmanager/approval-notification-routing.yaml"
    ).read_text(encoding="utf-8")
    canonical = yaml.safe_load(canonical_text)
    custom_resource = _document("alertmanager-config.yaml", "AlertmanagerConfig")
    route = custom_resource["spec"]["route"]
    webhook = custom_resource["spec"]["receivers"][0]["webhookConfigs"][0]

    assert canonical["route"]["routes"][0]["matchers"] == [
        'alertname=~"GDAApprovalCase|GDAApprovalNotification.*"'
    ]
    assert canonical["receivers"][1]["webhook_configs"][0]["url_file"].startswith(
        "/etc/alertmanager/secrets/"
    )
    assert "http://" not in canonical_text and "https://" not in canonical_text
    assert route["matchers"] == [
        {
            "name": "alertname",
            "value": "GDAApprovalCase|GDAApprovalNotification.*",
            "matchType": "=~",
        }
    ]
    assert webhook["urlSecret"] == {
        "name": "gis-agent-approval-oncall",
        "key": "webhook-url",
    }


def test_network_policy_limits_database_alertmanager_and_scrape_traffic() -> None:
    policy = _document("networkpolicy.yaml", "NetworkPolicy")
    ingress_ports = {
        port["port"]
        for rule in policy["spec"]["ingress"]
        for port in rule["ports"]
    }
    egress_ports = {
        port["port"]
        for rule in policy["spec"]["egress"]
        for port in rule["ports"]
    }

    assert policy["spec"]["policyTypes"] == ["Ingress", "Egress"]
    assert ingress_ports == {9465}
    assert egress_ports == {53, 443, 5432, 9093}


def test_worker_pod_disruption_budget_preserves_one_replica() -> None:
    budget = _document("worker.yaml", "PodDisruptionBudget")

    assert budget["spec"]["minAvailable"] == 1
