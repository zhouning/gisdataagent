"""Contracts for fail-closed PostgreSQL CDC physical failover admission."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from data_agent.platform_contracts import (
    SourceSyncDefinitionVersion,
    source_sync_definition_fingerprint,
)
from data_agent.postgresql_cdc_recovery_controller import (
    PostgresqlCdcRecoveryController,
    build_postgresql_cdc_recovery_controller_artifact,
    build_slot_continuity_observation,
)
from scripts.certify_chongqing_osm_postgres_cdc_failover import (
    PhysicalStandbySandbox,
    _failover_fault_checks,
    _resnapshot_recovery_schedule_spec,
    assess_failover_continuity,
    build_postgresql_cdc_failover_recovery_artifact,
    build_postgresql_cdc_failover_recovery_plan,
    build_postgresql_cdc_failover_resnapshot_admission,
    build_postgresql_cdc_failover_resnapshot_definition,
)


class _SnapshotRowsStub:
    source = type("Source", (), {"table": "osm_road_changes"})()

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def _psql(self, _sql: str) -> str:
        import json

        return json.dumps(self.rows)


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


def _source_definition() -> SourceSyncDefinitionVersion:
    values = {
        "tenant_id": "tenant-a",
        "sync_definition_urn": "gda://tenant-a/sync_definition/osm-cdc-v1",
        "sync_definition_version_id": UUID("00000000-0000-4000-8000-000000000201"),
        "platform_definition_version_id": UUID(
            "00000000-0000-4000-8000-000000000212"
        ),
        "source_resource_urn": "gda://tenant-a/source/osm-roads",
        "source_definition_fingerprint": "a" * 64,
        "target_resource_urn": "gda://tenant-a/table/osm-roads-silver",
        "mode": "incremental",
        "write_disposition": "merge",
        "cursor_kind": "provider_token",
        "cursor_field": None,
        "primary_keys": ("road_id",),
        "delete_mode": "hard_delete",
        "config": {"provider": "flink-postgres-cdc"},
        "governance_contract": {
            "schema": "gda.source_sync_governance.v1",
            "target_layer": "silver",
            "data_kind": "vector",
            "capture_kind": "cdc",
            "source_adapter": {
                "adapter_id": "flink-postgres-cdc",
                "adapter_version": "3.3.0",
                "adapter_fingerprint": "b" * 64,
            },
            "standard_mapping_contract_id": UUID(
                "00000000-0000-4000-8000-000000000213"
            ),
            "standard_version_id": UUID("00000000-0000-4000-8000-000000000214"),
            "data_model_version_id": UUID("00000000-0000-4000-8000-000000000215"),
            "quality_rule_version_refs": ("quality:cdc-v1",),
            "classification_policy_version_ref": "classification:internal-v1",
            "retention_policy_version_ref": "retention:silver-v1",
            "schema_change_policy": "approval_required",
            "promotion_mode": "quality_gated",
            "quarantine_resource_urn": (
                "gda://tenant-a/table/osm-roads-quarantine"
            ),
            "event_time_field": None,
            "watermark_delay_seconds": None,
        },
        "created_by": "workload:dataops-controller",
        "created_at": datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
    }
    semantic = {
        key: values[key]
        for key in (
            "tenant_id",
            "sync_definition_urn",
            "sync_definition_version_id",
            "platform_definition_version_id",
            "source_resource_urn",
            "source_definition_fingerprint",
            "target_resource_urn",
            "mode",
            "write_disposition",
            "cursor_kind",
            "cursor_field",
            "primary_keys",
            "delete_mode",
            "config",
            "governance_contract",
        )
    }
    values["definition_sha256"] = source_sync_definition_fingerprint(**semantic)
    return SourceSyncDefinitionVersion.model_validate(values)


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
        "fencing": {
            "schema": "gda.postgresql_primary_fencing.v1",
            "mode": "stop_and_detach",
            "old_primary_stopped": True,
            "old_primary_network_detached": True,
            "old_primary_write_probe": {
                "attempted": True,
                "accepted": False,
            },
        },
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
            "primary_fence_verified": 7,
            "standby_promoted": 8,
            "admission_rejected": 9,
            "source_alias_transferred": 10,
            "post_promotion_probe_mutated": 11,
            "runtime_terminated": 12,
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


def test_failover_slot_evidence_drives_checkpoint_preserving_controller_schedule() -> None:
    evidence = _admission_evidence(promoted_slot_exists=False)
    observation = build_slot_continuity_observation(
        tenant_id="tenant-a",
        sync_definition_urn="gda://tenant-a/sync_definition/osm-cdc-v1",
        sync_definition_version_id=UUID(
            "00000000-0000-4000-8000-000000000201"
        ),
        checkpoint_state_version=0,
        checkpoint_cursor={"change_set_sequence": 0},
        original_slot=evidence["primary_slot"],
        current_slot=evidence["promoted_slot"],
        absence_witnessed=True,
        observed_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
        original_creation_anchor_lsn=evidence["primary_identity"]["checkpoint_lsn"],
    )

    decision = PostgresqlCdcRecoveryController.evaluate(
        observation,
        decided_at=datetime(2026, 8, 7, 12, 0, 1, tzinfo=UTC),
    )

    assert decision.disposition == "schedule_resnapshot"
    assert decision.checkpoint_action == "preserve_and_resnapshot"
    assert decision.requires_new_run is True
    assert observation.checkpoint_state_version == 0


def test_live_old_primary_is_rejected_as_split_brain() -> None:
    evidence = _admission_evidence(promoted_slot_exists=True)
    evidence["primary_stopped_before_promotion"] = False
    evidence["fencing"] = {
        "schema": "gda.postgresql_primary_fencing.v1",
        "mode": "none",
        "old_primary_stopped": False,
        "old_primary_network_detached": False,
        "old_primary_write_probe": {"attempted": True, "accepted": True},
    }

    decision = assess_failover_continuity(evidence)

    assert decision["admitted"] is False
    assert decision["disposition"] == "rejected_fail_closed"
    assert "postgresql_primary_stop_order_unproven" in decision["reason_codes"]
    assert "postgresql_primary_fencing_mode_unapproved" in decision["reason_codes"]
    assert "postgresql_primary_not_fenced_before_promotion" in decision["reason_codes"]
    assert "postgresql_primary_network_not_fenced_before_promotion" in decision[
        "reason_codes"
    ]
    assert "postgresql_primary_write_fence_probe_failed" in decision["reason_codes"]


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


def test_promoted_postgresql_resnapshot_requires_ordered_complete_rows() -> None:
    rows = [
        {
            "road_id": 101,
            "revision": 3,
            "road_name_base64": "cm9hZA==",
            "geometry_sha256": "a" * 64,
        },
        {
            "road_id": 102,
            "revision": 1,
            "road_name_base64": "cm9hZC0y",
            "geometry_sha256": "b" * 64,
        },
    ]

    assert PhysicalStandbySandbox.snapshot_rows(_SnapshotRowsStub(rows)) == rows
    with pytest.raises(RuntimeError, match="not ordered"):
        PhysicalStandbySandbox.snapshot_rows(_SnapshotRowsStub(list(reversed(rows))))


def test_rejected_failover_builds_non_advancing_resnapshot_recovery_plan() -> None:
    evidence = _admission_evidence(promoted_slot_exists=False)
    admission = assess_failover_continuity(evidence)
    checkpoint = {"change_set_sequence": 0, "source_slice_sha256": None}

    plan = build_postgresql_cdc_failover_recovery_plan(
        tenant_id="tenant-a",
        sync_definition_urn="gda://tenant-a/sync_definition/osm-cdc-v1",
        sync_definition_version_id=UUID(
            "00000000-0000-4000-8000-000000000201"
        ),
        source_resource_urn="gda://tenant-a/source/osm-roads",
        target_resource_urn="gda://tenant-a/table/osm-roads-silver",
        checkpoint_state_version=0,
        checkpoint_cursor=checkpoint,
        admission=admission,
        admission_evidence=evidence,
        created_by="workload:dataops-controller",
        created_at=datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
    )

    assert plan.model_dump(mode="json")["schema"] == (
        "gda.postgresql_cdc_failover_recovery_plan.v1"
    )
    assert plan.recovery_mode == "resnapshot_and_reconcile"
    assert plan.cursor_disposition == "do_not_advance"
    assert plan.requires_new_run is True
    assert plan.checkpoint_cursor == checkpoint
    assert plan.admission_reason_codes == (
        "logical_replication_slot_missing_after_promotion",
    )
    assert plan.contract_fingerprint() == plan.contract_fingerprint()

    artifact = build_postgresql_cdc_failover_recovery_artifact(
        plan,
        run_id=UUID("00000000-0000-4000-8000-000000000203"),
    )
    replay = build_postgresql_cdc_failover_recovery_artifact(
        plan,
        run_id=UUID("00000000-0000-4000-8000-000000000203"),
    )
    assert artifact == replay
    assert artifact.artifact_role.value == "evidence"
    assert artifact.manifest["schema"] == (
        "gda.postgresql_cdc_failover_recovery_plan.v1"
    )
    assert artifact.resource_version_id == plan.sync_definition_version_id
    assert artifact.run_id == UUID("00000000-0000-4000-8000-000000000203")

    observation = build_slot_continuity_observation(
        tenant_id="tenant-a",
        sync_definition_urn="gda://tenant-a/sync_definition/osm-cdc-v1",
        sync_definition_version_id=plan.sync_definition_version_id,
        checkpoint_state_version=plan.checkpoint_state_version,
        checkpoint_cursor=plan.checkpoint_cursor,
        original_slot=evidence["primary_slot"],
        current_slot=evidence["promoted_slot"],
        absence_witnessed=True,
        observed_at=datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
        original_creation_anchor_lsn=evidence["primary_identity"]["checkpoint_lsn"],
    )
    controller_decision = PostgresqlCdcRecoveryController.evaluate(
        observation,
        decided_at=datetime(2026, 8, 6, 10, 0, 1, tzinfo=UTC),
    )
    controller_artifact = build_postgresql_cdc_recovery_controller_artifact(
        observation,
        controller_decision,
        recovery_plan_sha256=plan.plan_sha256,
        run_id=UUID("00000000-0000-4000-8000-000000000203"),
    )
    assert controller_artifact == build_postgresql_cdc_recovery_controller_artifact(
        observation,
        controller_decision,
        recovery_plan_sha256=plan.plan_sha256,
        run_id=UUID("00000000-0000-4000-8000-000000000203"),
    )
    assert controller_artifact.manifest["decision"]["disposition"] == (
        "schedule_resnapshot"
    )
    assert controller_artifact.manifest["recovery_plan_sha256"] == plan.plan_sha256

    resnapshot_definition = build_postgresql_cdc_failover_resnapshot_definition(
        _source_definition(),
        plan,
        sync_definition_urn="gda://tenant-a/sync_definition/osm-resnapshot-v1",
        sync_definition_version_id=UUID(
            "00000000-0000-4000-8000-000000000216"
        ),
        platform_definition_version_id=UUID(
            "00000000-0000-4000-8000-000000000217"
        ),
        created_by="workload:dataops-controller",
        created_at=datetime(2026, 8, 6, 10, 1, tzinfo=UTC),
    )
    assert resnapshot_definition.mode.value == "full"
    assert resnapshot_definition.write_disposition.value == "overwrite"
    assert resnapshot_definition.cursor_kind.value == "none"
    assert resnapshot_definition.delete_mode.value == "ignore"
    assert resnapshot_definition.governance_contract is not None
    assert resnapshot_definition.governance_contract.capture_kind.value == "batch"
    assert resnapshot_definition.config["recovery_plan_sha256"] == plan.plan_sha256

    admission = build_postgresql_cdc_failover_resnapshot_admission(
        plan,
        resnapshot_definition,
        new_run_id=UUID("00000000-0000-4000-8000-000000000218"),
        admitted_by="workload:dataops-controller",
        admitted_at=datetime(2026, 8, 6, 10, 2, tzinfo=UTC),
    )
    assert admission.new_run_id == UUID("00000000-0000-4000-8000-000000000218")
    assert admission.admission_mode == "resnapshot_and_reconcile"
    assert admission.cursor_disposition == "old_checkpoint_unchanged"


def test_admitted_failover_cannot_create_recovery_plan() -> None:
    evidence = _admission_evidence(promoted_slot_exists=True)
    admission = assess_failover_continuity(evidence)

    with pytest.raises(
        ValueError, match="an admitted failover cannot create a recovery plan"
    ):
        build_postgresql_cdc_failover_recovery_plan(
            tenant_id="tenant-a",
            sync_definition_urn="gda://tenant-a/sync_definition/osm-cdc-v1",
            sync_definition_version_id=UUID(
                "00000000-0000-4000-8000-000000000202"
            ),
            source_resource_urn="gda://tenant-a/source/osm-roads",
            target_resource_urn="gda://tenant-a/table/osm-roads-silver",
            checkpoint_state_version=0,
            checkpoint_cursor={},
            admission=admission,
            admission_evidence=evidence,
            created_by="workload:dataops-controller",
            created_at=datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
        )


def test_resnapshot_recovery_trigger_is_workload_schedule_bound_to_plan() -> None:
    plan_sha256 = "a" * 64
    created_at = datetime(2026, 8, 6, 10, 3, tzinfo=UTC)

    spec = _resnapshot_recovery_schedule_spec(
        definition_version_id=UUID("00000000-0000-4000-8000-000000000217"),
        source_resource_version_id=UUID("00000000-0000-4000-8000-000000000218"),
        binding_artifact_id=UUID("00000000-0000-4000-8000-000000000219"),
        compiled_sha256="b" * 64,
        namespace="osm-resnapshot",
        recovery_plan_sha256=plan_sha256,
        created_at=created_at,
    )

    assert spec.schedule_ref.endswith(f"/osm-resnapshot/{plan_sha256}")
    assert spec.scheduled_for == created_at
    assert spec.workload_subject_id == "dolphinscheduler-gda-dataops"
    assert spec.input_bindings[0].binding_name == "source"
