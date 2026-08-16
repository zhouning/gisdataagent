import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from data_agent import metadata_fabric_otel_metrics as otel
from data_agent import metadata_fabric_recovery_rehearsal as recovery


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _prometheus_payload() -> str:
    common_openmetadata = (
        'gda_pipeline="metadata_fabric_local",'
        'gda_provider="openmetadata",job="openmetadata"'
    )
    common_gravitino = (
        'gda_pipeline="metadata_fabric_local",'
        'gda_provider="gravitino",job="gravitino"'
    )
    return f"""# TYPE auth_attempts_total counter
auth_attempts_total{{{common_openmetadata}}} 0
# TYPE db_connections_total counter
db_connections_total{{{common_openmetadata}}} 0
# TYPE http_server_requests_sec_seconds histogram
http_server_requests_sec_seconds_bucket{{{common_openmetadata},le="+Inf"}} 1
http_server_requests_sec_seconds_sum{{{common_openmetadata}}} 0.1
http_server_requests_sec_seconds_count{{{common_openmetadata}}} 1
# TYPE jvm_memory_used_bytes gauge
jvm_memory_used_bytes{{{common_openmetadata},area="heap"}} 536870912
# TYPE gda_gravitino_datasource_active_connections gauge
gda_gravitino_datasource_active_connections{{{common_gravitino}}} 1
# TYPE gda_gravitino_datasource_max_connections gauge
gda_gravitino_datasource_max_connections{{{common_gravitino}}} 100
# TYPE gda_gravitino_http_threads gauge
gda_gravitino_http_threads{{{common_gravitino}}} 8
# TYPE gda_gravitino_jvm_heap_used_bytes gauge
gda_gravitino_jvm_heap_used_bytes{{{common_gravitino}}} 536870912
# TYPE gda_gravitino_jvm_heap_max_bytes gauge
gda_gravitino_jvm_heap_max_bytes{{{common_gravitino}}} 4294967296
# TYPE scrape_samples_scraped gauge
scrape_samples_scraped{{{common_openmetadata}}} 417
scrape_samples_scraped{{{common_gravitino}}} 5
# TYPE up gauge
up{{{common_openmetadata}}} 1
up{{{common_gravitino}}} 1
"""


def _component_identities() -> dict:
    contract = otel.build_otel_metrics_contract_report()
    return {
        "deployments": {
            name: {
                "uid": f"{name}-uid",
                "image": image,
                "ready_replicas": 1,
                "service_account": name,
            }
            for name, image in otel.EXPECTED_DEPLOYMENTS.items()
        },
        "services": {
            name: {
                "uid": f"{name}-service-uid",
                "type": "ClusterIP",
                "ports": sorted(ports),
            }
            for name, ports in otel.EXPECTED_SERVICES.items()
        },
        "configmaps": {
            name: {
                "uid": f"{name}-uid",
                "config_sha256": contract["config_hashes"][name],
                "matches_static_contract": True,
            }
            for name in otel.EXPECTED_CONFIGMAPS
        },
    }


def _observation() -> dict:
    first = otel._pipeline_summary(
        _prometheus_payload(), sequence=1, observed_at=NOW
    )
    second_at = NOW + timedelta(seconds=6)
    second = otel._pipeline_summary(
        _prometheus_payload(), sequence=2, observed_at=second_at
    )
    contract = otel.build_otel_metrics_contract_report()
    return {
        "schema": otel.OBSERVATION_SCHEMA,
        "observed_at": second_at.isoformat(),
        "started_at": (NOW - timedelta(seconds=2)).isoformat(),
        "duration_seconds": 8.0,
        "contract": {
            "local_static_contract_verified": True,
            "contract_fingerprint": contract["contract_fingerprint"],
        },
        "cluster": {
            "context": otel.CONTEXT,
            "uid": "cluster-uid",
            "namespace": {"name": otel.NAMESPACE, "uid": "namespace-uid"},
        },
        "components": _component_identities(),
        "scrapes": [first, second],
        "scrape_separation_seconds": 6.0,
        "runtime_checks": {
            "resources_absent_before_apply": True,
            "apply_completed": True,
            "rollouts_completed": {
                name: True for name in otel.EXPECTED_DEPLOYMENTS
            },
            "runtime_resource_inventory": otel.EXPECTED_RUNTIME_RESOURCES,
            "runtime_resource_inventory_matches": True,
            "port_forward_stopped": True,
            "cleanup_command_completed": True,
            "ephemeral_resources_removed": True,
            "remaining_resources": [],
            "provider_identities_preserved": True,
            "kubernetes_credential_resources_requested": False,
            "persistent_volume_resources_requested": False,
            "rbac_resources_requested": False,
        },
    }


def test_static_otel_metrics_contract_is_valid_bounded_and_portable():
    report = otel.build_otel_metrics_contract_report()

    assert report["local_static_contract_verified"] is True
    assert report["errors"] == []
    assert report["local_otel_metrics_pipeline_verified"] is False
    assert report["otel_pipeline_verified"] is False
    assert report["production_metrics_verified"] is False
    assert report["runtime_resource_inventory"] == otel.EXPECTED_RUNTIME_RESOURCES
    assert all(
        not Path(item["path"]).is_absolute() for item in report["files"].values()
    )


