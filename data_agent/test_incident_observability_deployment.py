from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "k8s/observability/incident-notifications"


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
        "name": "gis-agent-incident-notification-runtime",
        "key": "alertmanager-url",
    }
    assert environment["POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == (
        "gis-agent-incident-notification-runtime"
    )
    assert environment["GDA_INCIDENT_NOTIFICATION_ROUTE_NAMESPACE"]["valueFrom"][
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

    assert monitor["spec"]["jobLabel"] == "app.kubernetes.io/name"
    assert monitor["spec"]["namespaceSelector"]["matchNames"] == ["gis-agent"]
    assert monitor["spec"]["endpoints"] == [
        {
            "port": "metrics",
            "path": "/metrics",
            "scheme": "http",
            "interval": "30s",
            "scrapeTimeout": "10s",
        }
    ]


def test_prometheus_rule_crd_matches_the_promtool_source() -> None:
    canonical = yaml.safe_load(
        (ROOT / "config/prometheus/incident-notification-rules.yaml").read_text(
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
        "GDAIncidentNotificationWorkerUnavailable",
        "GDAIncidentNotificationWorkerStalled",
        "GDAIncidentNotificationCycleErrors",
        "GDAIncidentNotificationDeadLettered",
        "GDAIncidentNotificationRetrySurge",
    }


def test_alertmanager_routes_use_secret_references_not_embedded_urls() -> None:
    canonical_text = (
        ROOT / "config/alertmanager/incident-notification-routing.yaml"
    ).read_text(encoding="utf-8")
    canonical = yaml.safe_load(canonical_text)
    custom_resource = _document("alertmanager-config.yaml", "AlertmanagerConfig")
    route = custom_resource["spec"]["route"]
    webhook = custom_resource["spec"]["receivers"][0]["webhookConfigs"][0]

    assert canonical["route"]["routes"][0]["matchers"] == [
        'alertname=~"GDADataIncident|GDAIncidentNotification.*"'
    ]
    assert canonical["receivers"][1]["webhook_configs"][0]["url_file"].startswith(
        "/etc/alertmanager/secrets/"
    )
    assert "http://" not in canonical_text and "https://" not in canonical_text
    assert route["matchers"] == [
        {
            "name": "alertname",
            "value": "GDADataIncident|GDAIncidentNotification.*",
            "matchType": "=~",
        }
    ]
    assert webhook["urlSecret"] == {
        "name": "gis-agent-incident-oncall",
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
