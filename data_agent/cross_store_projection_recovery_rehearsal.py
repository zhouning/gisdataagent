"""Repeatable in-memory rehearsal for cross-store projection recovery states.

This report validates the orchestration contract only.  It is intentionally
marked as non-production: it does not measure PostgreSQL, network, provider,
queue, or customer-topology recovery time.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import Field, model_validator

from .cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from .cross_store_projection_recovery import (
    InMemoryProjectionRecoveryLedger,
    ProjectionRecoveryCoordinator,
    ProjectionRecoveryState,
)
from .platform_contracts import FrozenContract, canonical_json_fingerprint

TENANT = "chongqing-customer"
PROJECTION = "cq.land_parcel"
TARGET_REF = "postgis://cq-db/public.land_parcel_current"
SOURCE_SHA = "a" * 64
TARGET_SHA = "b" * 64
NOW = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)


class CrossStoreProjectionRecoveryScenario(FrozenContract):
    schema_id: Literal[
        "gda.cross-store-projection-recovery-scenario.v1"
    ] = "gda.cross-store-projection-recovery-scenario.v1"
    scenario: str
    status: Literal["passed", "failed"]
    expected_state: str
    observed_state: str
    next_action: str
    events: tuple[str, ...]
    duration_ms: float = Field(ge=0)


class CrossStoreProjectionRecoveryReport(FrozenContract):
    schema_id: Literal[
        "gda.cross-store-projection-recovery-report.v1"
    ] = "gda.cross-store-projection-recovery-report.v1"
    generated_at: datetime
    scenario_results: tuple[CrossStoreProjectionRecoveryScenario, ...]
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    recovery_scope: Literal["in_memory_recovery_orchestration_only"] = (
        "in_memory_recovery_orchestration_only"
    )
    production_recovery_certified: Literal[False] = False
    technical_baseline_status: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    decision_status: Literal[
        "assisted_precheck_not_for_production_decision"
    ] = "assisted_precheck_not_for_production_decision"
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _report_is_canonical(self) -> CrossStoreProjectionRecoveryReport:
        if self.passed_count + self.failed_count != len(self.scenario_results):
            raise ValueError("recovery scenario counts do not match results")
        expected = _report_hash(self.model_dump(mode="json"))
        if self.report_sha256 != expected:
            raise ValueError("recovery report fingerprint is invalid")
        return self


class _FailOnceAuthority:
    def __init__(self) -> None:
        self.ledger = InMemoryProjectionCheckpointLedger()
        self.fail = True

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        if self.fail:
            self.fail = False
            raise RuntimeError("postgresql_unavailable")
        return self.ledger.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )

    def history(self, **identity):
        return self.ledger.history(**identity)


def _report_hash(payload: dict[str, Any]) -> str:
    def _ready(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return _ready(value.model_dump(mode="json"))
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        if isinstance(value, dict):
            return {str(key): _ready(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_ready(item) for item in value]
        return value

    normalized = json.loads(json.dumps(_ready(payload), ensure_ascii=True))
    return canonical_json_fingerprint(
        {key: value for key, value in normalized.items() if key != "report_sha256"}
    )


def _plan(
    *,
    projection_id: str = PROJECTION,
    target_ref: str = TARGET_REF,
):
    desired = ProjectionDesiredState(
        tenant_id=TENANT,
        projection_id=projection_id,
        source_resource_version_ref="gda://chongqing-customer/data_product/parcel-v1",
        source_content_sha256=SOURCE_SHA,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=target_ref,
        target_exists=True,
        expected_target_content_sha256=TARGET_SHA,
        expected_row_count=455,
    )
    observation = ProjectionTargetObservation(
        tenant_id=TENANT,
        projection_id=projection_id,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=target_ref,
        target_exists=False,
        observed_content_sha256=None,
        observed_row_count=0,
        observed_by="workload:recovery-rehearsal",
        observed_at=NOW,
    )
    return build_projection_repair_plan(desired, observation, None)


def _post_observation(
    *,
    projection_id: str = PROJECTION,
    target_ref: str = TARGET_REF,
    **overrides,
):
    values = {
        "tenant_id": TENANT,
        "projection_id": projection_id,
        "target_engine": ProjectionEngine.POSTGIS,
        "target_ref": target_ref,
        "target_exists": True,
        "observed_content_sha256": TARGET_SHA,
        "observed_row_count": 455,
        "observed_by": "workload:recovery-rehearsal",
        "observed_at": NOW + timedelta(seconds=1),
    }
    values.update(overrides)
    return ProjectionTargetObservation(**values)


def _receipt(plan):
    ref = {
        "provider": "postgis",
        "provider_commit": "public.land_parcel_current:1",
        "plan_sha256": plan.plan_sha256,
        "idempotency_key": plan.plan_idempotency_key,
    }
    return SimpleNamespace(
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=ref,
    )


def _scenario_known_authority_gap() -> tuple[str, str, str, tuple[str, ...]]:
    plan = _plan()
    authority = _FailOnceAuthority()
    coordinator = ProjectionRecoveryCoordinator(
        plan,
        checkpointed_by="workload:recovery-rehearsal",
        ledger=InMemoryProjectionRecoveryLedger(),
        now=lambda: NOW + timedelta(seconds=2),
    )
    coordinator.provider_committed(_receipt(plan))
    coordinator.authority_failed("postgresql_unavailable")
    authority.fail = False
    snapshot, checkpoint = coordinator.recover_authority(_post_observation(), authority)
    if checkpoint is None:
        raise AssertionError("authority recovery did not produce a checkpoint")
    return (
        ProjectionRecoveryState.AUTHORITY_COMMITTED.value,
        snapshot.state.value,
        snapshot.next_action,
        tuple(event.event_type for event in snapshot.events),
    )


def _scenario_target_drift() -> tuple[str, str, str, tuple[str, ...]]:
    plan = _plan()
    coordinator = ProjectionRecoveryCoordinator(plan, checkpointed_by="agent:recovery")
    coordinator.provider_committed(_receipt(plan))
    snapshot, checkpoint = coordinator.recover_authority(
        _post_observation(observed_content_sha256="c" * 64),
        InMemoryProjectionCheckpointLedger(),
    )
    if checkpoint is not None:
        raise AssertionError("drift recovery unexpectedly produced a checkpoint")
    return (
        ProjectionRecoveryState.RECONCILIATION_REQUIRED.value,
        snapshot.state.value,
        snapshot.next_action,
        tuple(event.event_type for event in snapshot.events),
    )


def _scenario_unknown_provider_outcome() -> tuple[str, str, str, tuple[str, ...]]:
    plan = _plan()
    coordinator = ProjectionRecoveryCoordinator(plan, checkpointed_by="workload:recovery")
    snapshot = coordinator.provider_failed("worker_hard_kill", outcome_known=False)
    return (
        ProjectionRecoveryState.RECONCILIATION_REQUIRED.value,
        snapshot.state.value,
        snapshot.next_action,
        tuple(event.event_type for event in snapshot.events),
    )


def _scenario_known_provider_failure() -> tuple[str, str, str, tuple[str, ...]]:
    plan = _plan()
    coordinator = ProjectionRecoveryCoordinator(plan, checkpointed_by="workload:recovery")
    coordinator.provider_failed("validation_error", outcome_known=True)
    snapshot = coordinator.provider_committed(_receipt(plan))
    return (
        ProjectionRecoveryState.PROVIDER_COMMITTED.value,
        snapshot.state.value,
        snapshot.next_action,
        tuple(event.event_type for event in snapshot.events),
    )


def run_cross_store_projection_recovery_rehearsal() -> CrossStoreProjectionRecoveryReport:
    scenarios = (
        ("known_provider_authority_gap", _scenario_known_authority_gap),
        ("target_drift_requires_manual_compensation", _scenario_target_drift),
        ("unknown_provider_outcome_requires_reobservation", _scenario_unknown_provider_outcome),
        ("known_provider_failure_can_retry", _scenario_known_provider_failure),
    )
    results: list[CrossStoreProjectionRecoveryScenario] = []
    for name, runner in scenarios:
        started = perf_counter()
        expected, observed, next_action, events = runner()
        passed = expected == observed
        results.append(
            CrossStoreProjectionRecoveryScenario(
                scenario=name,
                status="passed" if passed else "failed",
                expected_state=expected,
                observed_state=observed,
                next_action=next_action,
                events=events,
                duration_ms=(perf_counter() - started) * 1000,
            )
        )
    passed_count = sum(result.status == "passed" for result in results)
    values = {
        "generated_at": datetime.now(UTC),
        "scenario_results": tuple(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "recovery_scope": "in_memory_recovery_orchestration_only",
        "production_recovery_certified": False,
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    draft = CrossStoreProjectionRecoveryReport.model_construct(
        **values,
        report_sha256="0" * 64,
    )
    return CrossStoreProjectionRecoveryReport(
        **values,
        report_sha256=_report_hash(draft.model_dump(mode="json")),
    )


def write_cross_store_projection_recovery_report(
    report: CrossStoreProjectionRecoveryReport,
    path: str | Path,
) -> None:
    Path(path).write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "CrossStoreProjectionRecoveryReport",
    "CrossStoreProjectionRecoveryScenario",
    "run_cross_store_projection_recovery_rehearsal",
    "write_cross_store_projection_recovery_report",
]
