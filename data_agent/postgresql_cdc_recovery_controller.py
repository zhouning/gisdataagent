"""Deterministic PostgreSQL CDC recovery-controller contracts.

The controller owns admission decisions around replication-slot continuity.  It
does not own a provider cursor, execute a resnapshot, or replace
DolphinScheduler.  A decision preserves the last accepted checkpoint and makes
the next governed action explicit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from .platform_contracts import (
    Artifact,
    ArtifactRole,
    FrozenContract,
    NonEmptyText,
    ResourceURNText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _slot_identity(
    *,
    system_identifier: str,
    database_identity: str,
    slot_name: str,
    plugin: str,
    slot_type: str,
    creation_anchor_lsn: str,
    incarnation_ordinal: int,
    established_by: str,
) -> dict[str, Any]:
    return {
        "system_identifier": system_identifier,
        "database_identity": database_identity,
        "slot_name": slot_name,
        "plugin": plugin,
        "slot_type": slot_type,
        "creation_anchor_lsn": creation_anchor_lsn,
        "incarnation_ordinal": incarnation_ordinal,
        "established_by": established_by,
    }


class PostgresqlCdcSlotIncarnation(FrozenContract):
    """Immutable identity for one logical replication-slot incarnation."""

    schema_id = "postgresql_cdc_slot_incarnation"

    system_identifier: NonEmptyText
    database_identity: NonEmptyText
    slot_name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,62}$",
    )
    plugin: Literal["pgoutput"]
    slot_type: Literal["logical"]
    creation_anchor_lsn: NonEmptyText
    incarnation_ordinal: int = Field(gt=0)
    established_by: NonEmptyText
    incarnation_fingerprint: Sha256

    @model_validator(mode="after")
    def _fingerprint_matches(self) -> PostgresqlCdcSlotIncarnation:
        expected = canonical_json_fingerprint(
            _slot_identity(
                system_identifier=self.system_identifier,
                database_identity=self.database_identity,
                slot_name=self.slot_name,
                plugin=self.plugin,
                slot_type=self.slot_type,
                creation_anchor_lsn=self.creation_anchor_lsn,
                incarnation_ordinal=self.incarnation_ordinal,
                established_by=self.established_by,
            )
        )
        if self.incarnation_fingerprint != expected:
            raise ValueError("slot incarnation fingerprint does not match identity")
        return self

    @classmethod
    def from_observation(
        cls,
        observation: dict[str, Any],
        *,
        ordinal: int,
        creation_anchor_lsn: str,
        established_by: str,
    ) -> PostgresqlCdcSlotIncarnation:
        if observation.get("exists") is not True:
            raise ValueError("slot incarnation requires an existing slot observation")
        identity = _slot_identity(
            system_identifier=str(observation["system_identifier"]),
            database_identity=str(observation["database_identity"]),
            slot_name=str(observation["slot_name"]),
            plugin=str(observation["plugin"]),
            slot_type=str(observation["slot_type"]),
            creation_anchor_lsn=creation_anchor_lsn,
            incarnation_ordinal=ordinal,
            established_by=established_by,
        )
        return cls(
            **identity,
            incarnation_fingerprint=canonical_json_fingerprint(identity),
        )


def build_slot_incarnation(
    observation: dict[str, Any],
    *,
    ordinal: int,
    creation_anchor_lsn: str,
    established_by: str,
) -> dict[str, Any]:
    """Build the legacy JSON projection from a validated incarnation."""

    return PostgresqlCdcSlotIncarnation.from_observation(
        observation,
        ordinal=ordinal,
        creation_anchor_lsn=creation_anchor_lsn,
        established_by=established_by,
    ).model_dump(mode="json")


def assess_slot_continuity(evidence: dict[str, Any]) -> dict[str, Any]:
    """Admit only a continuously observed slot incarnation; missing proof fails closed."""

    original = evidence.get("original_incarnation")
    current = evidence.get("current_incarnation")
    absence_witnessed = evidence.get("absence_witnessed") is True
    reasons: list[str] = []
    if not isinstance(original, dict) or not isinstance(current, dict):
        reasons.append("replication_slot_continuity_evidence_missing")
    else:
        required = {
            "system_identifier",
            "database_identity",
            "slot_name",
            "plugin",
            "slot_type",
            "incarnation_fingerprint",
        }
        if not required.issubset(original) or not required.issubset(current):
            reasons.append("replication_slot_continuity_evidence_incomplete")
        elif any(
            original[key] != current[key]
            for key in required - {"incarnation_fingerprint"}
        ):
            reasons.append("replication_slot_identity_changed")
        elif original["incarnation_fingerprint"] != current["incarnation_fingerprint"]:
            reasons.append("replication_slot_incarnation_changed")
    if absence_witnessed:
        reasons.append("replication_slot_absence_witnessed")
    if evidence.get("current_slot_exists") is not True:
        reasons.append("replication_slot_current_observation_missing")
    admitted = not reasons
    return {
        "schema": "gda.postgres_cdc_slot_continuity_admission.v1",
        "admitted": admitted,
        "disposition": "admitted" if admitted else "rejected_fail_closed",
        "reason_codes": sorted(set(reasons)),
        "original_incarnation_fingerprint": (
            original.get("incarnation_fingerprint")
            if isinstance(original, dict)
            else None
        ),
        "current_incarnation_fingerprint": (
            current.get("incarnation_fingerprint")
            if isinstance(current, dict)
            else None
        ),
    }


def _observation_fingerprint_payload(
    *,
    tenant_id: str,
    sync_definition_urn: str,
    sync_definition_version_id: UUID,
    checkpoint_state_version: int,
    checkpoint_cursor: dict[str, Any],
    original_incarnation: PostgresqlCdcSlotIncarnation,
    current_incarnation: PostgresqlCdcSlotIncarnation | None,
    absence_witnessed: bool,
    current_slot_exists: bool,
    observed_at: datetime,
) -> dict[str, Any]:
    return {
        "schema": "gda.postgresql_cdc_slot_continuity_observation.v1",
        "tenant_id": tenant_id,
        "sync_definition_urn": sync_definition_urn,
        "sync_definition_version_id": str(sync_definition_version_id),
        "checkpoint_state_version": checkpoint_state_version,
        "checkpoint_cursor": checkpoint_cursor,
        "original_incarnation": original_incarnation.model_dump(mode="json"),
        "current_incarnation": (
            current_incarnation.model_dump(mode="json")
            if current_incarnation is not None
            else None
        ),
        "absence_witnessed": absence_witnessed,
        "current_slot_exists": current_slot_exists,
        "observed_at": _aware_utc(observed_at).isoformat().replace("+00:00", "Z"),
    }


class PostgresqlCdcSlotContinuityObservation(FrozenContract):
    """A checkpoint-bound observation collected by the recovery controller."""

    schema_id = "postgresql_cdc_slot_continuity_observation"

    contract_schema: Literal[
        "gda.postgresql_cdc_slot_continuity_observation.v1"
    ] = Field(alias="schema")
    tenant_id: TenantId
    sync_definition_urn: ResourceURNText
    sync_definition_version_id: UUID
    checkpoint_state_version: int = Field(ge=0)
    checkpoint_cursor: dict[str, Any]
    checkpoint_cursor_sha256: Sha256
    original_incarnation: PostgresqlCdcSlotIncarnation
    current_incarnation: PostgresqlCdcSlotIncarnation | None = None
    absence_witnessed: bool
    current_slot_exists: bool
    observed_at: datetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def _validate_observation(self) -> PostgresqlCdcSlotContinuityObservation:
        identity = parse_resource_urn(self.sync_definition_urn)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("slot observation sync definition tenant mismatch")
        if identity["resource_kind"] != "sync_definition":
            raise ValueError("slot observation must reference a sync_definition")
        if self.checkpoint_cursor_sha256 != canonical_json_fingerprint(self.checkpoint_cursor):
            raise ValueError("slot observation checkpoint fingerprint does not match cursor")
        if self.current_slot_exists != (self.current_incarnation is not None):
            raise ValueError("slot observation current existence does not match incarnation")
        observed_at = _aware_utc(self.observed_at)
        expected = canonical_json_fingerprint(
            _observation_fingerprint_payload(
                tenant_id=self.tenant_id,
                sync_definition_urn=self.sync_definition_urn,
                sync_definition_version_id=self.sync_definition_version_id,
                checkpoint_state_version=self.checkpoint_state_version,
                checkpoint_cursor=self.checkpoint_cursor,
                original_incarnation=self.original_incarnation,
                current_incarnation=self.current_incarnation,
                absence_witnessed=self.absence_witnessed,
                current_slot_exists=self.current_slot_exists,
                observed_at=observed_at,
            )
        )
        if self.observation_sha256 != expected:
            raise ValueError("slot observation fingerprint does not match content")
        return self


def build_slot_continuity_observation(
    *,
    tenant_id: str,
    sync_definition_urn: str,
    sync_definition_version_id: UUID,
    checkpoint_state_version: int,
    checkpoint_cursor: dict[str, Any],
    original_slot: dict[str, Any],
    current_slot: dict[str, Any] | None,
    absence_witnessed: bool,
    observed_at: datetime,
    original_creation_anchor_lsn: str,
    current_creation_anchor_lsn: str | None = None,
    current_incarnation_ordinal: int | None = None,
) -> PostgresqlCdcSlotContinuityObservation:
    """Bind provider slot observations to the last accepted SourceSync cursor."""

    original = PostgresqlCdcSlotIncarnation.from_observation(
        original_slot,
        ordinal=1,
        creation_anchor_lsn=original_creation_anchor_lsn,
        established_by="controller_initial_slot_observation",
    )
    current = None
    if current_slot is not None and current_slot.get("exists") is True:
        current = PostgresqlCdcSlotIncarnation.from_observation(
            current_slot,
            ordinal=current_incarnation_ordinal or 1,
            creation_anchor_lsn=(
                current_creation_anchor_lsn or original_creation_anchor_lsn
            ),
            established_by="controller_current_slot_observation",
        )
    values = {
        "tenant_id": tenant_id,
        "sync_definition_urn": sync_definition_urn,
        "sync_definition_version_id": sync_definition_version_id,
        "checkpoint_state_version": checkpoint_state_version,
        "checkpoint_cursor": checkpoint_cursor,
        "original_incarnation": original,
        "current_incarnation": current,
        "absence_witnessed": absence_witnessed,
        "current_slot_exists": current is not None,
        "observed_at": observed_at,
    }
    return PostgresqlCdcSlotContinuityObservation(
        schema="gda.postgresql_cdc_slot_continuity_observation.v1",
        checkpoint_cursor_sha256=canonical_json_fingerprint(checkpoint_cursor),
        observation_sha256=slot_continuity_observation_fingerprint(**values),
        **values,
    )


def slot_continuity_observation_fingerprint(
    *,
    tenant_id: str,
    sync_definition_urn: str,
    sync_definition_version_id: UUID,
    checkpoint_state_version: int,
    checkpoint_cursor: dict[str, Any],
    original_incarnation: PostgresqlCdcSlotIncarnation,
    current_incarnation: PostgresqlCdcSlotIncarnation | None,
    absence_witnessed: bool,
    current_slot_exists: bool,
    observed_at: datetime,
) -> str:
    return canonical_json_fingerprint(
        _observation_fingerprint_payload(
            tenant_id=tenant_id,
            sync_definition_urn=sync_definition_urn,
            sync_definition_version_id=sync_definition_version_id,
            checkpoint_state_version=checkpoint_state_version,
            checkpoint_cursor=checkpoint_cursor,
            original_incarnation=original_incarnation,
            current_incarnation=current_incarnation,
            absence_witnessed=absence_witnessed,
            current_slot_exists=current_slot_exists,
            observed_at=observed_at,
        )
    )


def build_postgresql_cdc_recovery_controller_artifact(
    observation: PostgresqlCdcSlotContinuityObservation,
    decision: PostgresqlCdcRecoveryDecision,
    *,
    recovery_plan_sha256: str,
    run_id: UUID,
) -> Artifact:
    """Persist one controller gate in the existing immutable evidence ledger."""

    observation_document = observation.model_dump(mode="json", by_alias=True)
    decision_document = decision.model_dump(mode="json", by_alias=True)
    manifest = {
        "schema": "gda.postgresql_cdc_recovery_controller_evidence.v1",
        "observation": observation_document,
        "decision": decision_document,
        "recovery_plan_sha256": recovery_plan_sha256,
    }
    content = json.dumps(
        manifest,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    evidence_sha256 = canonical_json_fingerprint(manifest)
    return Artifact(
        tenant_id=observation.tenant_id,
        artifact_id=uuid5(
            run_id,
            f"gda.postgresql_cdc_recovery_controller_evidence.v1:{evidence_sha256}",
        ),
        artifact_key=f"cdc-recovery-controller-{evidence_sha256[:16]}",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri=(
            "postgresql://gda-control/recovery-controller-evidence/"
            f"{observation.tenant_id}/{evidence_sha256}"
        ),
        media_type="application/vnd.gda.postgresql-cdc-recovery-controller+json",
        content_sha256=evidence_sha256,
        size_bytes=len(content.encode("utf-8")),
        run_id=run_id,
        resource_version_id=observation.sync_definition_version_id,
        manifest=manifest,
        created_by=decision.decided_by,
        created_at=decision.decided_at,
    )


class PostgresqlCdcRecoveryDecision(FrozenContract):
    """Auditable next action after a slot-continuity observation."""

    schema_id = "postgresql_cdc_recovery_controller_decision"

    contract_schema: Literal[
        "gda.postgresql_cdc_recovery_controller_decision.v1"
    ] = Field(alias="schema")
    tenant_id: TenantId
    sync_definition_version_id: UUID
    observation_sha256: Sha256
    disposition: Literal[
        "resume_cdc",
        "schedule_resnapshot",
        "rejected_fail_closed",
    ]
    reason_codes: tuple[str, ...] = ()
    checkpoint_action: Literal[
        "preserve_and_resume",
        "preserve_and_resnapshot",
        "preserve_and_stop",
    ]
    requires_new_run: bool
    decided_by: NonEmptyText
    decided_at: datetime
    decision_sha256: Sha256

    @model_validator(mode="after")
    def _validate_decision(self) -> PostgresqlCdcRecoveryDecision:
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("recovery decision reason codes must be unique and sorted")
        if not self.decided_by.startswith("workload:"):
            raise ValueError("recovery controller decision actor must be a workload")
        if self.disposition == "resume_cdc":
            if self.reason_codes or self.requires_new_run:
                raise ValueError("resume decision cannot contain recovery reasons or a new Run")
            if self.checkpoint_action != "preserve_and_resume":
                raise ValueError("resume decision must preserve the checkpoint and resume")
        elif self.disposition == "schedule_resnapshot":
            if not self.reason_codes or not self.requires_new_run:
                raise ValueError("resnapshot decision requires reasons and a new Run")
            if self.checkpoint_action != "preserve_and_resnapshot":
                raise ValueError("resnapshot decision must preserve the old checkpoint")
        elif self.checkpoint_action != "preserve_and_stop" or self.requires_new_run:
            raise ValueError("fail-closed decision must stop without creating a Run")
        expected = canonical_json_fingerprint(
            {
                "schema": self.contract_schema,
                "tenant_id": self.tenant_id,
                "sync_definition_version_id": str(self.sync_definition_version_id),
                "observation_sha256": self.observation_sha256,
                "disposition": self.disposition,
                "reason_codes": list(self.reason_codes),
                "checkpoint_action": self.checkpoint_action,
                "requires_new_run": self.requires_new_run,
                "decided_by": self.decided_by,
                "decided_at": _aware_utc(self.decided_at).isoformat().replace(
                    "+00:00", "Z"
                ),
            }
        )
        if self.decision_sha256 != expected:
            raise ValueError("recovery decision fingerprint does not match content")
        return self


class PostgresqlCdcRecoveryObservationRecord(FrozenContract):
    """Queryable projection of one durable recovery-controller ledger row."""

    schema_id = "postgresql_cdc_recovery_observation_record"

    tenant_id: TenantId
    artifact_id: UUID
    sync_definition_version_id: UUID
    run_id: UUID
    sync_definition_urn: ResourceURNText
    checkpoint_state_version: int = Field(ge=0)
    checkpoint_cursor: dict[str, Any]
    observation_sha256: Sha256
    decision_sha256: Sha256
    disposition: Literal[
        "resume_cdc",
        "schedule_resnapshot",
        "rejected_fail_closed",
    ]
    reason_codes: tuple[str, ...] = ()
    recovery_plan_sha256: Sha256
    observation: PostgresqlCdcSlotContinuityObservation
    decision: PostgresqlCdcRecoveryDecision
    observed_at: datetime
    decided_at: datetime
    recorded_by: NonEmptyText
    recorded_at: datetime

    @model_validator(mode="after")
    def _consistent_projection(self) -> PostgresqlCdcRecoveryObservationRecord:
        if self.observation.tenant_id != self.tenant_id:
            raise ValueError("recovery observation tenant does not match projection")
        if self.observation.sync_definition_version_id != self.sync_definition_version_id:
            raise ValueError("recovery observation definition does not match projection")
        if self.observation.observation_sha256 != self.observation_sha256:
            raise ValueError("recovery observation fingerprint does not match projection")
        if self.decision.observation_sha256 != self.observation_sha256:
            raise ValueError("recovery decision is not bound to the observation")
        if self.decision.decision_sha256 != self.decision_sha256:
            raise ValueError("recovery decision fingerprint does not match projection")
        if self.decision.disposition != self.disposition:
            raise ValueError("recovery disposition does not match projection")
        if tuple(self.decision.reason_codes) != tuple(self.reason_codes):
            raise ValueError("recovery reason codes do not match projection")
        if self.observation.observed_at != self.observed_at:
            raise ValueError("observation timestamp does not match projection")
        if self.decision.decided_at != self.decided_at:
            raise ValueError("decision timestamp does not match projection")
        if not self.recorded_by.startswith("workload:"):
            raise ValueError("recovery observation recorder must be a workload")
        return self


class PostgresqlCdcRecoveryController:
    """Evaluate slot continuity without mutating SourceSync state."""

    @staticmethod
    def evaluate(
        observation: PostgresqlCdcSlotContinuityObservation,
        *,
        decided_by: str = "workload:gda-postgresql-cdc-recovery-controller",
        decided_at: datetime | None = None,
    ) -> PostgresqlCdcRecoveryDecision:
        reasons: list[str] = []
        original = observation.original_incarnation
        current = observation.current_incarnation
        if observation.absence_witnessed:
            reasons.append("replication_slot_absence_witnessed")
        if current is None:
            if observation.absence_witnessed:
                reasons.append("replication_slot_current_observation_missing")
            else:
                reasons.append("replication_slot_continuity_evidence_incomplete")
        else:
            identity_fields = (
                "system_identifier",
                "database_identity",
                "slot_name",
                "plugin",
                "slot_type",
            )
            if any(getattr(original, key) != getattr(current, key) for key in identity_fields):
                reasons.append("replication_slot_identity_changed")
            if original.incarnation_fingerprint != current.incarnation_fingerprint:
                reasons.append("replication_slot_incarnation_changed")

        if not reasons:
            disposition = "resume_cdc"
            checkpoint_action = "preserve_and_resume"
            requires_new_run = False
        elif observation.absence_witnessed:
            disposition = "schedule_resnapshot"
            checkpoint_action = "preserve_and_resnapshot"
            requires_new_run = True
        else:
            disposition = "rejected_fail_closed"
            checkpoint_action = "preserve_and_stop"
            requires_new_run = False

        timestamp = _aware_utc(decided_at or datetime.now(UTC))
        ordered_reasons = tuple(sorted(set(reasons)))
        decision_sha256 = canonical_json_fingerprint(
            {
                "schema": "gda.postgresql_cdc_recovery_controller_decision.v1",
                "tenant_id": observation.tenant_id,
                "sync_definition_version_id": str(
                    observation.sync_definition_version_id
                ),
                "observation_sha256": observation.observation_sha256,
                "disposition": disposition,
                "reason_codes": list(ordered_reasons),
                "checkpoint_action": checkpoint_action,
                "requires_new_run": requires_new_run,
                "decided_by": decided_by,
                "decided_at": timestamp.isoformat().replace("+00:00", "Z"),
            }
        )
        return PostgresqlCdcRecoveryDecision(
            schema="gda.postgresql_cdc_recovery_controller_decision.v1",
            tenant_id=observation.tenant_id,
            sync_definition_version_id=observation.sync_definition_version_id,
            observation_sha256=observation.observation_sha256,
            disposition=disposition,
            reason_codes=ordered_reasons,
            checkpoint_action=checkpoint_action,
            requires_new_run=requires_new_run,
            decided_by=decided_by,
            decided_at=timestamp,
            decision_sha256=decision_sha256,
        )


@dataclass(frozen=True)
class RecoveryControllerEvidenceWrite:
    """Gateway write result normalized for controller callers."""

    artifact: Artifact
    created: bool
    ledger_created: bool = False


class PostgresqlCdcRecoveryControllerRuntime:
    """Runtime facade for controller evaluation and evidence persistence."""

    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway

    def evaluate(
        self,
        observation: PostgresqlCdcSlotContinuityObservation,
        *,
        decided_by: str = "workload:gda-postgresql-cdc-recovery-controller",
        decided_at: datetime | None = None,
    ) -> PostgresqlCdcRecoveryDecision:
        return PostgresqlCdcRecoveryController.evaluate(
            observation,
            decided_by=decided_by,
            decided_at=decided_at,
        )

    def record_evidence(
        self,
        observation: PostgresqlCdcSlotContinuityObservation,
        decision: PostgresqlCdcRecoveryDecision,
        *,
        recovery_plan_sha256: str,
        run_id: UUID,
    ) -> RecoveryControllerEvidenceWrite:
        artifact = build_postgresql_cdc_recovery_controller_artifact(
            observation,
            decision,
            recovery_plan_sha256=recovery_plan_sha256,
            run_id=run_id,
        )
        durable_writer = getattr(
            self.gateway, "record_postgresql_cdc_recovery_observation", None
        )
        if callable(durable_writer):
            write = durable_writer(
                artifact,
                recovery_plan_sha256=recovery_plan_sha256,
                observation=observation,
                decision=decision,
            )
            stored = getattr(write, "artifact", artifact)
            if stored != artifact:
                raise ValueError(
                    "recovery controller durable write returned a different artifact"
                )
            artifact_created = bool(getattr(write, "artifact_created", False))
            ledger_created = bool(getattr(write, "ledger_created", False))
            return RecoveryControllerEvidenceWrite(
                artifact=artifact,
                created=artifact_created or ledger_created,
                ledger_created=ledger_created,
            )
        write = self.gateway.record_artifact(artifact)
        stored = getattr(write, "value", artifact)
        if stored != artifact:
            raise ValueError("recovery controller evidence write returned a different artifact")
        return RecoveryControllerEvidenceWrite(
            artifact=artifact,
            created=bool(getattr(write, "created", True)),
        )
