from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_cohort import (
    ProjectionCohortAdmissionError,
    ProjectionCohortExecutionState,
    ProjectionCohortPlan,
    ProjectionCohortStatus,
    ProjectionCohortTargetInput,
    build_projection_cohort_plan,
    build_projection_cohort_request,
    build_projection_source_snapshot_evidence,
    execute_federated_projection_cohort,
)
from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
)
from data_agent.cross_store_projection_federated_recovery import (
    FederatedProjectionItemState,
    FederatedProjectionRecoveryCoordinator,
    FederatedProjectionRecoveryError,
    FederatedProjectionRecoveryState,
    InMemoryFederatedProjectionRecoveryLedger,
)
from data_agent.cross_store_projection_recovery import (
    InMemoryProjectionRecoveryLedger,
)
from data_agent.cross_store_projection_recovery_worker import (
    ProjectionProviderFailure,
)

TENANT = "cq-projection-cohort"
SOURCE_REF = f"gda://{TENANT}/data_product/parcel-current-v7"
SOURCE_SHA = "a" * 64
NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
ENGINES = (
    ProjectionEngine.POSTGIS,
    ProjectionEngine.RDF,
    ProjectionEngine.VECTOR,
)


def _target(
    position: int,
    *,
    source_ref: str = SOURCE_REF,
    source_sha: str = SOURCE_SHA,
    target_missing: bool = True,
) -> ProjectionCohortTargetInput:
    engine = ENGINES[position]
    projection_id = f"cq.cohort.{engine.value}"
    target_ref = f"{engine.value}://cq-customer/{projection_id}"
    expected_sha = f"{position + 1:x}" * 64
    desired = ProjectionDesiredState(
        tenant_id=TENANT,
        projection_id=projection_id,
        source_resource_version_ref=source_ref,
        source_content_sha256=source_sha,
        target_engine=engine,
        target_ref=target_ref,
        target_exists=True,
        expected_target_content_sha256=expected_sha,
        expected_row_count=100 + position,
    )
    observation = ProjectionTargetObservation(
        tenant_id=TENANT,
        projection_id=projection_id,
        target_engine=engine,
        target_ref=target_ref,
        target_exists=not target_missing,
        observed_content_sha256=None if target_missing else expected_sha,
        observed_row_count=0 if target_missing else 100 + position,
        observed_by="workload:projection-cohort-observer",
        observed_at=NOW,
    )
    return ProjectionCohortTargetInput(
        desired_state=desired,
        observation=observation,
        checkpoint=None,
    )


def _request(
    targets: tuple[ProjectionCohortTargetInput, ...] | None = None,
    *,
    max_provider_mutations: int = 3,
):
    return build_projection_cohort_request(
        tenant_id=TENANT,
        cohort_id="parcel-current-multi-store-v7",
        source_resource_version_ref=SOURCE_REF,
        source_content_sha256=SOURCE_SHA,
        targets=targets or tuple(_target(position) for position in range(3)),
        max_provider_mutations=max_provider_mutations,
        requested_by="workload:projection-cohort-planner",
        requested_at=NOW,
    )


def _receipt(plan):
    commit_ref = {
        "provider": plan.target_engine.value,
        "provider_commit": f"{plan.target_engine.value}:commit-1",
        "plan_sha256": plan.plan_sha256,
        "idempotency_key": plan.plan_idempotency_key,
    }
    return SimpleNamespace(
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=commit_ref,
    )


def _post_observation(plan):
    desired = plan.desired_state
    return ProjectionTargetObservation(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=plan.target_engine,
        target_ref=plan.target_ref,
        target_exists=desired.target_exists,
        observed_content_sha256=desired.expected_target_content_sha256,
        observed_row_count=desired.expected_row_count,
        observed_by="workload:projection-cohort-provider",
        observed_at=NOW + timedelta(seconds=1),
    )


class _Provider:
    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.execute_count = 0
        self.observe_count = 0
        self.recover_count = 0

    def execute(self, plan):
        self.execute_count += 1
        if self.mode == "unknown":
            raise ProjectionProviderFailure(
                "provider_connection_lost_after_request",
                outcome_known=False,
            )
        return _receipt(plan)

    def observe(self, plan):
        self.observe_count += 1
        return _post_observation(plan)

    def recover_receipt(self, plan):
        self.recover_count += 1
        return None


class _Authority:
    def __init__(self) -> None:
        self.ledger = InMemoryProjectionCheckpointLedger()

    def current(self, **identity):
        return self.ledger.current(**identity)

    def history(self, **identity):
        return self.ledger.history(**identity)

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        return self.ledger.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )


