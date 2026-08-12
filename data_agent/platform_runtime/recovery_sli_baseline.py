"""Versioned, observation-only SLI baselines for recovery rehearsals."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .deployment_profile import SHA256_RE, DeploymentProfile
from .recovery_rehearsal import (
    RECOVERY_LIMITATIONS,
    REPORT_SCHEMA,
    database_logical_identity,
)

BASELINE_SCHEMA = "gis-data-agent.recovery-sli-baseline.v1"
VERIFICATION_SCHEMA = "gis-data-agent.recovery-sli-baseline-verification.v1"
RECOVERY_SCOPE = "compose_isolated_logical_recovery"
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
REQUIRED_PROMOTION_BLOCKERS = tuple(
    dict.fromkeys(("slo", "backup_restore", *RECOVERY_LIMITATIONS))
)
SENSITIVE_REPORT_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "access_key",
    "private_key",
    "credential",
    "object_key",
    "host_path",
    "sample_value",
)
FORBIDDEN_REPORT_KEYS = {"key", "keys", "path", "paths", "sample", "samples"}
HOST_PATH_RE = re.compile(r"^(?:/Users/|/home/|/private/|/tmp/|[A-Za-z]:[\\/])")


class RecoverySLIBaselineError(ValueError):
    """A recovery report cannot support the requested observation baseline."""

    def __init__(self, stage: str):
        super().__init__(f"recovery SLI baseline failed at {stage}")
        self.stage = stage


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RecoveryTimingObservation(StrictModel):
    database_backup_seconds: float = Field(gt=0)
    database_restore_seconds: float = Field(gt=0)
    object_rehearsal_seconds: float = Field(gt=0)
    end_to_end_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_end_to_end_duration(self) -> RecoveryTimingObservation:
        stage_total = (
            self.database_backup_seconds
            + self.database_restore_seconds
            + self.object_rehearsal_seconds
        )
        if self.end_to_end_seconds < stage_total:
            raise ValueError("end-to-end duration cannot be shorter than measured stages")
        return self


class DatabaseRecoveryObservation(StrictModel):
    source_database_bytes: int = Field(gt=0)
    dump_bytes: int = Field(gt=0)
    logical_identity_sha256: str

    @field_validator("logical_identity_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("database identity must be a lowercase SHA-256")
        return value


class ObjectRecoveryObservation(StrictModel):
    bucket_count: int = Field(gt=0)
    object_count: int = Field(ge=0)
    bytes: int = Field(ge=0)
    logical_identity_sha256: str

    @field_validator("logical_identity_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("object identity must be a lowercase SHA-256")
        return value


class RecoverySLIObservation(StrictModel):
    sample_count: Literal[1]
    observed_at: datetime
    scope: Literal[RECOVERY_SCOPE]
    report_schema: Literal[REPORT_SCHEMA]
    report_evidence_sha256: str
    compose_config_sha256: str
    timings: RecoveryTimingObservation
    database: DatabaseRecoveryObservation
    object_storage: ObjectRecoveryObservation

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @field_validator("report_evidence_sha256", "compose_config_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("evidence identities must be lowercase SHA-256 values")
        return value


class RecoverySLIGovernance(StrictModel):
    interpretation: Literal["single_observation_not_objective"]
    sli_status: Literal["observed_not_approved"]
    slo_status: Literal["not_approved"]
    rpo_status: Literal["not_defined"]
    rto_status: Literal["not_approved"]
    promotion_ready: Literal[False]
    promotion_blockers: tuple[str, ...]

    @model_validator(mode="after")
    def validate_fail_closed_governance(self) -> RecoverySLIGovernance:
        if len(set(self.promotion_blockers)) != len(self.promotion_blockers):
            raise ValueError("promotion blockers must be unique")
        missing = set(REQUIRED_PROMOTION_BLOCKERS) - set(self.promotion_blockers)
        if missing:
            raise ValueError("recovery baseline is missing required promotion blockers")
        return self


class RecoverySLIBaseline(StrictModel):
    schema_name: Literal[BASELINE_SCHEMA] = Field(alias="schema")
    baseline_id: str
    profile_id: str
    environment: Literal["dev", "test", "staging", "production", "customer"]
    observation: RecoverySLIObservation
    governance: RecoverySLIGovernance

    @field_validator("baseline_id", "profile_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("baseline/profile IDs must be lowercase identifiers")
        return value


@dataclass(frozen=True)
class RecoverySLIVerificationReport:
    baseline_id: str
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
            "baseline_id": self.baseline_id,
            "profile_id": self.profile_id,
            "technical_pass": self.technical_pass,
            "promotion_ready": False,
            "sli_status": "observed_not_approved",
            "checks": dict(self.checks),
            "promotion_blockers": list(self.promotion_blockers),
        }


def canonical_json_sha256(value: Any) -> str:
    """Hash JSON semantics independently of whitespace and object key order."""
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def build_recovery_sli_baseline(
    *,
    baseline_id: str,
    profile: DeploymentProfile,
    report: dict[str, Any],
) -> RecoverySLIBaseline:
    """Build one fail-closed SLI observation from a successful recovery report."""
    _validate_report_envelope(profile, report)
    database = _mapping(report, "database")
    source = _mapping(database, "source")
    restored = _mapping(database, "restored")
    if database_logical_identity(source) != database_logical_identity(restored):
        raise RecoverySLIBaselineError("database.logical_identity")
    _validate_database_profile_identity(profile, source)

    object_storage = _mapping(report, "object_storage")
    buckets = object_storage.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        raise RecoverySLIBaselineError("object_storage.buckets")
    object_identities: list[dict[str, Any]] = []
    bucket_names: set[str] = set()
    object_count = 0
    object_bytes = 0
    for entry in buckets:
        if not isinstance(entry, dict):
            raise RecoverySLIBaselineError("object_storage.bucket_shape")
        bucket = entry.get("bucket")
        source_facts = entry.get("source")
        restored_facts = entry.get("restored")
        if (
            not isinstance(bucket, str)
            or not bucket
            or bucket in bucket_names
            or not isinstance(source_facts, dict)
            or source_facts != restored_facts
        ):
            raise RecoverySLIBaselineError("object_storage.logical_identity")
        count = _non_negative_int(source_facts, "object_count")
        size = _non_negative_int(source_facts, "bytes")
        inventory_sha256 = source_facts.get("inventory_sha256")
        if not isinstance(inventory_sha256, str) or not SHA256_RE.fullmatch(
            inventory_sha256
        ):
            raise RecoverySLIBaselineError("object_storage.inventory_identity")
        bucket_names.add(bucket)
        object_count += count
        object_bytes += size
        object_identities.append({"bucket": bucket, "facts": source_facts})

    blockers = report.get("promotion_blockers")
    if not isinstance(blockers, list) or any(
        not isinstance(item, str) or not item for item in blockers
    ):
        raise RecoverySLIBaselineError("governance.blockers")

    payload = {
        "schema": BASELINE_SCHEMA,
        "baseline_id": baseline_id,
        "profile_id": profile.profile_id,
        "environment": profile.environment,
        "observation": {
            "sample_count": 1,
            "observed_at": report.get("generated_at"),
            "scope": RECOVERY_SCOPE,
            "report_schema": REPORT_SCHEMA,
            "report_evidence_sha256": canonical_json_sha256(report),
            "compose_config_sha256": profile.compose.config_sha256,
            "timings": {
                "database_backup_seconds": _positive_number(
                    database, "backup_duration_seconds"
                ),
                "database_restore_seconds": _positive_number(
                    database, "restore_duration_seconds"
                ),
                "object_rehearsal_seconds": _positive_number(
                    object_storage, "rehearsal_duration_seconds"
                ),
                "end_to_end_seconds": _positive_number(
                    report, "observed_total_seconds"
                ),
            },
            "database": {
                "source_database_bytes": _positive_int(source, "database_bytes"),
                "dump_bytes": _positive_int(database, "dump_bytes"),
                "logical_identity_sha256": canonical_json_sha256(
                    database_logical_identity(source)
                ),
            },
            "object_storage": {
                "bucket_count": len(object_identities),
                "object_count": object_count,
                "bytes": object_bytes,
                "logical_identity_sha256": canonical_json_sha256(
                    sorted(object_identities, key=lambda item: item["bucket"])
                ),
            },
        },
        "governance": {
            "interpretation": "single_observation_not_objective",
            "sli_status": "observed_not_approved",
            "slo_status": "not_approved",
            "rpo_status": "not_defined",
            "rto_status": "not_approved",
            "promotion_ready": False,
            "promotion_blockers": blockers,
        },
    }
    return RecoverySLIBaseline.model_validate(payload)


def verify_recovery_sli_baseline(
    *,
    baseline: RecoverySLIBaseline,
    profile: DeploymentProfile,
    report: dict[str, Any] | None,
) -> RecoverySLIVerificationReport:
    """Verify profile identity and, when supplied, the complete source evidence."""
    profile_blockers = set(profile.governance.promotion_blockers)
    checks = {
        "profile_identity": baseline.profile_id == profile.profile_id
        and baseline.environment == profile.environment,
        "compose_config_identity": (
            baseline.observation.compose_config_sha256
            == profile.compose.config_sha256
        ),
        "profile_governance_bound": profile_blockers.issubset(
            baseline.governance.promotion_blockers
        ),
        "report_evidence_identity": False,
        "observation_reproducible": False,
    }
    if report is not None:
        checks["report_evidence_identity"] = (
            canonical_json_sha256(report)
            == baseline.observation.report_evidence_sha256
        )
        try:
            expected = build_recovery_sli_baseline(
                baseline_id=baseline.baseline_id,
                profile=profile,
                report=report,
            )
        except (RecoverySLIBaselineError, TypeError, ValueError):
            pass
        else:
            checks["observation_reproducible"] = expected == baseline
    return RecoverySLIVerificationReport(
        baseline_id=baseline.baseline_id,
        profile_id=baseline.profile_id,
        checks=checks,
        promotion_blockers=baseline.governance.promotion_blockers,
    )


def load_recovery_sli_baseline(path: str | Path) -> RecoverySLIBaseline:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return RecoverySLIBaseline.model_validate(payload)


def _validate_report_envelope(
    profile: DeploymentProfile, report: dict[str, Any]
) -> None:
    reject_sensitive_report_evidence(report)
    expected = {
        "schema": REPORT_SCHEMA,
        "profile_id": profile.profile_id,
        "environment": profile.environment,
        "scope": RECOVERY_SCOPE,
        "technical_pass": True,
        "promotion_ready": False,
        "slo_status": "observed_not_approved",
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise RecoverySLIBaselineError("report.envelope")
    deployment = _mapping(report, "deployment")
    if (
        deployment.get("technical_pass") is not True
        or deployment.get("profile_contamination") is not False
    ):
        raise RecoverySLIBaselineError("report.deployment")
    blockers = report.get("promotion_blockers")
    required = set(profile.governance.promotion_blockers) | set(
        REQUIRED_PROMOTION_BLOCKERS
    )
    if not isinstance(blockers, list) or not required.issubset(blockers):
        raise RecoverySLIBaselineError("report.governance")


def _validate_database_profile_identity(
    profile: DeploymentProfile, source: dict[str, Any]
) -> None:
    standard = source.get("standard")
    expected_standard = profile.released_standard
    if (
        source.get("migration_count") != profile.migrations.count
        or source.get("migration_fingerprint") != profile.migrations.fingerprint
        or standard
        != {
            "doc_code": expected_standard.doc_code,
            "version_label": expected_standard.version_label,
            "status": "released",
            "element_count": expected_standard.element_count,
            "elements_sha256": expected_standard.elements_sha256,
        }
    ):
        raise RecoverySLIBaselineError("database.profile_identity")


def reject_sensitive_report_evidence(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_REPORT_KEYS or any(
                part in normalized for part in SENSITIVE_REPORT_KEY_PARTS
            ):
                raise RecoverySLIBaselineError("report.sensitive_evidence")
            reject_sensitive_report_evidence(item)
        return
    if isinstance(value, list):
        for item in value:
            reject_sensitive_report_evidence(item)
        return
    if isinstance(value, str) and HOST_PATH_RE.match(value):
        raise RecoverySLIBaselineError("report.sensitive_evidence")


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise RecoverySLIBaselineError(f"report.{key}")
    return item


def _positive_number(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or item <= 0:
        raise RecoverySLIBaselineError(f"report.{key}")
    return float(item)


def _positive_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
        raise RecoverySLIBaselineError(f"report.{key}")
    return item


def _non_negative_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise RecoverySLIBaselineError(f"report.{key}")
    return item
