"""Contracts for fail-closed PostgreSQL CDC slot WAL-capacity handling."""

from __future__ import annotations

from scripts.certify_chongqing_osm_postgres_cdc_wal_capacity import (
    _wal_capacity_fault_checks,
    assess_slot_wal_capacity,
)


def _slot(
    *,
    wal_status: str = "reserved",
    restart_lsn: str = "0/100",
    safe_wal_size: int | None = 1_048_576,
) -> dict[str, object]:
    return {
        "exists": True,
        "slot_name": "gda_slot_contract",
        "plugin": "pgoutput",
        "slot_type": "logical",
        "database_identity": "cdc_acceptance",
        "active": False,
        "active_pid": None,
        "restart_lsn": restart_lsn,
        "confirmed_flush_lsn": "0/180",
        "xmin": None,
        "catalog_xmin": "740",
        "wal_status": wal_status,
        "safe_wal_size": safe_wal_size,
        "two_phase": False,
        "system_identifier": "7542498392981349781",
    }


def _policy() -> dict[str, int]:
    return {
        "max_slot_wal_keep_size_bytes": 1_048_576,
        "minimum_safe_wal_bytes": 65_536,
    }


def _capacity_fault() -> dict[str, object]:
    baseline_slot = _slot(safe_wal_size=2_097_152)
    lost_slot = _slot(wal_status="lost", restart_lsn="", safe_wal_size=None)
    admission = assess_slot_wal_capacity(
        {"slot": lost_slot, "policy": _policy()}
    )
    storage = {
        "measurement_path": "/var/lib/postgresql/data",
        "pg_wal_bytes": 16_777_216,
        "filesystem_bytes": 4_294_967_296,
        "filesystem_used_bytes": 536_870_912,
        "filesystem_available_bytes": 1_073_741_824,
        "filesystem_capacity_percent": "13%",
        "filesystem_mount_reported": "/var/lib/postgresql/data",
    }
    return {
        "event_sequence": {
            "network_disconnected": 1,
            "slot_backend_terminated": 2,
            "wal_pressure_started": 3,
            "slot_wal_lost": 4,
            "admission_rejected": 5,
            "runtime_terminated": 6,
            "network_reconnected_for_observation": 7,
        },
        "configuration": {
            "max_slot_wal_keep_size": "1MB",
            "max_slot_wal_keep_size_bytes": 1_048_576,
            "wal_segment_size": "16MB",
            "wal_segment_size_bytes": 16_777_216,
            "data_directory": "/var/lib/postgresql/data",
        },
        "pressure_policy": {
            "max_slot_wal_keep_size_bytes": 1_048_576,
            "maximum_cycles": 4,
            "message_count_per_cycle": 16,
            "message_bytes": 524_288,
            "maximum_requested_payload_bytes": 67_108_864,
            "maximum_observed_wal_budget_bytes": 201_326_592,
            "filesystem_safety_floor_bytes": 536_870_912,
        },
        "disconnect": {"disconnected": True},
        "reconnect": {"reconnected": True},
        "backend_termination": {"terminated": True},
        "slot_incarnation": {
            "slot_name": "gda_slot_contract",
            "system_identifier": "7542498392981349781",
        },
        "baseline": {"slot": baseline_slot, "storage": storage},
        "pressure_cycles": [
            {
                "cycle": 1,
                "message_count": 16,
                "message_bytes": 524_288,
                "requested_payload_bytes": 8_388_608,
                "start_lsn": "0/200",
                "emitted_lsn": "0/800200",
                "checkpoint_lsn": "0/1000200",
                "observed_wal_bytes": 16_777_216,
                "slot": lost_slot,
                "storage": {
                    **storage,
                    "filesystem_available_bytes": 939_524_096,
                },
            }
        ],
        "observed_wal_bytes_total": 16_777_216,
        "final_slot": lost_slot,
        "admission_policy": _policy(),
        "admission": admission,
        "runtime_termination": {
            "status_before_controller_cancel": "RUNNING",
            "final_job_status": "CANCELED",
            "origin": "controller_cancel_after_wal_capacity_rejection",
        },
        "sink": {
            "accepted_before": 3,
            "accepted_after": 3,
            "rejected_before": 0,
            "rejected_after": 0,
            "post_fault_accepted_delta": 0,
            "post_fault_rejected_delta": 0,
        },
        "slot_after_reconnect": lost_slot,
    }


