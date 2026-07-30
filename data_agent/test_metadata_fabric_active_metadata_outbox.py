import json
from copy import deepcopy

from data_agent import metadata_fabric_active_metadata_outbox as outbox


def test_static_contract_binds_transactional_event_and_safe_activation_route():
    report = outbox.build_contract_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["activation_route"] == "metadata_fabric.projection_plan"
    assert report["consumer_subject"] == outbox.CONSUMER_SUBJECT
    assert report["production_ready"] is False


def test_checked_evidence_is_current_content_bound_and_locally_scoped():
    evidence = json.loads(
        outbox.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    )

    assert outbox.validate_rehearsal_evidence(evidence) == []
    assert evidence["local_postgresql_active_metadata_loop_verified"] is True
    assert evidence["transactional_outbox_verified"] is True
    assert evidence["legacy_backfill_blocked"] is True
    assert evidence["provider_apply_authorized"] is False
    assert evidence["provider_mutations_executed"] is False
    assert evidence["production_ingestion_verified"] is False
    assert evidence["production_scheduler_submission_verified"] is False
    assert evidence["production_ready"] is False


def test_evidence_validation_rejects_tampering_and_production_overclaim():
    evidence = json.loads(
        outbox.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    )
    tampered = deepcopy(evidence)
    tampered["authoritative_event_count"] = 2
    tampered["production_ready"] = True

    errors = outbox.validate_rehearsal_evidence(tampered)

    assert "Active Metadata evidence SHA-256 does not match" in errors
    assert "local Active Metadata evidence may not claim production_ready" in errors
    assert "Active Metadata evidence must contain exactly one event" in errors
