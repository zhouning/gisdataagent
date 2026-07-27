import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import yaml

from data_agent import metadata_fabric_provider_metrics as metrics


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _dropwizard_payload(required: tuple[str, ...]) -> dict:
    values = {
        "database.pool.MaxConnections": 100,
        "database.pool.TotalConnections": 4,
        "health.aggregate.healthy": 1,
        "health.aggregate.unhealthy": 0,
        "gravitino-relational-store.datasource.active-connections": 1,
        "gravitino-relational-store.datasource.max-connections": 10,
        "gravitino-server.http-server.total-thread.num": 24,
        "jvm.heap.max": 4_294_967_296,
        "jvm.heap.used": 536_870_912,
    }
    return {
        "version": metrics.DROPWIZARD_VERSION,
        "gauges": {name: {"value": values[name]} for name in required},
        "counters": {"requests": {"count": 3}},
        "histograms": {},
        "meters": {},
        "timers": {},
    }


def _prometheus_payload() -> str:
    return """# TYPE auth_attempts counter
auth_attempts 1
# TYPE db_connections gauge
db_connections 4
# TYPE http_server_requests_sec_seconds histogram
http_server_requests_sec_seconds_bucket{method="GET",le="1.0"} 1
http_server_requests_sec_seconds_bucket{method="GET",le="+Inf"} 1
http_server_requests_sec_seconds_sum{method="GET"} 0.1
http_server_requests_sec_seconds_count{method="GET"} 1
# TYPE jvm_memory_used_bytes gauge
jvm_memory_used_bytes{area="heap"} 536870912
"""


def _observation() -> dict:
    providers = {}
    for name, spec in metrics.PROVIDERS.items():
        required = (
            metrics.OPENMETADATA_REQUIRED_GAUGES
            if name == "openmetadata"
            else metrics.GRAVITINO_REQUIRED_GAUGES
        )
        expected_kind = "Deployment" if name == "openmetadata" else "StatefulSet"
        provider = {
            "identity": {
                "service": {
                    "name": spec["service"],
                    "uid": f"{name}-service-uid",
                    "type": "ClusterIP",
                    "ports": [spec["port"]],
                },
                "workload": {
                    "kind": expected_kind,
                    "name": str(spec["workload"]).split("/", 1)[1],
                    "uid": f"{name}-workload-uid",
                    "image": spec["image"],
                    "ready_replicas": 1,
                },
            },
            "transport": {
                "scheme": "http",
                "service_port": spec["port"],
                "dropwizard_path": "/metrics",
                "dropwizard_content_type": "application/json",
            },
            "dropwizard": metrics._dropwizard_summary(
                _dropwizard_payload(required), required
            ),
        }
        if name == "openmetadata":
            provider["transport"].update(
                {
                    "prometheus_path": "/prometheus",
                    "prometheus_content_type": "text/plain",
                }
            )
            provider["prometheus"] = metrics._prometheus_summary(
                _prometheus_payload()
            )
        providers[name] = provider
    return {
        "schema": metrics.OBSERVATION_SCHEMA,
        "observed_at": NOW.isoformat(),
        "started_at": NOW.isoformat(),
        "duration_seconds": 1.0,
        "contract": {
            "local_static_contract_verified": True,
            "contract_fingerprint": "a" * 64,
        },
        "cluster": {
            "context": metrics.CONTEXT,
            "uid": "cluster-uid",
            "namespace": {"name": metrics.NAMESPACE, "uid": "namespace-uid"},
        },
        "providers": providers,
        "runtime_checks": {
            "all_port_forwards_stopped": True,
            "port_forwards": {"openmetadata": True, "gravitino": True},
            "provider_resources_mutated": False,
            "kubernetes_credential_resources_requested": False,
        },
    }


def test_static_provider_metrics_contract_is_valid_and_portable():
    report = metrics.build_provider_metrics_contract_report()

    assert report["local_static_contract_verified"] is True
    assert report["errors"] == []
    assert report["local_provider_metrics_verified"] is False
    assert report["production_metrics_verified"] is False
    assert report["otel_pipeline_verified"] is False
    assert all(
        not Path(item["path"]).is_absolute() for item in report["files"].values()
    )