def test_static_contract_rejects_pipeline_drift_and_claim_overreach(tmp_path):
    profile = yaml.safe_load(otel.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["pipeline"]["scrape_interval_seconds"] = 30
    profile["claims"]["production_metrics_verified"] = True
    target = tmp_path / "profile.yaml"
    target.write_text(yaml.safe_dump(profile), encoding="utf-8")

    report = otel.build_otel_metrics_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "pipeline profile does not match" in rendered
    assert "production_metrics_verified" in rendered


def test_static_contract_rejects_malformed_profile(tmp_path):
    target = tmp_path / "profile.yaml"
    target.write_text("components: [\n", encoding="utf-8")

    report = otel.build_otel_metrics_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    assert any("profile is invalid" in error for error in report["errors"])


def test_pipeline_summary_is_allowlisted_and_proves_both_jobs():
    summary = otel._pipeline_summary(
        _prometheus_payload(), sequence=1, observed_at=NOW
    )

    assert otel._pipeline_summary_errors(summary) == []
    assert summary["jobs"] == {
        "openmetadata": {"up": 1.0, "scrape_samples_scraped": 417.0},
        "gravitino": {"up": 1.0, "scrape_samples_scraped": 5.0},
    }
    assert set(summary["gravitino_values"]) == set(
        otel.GRAVITINO_REQUIRED_FAMILIES
    )
    assert summary["raw_metrics_retained"] is False
    assert "auth_attempts_total{" not in json.dumps(summary)


def test_valid_evidence_proves_only_the_local_ephemeral_pipeline():
    report = otel.build_otel_metrics_evidence(
        _observation(), now=NOW + timedelta(seconds=6)
    )

    assert report["status"] == "local_otel_metrics_pipeline_verified"
    assert report["local_otel_metrics_pipeline_verified"] is True
    assert report["local_repeated_scrape_verified"] is True
    assert report["otel_pipeline_verified"] is False
    assert report["production_metrics_verified"] is False
    assert report["persistent_metrics_storage_verified"] is False
    assert report["network_policy_enforcement_verified"] is False
    assert report["production_ready"] is False
    assert otel.verify_evidence_integrity(report) == []


def test_evidence_blocks_missing_metrics_sensitive_fields_and_cleanup_failures():
    observation = _observation()
    observation["scrapes"][1]["missing_required_families"]["gravitino"] = [
        otel.GRAVITINO_REQUIRED_FAMILIES[0]
    ]
    observation["runtime_checks"]["ephemeral_resources_removed"] = False
    observation["runtime_checks"]["remaining_resources"] = [
        "Deployment/metadata-otel-collector"
    ]
    observation["runtime_checks"]["api_token"] = "must-not-be-recorded"

    report = otel.build_otel_metrics_evidence(
        observation, now=NOW + timedelta(seconds=6)
    )

    assert report["status"] == "blocked"
    assert report["local_otel_metrics_pipeline_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "credential-bearing fields" in rendered
    assert "required metric families are missing" in rendered
    assert "ephemeral_resources_removed" in rendered
    assert "resources remain" in rendered


def test_port_forward_command_pins_context_namespace_and_loopback():
    forward = otel._OtelPortForward(
        kubectl="kubectl",
        context=otel.CONTEXT,
        local_port=49152,
    )

    command = forward.command()
    assert command[:3] == ["kubectl", "--context", otel.CONTEXT]
    assert command[3:5] == ["-n", otel.NAMESPACE]
    assert f"service/{otel.OTEL_SERVICE}" in command
    assert "49152:8889" in command
    assert command[-1] == "--address=127.0.0.1"


def test_preflight_retries_transient_cluster_api_failure(monkeypatch):
    attempts = 0

    def cluster_uid(_runner):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise recovery.MetadataFabricRecoveryError("transient API failure")
        return "cluster-uid"

    monkeypatch.setattr(otel.recovery, "_cluster_uid", cluster_uid)
    monkeypatch.setattr(
        otel.recovery,
        "_namespace_identity",
        lambda _runner, _namespace: {"name": otel.NAMESPACE, "uid": "namespace-uid"},
    )
    monkeypatch.setattr(otel, "_list_ephemeral_resources", lambda _runner: [])
    monkeypatch.setattr(
        otel.provider_metrics,
        "_provider_identity",
        lambda _runner, name, _spec: {"provider": name},
    )
    monkeypatch.setattr(otel.time, "sleep", lambda _seconds: None)

    snapshot = otel._preflight_snapshot(object())

    assert attempts == 3
    assert snapshot[0] == "cluster-uid"
    assert snapshot[1]["uid"] == "namespace-uid"
    assert snapshot[2] == []
    assert set(snapshot[3]) == set(otel.provider_metrics.PROVIDERS)


def test_integrity_verifier_rejects_tampering_and_production_overclaim():
    report = otel.build_otel_metrics_evidence(
        _observation(), now=NOW + timedelta(seconds=6)
    )
    tampered = deepcopy(report)
    tampered["production_ready"] = True

    errors = otel.verify_evidence_integrity(tampered)

    assert "OTel metrics evidence fingerprint does not match" in errors
    assert "OTel metrics evidence may not claim production_ready" in errors


def test_committed_otel_metrics_evidence_is_integral_and_current():
    evidence_path = (
        Path(__file__).resolve().parent.parent
        / "docs/evidence/metadata-fabric-otel-metrics-2026-07-27.json"
    )
    report = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert otel.verify_evidence_integrity(report) == []
    assert report["observation"]["contract"]["contract_fingerprint"] == (
        otel.build_otel_metrics_contract_report()["contract_fingerprint"]
    )
    assert report["local_otel_metrics_pipeline_verified"] is True
    assert report["local_repeated_scrape_verified"] is True
    assert report["otel_pipeline_verified"] is False
    assert report["production_ready"] is False