class _SourceReader:
    def __init__(self, *, content_sha256: str = SOURCE_SHA) -> None:
        self.content_sha256 = content_sha256
        self.read_count = 0

    def read(self, *, tenant_id, source_resource_version_ref):
        self.read_count += 1
        return build_projection_source_snapshot_evidence(
            tenant_id=tenant_id,
            source_resource_version_ref=source_resource_version_ref,
            source_content_sha256=self.content_sha256,
            observed_by="workload:projection-source-authority",
            observed_at=NOW + timedelta(seconds=2),
        )


class _CheckpointReader:
    def __init__(self, authorities, *, drift_position: int | None = None) -> None:
        self.authorities = authorities
        self.drift_position = drift_position
        self.read_count = 0

    def current(self, **identity):
        position = self.read_count
        self.read_count += 1
        current = self.authorities[position].current(**identity)
        if self.drift_position == position and current is None:
            return "invalid-current-checkpoint"
        return current


def _runtime(plan, *, provider_modes=None):
    provider_modes = provider_modes or {}
    providers = {
        repair.plan_sha256: _Provider(provider_modes.get(position, "success"))
        for position, repair in enumerate(plan.executable_plans)
    }
    authorities = tuple(_Authority() for _ in plan.executable_plans)
    authority_by_plan = {
        repair.plan_sha256: authority
        for repair, authority in zip(
            plan.executable_plans,
            authorities,
            strict=True,
        )
    }
    plan_ledgers = {
        repair.plan_sha256: InMemoryProjectionRecoveryLedger() for repair in plan.executable_plans
    }
    coordinator = FederatedProjectionRecoveryCoordinator(
        "parcel-current-multi-store-run-v7",
        plan.executable_plans,
        checkpointed_by="workload:projection-cohort-executor",
        provider_resolver=lambda repair: providers[repair.plan_sha256],
        authority_resolver=lambda repair: authority_by_plan[repair.plan_sha256],
        ledger=InMemoryFederatedProjectionRecoveryLedger(),
        plan_ledger_resolver=lambda repair: plan_ledgers[repair.plan_sha256],
        now=lambda: NOW + timedelta(seconds=3),
    )
    return coordinator, providers, authorities


def test_cohort_requires_one_source_snapshot_and_unique_targets():
    with pytest.raises(ValidationError, match="source snapshot"):
        _request((_target(0), _target(1, source_sha="b" * 64)))

    with pytest.raises(ValidationError, match="unique"):
        _request((_target(0), _target(0)))


def test_blocked_target_or_mutation_budget_hides_all_executable_plans():
    blocked = build_projection_cohort_plan(_request((_target(0), _target(1, target_missing=False))))

    assert blocked.status is ProjectionCohortStatus.BLOCKED
    assert blocked.executable_plans == ()
    assert any("checkpoint_missing" in item for item in blocked.blocked_reason_codes)

    over_budget = build_projection_cohort_plan(
        _request((_target(0), _target(1)), max_provider_mutations=1)
    )
    assert over_budget.status is ProjectionCohortStatus.BLOCKED
    assert over_budget.executable_plans == ()
    assert over_budget.blocked_reason_codes == ("provider_mutation_budget_exceeded",)


def test_source_drift_fails_before_checkpoint_or_provider_access():
    plan = build_projection_cohort_plan(_request((_target(0), _target(1))))
    coordinator, providers, authorities = _runtime(plan)
    source_reader = _SourceReader(content_sha256="b" * 64)
    checkpoint_reader = _CheckpointReader(authorities)

    with pytest.raises(ProjectionCohortAdmissionError, match="source snapshot"):
        execute_federated_projection_cohort(
            plan,
            coordinator,
            source_reader=source_reader,
            checkpoint_reader=checkpoint_reader,
            admitted_by="workload:projection-cohort-executor",
            admitted_at=NOW + timedelta(seconds=2),
        )

    assert source_reader.read_count == 1
    assert checkpoint_reader.read_count == 0
    assert sum(provider.execute_count for provider in providers.values()) == 0
    assert coordinator.snapshot.state is FederatedProjectionRecoveryState.PLANNED


