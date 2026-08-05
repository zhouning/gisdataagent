"""Focused contracts for the real PostgreSQL CDC acceptance."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from scripts.certify_chongqing_osm_postgres_cdc import (
    CONNECTOR_BYTES,
    CONNECTOR_SHA1,
    CONNECTOR_SHA256,
    DEFAULT_CONNECTOR,
    DEFAULT_SOURCE,
    _long_duration_outage_recovered,
    _lsn_value,
    _partition_slot_recovered,
    _postgres_bool,
    _rapid_network_flapping_recovered,
    _sustained_network_flapping_recovered,
    _sync_definition,
    build_cdc_plan,
    verify_connector_artifact,
)


def test_postgres_lsn_ordering_uses_full_64_bit_position() -> None:
    assert _lsn_value("0/19520D0") < _lsn_value("0/1952778")
    assert _lsn_value("1/0") > _lsn_value("0/FFFFFFFF")


def test_postgres_boolean_evidence_accepts_wire_and_explicit_text_forms() -> None:
    assert _postgres_bool("t") is True
    assert _postgres_bool("true") is True
    assert _postgres_bool("f") is False
    assert _postgres_bool("false") is False


def test_partition_recovery_requires_same_slot_lsn_progress_and_lag_reduction() -> None:
    partition = {
        "disconnect": {"disconnected": True},
        "reconnect": {"reconnected": True},
        "slot_before": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/100",
        },
        "slot_during": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/100",
        },
        "slot_after": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/300",
        },
        "target_lsn": "0/280",
        "wal_lag_bytes_before": 100,
        "wal_lag_bytes_during": 900,
        "wal_lag_bytes_after": 200,
    }

    assert _partition_slot_recovered(partition)
    assert not _partition_slot_recovered(
        {**partition, "wal_lag_bytes_after": 1_000}
    )
    assert not _partition_slot_recovered(
        {
            **partition,
            "slot_after": {
                "slot_name": "gda_slot_contract",
                "confirmed_flush_lsn": "0/250",
            },
        }
    )
    assert not _partition_slot_recovered(
        {
            **partition,
            "slot_after": {
                "slot_name": "gda_slot_recreated",
                "confirmed_flush_lsn": "0/300",
            },
        }
    )
    assert not _partition_slot_recovered(
        {
            **partition,
            "slot_during": {
                "slot_name": "gda_slot_contract",
                "confirmed_flush_lsn": "0/120",
            },
        }
    )
    assert not _partition_slot_recovered(
        {**partition, "wal_lag_bytes_during": 50}
    )


def test_rapid_flapping_requires_all_cycles_one_slot_and_exact_recovery() -> None:
    cycle = {
        "accepted_before": 12,
        "accepted_during": 12,
        "rejected_before": 2,
        "rejected_during": 2,
        "disconnect": {"disconnected": True},
        "reconnect": {"reconnected": True},
        "slot_before": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/400",
        },
        "slot_disconnected": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/400",
        },
        "slot_during": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/400",
        },
        "wal_lag_bytes_before": 10,
        "wal_lag_bytes_disconnected": 10,
        "wal_lag_bytes_during": 100,
    }
    flapping = {
        "cycles": [
            {**cycle, "cycle": 1},
            {**cycle, "cycle": 2, "accepted_during": 14},
            {
                **cycle,
                "cycle": 3,
                "accepted_before": 14,
                "accepted_during": 14,
            },
        ],
        "target_lsn": "0/500",
        "slot_after": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/500",
        },
        "wal_lag_bytes_after": 0,
        "wal_lag_bytes_peak": 100,
    }

    assert _rapid_network_flapping_recovered(flapping)
    assert _rapid_network_flapping_recovered(
        {
            **flapping,
            "cycles": [
                {
                    **cycle,
                    "cycle": 1,
                    "slot_before": {
                        "slot_name": "gda_slot_contract",
                        "confirmed_flush_lsn": "0/3F0",
                    },
                },
                {**cycle, "cycle": 2, "accepted_during": 14},
                {
                    **cycle,
                    "cycle": 3,
                    "accepted_before": 14,
                    "accepted_during": 14,
                },
            ],
        }
    )
    assert not _rapid_network_flapping_recovered(
        {
            **flapping,
            "slot_after": {
                "slot_name": "gda_slot_recreated",
                "confirmed_flush_lsn": "0/500",
            },
        }
    )
    assert not _rapid_network_flapping_recovered(
        {
            **flapping,
            "cycles": [
                {**cycle, "cycle": 1, "accepted_during": 14},
                {**cycle, "cycle": 2},
                {**cycle, "cycle": 3},
            ],
        }
    )
    assert not _rapid_network_flapping_recovered(
        {
            **flapping,
            "cycles": [
                {
                    **cycle,
                    "cycle": 1,
                    "wal_lag_bytes_disconnected": 100,
                },
                {**cycle, "cycle": 2},
                {**cycle, "cycle": 3},
            ],
        }
    )
    assert not _rapid_network_flapping_recovered(
        {
            **flapping,
            "cycles": [
                {**cycle, "cycle": 1},
                {
                    **cycle,
                    "cycle": 2,
                    "slot_during": {
                        "slot_name": "gda_slot_contract",
                        "confirmed_flush_lsn": "0/410",
                    },
                },
                {**cycle, "cycle": 3},
            ],
        }
    )
    assert not _rapid_network_flapping_recovered(
        {
            **flapping,
            "slot_after": {
                "slot_name": "gda_slot_contract",
                "confirmed_flush_lsn": "0/4FF",
            },
        }
    )
    assert not _rapid_network_flapping_recovered(
        {
            **flapping,
            "cycles": [
                {**cycle, "cycle": 1},
                {
                    **cycle,
                    "cycle": 2,
                    "reconnect": {"reconnected": False},
                },
                {**cycle, "cycle": 3},
            ],
        }
    )


def test_long_outage_requires_checkpoint_timeout_and_bounded_exact_recovery() -> None:
    outage = {
        "outage_objective_seconds": 20.0,
        "checkpoint_timeout_seconds": 15,
        "duration_seconds": 20.1,
        "accepted_before": 14,
        "accepted_during": 14,
        "accepted_after": 16,
        "rejected_before": 2,
        "rejected_during": 2,
        "rejected_after": 2,
        "during_observation": {"job_status": "RUNNING"},
        "job_status_after_reconnect": "RUNNING",
        "recovery_duration_seconds": 12.5,
        "recovery_budget_seconds": 60,
        "disconnect": {"disconnected": True},
        "reconnect": {"reconnected": True},
        "slot_before": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/400",
        },
        "slot_during": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/400",
        },
        "slot_after": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/500",
        },
        "target_lsn": "0/500",
        "wal_lag_bytes_before": 10,
        "wal_lag_bytes_during": 100,
        "wal_lag_bytes_after": 0,
    }

    assert _long_duration_outage_recovered(outage)
    assert not _long_duration_outage_recovered(
        {**outage, "outage_objective_seconds": 15.0}
    )
    assert not _long_duration_outage_recovered(
        {**outage, "duration_seconds": 19.9}
    )
    assert not _long_duration_outage_recovered(
        {**outage, "accepted_during": 16}
    )
    assert not _long_duration_outage_recovered(
        {**outage, "recovery_budget_seconds": 10}
    )
    assert not _long_duration_outage_recovered(
        {**outage, "during_observation": {"job_status": "RESTARTING"}}
    )
    assert not _long_duration_outage_recovered(
        {
            **outage,
            "slot_after": {
                "slot_name": "gda_slot_recreated",
                "confirmed_flush_lsn": "0/500",
            },
        }
    )


def test_sustained_flapping_requires_twenty_cycles_and_bounded_recovery() -> None:
    cycle = {
        "accepted_before": 16,
        "accepted_during": 16,
        "rejected_before": 2,
        "rejected_during": 2,
        "disconnect": {"disconnected": True},
        "during_observation": {"job_status": "RUNNING"},
        "reconnect": {"reconnected": True},
        "slot_before": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/600",
        },
        "slot_disconnected": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/600",
        },
        "slot_during": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/600",
        },
        "wal_lag_bytes_before": 10,
        "wal_lag_bytes_disconnected": 10,
        "wal_lag_bytes_during": 100,
    }
    cycles = [{**cycle, "cycle": number} for number in range(1, 21)]
    flapping = {
        "phase": "sustained_high_frequency_network_flapping",
        "flap_count": 20,
        "interval_seconds": 0.1,
        "cycles": cycles,
        "target_lsn": "0/700",
        "slot_after": {
            "slot_name": "gda_slot_contract",
            "confirmed_flush_lsn": "0/700",
        },
        "wal_lag_bytes_after": 0,
        "wal_lag_bytes_peak": 100,
        "job_status_after_recovery": "RUNNING",
        "recovery_duration_seconds": 9.5,
        "recovery_budget_seconds": 60,
        "recovery_wal_lag_budget_bytes": 1_024,
    }

    assert _sustained_network_flapping_recovered(flapping)
    assert not _sustained_network_flapping_recovered(
        {**flapping, "flap_count": 19, "cycles": cycles[:19]}
    )
    assert not _sustained_network_flapping_recovered(
        {**flapping, "interval_seconds": 0.11}
    )
    assert not _sustained_network_flapping_recovered(
        {
            **flapping,
            "cycles": [
                *cycles[:10],
                {
                    **cycles[10],
                    "during_observation": {"job_status": "RESTARTING"},
                },
                *cycles[11:],
            ],
        }
    )
    assert not _sustained_network_flapping_recovered(
        {**flapping, "recovery_budget_seconds": 9}
    )
    assert not _sustained_network_flapping_recovered(
        {**flapping, "wal_lag_bytes_after": 1_025}
    )
    assert not _sustained_network_flapping_recovered(
        {
            **flapping,
            "slot_after": {
                "slot_name": "gda_slot_recreated",
                "confirmed_flush_lsn": "0/700",
            },
        }
    )


def test_cdc_plan_is_deterministic_and_reconciles_operations() -> None:
    first = build_cdc_plan(DEFAULT_SOURCE)
    second = build_cdc_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["initial"]) == 3
    assert len(first["expected_changelog"]) == 18
    assert len(first["expected_quarantine"]) == 2
    assert len(first["final_rows"]) == 2
    assert first["a_after"]["revision"] == 2
    assert first["a_projection_after"]["revision"] == 3
    assert first["a_flap_after"]["revision"] == 4
    assert first["a_long_outage_after"]["revision"] == 5
    assert first["a_sustained_flap_after"]["revision"] == 6
    assert first["c_after"]["revision"] == 2
    assert first["final_rows"][0]["revision"] == 6
    assert first["milestone_counts"] == {
        "initial_snapshot_accepted": 3,
        "base_mutations_accepted": 10,
        "additive_schema_accepted": 12,
        "rapid_flapping_accepted": 14,
        "long_outage_accepted": 16,
        "sustained_flapping_accepted": 18,
        "quarantined": 2,
    }
    assert first["operation_counts"] == {
        "read": 20,
        "inserted": 5,
        "updated": 6,
        "deleted": 3,
        "output": 2,
    }
    assert {line.split("\t", 1)[0] for line in first["expected_changelog"]} == {
        "+I",
        "-U",
        "+U",
        "-D",
    }
    assert {
        line.split("\t", 1)[0] for line in first["expected_quarantine"]
    } == {"invalid_geometry_sha256"}


def test_cdc_definition_is_governed_silver_with_quarantine() -> None:
    namespace = "chongqing_osm_cdc_contract"
    definition = _sync_definition(
        sync_definition_version_id=uuid4(),
        platform_definition_version_id=uuid4(),
        namespace=namespace,
        source_slice_sha256="a" * 64,
        connector={"sha256": CONNECTOR_SHA256},
        flink_image="flink:test",
        flink_image_id="sha256:" + "b" * 64,
        job_source_sha256="c" * 64,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
    )

    governance = definition.governance_contract
    assert governance is not None
    assert governance.target_layer.value == "silver"
    assert governance.capture_kind.value == "cdc"
    assert governance.promotion_mode.value == "quality_gated"
    assert governance.quarantine_resource_urn == (
        f"gda://local-dev/table/{namespace}-quarantine"
    )
    assert governance.standard_mapping_contract_id is not None
    assert governance.standard_version_id is not None
    assert governance.data_model_version_id is not None
    assert definition.config["source_projection_fields"] == [
        "road_id",
        "revision",
        "road_name_base64",
        "geometry_sha256",
    ]
    assert (
        definition.config["schema_evolution_mode"]
        == "explicit_projection_with_drift_gate"
    )


def test_cdc_connector_artifact_matches_frozen_supply_chain_identity() -> None:
    evidence = verify_connector_artifact(DEFAULT_CONNECTOR)

    assert evidence == {
        "coordinate": "org.apache.flink:flink-sql-connector-postgres-cdc:3.3.0",
        "bytes": CONNECTOR_BYTES,
        "maven_sha1": CONNECTOR_SHA1,
        "sha256": CONNECTOR_SHA256,
    }
