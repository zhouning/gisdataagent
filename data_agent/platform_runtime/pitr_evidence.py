"""Strict, versioned evidence seals for bounded streamed-WAL PITR rehearsals."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .deployment_profile import SHA256_RE, DeploymentProfile
from .pitr_rehearsal import PITR_LIMITATIONS, PITR_SCOPE, REPORT_SCHEMA
from .recovery_rehearsal import database_logical_identity
from .recovery_sli_baseline import (
    canonical_json_sha256,
    reject_sensitive_report_evidence,
)

SEAL_SCHEMA = "gis-data-agent.pitr-evidence-seal.v1"
VERIFICATION_SCHEMA = "gis-data-agent.pitr-evidence-verification.v1"
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class PITREvidenceError(ValueError):
    def __init__(self, stage: str):
        super().__init__(f"PITR evidence failed at {stage}")
        self.stage = stage


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PhysicalBackupObservation(StrictModel):
    bytes: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    manifest_verification_seconds: float = Field(gt=0)
    manifest_sha256: str

    @field_validator("manifest_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("manifest identity must be a lowercase SHA-256")
        return value


class WALObservation(StrictModel):
    bytes: int = Field(gt=0)
    complete_segment_count: int = Field(gt=0)
    partial_segment_count: int = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    target_to_later_seconds: float = Field(gt=0)
    inventory_sha256: str

    @field_validator("inventory_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("WAL identity must be a lowercase SHA-256")
        return value


class PITRObservation(StrictModel):
    sample_count: Literal[1]
    observed_at: datetime
    report_schema: Literal[REPORT_SCHEMA]
    report_evidence_sha256: str
    compose_config_sha256: str
    source_archive_mode: Literal["off", "on", "always"]
    source_wal_level: Literal["replica", "logical"]
    source_database_bytes: int = Field(gt=0)
    database_logical_identity_sha256: str
    physical_backup: PhysicalBackupObservation
    wal_stream: WALObservation
    target_recovery_seconds: float = Field(gt=0)
    end_to_end_seconds: float = Field(gt=0)

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @field_validator(
        "report_evidence_sha256",
        "compose_config_sha256",
        "database_logical_identity_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("evidence identities must be lowercase SHA-256 values")
        return value

    @model_validator(mode="after")
    def validate_total_duration(self) -> PITRObservation:
        measured = (
            self.physical_backup.duration_seconds
            + self.physical_backup.manifest_verification_seconds
            + self.wal_stream.duration_seconds
            + self.target_recovery_seconds
        )
        if self.end_to_end_seconds < measured:
            raise ValueError("end-to-end duration cannot be shorter than measured stages")
        return self


class PITRProof(StrictModel):
    manifest_verified: Literal[True]
    target_after_base_backup: Literal[True]
    target_lsn_observed: Literal[True]
    later_lsn_observed: Literal[True]
    source_later_state_observed: Literal[True]
    restored_target_state_observed: Literal[True]
    later_state_excluded: Literal[True]
    promoted: Literal[True]
    network_isolated: Literal[True]
    database_logical_identity_equal: Literal[True]
    probe_database_removed: Literal[True]
    replication_slot_removed: Literal[True]
    temporary_containers_removed: Literal[True]
    temporary_media_retained: Literal[False]
    continuous_archive_configured: Literal[False]


class PITRGovernance(StrictModel):
    interpretation: Literal["bounded_streamed_wal_observation_not_continuous_pitr_slo"]
    rpo_status: Literal["not_defined"]
    rto_status: Literal["not_approved"]
    promotion_ready: Literal[False]
    promotion_blockers: tuple[str, ...]

    @model_validator(mode="after")
    def validate_blockers(self) -> PITRGovernance:
        if len(set(self.promotion_blockers)) != len(self.promotion_blockers):
            raise ValueError("promotion blockers must be unique")
        if not set(PITR_LIMITATIONS).issubset(self.promotion_blockers):
            raise ValueError("PITR evidence is missing required promotion blockers")
        return self


class PITREvidenceSeal(StrictModel):
    schema_name: Literal[SEAL_SCHEMA] = Field(alias="schema")
    seal_id: str
    profile_id: str
    environment: Literal["dev", "test", "staging", "production", "customer"]
    scope: Literal[PITR_SCOPE]
    observation: PITRObservation
    proof: PITRProof
    governance: PITRGovernance

    @field_validator("seal_id", "profile_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("seal/profile IDs must be lowercase identifiers")
        return value


@dataclass(frozen=True)
class PITREvidenceVerification:
    seal_id: str
    profile_id: str
    checks: dict[str, bool]
    promotion_blockers: tuple[str, ...]

    @property
    def technical_pass(self) -> bool:
        return all(self.checks.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": VERIFICATION_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "seal_id": self.seal_id,
            "profile_id": self.profile_id,
            "technical_pass": self.technical_pass,
            "promotion_ready": False,
            "rpo_status": "not_defined",
            "rto_status": "not_approved",
            "checks": dict(self.checks),
            "promotion_blockers": list(self.promotion_blockers),
        }


def build_pitr_evidence_seal(
    *, seal_id: str, profile: DeploymentProfile, report: dict[str, Any]
) -> PITREvidenceSeal:
    reject_sensitive_report_evidence(report)
    _validate_envelope(profile, report)
    deployment = _mapping(report, "deployment")
    if (
        deployment.get("technical_pass") is not True
        or deployment.get("profile_contamination") is not False
    ):
        raise PITREvidenceError("deployment")

    source_capability = _mapping(report, "source_capability")
    if (
        source_capability.get("wal_level") not in {"replica", "logical"}
        or source_capability.get("in_recovery") is not False
        or _positive_int(source_capability, "max_wal_senders") < 2
        or _positive_int(source_capability, "max_replication_slots") < 1
    ):
        raise PITREvidenceError("source_capability")

    physical = _mapping(report, "physical_backup")
    wal = _mapping(report, "wal_stream")
    recovery = _mapping(report, "target_recovery")
    cleanup = _mapping(report, "cleanup")
    database = _mapping(report, "database")
    source = _mapping(database, "source")
    restored = _mapping(database, "restored")
    if database_logical_identity(source) != database_logical_identity(restored):
        raise PITREvidenceError("database.logical_identity")
    _validate_database_profile_identity(profile, source)

    target_time = _aware_datetime(wal, "target_timestamp")
    later_time = _aware_datetime(wal, "later_timestamp")
    if target_time >= later_time:
        raise PITREvidenceError("wal.timeline")

    proof = {
        "manifest_verified": physical.get("manifest_verified"),
        "target_after_base_backup": wal.get("target_after_base_backup"),
        "target_lsn_observed": wal.get("target_lsn_observed"),
        "later_lsn_observed": wal.get("later_lsn_observed"),
        "source_later_state_observed": wal.get("source_later_state_observed"),
        "restored_target_state_observed": recovery.get(
            "restored_target_state_observed"
        ),
        "later_state_excluded": recovery.get("later_state_excluded"),
        "promoted": recovery.get("promoted"),
        "network_isolated": recovery.get("network_isolated"),
        "database_logical_identity_equal": True,
        "probe_database_removed": cleanup.get("probe_database_removed"),
        "replication_slot_removed": cleanup.get("replication_slot_removed"),
        "temporary_containers_removed": cleanup.get(
            "temporary_containers_removed"
        ),
        "temporary_media_retained": cleanup.get("temporary_media_retained"),
        "continuous_archive_configured": wal.get(
            "continuous_archive_configured"
        ),
    }
    if physical.get("artifact_retained") is not False:
        raise PITREvidenceError("backup.retention")

    payload = {
        "schema": SEAL_SCHEMA,
        "seal_id": seal_id,
        "profile_id": profile.profile_id,
        "environment": profile.environment,
        "scope": PITR_SCOPE,
        "observation": {
            "sample_count": 1,
            "observed_at": report.get("generated_at"),
            "report_schema": REPORT_SCHEMA,
            "report_evidence_sha256": canonical_json_sha256(report),
            "compose_config_sha256": profile.compose.config_sha256,
            "source_archive_mode": source_capability.get("archive_mode"),
            "source_wal_level": source_capability.get("wal_level"),
            "source_database_bytes": _positive_int(source, "database_bytes"),
            "database_logical_identity_sha256": canonical_json_sha256(
                database_logical_identity(source)
            ),
            "physical_backup": {
                "bytes": _positive_int(physical, "bytes"),
                "duration_seconds": _positive_number(physical, "duration_seconds"),
                "manifest_verification_seconds": _positive_number(
                    physical, "manifest_verification_seconds"
                ),
                "manifest_sha256": _sha256(physical, "manifest_sha256"),
            },
            "wal_stream": {
                "bytes": _positive_int(wal, "bytes"),
                "complete_segment_count": _positive_int(
                    wal, "complete_segment_count"
                ),
                "partial_segment_count": _non_negative_int(
                    wal, "partial_segment_count"
                ),
                "duration_seconds": _positive_number(wal, "duration_seconds"),
                "target_to_later_seconds": round(
                    (later_time - target_time).total_seconds(), 6
                ),
                "inventory_sha256": _sha256(wal, "inventory_sha256"),
            },
            "target_recovery_seconds": _positive_number(
                recovery, "duration_seconds"
            ),
            "end_to_end_seconds": _positive_number(
                report, "observed_total_seconds"
            ),
        },
        "proof": proof,
        "governance": {
            "interpretation": (
                "bounded_streamed_wal_observation_not_continuous_pitr_slo"
            ),
            "rpo_status": report.get("rpo_status"),
            "rto_status": report.get("rto_status"),
            "promotion_ready": False,
            "promotion_blockers": report.get("promotion_blockers"),
        },
    }
    return PITREvidenceSeal.model_validate(payload)


def verify_pitr_evidence(
    *,
    seal: PITREvidenceSeal,
    profile: DeploymentProfile,
    report: dict[str, Any] | None,
) -> PITREvidenceVerification:
    profile_blockers = set(profile.governance.promotion_blockers)
    checks = {
        "profile_identity": seal.profile_id == profile.profile_id
        and seal.environment == profile.environment,
        "compose_config_identity": (
            seal.observation.compose_config_sha256 == profile.compose.config_sha256
        ),
        "profile_governance_bound": profile_blockers.issubset(
            seal.governance.promotion_blockers
        ),
        "report_evidence_identity": False,
        "evidence_reproducible": False,
    }
    if report is not None:
        checks["report_evidence_identity"] = (
            canonical_json_sha256(report)
            == seal.observation.report_evidence_sha256
        )
        try:
            expected = build_pitr_evidence_seal(
                seal_id=seal.seal_id,
                profile=profile,
                report=report,
            )
        except (PITREvidenceError, TypeError, ValueError):
            pass
        else:
            checks["evidence_reproducible"] = expected == seal
    return PITREvidenceVerification(
        seal_id=seal.seal_id,
        profile_id=seal.profile_id,
        checks=checks,
        promotion_blockers=seal.governance.promotion_blockers,
    )


def load_pitr_evidence_seal(path: str | Path) -> PITREvidenceSeal:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return PITREvidenceSeal.model_validate(payload)


def _validate_envelope(
    profile: DeploymentProfile, report: dict[str, Any]
) -> None:
    expected = {
        "schema": REPORT_SCHEMA,
        "profile_id": profile.profile_id,
        "environment": profile.environment,
        "scope": PITR_SCOPE,
        "technical_pass": True,
        "promotion_ready": False,
        "rpo_status": "not_defined",
        "rto_status": "not_approved",
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise PITREvidenceError("envelope")
    blockers = report.get("promotion_blockers")
    required = set(profile.governance.promotion_blockers) | set(PITR_LIMITATIONS)
    if not isinstance(blockers, list) or not required.issubset(blockers):
        raise PITREvidenceError("governance")


def _validate_database_profile_identity(
    profile: DeploymentProfile, source: dict[str, Any]
) -> None:
    standard = source.get("standard")
    expected = profile.released_standard
    if (
        source.get("migration_count") != profile.migrations.count
        or source.get("migration_fingerprint") != profile.migrations.fingerprint
        or standard
        != {
            "doc_code": expected.doc_code,
            "version_label": expected.version_label,
            "status": "released",
            "element_count": expected.element_count,
            "elements_sha256": expected.elements_sha256,
        }
    ):
        raise PITREvidenceError("database.profile_identity")


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise PITREvidenceError(f"report.{key}")
    return item


def _aware_datetime(value: dict[str, Any], key: str) -> datetime:
    item = value.get(key)
    if not isinstance(item, str):
        raise PITREvidenceError(f"report.{key}")
    try:
        result = datetime.fromisoformat(item)
    except ValueError as exc:
        raise PITREvidenceError(f"report.{key}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PITREvidenceError(f"report.{key}")
    return result.astimezone(UTC)


def _positive_number(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or item <= 0:
        raise PITREvidenceError(f"report.{key}")
    return float(item)


def _positive_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
        raise PITREvidenceError(f"report.{key}")
    return item


def _non_negative_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise PITREvidenceError(f"report.{key}")
    return item


def _sha256(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not SHA256_RE.fullmatch(item):
        raise PITREvidenceError(f"report.{key}")
    return item