def test_reserved_slot_with_safety_margin_is_admitted() -> None:
    decision = assess_slot_wal_capacity({"slot": _slot(), "policy": _policy()})

    assert decision["admitted"] is True
    assert decision["disposition"] == "admitted"
    assert decision["reason_codes"] == []


def test_extended_unreserved_and_lost_slots_are_rejected() -> None:
    for status in ("extended", "unreserved"):
        decision = assess_slot_wal_capacity(
            {"slot": _slot(wal_status=status), "policy": _policy()}
        )
        assert decision["admitted"] is False
        assert f"replication_slot_wal_status_{status}" in decision["reason_codes"]

    lost = assess_slot_wal_capacity(
        {
            "slot": _slot(wal_status="lost", restart_lsn="", safe_wal_size=None),
            "policy": _policy(),
        }
    )
    assert lost["admitted"] is False
    assert lost["reason_codes"] == [
        "replication_slot_restart_lsn_missing",
        "replication_slot_safe_wal_size_exhausted",
        "replication_slot_wal_status_lost",
    ]


def test_missing_policy_or_slot_capacity_evidence_fails_closed() -> None:
    missing = assess_slot_wal_capacity({})
    incomplete_policy = assess_slot_wal_capacity(
        {"slot": _slot(), "policy": {}}
    )

    assert missing["admitted"] is False
    assert (
        "replication_slot_wal_capacity_policy_missing"
        in missing["reason_codes"]
    )
    assert (
        "replication_slot_wal_capacity_evidence_missing"
        in missing["reason_codes"]
    )
    assert incomplete_policy["admitted"] is False
    assert (
        "replication_slot_wal_capacity_limit_missing"
        in incomplete_policy["reason_codes"]
    )
    assert (
        "replication_slot_wal_safety_margin_missing"
        in incomplete_policy["reason_codes"]
    )


def test_negative_capacity_proof_accepts_bounded_lost_slot_evidence() -> None:
    assert all(_wal_capacity_fault_checks(_capacity_fault()).values())


def test_negative_capacity_proof_rejects_disk_floor_or_sink_growth() -> None:
    low_disk = _capacity_fault()
    low_disk["pressure_cycles"][0]["storage"][
        "filesystem_available_bytes"
    ] = 268_435_456
    sink_growth = _capacity_fault()
    sink_growth["sink"] = {
        **sink_growth["sink"],
        "accepted_after": 5,
        "post_fault_accepted_delta": 2,
    }

    assert not _wal_capacity_fault_checks(low_disk)[
        "source_filesystem_safety_floor_was_preserved"
    ]
    assert not _wal_capacity_fault_checks(sink_growth)[
        "post_fault_physical_sink_did_not_advance"
    ]


def test_negative_capacity_proof_requires_same_present_slot_and_lost_status() -> None:
    missing_slot = _capacity_fault()
    missing_slot["final_slot"] = {
        **missing_slot["final_slot"],
        "exists": False,
    }
    not_lost = _capacity_fault()
    not_lost["final_slot"] = _slot(wal_status="unreserved", safe_wal_size=0)

    assert not _wal_capacity_fault_checks(missing_slot)[
        "one_slot_incarnation_remained_continuously_present"
    ]
    assert not _wal_capacity_fault_checks(not_lost)[
        "slot_transitioned_to_lost_with_no_restart_lsn"
    ]
