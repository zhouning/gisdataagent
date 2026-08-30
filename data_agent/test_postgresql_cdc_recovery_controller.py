"""Contracts for checkpoint-safe PostgreSQL CDC slot-loss recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.platform_contracts import Artifact, canonical_json_fingerprint
from data_agent.postgresql_cdc_recovery_controller import (
    PostgresqlCdcRecoveryController,
    PostgresqlCdcRecoveryControllerRuntime,
    PostgresqlCdcRecoveryDecision,
    PostgresqlCdcSlotContinuityObservation,
    PostgresqlCdcSlotIncarnation,
    assess_slot_continuity,
    build_slot_continuity_observation,
    slot_continuity_observation_fingerprint,
)

TENANT = "tenant-a"
SYNC_URN = "gda://tenant-a/sync_definition/osm-cdc-v1"
SYNC_VERSION_ID = UUID("00000000-0000-4000-8000-000000000301")
OBSERVED_AT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
DECIDED_AT = datetime(2026, 8, 7, 12, 0, 1, tzinfo=UTC)


def _provider_observation() -> dict[str, object]:
    return {
        "exists": True,
        "system_identifier": "7671164979134124066",
        "database_identity": "cdc_acceptance",
        "slot_name": "gda_slot_contract",
        "plugin": "pgoutput",
        "slot_type": "logical",
    }


def _incarnation(
    *,
    ordinal: int = 1,
    creation_anchor_lsn: str = "0/100",
) -> PostgresqlCdcSlotIncarnation:
    return PostgresqlCdcSlotIncarnation.from_observation(
        _provider_observation(),
        ordinal=ordinal,
        creation_anchor_lsn=creation_anchor_lsn,
        established_by=(
            "connector_initial_slot_observation"
            if ordinal == 1
            else "same_name_recreation_after_absence"
        ),
    )


def _observation(
    *,
    original: PostgresqlCdcSlotIncarnation | None = None,
    current: PostgresqlCdcSlotIncarnation | None = None,
    absence_witnessed: bool = False,
    current_slot_exists: bool = True,
    checkpoint_cursor: dict[str, object] | None = None,
) -> PostgresqlCdcSlotContinuityObservation:
    original = original or _incarnation()
    if current is None and current_slot_exists:
        current = original
    cursor = checkpoint_cursor or {
        "provider": "postgresql",
        "confirmed_flush_lsn": "0/180",
    }
    values = {
        "tenant_id": TENANT,
        "sync_definition_urn": SYNC_URN,
        "sync_definition_version_id": SYNC_VERSION_ID,
        "checkpoint_state_version": 3,
        "checkpoint_cursor": cursor,
        "original_incarnation": original,
        "current_incarnation": current,
        "absence_witnessed": absence_witnessed,
        "current_slot_exists": current_slot_exists,
        "observed_at": OBSERVED_AT,
    }
    return PostgresqlCdcSlotContinuityObservation(
        schema="gda.postgresql_cdc_slot_continuity_observation.v1",
        checkpoint_cursor_sha256=canonical_json_fingerprint(cursor),
        observation_sha256=slot_continuity_observation_fingerprint(**values),
        **values,
    )


def test_continuous_incarnation_resumes_without_advancing_checkpoint() -> None:
    observation = _observation()

    decision = PostgresqlCdcRecoveryController.evaluate(
        observation,
        decided_at=DECIDED_AT,
    )

    assert decision.disposition == "resume_cdc"
    assert decision.reason_codes == ()
    assert decision.checkpoint_action == "preserve_and_resume"
    assert decision.requires_new_run is False
    assert decision.observation_sha256 == observation.observation_sha256


def test_witnessed_same_name_recreation_schedules_governed_resnapshot() -> None:
    original = _incarnation()
    recreated = _incarnation(ordinal=2, creation_anchor_lsn="0/300")
    observation = _observation(
        original=original,
        current=recreated,
        absence_witnessed=True,
    )

    decision = PostgresqlCdcRecoveryController.evaluate(
        observation,
        decided_at=DECIDED_AT,
    )

    assert decision.disposition == "schedule_resnapshot"
    assert decision.reason_codes == (
        "replication_slot_absence_witnessed",
        "replication_slot_incarnation_changed",
    )
    assert decision.checkpoint_action == "preserve_and_resnapshot"
    assert decision.requires_new_run is True


def test_provider_adapter_binds_missing_slot_to_last_checkpoint() -> None:
    cursor = {"confirmed_flush_lsn": "0/180"}
    observation = build_slot_continuity_observation(
        tenant_id=TENANT,
        sync_definition_urn=SYNC_URN,
        sync_definition_version_id=SYNC_VERSION_ID,
        checkpoint_state_version=3,
        checkpoint_cursor=cursor,
        original_slot=_provider_observation(),
        current_slot={
            "exists": False,
            "slot_name": "gda_slot_contract",
            "system_identifier": "7671164979134124066",
        },
        absence_witnessed=True,
        observed_at=OBSERVED_AT,
        original_creation_anchor_lsn="0/100",
    )

    assert observation.current_incarnation is None
    assert observation.current_slot_exists is False
    assert observation.checkpoint_cursor == cursor
    decision = PostgresqlCdcRecoveryController.evaluate(
        observation,
        decided_at=DECIDED_AT,
    )
    assert decision.disposition == "schedule_resnapshot"
    assert decision.checkpoint_action == "preserve_and_resnapshot"


def test_unwitnessed_missing_slot_stops_fail_closed() -> None:
    observation = _observation(
        current=None,
        absence_witnessed=False,
        current_slot_exists=False,
    )

    decision = PostgresqlCdcRecoveryController.evaluate(
        observation,
        decided_at=DECIDED_AT,
    )

    assert decision.disposition == "rejected_fail_closed"
    assert decision.reason_codes == (
        "replication_slot_continuity_evidence_incomplete",
    )
    assert decision.checkpoint_action == "preserve_and_stop"
    assert decision.requires_new_run is False


def test_observation_binds_checkpoint_and_current_slot_existence() -> None:
    original = _incarnation()
    values = {
        "schema": "gda.postgresql_cdc_slot_continuity_observation.v1",
        "tenant_id": TENANT,
        "sync_definition_urn": SYNC_URN,
        "sync_definition_version_id": SYNC_VERSION_ID,
        "checkpoint_state_version": 3,
        "checkpoint_cursor": {"confirmed_flush_lsn": "0/180"},
        "checkpoint_cursor_sha256": "f" * 64,
        "original_incarnation": original,
        "current_incarnation": None,
        "absence_witnessed": True,
        "current_slot_exists": True,
        "observed_at": OBSERVED_AT,
        "observation_sha256": "e" * 64,
    }

    with pytest.raises(ValidationError, match="checkpoint fingerprint"):
        PostgresqlCdcSlotContinuityObservation(**values)

    values["checkpoint_cursor_sha256"] = canonical_json_fingerprint(
        values["checkpoint_cursor"]
    )
    with pytest.raises(ValidationError, match="current existence"):
        PostgresqlCdcSlotContinuityObservation(**values)


def test_decision_rejects_tampered_fingerprint_or_human_actor() -> None:
    decision = PostgresqlCdcRecoveryController.evaluate(
        _observation(),
        decided_at=DECIDED_AT,
    )
    values = decision.model_dump(mode="python", by_alias=True)
    values["decision_sha256"] = "f" * 64

    with pytest.raises(ValidationError, match="fingerprint"):
        PostgresqlCdcRecoveryDecision.model_validate(values)

    values = decision.model_dump(mode="python", by_alias=True)
    values["decided_by"] = "human:operator"
    with pytest.raises(ValidationError, match="must be a workload"):
        PostgresqlCdcRecoveryDecision.model_validate(values)


def test_runtime_persists_controller_evidence_idempotently() -> None:
    class _Gateway:
        def __init__(self) -> None:
            self.artifacts: dict[str, object] = {}

        def record_artifact(self, artifact: Artifact) -> SimpleNamespace:
            key = str(artifact.artifact_id)
            created = key not in self.artifacts
            self.artifacts[key] = artifact
            return SimpleNamespace(value=artifact, created=created)

    observation = _observation(
        current=None,
        absence_witnessed=True,
        current_slot_exists=False,
    )
    runtime = PostgresqlCdcRecoveryControllerRuntime(_Gateway())
    decision = runtime.evaluate(observation, decided_at=DECIDED_AT)
    first = runtime.record_evidence(
        observation,
        decision,
        recovery_plan_sha256="a" * 64,
        run_id=UUID("00000000-0000-4000-8000-000000000302"),
    )
    replay = runtime.record_evidence(
        observation,
        decision,
        recovery_plan_sha256="a" * 64,
        run_id=UUID("00000000-0000-4000-8000-000000000302"),
    )

    assert first.created is True
    assert replay.created is False
    assert replay.artifact == first.artifact
    assert replay.artifact.manifest["recovery_plan_sha256"] == "a" * 64


def test_runtime_uses_atomic_artifact_and_durable_ledger_writer() -> None:
    class _Gateway:
        def __init__(self) -> None:
            self.calls: list[tuple[Artifact, object, object]] = []

        def record_postgresql_cdc_recovery_observation(
            self,
            artifact: Artifact,
            *,
            recovery_plan_sha256: str,
            observation: object,
            decision: object,
        ) -> SimpleNamespace:
            assert recovery_plan_sha256 == "b" * 64
            self.calls.append((artifact, observation, decision))
            return SimpleNamespace(
                artifact=artifact,
                artifact_created=not self.calls[:-1],
                ledger_created=not self.calls[:-1],
            )

        def record_artifact(self, _artifact: Artifact) -> SimpleNamespace:
            raise AssertionError("durable writer must be preferred")

    observation = _observation(
        current=None,
        absence_witnessed=True,
        current_slot_exists=False,
    )
    gateway = _Gateway()
    runtime = PostgresqlCdcRecoveryControllerRuntime(gateway)
    decision = runtime.evaluate(observation, decided_at=DECIDED_AT)
    first = runtime.record_evidence(
        observation,
        decision,
        recovery_plan_sha256="b" * 64,
        run_id=UUID("00000000-0000-4000-8000-000000000302"),
    )
    replay = runtime.record_evidence(
        observation,
        decision,
        recovery_plan_sha256="b" * 64,
        run_id=UUID("00000000-0000-4000-8000-000000000302"),
    )

    assert len(gateway.calls) == 2
    assert first.created is True
    assert first.ledger_created is True
    assert replay.created is False
    assert replay.ledger_created is False


def test_certifier_compatibility_assessment_still_fails_closed() -> None:
    original = _incarnation()
    recreated = _incarnation(ordinal=2, creation_anchor_lsn="0/300")

    decision = assess_slot_continuity(
        {
            "original_incarnation": original.model_dump(mode="json"),
            "current_incarnation": recreated.model_dump(mode="json"),
            "absence_witnessed": True,
            "current_slot_exists": True,
        }
    )

    assert decision["disposition"] == "rejected_fail_closed"
    assert decision["reason_codes"] == [
        "replication_slot_absence_witnessed",
        "replication_slot_incarnation_changed",
    ]
