"""Contracts for fail-closed PostgreSQL CDC physical failover admission."""

from __future__ import annotations

from scripts.certify_chongqing_osm_postgres_cdc_failover import (
    _failover_fault_checks,
    assess_failover_continuity,
)


def _identity(
    *,
    timeline_id: int,
    previous_timeline_id: int,
    in_recovery: bool,
) -> dict[str, object]:
    return {
        "system_identifier": "7542498392981349781",
        "timeline_id": timeline_id,
        "previous_timeline_id": previous_timeline_id,
        "checkpoint_lsn": "0/200",
        "redo_lsn": "0/180",
        "in_recovery": in_recovery,
        "observation_lsn": "0/300",
        "receive_lsn": "0/300" if in_recovery else "",
        "replay_lsn": "0/300" if in_recovery else "",
    }


def _slot(*, exists: bool = True, active: bool = True) -> dict[str, object]:
    slot = {
        "exists": exists,
        "slot_name": "gda_slot_contract",
        "system_identifier": "7542498392981349781",
    }
    if exists:
        slot.update(
            {
                "plugin": "pgoutput",
                "slot_type": "logical",
                "database_identity": "cdc_acceptance",
                "active": active,
            }
        )
    return slot


def _admission_evidence(*, promoted_slot_exists: bool) -> dict[str, object]:
    return {
        "primary_identity": _identity(
            timeline_id=1, previous_timeline_id=1, in_recovery=False
        ),
        "standby_identity_before_promotion": _identity(
            timeline_id=1, previous_timeline_id=1, in_recovery=True
        ),
        "promoted_identity": _identity(
            timeline_id=2, previous_timeline_id=1, in_recovery=False
        ),
        "primary_slot": _slot(),
        "promoted_slot": _slot(exists=promoted_slot_exists, active=False),
        "mutation_replayed_before_promotion": True,
        "primary_stopped_before_promotion": True,
        "publication_present_after_promotion": True,
    }


def _failover_fault() -> dict[str, object]:
    row = {
        "road_id": 101,
        "revision": 2,
        "road_name_base64": "cm9hZA==",
        "geometry_sha256": "a" * 64,
    }
    admission_evidence = _admission_evidence(promoted_slot_exists=False)
    return {
        "event_sequence": {
            "initial_checkpoint_completed": 1,
            "physical_basebackup_completed": 2,
            "source_mutated": 3,
            "standby_replay_reached_target": 4,
            "pre_failover_sink_checkpoint_completed": 5,
            "primary_stopped": 6,
            "standby_promoted": 7,
            "admission_rejected": 8,
            "source_alias_transferred": 9,
            "post_promotion_probe_mutated": 10,
            "runtime_terminated": 11,
        },
        "postgres_major_version": 16,
        "basebackup": {
            "completed": True,
            "application_name": "gda_physical_standby_contract",
        },
        "physical_replication": {
            "application_name": "gda_physical_standby_contract",
            "state": "streaming",
        },
        "source_mutation": {"target_lsn": "0/280", "row": row},
        "standby_replay": {"replay_lsn": "0/300", "row": row},
        "pre_failover_sink": {
            "accepted": 5,
            "rejected": 0,
            "checkpoint_count": 5,
        },
        "primary_stop": {"stopped": True},
        "primary_stopped_before_promotion": True,
        "mutation_replayed_before_promotion": True,
        "source_alias_transfer": {
            "source_alias": "gda-cdc-source-contract",
            "primary_detached": True,
            "standby_attached": True,
            "standby_network_aliases": [
                "gda-cdc-source-contract",
                "gda-cdc-standby-contract",
            ],
        },
        "publication_present_after_promotion": True,
        "promoted_row": row,
        "post_promotion_probe": {
            "target_lsn": "0/380",
            "row": {**row, "revision": 3},
        },
        "post_failover_observation_seconds": 2.0,
        "runtime_termination": {
            "final_job_status": "CANCELED",
            "origin": "controller_cancel_after_failover_admission_rejection",
        },
        "sink": {
            "accepted_before": 5,
            "accepted_after": 5,
            "rejected_before": 0,
            "rejected_after": 0,
            "post_failover_accepted_delta": 0,
            "post_failover_rejected_delta": 0,
        },
        **admission_evidence,
        "admission": assess_failover_continuity(admission_evidence),
    }


def test_continuous_slot_on_incremented_timeline_is_admitted() -> None:
    decision = assess_failover_continuity(
        _admission_evidence(promoted_slot_exists=True)
    )

    assert decision["admitted"] is True
    assert decision["disposition"] == "admitted"
    assert decision["reason_codes"] == []


def test_postgresql_16_missing_promoted_slot_is_rejected_fail_closed() -> None:
    decision = assess_failover_continuity(
        _admission_evidence(promoted_slot_exists=False)
    )

    assert decision["admitted"] is False
    assert decision["disposition"] == "rejected_fail_closed"
    assert decision["reason_codes"] == [
        "logical_replication_slot_missing_after_promotion"
    ]


def test_missing_or_inconsistent_failover_identity_evidence_fails_closed() -> None:
    missing = assess_failover_continuity({})
    changed = _admission_evidence(promoted_slot_exists=True)
    changed["promoted_identity"] = {
        **changed["promoted_identity"],
        "system_identifier": "different-cluster",
        "timeline_id": 4,
    }
    decision = assess_failover_continuity(changed)
    malformed = _admission_evidence(promoted_slot_exists=True)
    malformed["promoted_identity"] = {
        **malformed["promoted_identity"],
        "timeline_id": "2",
    }
    malformed_decision = assess_failover_continuity(malformed)

    assert missing["admitted"] is False
    assert "postgresql_failover_identity_evidence_missing" in missing["reason_codes"]
    assert decision["admitted"] is False
    assert "postgresql_system_identifier_changed" in decision["reason_codes"]
    assert "postgresql_timeline_did_not_increment_once" in decision["reason_codes"]
    assert malformed_decision["admitted"] is False
    assert (
        "postgresql_failover_identity_evidence_incomplete"
        in malformed_decision["reason_codes"]
    )


def test_negative_failover_proof_accepts_missing_slot_only_rejection() -> None:
    assert all(_failover_fault_checks(_failover_fault()).values())


def test_negative_failover_proof_rejects_timeline_or_sink_regression() -> None:
    timeline = _failover_fault()
    timeline["promoted_identity"] = {
        **timeline["promoted_identity"],
        "timeline_id": 1,
    }
    sink = _failover_fault()
    sink["sink"] = {
        **sink["sink"],
        "accepted_after": 7,
        "post_failover_accepted_delta": 2,
    }

    assert not _failover_fault_checks(timeline)[
        "promotion_incremented_exactly_one_timeline"
    ]
    assert not _failover_fault_checks(sink)[
        "post_promotion_probe_advanced_source_but_not_sink"
    ]
