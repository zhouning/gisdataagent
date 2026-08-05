"""Contracts for fail-closed PostgreSQL CDC replication-slot invalidation."""

from __future__ import annotations

from scripts.certify_chongqing_osm_postgres_cdc_slot_invalidation import (
    _slot_fault_checks,
    _slot_incarnation,
    assess_slot_continuity,
)


def _observation(*, restart_lsn: str, confirmed_flush_lsn: str) -> dict[str, object]:
    return {
        "exists": True,
        "slot_name": "gda_slot_contract",
        "plugin": "pgoutput",
        "slot_type": "logical",
        "database_identity": "cdc_acceptance",
        "active": False,
        "active_pid": None,
        "restart_lsn": restart_lsn,
        "confirmed_flush_lsn": confirmed_flush_lsn,
        "xmin": None,
        "catalog_xmin": "740",
        "wal_status": "reserved",
        "safe_wal_size": None,
        "two_phase": False,
        "system_identifier": "7542498392981349781",
    }


def _slot_fault() -> dict[str, object]:
    original_observation = _observation(
        restart_lsn="0/100", confirmed_flush_lsn="0/180"
    )
    recreated_observation = _observation(
        restart_lsn="0/300", confirmed_flush_lsn="0/300"
    )
    original = _slot_incarnation(
        original_observation,
        ordinal=1,
        creation_anchor_lsn="0/100",
        established_by="connector_initial_slot_observation",
    )
    recreated = _slot_incarnation(
        recreated_observation,
        ordinal=2,
        creation_anchor_lsn="0/300",
        established_by="same_name_recreation_after_absence",
    )
    admission = assess_slot_continuity(
        {
            "original_incarnation": original,
            "current_incarnation": recreated,
            "absence_witnessed": True,
            "current_slot_exists": True,
        }
    )
    return {
        "event_sequence": {
            "network_disconnected": 1,
            "slot_backend_terminated": 2,
            "slot_dropped": 3,
            "source_mutated": 4,
            "slot_recreated": 5,
            "admission_rejected": 6,
            "runtime_terminated": 7,
            "network_reconnected_for_observation": 8,
        },
        "disconnect": {"disconnected": True},
        "reconnect": {"reconnected": True},
        "backend_termination": {"terminated": True},
        "teardown": {
            "slot_before": original_observation,
            "drop_command_lsn": "0/200",
            "slot_after": {
                "exists": False,
                "slot_name": "gda_slot_contract",
                "system_identifier": "7542498392981349781",
            },
            "absence_witnessed": True,
        },
        "mutation_target_lsn": "0/280",
        "recreation": {
            "slot_name": "gda_slot_contract",
            "consistent_lsn": "0/300",
            "observation": recreated_observation,
        },
        "original_incarnation": original,
        "current_incarnation": recreated,
        "absence_witnessed": True,
        "current_slot_exists": True,
        "admission": admission,
        "runtime_termination": {
            "status_before_controller_cancel": "RUNNING",
            "final_job_status": "CANCELED",
            "origin": "controller_cancel_after_admission_rejection",
        },
        "sink": {
            "accepted_before": 3,
            "accepted_after": 3,
            "rejected_before": 0,
            "rejected_after": 0,
            "post_fault_accepted_delta": 0,
            "post_fault_rejected_delta": 0,
        },
        "recreated_slot_after_reconnect": recreated_observation,
    }


def test_continuous_slot_incarnation_is_admitted() -> None:
    observation = _observation(
        restart_lsn="0/100", confirmed_flush_lsn="0/180"
    )
    incarnation = _slot_incarnation(
        observation,
        ordinal=1,
        creation_anchor_lsn="0/100",
        established_by="connector_initial_slot_observation",
    )

    decision = assess_slot_continuity(
        {
            "original_incarnation": incarnation,
            "current_incarnation": incarnation,
            "absence_witnessed": False,
            "current_slot_exists": True,
        }
    )

    assert decision["admitted"] is True
    assert decision["disposition"] == "admitted"
    assert decision["reason_codes"] == []


def test_same_name_slot_recreation_is_rejected_after_absence() -> None:
    fault = _slot_fault()
    decision = fault["admission"]

    assert decision["admitted"] is False
    assert decision["disposition"] == "rejected_fail_closed"
    assert decision["reason_codes"] == [
        "replication_slot_absence_witnessed",
        "replication_slot_incarnation_changed",
    ]
    assert (
        decision["original_incarnation_fingerprint"]
        != decision["current_incarnation_fingerprint"]
    )


def test_missing_or_incomplete_slot_evidence_fails_closed() -> None:
    missing = assess_slot_continuity({})
    incomplete = assess_slot_continuity(
        {
            "original_incarnation": {"slot_name": "gda_slot_contract"},
            "current_incarnation": {"slot_name": "gda_slot_contract"},
            "absence_witnessed": False,
            "current_slot_exists": True,
        }
    )

    assert missing["admitted"] is False
    assert "replication_slot_continuity_evidence_missing" in missing["reason_codes"]
    assert "replication_slot_current_observation_missing" in missing["reason_codes"]
    assert incomplete["admitted"] is False
    assert (
        "replication_slot_continuity_evidence_incomplete"
        in incomplete["reason_codes"]
    )


def test_negative_proof_requires_ordered_drop_mutation_and_recreation() -> None:
    fault = _slot_fault()

    assert all(_slot_fault_checks(fault).values())
    fault["event_sequence"] = {
        **fault["event_sequence"],
        "source_mutated": 1,
    }
    assert not _slot_fault_checks(fault)[
        "mutation_occured_between_drop_and_recreation"
    ]


def test_negative_proof_rejects_sink_growth_or_nonterminal_runtime() -> None:
    sink_growth = _slot_fault()
    sink_growth["sink"] = {
        **sink_growth["sink"],
        "accepted_after": 5,
        "post_fault_accepted_delta": 2,
    }
    wrong_terminal_origin = _slot_fault()
    wrong_terminal_origin["runtime_termination"] = {
        **wrong_terminal_origin["runtime_termination"],
        "origin": "connector_silently_resumed",
    }

    assert not _slot_fault_checks(sink_growth)[
        "post_fault_physical_sink_did_not_advance"
    ]
    assert not _slot_fault_checks(wrong_terminal_origin)[
        "runtime_terminal_state_is_separate_evidence"
    ]


def test_negative_proof_requires_physical_absence_and_new_incarnation() -> None:
    no_absence = _slot_fault()
    no_absence["teardown"] = {
        **no_absence["teardown"],
        "absence_witnessed": False,
    }
    same_incarnation = _slot_fault()
    same_incarnation["current_incarnation"] = same_incarnation[
        "original_incarnation"
    ]

    assert not _slot_fault_checks(no_absence)[
        "slot_absence_was_physically_witnessed"
    ]
    assert not _slot_fault_checks(same_incarnation)[
        "same_name_recreation_is_a_new_incarnation"
    ]
