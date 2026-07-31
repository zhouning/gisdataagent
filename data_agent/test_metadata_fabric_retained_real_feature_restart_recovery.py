import base64
import json
from copy import deepcopy

import pytest

from data_agent import metadata_fabric_retained_real_feature_restart_recovery as recovery


def _source() -> dict:
    return json.loads(recovery.DEFAULT_SOURCE_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _runtime_pair() -> tuple[dict, dict]:
    before = deepcopy(_source()["initial_runtime"])
    before["postgresql_service"] = {
        "name": "gravitino-persistence-postgresql",
        "uid": "00000000-0000-4000-8000-000000000251",
        "type": "ClusterIP",
        "ports": [{"name": "postgresql", "port": 5432}],
    }
    after = deepcopy(before)
    after["postgresql"]["pod_uid"] = "00000000-0000-4000-8000-000000000252"
    after["object_store"]["pod_uid"] = "00000000-0000-4000-8000-000000000253"
    after["gravitino"]["pod_uid"] = "00000000-0000-4000-8000-000000000254"
    return before, after


def _observation() -> dict:
    source = _source()
    retention = source["retention_observation"]
    before_runtime, after_runtime = _runtime_pair()
    material = {
        "object_count": 5,
        "object_inventory_sha256": retention["object_inventory_sha256"],
        "data_file_count": retention["data_file_count"],
        "metadata_file_count": 1,
        "manifest_file_count": 3,
        "metadata_body_sha256": retention["metadata_body_sha256"],
        "snapshot_id": retention["snapshot_id"],
        "schema_id": 0,
        "table_location": retention["storage_uri"],
        "fields": [],
    }
    ledger = {
        "ledger_counts": recovery.EXPECTED_LEDGER_COUNTS,
        "authority_counts": {
            "resources": 2,
            "resource_versions": 2,
            "definition_versions": 1,
            "platform_runs": 1,
        },
        "facts_sha256": "1" * 64,
        "platform_run_status": "succeeded",
        "platform_run_state_version": 3,
        "provider_observation_id": str(recovery.PROVIDER_OBSERVATION_ID),
        "provider_observation_sha256": source["provider_observation"]["observation_sha256"],
    }
    control_before = {
        "database_ref": source["control_database"]["database_ref"],
        "container_name": source["control_database"]["container_name"],
        "container_id": "2" * 64,
        "container_running": True,
        "container_status": "running",
        "process_id": 101,
        "started_at": "2026-07-31T04:15:30Z",
        "volume_name": source["control_database"]["volume_name"],
        "volume_retained": True,
        "host_port": source["control_database"]["host_port"],
        "retention_id": source["retention_id"],
        "owner": "team:metadata-platform",
        "expires_at": retention["expires_at"],
        "credential_material_recorded": False,
    }
    control_after = {
        **control_before,
        "process_id": 202,
        "started_at": "2026-07-31T05:00:00Z",
    }
    gravitino = {
        "read_status": 200,
        "table_projection_sha256": "3" * 64,
        "table_projection": {"name": "cultural_districts"},
    }
    return {
        "schema": recovery.OBSERVATION_SCHEMA,
        "observed_at": "2026-07-31T05:01:00Z",
        "contract_sha256": recovery.build_contract_report()["contract_sha256"],
        "source_evidence_sha256": recovery.SOURCE_EVIDENCE_SHA256,
        "retention_observation": retention,
        "m324_initial_runtime": source["initial_runtime"],
        "m324_independent_quality": source["independent_quality"],
        "kubernetes_restart": {
            "order": [
                "statefulset/gravitino-persistence-postgresql",
                "statefulset/metadata-object-store",
                "statefulset/gravitino-persistence",
            ],
            "before": before_runtime,
            "after": after_runtime,
        },
        "control_restart": {"before": control_before, "after": control_after},
        "material": {"before": material, "after": deepcopy(material)},
        "gravitino": {"before": gravitino, "after": deepcopy(gravitino)},
        "independent_quality": {
            "before": source["independent_quality"],
            "after": deepcopy(source["independent_quality"]),
        },
        "control_ledger": {
            "before": ledger,
            "after_restart": deepcopy(ledger),
            "after_terminal_replay": deepcopy(ledger),
        },
        "terminal_replay": {
            "promotion_created": False,
            "platform_run_status": "succeeded",
            "platform_run_state_version": 3,
        },
        "source_payload_absent_before": True,
        "source_payload_absent_after": True,
        "credential_material_recorded": False,
        "runtime_port_forwards_stopped": True,
    }


def test_contract_binds_intact_m324_without_production_overclaim():
    contract = recovery.build_contract_report()

    assert contract["status"] == "valid"
    assert contract["errors"] == []
    assert contract["source_evidence_sha256"] == recovery.SOURCE_EVIDENCE_SHA256
    assert contract["requires_kubernetes_pod_rotation"] is True
    assert contract["requires_control_process_rotation"] is True
    assert contract["production_restart_recovery_verified"] is False
    assert contract["production_ready"] is False


def test_checked_restart_recovery_evidence_is_self_validating():
    evidence = json.loads(recovery.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    validation = recovery.build_validation_report()

    assert recovery.validate_evidence(evidence) == []
    assert validation["status"] == "valid"
    assert validation["errors"] == []
    assert evidence["contract_sha256"] == validation["contract_sha256"]
    assert evidence["evidence_sha256"] == validation["evidence_sha256"]
    assert evidence["new_ingestion_executed"] is False
    assert evidence["new_authority_facts_created"] is False


def test_runtime_continuity_requires_all_pods_to_rotate_and_stable_identity():
    source = _source()
    before, after = _runtime_pair()

    assert recovery._runtime_continuity_errors(before, after, source["initial_runtime"]) == []

    after["object_store"]["pod_uid"] = before["object_store"]["pod_uid"]
    after["postgresql"]["pvc"]["uid"] = "00000000-0000-4000-8000-000000000255"
    errors = recovery._runtime_continuity_errors(before, after, source["initial_runtime"])

    assert "object_store pod did not rotate" in errors
    assert "retained Kubernetes stable runtime identity changed" in errors
    assert "postgresql PVC identity changed" in errors


def test_control_continuity_requires_same_container_volume_and_new_process():
    restart = _observation()["control_restart"]

    assert recovery._control_continuity_errors(restart) == []

    restart["after"]["container_id"] = "4" * 64
    restart["after"]["process_id"] = restart["before"]["process_id"]
    restart["after"]["started_at"] = restart["before"]["started_at"]
    errors = recovery._control_continuity_errors(restart)

    assert "retained control identity changed: container_id" in errors
    assert "retained control PostgreSQL process did not rotate" in errors
    assert "retained control PostgreSQL start time did not rotate" in errors


def test_runtime_material_decoding_and_control_password_are_memory_only():
    value = recovery._decode_runtime_material(
        {"data": {"value": base64.b64encode(b"unit-material").decode()}},
        "value",
        label="unit",
    )
    control = recovery._extract_control_password(
        ["PG_MAJOR=16", "POSTGRES_PASSWORD=control-material"]
    )

    assert value.get_secret_value() == "unit-material"
    assert control.get_secret_value() == "control-material"
    assert "unit-material" not in repr(value)
    with pytest.raises(
        recovery.RetainedRealFeatureRestartRecoveryError,
        match="credential is unavailable",
    ):
        recovery._extract_control_password(["PG_MAJOR=16"])


def test_evidence_verifies_and_rejects_drift_overclaim_and_sensitive_fields():
    evidence = recovery.build_evidence(_observation())

    assert evidence["status"] == ("local_retained_real_feature_restart_recovery_verified")
    assert evidence["errors"] == []
    assert recovery.validate_evidence(evidence) == []

    drifted = deepcopy(evidence)
    drifted["material"]["after"]["snapshot_id"] += 1
    assert "M3-25 evidence fingerprint does not match" in recovery.validate_evidence(drifted)

    overclaimed = deepcopy(evidence)
    overclaimed["production_ready"] = True
    overclaimed["evidence_sha256"] = recovery.canonical_json_fingerprint(
        {key: value for key, value in overclaimed.items() if key != "evidence_sha256"}
    )
    assert "M3-25 evidence may not claim production_ready" in (
        recovery.validate_evidence(overclaimed)
    )

    sensitive = deepcopy(evidence)
    sensitive["diagnostic"] = {"password": "must-not-appear"}
    sensitive["evidence_sha256"] = recovery.canonical_json_fingerprint(
        {key: value for key, value in sensitive.items() if key != "evidence_sha256"}
    )
    assert "M3-25 evidence contains local, source, or credential material" in (
        recovery.validate_evidence(sensitive)
    )


def test_build_evidence_fails_closed_on_material_and_ledger_drift():
    observation = _observation()
    observation["material"]["after"]["snapshot_id"] += 1
    observation["control_ledger"]["after_restart"]["facts_sha256"] = "0" * 64

    evidence = recovery.build_evidence(observation)

    assert evidence["status"] == "blocked"
    assert "retained Iceberg material changed across restart" in evidence["errors"]
    assert "GDA Control ledger changed across restart or replay" in evidence["errors"]
    assert evidence["production_ready"] is False