def test_static_contract_rejects_endpoint_drift_and_claim_overreach(tmp_path):
    profile = yaml.safe_load(metrics.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["providers"]["openmetadata"]["endpoints"]["prometheus"] = "/api/metrics"
    profile["claims"]["production_metrics_verified"] = True
    target = tmp_path / "profile.yaml"
    target.write_text(yaml.safe_dump(profile), encoding="utf-8")

    report = metrics.build_provider_metrics_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "OpenMetadata metrics profile does not match" in rendered
    assert "production_metrics_verified" in rendered


def test_static_contract_rejects_malformed_profile(tmp_path):
    target = tmp_path / "profile.yaml"
    target.write_text("providers: [\n", encoding="utf-8")

    report = metrics.build_provider_metrics_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    assert any("profile is invalid" in error for error in report["errors"])


def test_metric_summaries_project_only_allowlisted_inventory_and_values():
    dropwizard = metrics._dropwizard_summary(
        _dropwizard_payload(metrics.OPENMETADATA_REQUIRED_GAUGES),
        metrics.OPENMETADATA_REQUIRED_GAUGES,
    )
    prometheus = metrics._prometheus_summary(_prometheus_payload())

    assert dropwizard["version"] == metrics.DROPWIZARD_VERSION
    assert dropwizard["section_counts"] == {
        "gauges": 4,
        "counters": 1,
        "histograms": 0,
        "meters": 0,
        "timers": 0,
    }
    assert dropwizard["missing_required_metrics"] == []
    assert len(dropwizard["metric_name_fingerprint"]) == 64
    assert prometheus["missing_required_metrics"] == []
    assert prometheus["metric_family_count"] == 4
    assert prometheus["label_name_count"] == 3
    assert "method" not in prometheus
    assert "GET" not in json.dumps(prometheus)


def test_valid_evidence_proves_only_local_provider_native_metrics():
    report = metrics.build_provider_metrics_evidence(_observation(), now=NOW)

    assert report["status"] == "local_provider_metrics_verified"
    assert report["local_provider_metrics_verified"] is True
    assert report["production_metrics_verified"] is False
    assert report["otel_pipeline_verified"] is False
    assert report["alert_delivery_verified"] is False
    assert report["slo_verified"] is False
    assert report["metrics_tls_verified"] is False
    assert report["production_ready"] is False
    assert metrics.verify_evidence_integrity(report) == []


def test_evidence_blocks_missing_metrics_sensitive_fields_and_cleanup_failures():
    observation = _observation()
    observation["providers"]["gravitino"]["dropwizard"][
        "missing_required_metrics"
    ] = [metrics.GRAVITINO_REQUIRED_GAUGES[0]]
    observation["runtime_checks"]["all_port_forwards_stopped"] = False
    observation["runtime_checks"]["api_token"] = "must-not-be-recorded"

    report = metrics.build_provider_metrics_evidence(observation, now=NOW)

    assert report["status"] == "blocked"
    assert report["local_provider_metrics_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "credential-bearing fields" in rendered
    assert "required metrics are missing" in rendered
    assert "port-forwards were not stopped" in rendered


def test_port_forward_command_pins_context_namespace_and_loopback(monkeypatch):
    monkeypatch.setattr(metrics.repository, "_free_local_port", lambda: 49152)
    forward = metrics._PortForward(
        kubectl="kubectl",
        context=metrics.CONTEXT,
        namespace=metrics.NAMESPACE,
        service="openmetadata",
        target_port=8586,
    )

    command = forward.command()
    assert command[:3] == ["kubectl", "--context", metrics.CONTEXT]
    assert command[3:5] == ["-n", metrics.NAMESPACE]
    assert "service/openmetadata" in command
    assert command[-1] == "--address=127.0.0.1"


def test_integrity_verifier_rejects_tampering_and_production_overclaim():
    report = metrics.build_provider_metrics_evidence(_observation(), now=NOW)
    tampered = deepcopy(report)
    tampered["production_ready"] = True

    errors = metrics.verify_evidence_integrity(tampered)

    assert "provider metrics evidence fingerprint does not match" in errors
    assert "provider metrics evidence may not claim production_ready" in errors


def test_committed_provider_metrics_evidence_is_integral_and_current():
    evidence_path = (
        Path(__file__).resolve().parent.parent
        / "docs/evidence/metadata-fabric-provider-metrics-2026-07-27.json"
    )
    report = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert metrics.verify_evidence_integrity(report) == []
    assert report["observation"]["contract"]["contract_fingerprint"] == (
        metrics.build_provider_metrics_contract_report()["contract_fingerprint"]
    )
    assert report["local_provider_metrics_verified"] is True
    assert report["production_metrics_verified"] is False
    assert report["otel_pipeline_verified"] is False
    assert report["production_ready"] is False
