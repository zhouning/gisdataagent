import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from data_agent import metadata_fabric_otel_failure_rehearsal as rehearsal
from data_agent import metadata_fabric_otel_metrics as otel


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _prometheus_payload(*, faulted: bool = False) -> str:
    common_openmetadata = (
        'gda_pipeline="metadata_fabric_local",'
        'gda_provider="openmetadata",job="openmetadata"'
    )
    common_gravitino = (
        'gda_pipeline="metadata_fabric_local",'
        'gda_provider="gravitino",job="gravitino"'
    )
    gravitino_metrics = ""
    gravitino_samples = 0 if faulted else 5
    gravitino_up = 0 if faulted else 1
    if not faulted:
        gravitino_metrics = f"""# TYPE gda_gravitino_datasource_active_connections gauge
gda_gravitino_datasource_active_connections{{{common_gravitino}}} 1
# TYPE gda_gravitino_datasource_max_connections gauge
gda_gravitino_datasource_max_connections{{{common_gravitino}}} 100
# TYPE gda_gravitino_http_threads gauge
gda_gravitino_http_threads{{{common_gravitino}}} 8
# TYPE gda_gravitino_jvm_heap_used_bytes gauge
gda_gravitino_jvm_heap_used_bytes{{{common_gravitino}}} 536870912
# TYPE gda_gravitino_jvm_heap_max_bytes gauge
gda_gravitino_jvm_heap_max_bytes{{{common_gravitino}}} 4294967296
"""
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
{gravitino_metrics}# TYPE scrape_samples_scraped gauge
scrape_samples_scraped{{{common_openmetadata}}} 417
scrape_samples_scraped{{{common_gravitino}}} {gravitino_samples}
# TYPE up gauge
up{{{common_openmetadata}}} 1
up{{{common_gravitino}}} {gravitino_up}
"""


def _stage(stage: str) -> dict:
    summary = otel._pipeline_summary(
        _prometheus_payload(faulted=stage == "fault"),
        sequence=rehearsal.STAGES.index(stage) + 1,
        observed_at=NOW + timedelta(seconds=rehearsal.STAGES.index(stage) * 5),
    )
    summary["stage"] = stage
    return summary


def _component_identities() -> dict:
    base_contract = otel.build_otel_metrics_contract_report()
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
                "config_sha256": base_contract["config_hashes"][name],
                "matches_static_contract": True,
            }
            for name in otel.EXPECTED_CONFIGMAPS
        },
    }


def _observation() -> dict:
    contract = rehearsal.build_otel_failure_contract_report()
    components = _component_identities()
    return {
        "schema": rehearsal.OBSERVATION_SCHEMA,
        "observed_at": (NOW + timedelta(seconds=12)).isoformat(),
        "started_at": NOW.isoformat(),
        "duration_seconds": 12.0,
        "contract": {
            "local_static_contract_verified": True,
            "contract_fingerprint": contract["contract_fingerprint"],
        },
        "cluster": {
            "context": rehearsal.CONTEXT,
            "uid": "cluster-uid",
            "namespace": {"name": rehearsal.NAMESPACE, "uid": "namespace-uid"},
        },
        "components": {
            "baseline": deepcopy(components),
            "recovery": deepcopy(components),
        },
        "stages": {stage: _stage(stage) for stage in rehearsal.STAGES},
        "fault_injection": {
            "job": rehearsal.FAULT_JOB,
            "type": "collector_scrape_endpoint_replacement",
            "original_endpoint": rehearsal.ORIGINAL_ENDPOINT,
            "fault_endpoint": rehearsal.FAULT_ENDPOINT,
            "baseline_config_sha256": contract["base_config_sha256"],
            "fault_config_sha256": contract["fault_config_sha256"],
            "recovery_config_sha256": contract["base_config_sha256"],
            "expected_fault_config_sha256": contract["fault_config_sha256"],
            "configmap_uid_preserved": True,
        },
        "runtime_checks": {
            "resources_absent_before_apply": True,
            "apply_completed": True,
            "initial_rollouts_completed": {
                name: True for name in otel.EXPECTED_DEPLOYMENTS
            },
            "fault_config_applied": True,
            "fault_rollout_completed": True,
            "recovery_config_applied": True,
            "recovery_rollout_completed": True,
            "fallback_restore_completed": False,
            "port_forwards_stopped": {
                stage: True for stage in rehearsal.STAGES
            },
            "runtime_resource_inventory": otel.EXPECTED_RUNTIME_RESOURCES,
            "runtime_resource_inventory_matches": True,
            "cleanup_command_completed": True,
            "ephemeral_resources_removed": True,
            "remaining_resources": [],
            "provider_identities_preserved": True,
            "kubernetes_credential_resources_requested": False,
            "persistent_volume_resources_requested": False,
            "rbac_resources_requested": False,
        },
    }


def test_static_failure_rehearsal_contract_is_bounded_and_valid():
    report = rehearsal.build_otel_failure_contract_report()

    assert report["local_static_contract_verified"] is True
    assert report["errors"] == []
    assert report["base_config_sha256"] != report["fault_config_sha256"]
    assert report["local_otel_scrape_failure_recovery_verified"] is False
    assert report["otel_pipeline_verified"] is False
    assert report["production_metrics_verified"] is False
    assert all(
        not Path(item["path"]).is_absolute() for item in report["files"].values()
    )


def test_static_contract_rejects_fault_drift_and_claim_overreach(tmp_path):
    profile = yaml.safe_load(
        rehearsal.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8")
    )
    profile["fault"]["replacement_endpoint"] = "metadata-json-exporter:7979"
    profile["claims"]["production_metrics_verified"] = True
    target = tmp_path / "profile.yaml"
    target.write_text(yaml.safe_dump(profile), encoding="utf-8")

    report = rehearsal.build_otel_failure_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "failure injection profile does not match" in rendered
    assert "production_metrics_verified" in rendered


def test_static_contract_rejects_a_malformed_profile(tmp_path):
    target = tmp_path / "profile.yaml"
    target.write_text("fault: [\n", encoding="utf-8")

    report = rehearsal.build_otel_failure_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    assert any("profile is invalid" in error for error in report["errors"])


def test_fault_transform_changes_only_gravitino_exporter_address():
    base = rehearsal._collector_configmap(rehearsal.DEFAULT_CONFIGMAPS_PATH)
    faulted = rehearsal.build_faulted_collector_configmap()
    base_config = rehearsal._embedded_collector_config(base)
    expected = deepcopy(base_config)
    rehearsal._gravitino_address_relabel(expected)["replacement"] = (
        rehearsal.FAULT_ENDPOINT
    )

    assert rehearsal._fault_config_errors(base, faulted) == []
    assert rehearsal._embedded_collector_config(faulted) == expected
    assert (
        rehearsal._gravitino_address_relabel(base_config)["replacement"]
        == rehearsal.ORIGINAL_ENDPOINT
    )


def test_three_stage_summaries_prove_isolated_fault_and_recovery():
    baseline = _stage("baseline")
    fault = _stage("fault")
    recovered = _stage("recovery")

    assert rehearsal._stage_summary_errors(baseline, "baseline") == []
    assert rehearsal._stage_summary_errors(fault, "fault") == []
    assert rehearsal._stage_summary_errors(recovered, "recovery") == []
    assert fault["jobs"]["openmetadata"]["up"] == 1.0
    assert fault["jobs"]["gravitino"] == {
        "up": 0.0,
        "scrape_samples_scraped": 0.0,
    }
    assert recovered["jobs"]["gravitino"]["up"] == 1.0


def test_valid_evidence_proves_only_local_failure_recovery():
    report = rehearsal.build_otel_failure_evidence(
        _observation(), now=NOW + timedelta(seconds=12)
    )

    assert report["status"] == "local_otel_scrape_failure_recovery_verified"
    assert report["local_otel_scrape_failure_recovery_verified"] is True
    assert report["otel_pipeline_verified"] is False
    assert report["production_metrics_verified"] is False
    assert report["persistent_metrics_storage_verified"] is False
    assert report["alert_delivery_verified"] is False
    assert report["production_ready"] is False
    assert rehearsal.verify_evidence_integrity(report) == []


def test_evidence_blocks_missing_fault_failed_recovery_cleanup_and_secrets():
    observation = _observation()
    observation["stages"]["fault"] = deepcopy(observation["stages"]["baseline"])
    observation["stages"]["fault"]["stage"] = "fault"
    observation["stages"]["fault"]["sequence"] = 2
    observation["stages"]["recovery"]["jobs"]["gravitino"]["up"] = 0.0
    observation["runtime_checks"]["ephemeral_resources_removed"] = False
    observation["runtime_checks"]["remaining_resources"] = [
        "Deployment/metadata-otel-collector"
    ]
    observation["api_token"] = "must-not-be-recorded"

    report = rehearsal.build_otel_failure_evidence(
        observation, now=NOW + timedelta(seconds=12)
    )

    assert report["status"] == "blocked"
    assert report["local_otel_scrape_failure_recovery_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "credential-bearing fields" in rendered
    assert "Gravitino fault was not detected" in rendered
    assert "gravitino scrape is not up" in rendered
    assert "ephemeral_resources_removed" in rendered
    assert "ephemeral resources remain" in rendered


def test_integrity_verifier_rejects_tampering_and_production_overclaim():
    report = rehearsal.build_otel_failure_evidence(
        _observation(), now=NOW + timedelta(seconds=12)
    )
    tampered = deepcopy(report)
    tampered["production_ready"] = True

    errors = rehearsal.verify_evidence_integrity(tampered)

    assert "OTel failure rehearsal evidence fingerprint does not match" in errors
    assert "OTel failure rehearsal evidence may not claim production_ready" in errors
    assert "api_token" not in json.dumps(report)


def test_evidence_builder_rejects_a_stale_contract_fingerprint():
    observation = _observation()
    observation["contract"]["contract_fingerprint"] = "0" * 64

    report = rehearsal.build_otel_failure_evidence(
        observation, now=NOW + timedelta(seconds=12)
    )

    assert report["status"] == "blocked"
    assert "OTel failure rehearsal contract fingerprint is stale" in report["errors"]


def test_committed_failure_rehearsal_evidence_is_integral_and_current():
    evidence_path = (
        Path(__file__).resolve().parent.parent
        / "docs/evidence/metadata-fabric-otel-failure-rehearsal-2026-07-28.json"
    )
    report = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert rehearsal.verify_evidence_integrity(report) == []
    assert report["observation"]["contract"]["contract_fingerprint"] == (
        rehearsal.build_otel_failure_contract_report()["contract_fingerprint"]
    )
    assert report["local_otel_scrape_failure_recovery_verified"] is True
    assert report["otel_pipeline_verified"] is False
    assert report["production_ready"] is False