def test_checkpoint_current_drift_fails_before_provider_access():
    plan = build_projection_cohort_plan(_request((_target(0), _target(1))))
    coordinator, providers, authorities = _runtime(plan)
    source_reader = _SourceReader()
    checkpoint_reader = _CheckpointReader(authorities, drift_position=1)

    with pytest.raises(ProjectionCohortAdmissionError, match="invalid evidence"):
        execute_federated_projection_cohort(
            plan,
            coordinator,
            source_reader=source_reader,
            checkpoint_reader=checkpoint_reader,
            admitted_by="workload:projection-cohort-executor",
            admitted_at=NOW + timedelta(seconds=2),
        )

    assert source_reader.read_count == 1
    assert checkpoint_reader.read_count == 2
    assert sum(provider.execute_count for provider in providers.values()) == 0
    assert coordinator.snapshot.state is FederatedProjectionRecoveryState.PLANNED


def test_admitted_cohort_completes_and_records_all_target_checkpoints():
    plan = build_projection_cohort_plan(_request())
    coordinator, providers, authorities = _runtime(plan)

    result = execute_federated_projection_cohort(
        plan,
        coordinator,
        source_reader=_SourceReader(),
        checkpoint_reader=_CheckpointReader(authorities),
        admitted_by="workload:projection-cohort-executor",
        admitted_at=NOW + timedelta(seconds=2),
    )

    assert result.state is ProjectionCohortExecutionState.COMPLETED
    assert result.federated_snapshot.state is FederatedProjectionRecoveryState.COMPLETED
    assert result.pending_plan_sha256s == ()
    assert result.committed_plan_sha256s == tuple(
        repair.plan_sha256 for repair in plan.executable_plans
    )
    assert result.cross_target_atomic is False
    assert result.admission.checkpoint_write_performed is False
    assert all(provider.execute_count == 1 for provider in providers.values())
    assert all(
        authority.current(
            tenant_id=repair.tenant_id,
            projection_id=repair.projection_id,
            target_engine=repair.target_engine,
            target_ref=repair.target_ref,
        )
        is not None
        for repair, authority in zip(
            plan.executable_plans,
            authorities,
            strict=True,
        )
    )
    assert ProjectionCohortPlan.model_validate(plan.model_dump(mode="json")) == plan


def test_unknown_middle_target_preserves_prefix_stops_suffix_and_reconciles():
    plan = build_projection_cohort_plan(_request())
    coordinator, providers, authorities = _runtime(
        plan,
        provider_modes={1: "unknown"},
    )

    result = execute_federated_projection_cohort(
        plan,
        coordinator,
        source_reader=_SourceReader(),
        checkpoint_reader=_CheckpointReader(authorities),
        admitted_by="workload:projection-cohort-executor",
        admitted_at=NOW + timedelta(seconds=2),
    )

    first, middle, last = plan.executable_plans
    assert result.state is ProjectionCohortExecutionState.RECONCILING
    assert result.federated_snapshot.state is FederatedProjectionRecoveryState.COMPENSATION_REQUIRED
    assert result.committed_plan_sha256s == (first.plan_sha256,)
    assert result.pending_plan_sha256s == (middle.plan_sha256, last.plan_sha256)
    assert (
        result.federated_snapshot.items[0].state is FederatedProjectionItemState.AUTHORITY_COMMITTED
    )
    assert (
        result.federated_snapshot.items[1].state
        is FederatedProjectionItemState.COMPENSATION_REQUIRED
    )
    assert result.federated_snapshot.items[2].state is FederatedProjectionItemState.PENDING
    assert providers[last.plan_sha256].execute_count == 0

    repeated = execute_federated_projection_cohort(
        plan,
        coordinator,
        source_reader=_SourceReader(),
        checkpoint_reader=_CheckpointReader(authorities),
        admitted_by="workload:projection-cohort-executor",
        admitted_at=NOW + timedelta(seconds=4),
    )

    assert repeated.state is ProjectionCohortExecutionState.RECONCILING
    assert repeated.federated_snapshot == result.federated_snapshot
    assert providers[first.plan_sha256].execute_count == 1
    assert providers[middle.plan_sha256].execute_count == 1
    assert providers[last.plan_sha256].execute_count == 0


def test_federated_coordinator_revalidates_sealed_plans():
    plans = build_projection_cohort_plan(_request((_target(0), _target(1)))).executable_plans
    tampered = plans[1].model_copy(update={"plan_sha256": "f" * 64})

    with pytest.raises(FederatedProjectionRecoveryError, match="sealed repair plans"):
        FederatedProjectionRecoveryCoordinator(
            "tampered-plan-run",
            (plans[0], tampered),
            checkpointed_by="workload:projection-cohort-executor",
            provider_resolver=lambda _: None,
            authority_resolver=lambda _: None,
        )
