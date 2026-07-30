import json
from copy import deepcopy

from data_agent import metadata_fabric_active_metadata_consumer as consumer


def test_static_contract_binds_inert_request_staging_and_deployment():
    report = consumer.build_contract_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["activation_boundary"] == (
        "durable_request_awaiting_authorization"
    )
    assert report["deployment_expected_replicas"] == 0
    assert report["provider_apply_authorized"] is False
    assert report["production_scheduler_submission_verified"] is False
    assert report["production_ready"] is False
    assert all(
        not item["path"].startswith("/")
        for item in report["files"].values()
    )


def test_checked_evidence_is_current_content_bound_and_locally_scoped():
    evidence = json.loads(
        consumer.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    )

    assert consumer.validate_rehearsal_evidence(evidence) == []
    assert evidence["processed_event_count"] == 2
    assert evidence["activation_request_count"] == 2
    assert evidence["platform_command_count"] == 0
    assert evidence["atomic_completion_guard_verified"] is True
    assert evidence["requests_inert"] is True
    assert evidence["deployment_applied"] is False
    assert evidence["provider_apply_authorized"] is False
    assert evidence["production_scheduler_submission_verified"] is False
    assert evidence["production_ready"] is False


def test_evidence_validation_rejects_tampering_and_production_overclaim():
    evidence = json.loads(
        consumer.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    )
    tampered = deepcopy(evidence)
    tampered["platform_command_count"] = 1
    tampered["production_ready"] = True

    errors = consumer.validate_rehearsal_evidence(tampered)

    assert "Active Metadata consumer evidence SHA-256 does not match" in errors
    assert (
        "local Active Metadata consumer evidence may not claim production_ready"
        in errors
    )
    assert "Active Metadata consumer must not create platform commands" in errors
