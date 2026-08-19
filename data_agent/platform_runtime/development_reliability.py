"""Development-only reliability, percentile, capacity, and compatibility contracts.

The contract combines existing backup/PITR evidence references with fresh
measurement samples. It deliberately remains observation-only: no SLO,
RPO/RTO, production promotion, or compatibility certification is inferred.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .deployment_profile import SHA256_RE, DeploymentProfile
from .recovery_sli_baseline import canonical_json_sha256

RELIABILITY_SCHEMA = "gis-data-agent.development-reliability-baseline.v1"
VERIFICATION_SCHEMA = "gis-data-agent.development-reliability-verification.v1"
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class DevelopmentReliabilityError(ValueError):
    """A development reliability baseline cannot be sealed safely."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DevelopmentReliabilityError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_sha256({"schema": schema, "data": _json_ready(payload)})


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return _utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _percentile(samples: Sequence[float], percentile: float) -> float:
    if not samples:
        raise DevelopmentReliabilityError("percentile requires at least one sample")
    ordered = sorted(float(value) for value in samples)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(ordered[rank - 1], 6)


class ReliabilityEvidenceKind(StrEnum):
    BACKUP = "backup"
    PITR = "pitr"
    RECOVERY_SLI = "recovery_sli"


class ReliabilityEvidenceReference(StrictModel):
    schema_id: ClassVar[str] = "gda.development-reliability-evidence-ref.v1"
    kind: ReliabilityEvidenceKind
    evidence_sha256: str
    profile_id: str
    compose_config_sha256: str
    technical_pass: Literal[True]
    observed_at: datetime
    reference_sha256: str

    @field_validator("evidence_sha256", "compose_config_sha256", "reference_sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("reliability evidence identity must be SHA-256")
        return value

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("reliability profile ID is invalid")
        return value

    @field_validator("observed_at")
    @classmethod
    def _observed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _sealed(self) -> ReliabilityEvidenceReference:
        values = self.model_dump(mode="json", exclude={"reference_sha256"})
        expected = _fingerprint(self.schema_id, values, "reference_sha256")
        if self.reference_sha256 != expected:
            raise ValueError("reliability evidence reference fingerprint is invalid")
        return self


def build_evidence_reference(
    *,
    kind: ReliabilityEvidenceKind,
    evidence_sha256: str,
    profile_id: str,
    compose_config_sha256: str,
    observed_at: datetime,
) -> ReliabilityEvidenceReference:
    values = {
        "kind": kind,
        "evidence_sha256": evidence_sha256,
        "profile_id": profile_id,
        "compose_config_sha256": compose_config_sha256,
        "technical_pass": True,
        "observed_at": _utc(observed_at),
    }
    return ReliabilityEvidenceReference(
        **values,
        reference_sha256=_fingerprint(
            ReliabilityEvidenceReference.schema_id,
            values,
            "reference_sha256",
        ),
    )


class LatencyObservation(StrictModel):
    schema_id: ClassVar[str] = "gda.development-reliability-latency.v1"
    operation: str
    sample_count: int = Field(ge=5, le=100_000)
    samples_ms: tuple[float, ...] = Field(min_length=5, max_length=100_000)
    p50_ms: float = Field(gt=0)
    p95_ms: float = Field(gt=0)
    p99_ms: float = Field(gt=0)
    observed_at: datetime
    observation_sha256: str

    @field_validator("operation")
    @classmethod
    def _operation(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("latency operation must be a lowercase identifier")
        return value

    @field_validator("observed_at")
    @classmethod
    def _observed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("samples_ms")
    @classmethod
    def _positive_samples(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(sample <= 0 for sample in value):
            raise ValueError("latency samples must be positive")
        return value

    @model_validator(mode="after")
    def _sealed(self) -> LatencyObservation:
        if self.sample_count != len(self.samples_ms):
            raise ValueError("latency sample_count does not match samples_ms")
        expected = {
            "p50_ms": _percentile(self.samples_ms, 0.50),
            "p95_ms": _percentile(self.samples_ms, 0.95),
            "p99_ms": _percentile(self.samples_ms, 0.99),
        }
        if any(getattr(self, key) != value for key, value in expected.items()):
            raise ValueError("latency percentile values are not reproducible")
        values = self.model_dump(mode="json", exclude={"observation_sha256"})
        if self.observation_sha256 != _fingerprint(self.schema_id, values, "observation_sha256"):
            raise ValueError("latency observation fingerprint is invalid")
        return self


def build_latency_observation(
    *,
    operation: str,
    samples_ms: Sequence[float],
    observed_at: datetime,
) -> LatencyObservation:
    if len(samples_ms) < 5:
        raise DevelopmentReliabilityError("latency requires at least five samples")
    values = {
        "operation": operation,
        "sample_count": len(samples_ms),
        "samples_ms": tuple(float(value) for value in samples_ms),
        "p50_ms": _percentile(samples_ms, 0.50),
        "p95_ms": _percentile(samples_ms, 0.95),
        "p99_ms": _percentile(samples_ms, 0.99),
        "observed_at": _utc(observed_at),
    }
    return LatencyObservation(
        **values,
        observation_sha256=_fingerprint(
            LatencyObservation.schema_id,
            values,
            "observation_sha256",
        ),
    )


class CapacityObservation(StrictModel):
    schema_id: ClassVar[str] = "gda.development-reliability-capacity.v1"
    operation: str
    concurrency: int = Field(ge=1, le=100_000)
    duration_seconds: float = Field(gt=0)
    completed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    max_queue_depth: int = Field(ge=0)
    throughput_per_second: float = Field(ge=0)
    error_rate: float = Field(ge=0, le=1)
    observed_at: datetime
    observation_sha256: str

    @field_validator("operation")
    @classmethod
    def _operation(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("capacity operation must be a lowercase identifier")
        return value

    @field_validator("observed_at")
    @classmethod
    def _observed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _sealed(self) -> CapacityObservation:
        total = self.completed_count + self.failed_count
        if total == 0:
            raise ValueError("capacity observation requires at least one request")
        expected_throughput = round(self.completed_count / self.duration_seconds, 6)
        expected_error_rate = round((self.failed_count / total) if total else 0, 6)
        if self.throughput_per_second != expected_throughput:
            raise ValueError("capacity throughput is not reproducible")
        if self.error_rate != expected_error_rate:
            raise ValueError("capacity error rate is not reproducible")
        values = self.model_dump(mode="json", exclude={"observation_sha256"})
        if self.observation_sha256 != _fingerprint(self.schema_id, values, "observation_sha256"):
            raise ValueError("capacity observation fingerprint is invalid")
        return self


def build_capacity_observation(
    *,
    operation: str,
    concurrency: int,
    duration_seconds: float,
    completed_count: int,
    failed_count: int,
    max_queue_depth: int,
    observed_at: datetime,
) -> CapacityObservation:
    total = completed_count + failed_count
    values = {
        "operation": operation,
        "concurrency": concurrency,
        "duration_seconds": float(duration_seconds),
        "completed_count": completed_count,
        "failed_count": failed_count,
        "max_queue_depth": max_queue_depth,
        "throughput_per_second": round(completed_count / duration_seconds, 6),
        "error_rate": round((failed_count / total) if total else 0, 6),
        "observed_at": _utc(observed_at),
    }
    return CapacityObservation(
        **values,
        observation_sha256=_fingerprint(
            CapacityObservation.schema_id,
            values,
            "observation_sha256",
        ),
    )


class ReliabilitySLOThresholds(StrictModel):
    schema_id: ClassVar[str] = "gda.development-reliability-slo-thresholds.v1"
    operation: str
    max_p95_ms: float = Field(gt=0)
    max_p99_ms: float = Field(gt=0)
    min_throughput_per_second: float = Field(ge=0)
    max_error_rate: float = Field(ge=0, le=1)
    thresholds_sha256: str

    @field_validator("operation")
    @classmethod
    def _operation(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("SLO operation must be a lowercase identifier")
        return value

    @model_validator(mode="after")
    def _sealed(self) -> ReliabilitySLOThresholds:
        if self.max_p99_ms < self.max_p95_ms:
            raise ValueError("SLO p99 threshold cannot be lower than p95")
        values = self.model_dump(mode="json", exclude={"thresholds_sha256"})
        if self.thresholds_sha256 != _fingerprint(self.schema_id, values, "thresholds_sha256"):
            raise ValueError("SLO thresholds fingerprint is invalid")
        return self


def build_slo_thresholds(
    *,
    operation: str,
    max_p95_ms: float,
    max_p99_ms: float,
    min_throughput_per_second: float,
    max_error_rate: float,
) -> ReliabilitySLOThresholds:
    values = {
        "operation": operation,
        "max_p95_ms": float(max_p95_ms),
        "max_p99_ms": float(max_p99_ms),
        "min_throughput_per_second": float(min_throughput_per_second),
        "max_error_rate": float(max_error_rate),
    }
    return ReliabilitySLOThresholds(
        **values,
        thresholds_sha256=_fingerprint(
            ReliabilitySLOThresholds.schema_id,
            values,
            "thresholds_sha256",
        ),
    )


class CompatibilityStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNTESTED = "untested"


class CompatibilityCase(StrictModel):
    schema_id: ClassVar[str] = "gda.development-reliability-compatibility-case.v1"
    cpu: str
    os: str
    database: str
    middleware: str
    model_service: str
    status: CompatibilityStatus
    evidence_sha256: str | None = None
    case_sha256: str

    @field_validator("cpu", "os", "database", "middleware", "model_service")
    @classmethod
    def _component(cls, value: str) -> str:
        lowered = value.casefold()
        if (
            not value
            or any(char in value for char in "\n\r\t")
            or "/" in value
            or "\\" in value
            or any(token in lowered for token in ("password", "secret", "token", "key="))
        ):
            raise ValueError("compatibility component must be a single non-empty label")
        return value

    @field_validator("evidence_sha256")
    @classmethod
    def _evidence_sha256(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_RE.fullmatch(value):
            raise ValueError("compatibility evidence identity must be SHA-256")
        return value

    @model_validator(mode="after")
    def _sealed(self) -> CompatibilityCase:
        if self.status is CompatibilityStatus.PASSED and self.evidence_sha256 is None:
            raise ValueError("passed compatibility case requires evidence")
        if self.status is not CompatibilityStatus.PASSED and self.evidence_sha256 is not None:
            raise ValueError("only passed compatibility cases may bind evidence")
        values = self.model_dump(mode="json", exclude={"case_sha256"})
        if self.case_sha256 != _fingerprint(self.schema_id, values, "case_sha256"):
            raise ValueError("compatibility case fingerprint is invalid")
        return self


def build_compatibility_case(
    *,
    cpu: str,
    os: str,
    database: str,
    middleware: str,
    model_service: str,
    status: CompatibilityStatus,
    evidence_sha256: str | None = None,
) -> CompatibilityCase:
    values = {
        "cpu": cpu,
        "os": os,
        "database": database,
        "middleware": middleware,
        "model_service": model_service,
        "status": status,
        "evidence_sha256": evidence_sha256,
    }
    return CompatibilityCase(
        **values,
        case_sha256=_fingerprint(CompatibilityCase.schema_id, values, "case_sha256"),
    )


class ReliabilityCompatibilityMatrix(StrictModel):
    schema_id: ClassVar[str] = "gda.development-reliability-compatibility-matrix.v1"
    cases: tuple[CompatibilityCase, ...] = Field(min_length=1, max_length=256)
    matrix_sha256: str

    @model_validator(mode="after")
    def _sealed(self) -> ReliabilityCompatibilityMatrix:
        identities = tuple(
            (
                case.cpu,
                case.os,
                case.database,
                case.middleware,
                case.model_service,
            )
            for case in self.cases
        )
        if len(set(identities)) != len(identities):
            raise ValueError("compatibility matrix cases must be unique")
        values = {"cases": self.cases}
        if self.matrix_sha256 != _fingerprint(self.schema_id, values, "matrix_sha256"):
            raise ValueError("compatibility matrix fingerprint is invalid")
        return self


def build_compatibility_matrix(
    cases: Sequence[CompatibilityCase],
) -> ReliabilityCompatibilityMatrix:
    values = {"cases": tuple(cases)}
    return ReliabilityCompatibilityMatrix(
        **values,
        matrix_sha256=_fingerprint(
            ReliabilityCompatibilityMatrix.schema_id,
            values,
            "matrix_sha256",
        ),
    )


class DevelopmentReliabilityBaseline(StrictModel):
    schema_id: ClassVar[str] = RELIABILITY_SCHEMA
    baseline_id: str
    profile_id: str
    environment: Literal["dev", "test"]
    compose_config_sha256: str
    evidence: tuple[ReliabilityEvidenceReference, ...] = Field(min_length=3, max_length=3)
    latency: tuple[LatencyObservation, ...] = Field(min_length=1, max_length=64)
    capacity: tuple[CapacityObservation, ...] = Field(min_length=1, max_length=64)
    slo_thresholds: tuple[ReliabilitySLOThresholds, ...] = Field(min_length=1, max_length=64)
    compatibility: ReliabilityCompatibilityMatrix
    observed_at: datetime
    percentile_status: Literal["observed"] = "observed"
    capacity_status: Literal["observed"] = "observed"
    slo_status: Literal["observed_not_approved"] = "observed_not_approved"
    rpo_status: Literal["not_defined"] = "not_defined"
    rto_status: Literal["not_approved"] = "not_approved"
    promotion_ready: Literal[False] = False
    baseline_sha256: str

    @field_validator("baseline_id", "profile_id")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("reliability baseline/profile ID is invalid")
        return value

    @field_validator("compose_config_sha256", "baseline_sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("reliability identity must be SHA-256")
        return value

    @field_validator("observed_at")
    @classmethod
    def _observed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _sealed(self) -> DevelopmentReliabilityBaseline:
        if len({item.kind for item in self.evidence}) != 3:
            raise ValueError("reliability baseline requires backup, PITR, and recovery evidence")
        if any(item.profile_id != self.profile_id for item in self.evidence):
            raise ValueError("reliability evidence profile differs from baseline profile")
        if any(item.compose_config_sha256 != self.compose_config_sha256 for item in self.evidence):
            raise ValueError("reliability evidence compose config differs from baseline")

        latency_operations = tuple(item.operation for item in self.latency)
        capacity_operations = tuple(item.operation for item in self.capacity)
        threshold_operations = tuple(item.operation for item in self.slo_thresholds)
        if any(
            len(operations) != len(set(operations))
            for operations in (
                latency_operations,
                capacity_operations,
                threshold_operations,
            )
        ):
            raise ValueError("reliability operations must be unique per observation kind")
        if not (set(latency_operations) == set(capacity_operations) == set(threshold_operations)):
            raise ValueError("latency, capacity, and SLO operations must match exactly")

        observation_times = (
            *(item.observed_at for item in self.evidence),
            *(item.observed_at for item in self.latency),
            *(item.observed_at for item in self.capacity),
        )
        if any(observed_at > self.observed_at for observed_at in observation_times):
            raise ValueError("reliability evidence cannot postdate its baseline")
        values = self.model_dump(mode="json", exclude={"baseline_sha256"})
        if self.baseline_sha256 != _fingerprint(self.schema_id, values, "baseline_sha256"):
            raise ValueError("reliability baseline fingerprint is invalid")
        return self


def build_development_reliability_baseline(
    *,
    baseline_id: str,
    profile: DeploymentProfile,
    evidence: Sequence[ReliabilityEvidenceReference],
    latency: Sequence[LatencyObservation],
    capacity: Sequence[CapacityObservation],
    slo_thresholds: Sequence[ReliabilitySLOThresholds],
    compatibility: ReliabilityCompatibilityMatrix,
    observed_at: datetime,
) -> DevelopmentReliabilityBaseline:
    if profile.environment not in {"dev", "test"}:
        raise DevelopmentReliabilityError(
            "development reliability baselines require a dev or test profile"
        )
    values = {
        "baseline_id": baseline_id,
        "profile_id": profile.profile_id,
        "environment": profile.environment,
        "compose_config_sha256": profile.compose.config_sha256,
        "evidence": tuple(evidence),
        "latency": tuple(latency),
        "capacity": tuple(capacity),
        "slo_thresholds": tuple(slo_thresholds),
        "compatibility": compatibility,
        "observed_at": _utc(observed_at),
        "percentile_status": "observed",
        "capacity_status": "observed",
        "slo_status": "observed_not_approved",
        "rpo_status": "not_defined",
        "rto_status": "not_approved",
        "promotion_ready": False,
    }
    return DevelopmentReliabilityBaseline(
        **values,
        baseline_sha256=_fingerprint(
            DevelopmentReliabilityBaseline.schema_id,
            values,
            "baseline_sha256",
        ),
    )


def evaluate_development_slo(
    *,
    latency: LatencyObservation,
    capacity: CapacityObservation,
    thresholds: ReliabilitySLOThresholds,
) -> dict[str, bool]:
    if latency.operation != capacity.operation or latency.operation != thresholds.operation:
        raise DevelopmentReliabilityError("latency/capacity/SLO operation differs")
    return {
        "p95_within_threshold": latency.p95_ms <= thresholds.max_p95_ms,
        "p99_within_threshold": latency.p99_ms <= thresholds.max_p99_ms,
        "throughput_within_threshold": (
            capacity.throughput_per_second >= thresholds.min_throughput_per_second
        ),
        "error_rate_within_threshold": capacity.error_rate <= thresholds.max_error_rate,
    }


def verify_development_reliability_baseline(
    *,
    baseline: DevelopmentReliabilityBaseline,
    profile: DeploymentProfile,
    evidence: Sequence[ReliabilityEvidenceReference],
    latency: Sequence[LatencyObservation],
    capacity: Sequence[CapacityObservation],
    slo_thresholds: Sequence[ReliabilitySLOThresholds],
    compatibility: ReliabilityCompatibilityMatrix,
) -> dict[str, Any]:
    checks = {
        "profile_identity": baseline.profile_id == profile.profile_id,
        "compose_config_identity": (
            baseline.compose_config_sha256 == profile.compose.config_sha256
        ),
        "development_environment": baseline.environment in {"dev", "test"},
        "evidence_bindings": baseline.evidence == tuple(evidence),
        "latency_bindings": baseline.latency == tuple(latency),
        "capacity_bindings": baseline.capacity == tuple(capacity),
        "slo_bindings": baseline.slo_thresholds == tuple(slo_thresholds),
        "compatibility_binding": baseline.compatibility == compatibility,
        "promotion_blocked": baseline.promotion_ready is False,
        "rpo_rto_unapproved": baseline.rpo_status == "not_defined"
        and baseline.rto_status == "not_approved",
    }
    try:
        expected = build_development_reliability_baseline(
            baseline_id=baseline.baseline_id,
            profile=profile,
            evidence=evidence,
            latency=latency,
            capacity=capacity,
            slo_thresholds=slo_thresholds,
            compatibility=compatibility,
            observed_at=baseline.observed_at,
        )
    except (DevelopmentReliabilityError, TypeError, ValueError):
        checks["baseline_reproducible"] = False
    else:
        checks["baseline_reproducible"] = expected == baseline
    return {
        "schema": VERIFICATION_SCHEMA,
        "baseline_id": baseline.baseline_id,
        "profile_id": baseline.profile_id,
        "technical_pass": all(checks.values()),
        "promotion_ready": False,
        "checks": checks,
        "slo_status": "observed_not_approved",
        "rpo_status": "not_defined",
        "rto_status": "not_approved",
        "compatibility_status": (
            "complete"
            if all(item.status is CompatibilityStatus.PASSED for item in compatibility.cases)
            else "incomplete"
        ),
    }


__all__ = [
    "CapacityObservation",
    "CompatibilityCase",
    "CompatibilityStatus",
    "DevelopmentReliabilityBaseline",
    "DevelopmentReliabilityError",
    "LatencyObservation",
    "ReliabilityCompatibilityMatrix",
    "ReliabilityEvidenceKind",
    "ReliabilityEvidenceReference",
    "ReliabilitySLOThresholds",
    "build_capacity_observation",
    "build_compatibility_case",
    "build_compatibility_matrix",
    "build_development_reliability_baseline",
    "build_evidence_reference",
    "build_latency_observation",
    "build_slo_thresholds",
    "evaluate_development_slo",
    "verify_development_reliability_baseline",
]
