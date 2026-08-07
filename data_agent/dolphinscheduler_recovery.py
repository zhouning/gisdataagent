"""Fail-closed evidence contract for DolphinScheduler restart recovery."""

from __future__ import annotations

import hashlib
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

REPORT_SCHEMA = "gda.dolphinscheduler_restart_recovery.v1"
RECOVERY_LIMITATIONS = (
    "single_node_development_sandbox_only",
    "metadata_database_restore_not_exercised",
    "ha_failover_not_exercised",
    "schedule_and_backfill_not_exercised",
    "rpo_rto_not_approved",
)


class DolphinSchedulerRecoveryError(RuntimeError):
    """A recovery invariant failed without exposing runtime output."""

    def __init__(self, stage: str):
        super().__init__(f"DolphinScheduler recovery rehearsal failed at {stage}")
        self.stage = stage


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FinalizationSnapshot(_FrozenModel):
    schema_name: Literal["gda.chongqing_jqdltb_dataops_finalization.v1"] = Field(
        alias="schema"
    )
    run_id: UUID
    platform_run_status: Literal["failed"]
    platform_run_state_version: int = Field(ge=1)
    platform_run_transitioned: bool
    provider_state: Literal["SUCCESS"]
    workflow_instance_id: int = Field(gt=0)
    attempt_observation_id: UUID
    attempt_observation_created: bool
    quality_result_id: UUID
    quality_verdict: Literal["failed"]
    evidence_artifact_id: UUID
    records_scanned: int = Field(gt=0)
    assessment_resource_created: bool
    assessment_version_created: bool
    assessment_resource_version_id: UUID
    lineage_event_id: UUID
    lineage_created: bool
    data_product_version_created: Literal[False]

    def stable_identity(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude={
                "platform_run_transitioned",
                "attempt_observation_created",
                "assessment_resource_created",
                "assessment_version_created",
                "lineage_created",
            },
        )

    def assert_idempotent_replay(self) -> None:
        if self.platform_run_transitioned:
            raise DolphinSchedulerRecoveryError("ledger.run_transition_replayed")
        created = {
            "attempt_observation": self.attempt_observation_created,
            "assessment_resource": self.assessment_resource_created,
            "assessment_version": self.assessment_version_created,
            "lineage": self.lineage_created,
        }
        if any(created.values()):
            names = ",".join(sorted(name for name, value in created.items() if value))
            raise DolphinSchedulerRecoveryError(f"ledger.duplicate_write.{names}")


class ContainerSnapshot(_FrozenModel):
    service: str = Field(min_length=1, max_length=128)
    container_id: str = Field(pattern=r"^[0-9a-f]{12,64}$")
    started_at: str = Field(min_length=10, max_length=64)

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.container_id.encode("ascii")).hexdigest()


def build_recovery_report(
    *,
    before_document: dict[str, Any],
    after_document: dict[str, Any],
    runtime_before: ContainerSnapshot,
    runtime_after: ContainerSnapshot,
    metadata_before: ContainerSnapshot,
    metadata_after: ContainerSnapshot,
    restarted_at: str,
    ready_at: str,
    observed_seconds: float,
) -> dict[str, Any]:
    before = FinalizationSnapshot.model_validate(before_document)
    after = FinalizationSnapshot.model_validate(after_document)
    before.assert_idempotent_replay()
    after.assert_idempotent_replay()
    if before.stable_identity() != after.stable_identity():
        raise DolphinSchedulerRecoveryError("ledger.identity_drift")
    if runtime_before.service != runtime_after.service:
        raise DolphinSchedulerRecoveryError("runtime.service_identity")
    if runtime_before.container_id != runtime_after.container_id:
        raise DolphinSchedulerRecoveryError("runtime.container_recreated")
    if runtime_before.started_at == runtime_after.started_at:
        raise DolphinSchedulerRecoveryError("runtime.restart_not_observed")
    if metadata_before.service != metadata_after.service:
        raise DolphinSchedulerRecoveryError("metadata.service_identity")
    if metadata_before != metadata_after:
        raise DolphinSchedulerRecoveryError("metadata.container_changed")

    return {
        "schema": REPORT_SCHEMA,
        "technical_pass": True,
        "promotion_ready": False,
        "restarted_at": restarted_at,
        "ready_at": ready_at,
        "observed_seconds": round(observed_seconds, 3),
        "runtime": {
            "service": runtime_after.service,
            "container_identity_sha256": runtime_after.identity_sha256,
            "started_at_before": runtime_before.started_at,
            "started_at_after": runtime_after.started_at,
            "restart_observed": True,
        },
        "metadata_database": {
            "service": metadata_after.service,
            "container_identity_sha256": metadata_after.identity_sha256,
            "started_at": metadata_after.started_at,
            "restart_observed": False,
        },
        "authoritative_state": after.stable_identity(),
        "checks": {
            "provider_instance_recovered": True,
            "platform_run_terminal_state_preserved": True,
            "quality_evidence_preserved": True,
            "assessment_version_preserved": True,
            "lineage_preserved": True,
            "idempotent_replay": True,
            "data_product_version_created": False,
        },
        "limitations": list(RECOVERY_LIMITATIONS),
    }
