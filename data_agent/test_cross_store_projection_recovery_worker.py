from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from data_agent.cross_store_projection_recovery import (
    InMemoryProjectionRecoveryLedger,
    ProjectionRecoveryState,
)
from data_agent.cross_store_projection_recovery_worker import (
    ProjectionProviderFailure,
    ProjectionRecoveryWorker,
    RegisteredExecutorProjectionProvider,
)

TENANT = "cq-recovery-worker"
PROJECTION = "cq.land_parcel"
TARGET_REF = "postgis://cq-db/public.land_parcel_current"
SOURCE_SHA = "a" * 64
TARGET_SHA = "b" * 64
NOW = datetime(2026, 8, 15, 18, 0, tzinfo=UTC)


def _plan():
    desired = ProjectionDesiredState(
        tenant_id=TENANT,
        projection_id=PROJECTION,
        source_resource_version_ref="gda://cq-recovery-worker/data_product/parcel-v1",
        source_content_sha256=SOURCE_SHA,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=TARGET_REF,
        target_exists=True,
        expected_target_content_sha256=TARGET_SHA,
        expected_row_count=455,
    )
    observation = ProjectionTargetObservation(
        tenant_id=TENANT,
        projection_id=PROJECTION,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=TARGET_REF,
        target_exists=False,
        observed_content_sha256=None,
        observed_row_count=0,
        observed_by="workload:recovery-worker-test",
        observed_at=NOW,
    )
    return build_projection_repair_plan(desired, observation, None)


def _observation(plan):
    return ProjectionTargetObservation(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=plan.target_engine,
        target_ref=plan.target_ref,
        target_exists=True,
        observed_content_sha256=TARGET_SHA,
        observed_row_count=455,
        observed_by="workload:recovery-worker-provider",
        observed_at=NOW + timedelta(seconds=1),
    )


def _receipt(plan):
    commit_ref = {
        "provider": "postgis",
        "provider_commit": "public.land_parcel_current:1",
        "plan_sha256": plan.plan_sha256,
        "idempotency_key": plan.plan_idempotency_key,
    }
    return SimpleNamespace(
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=commit_ref,
    )


class _Authority:
    def __init__(self, *, fail_once: bool = False):
        self.ledger = InMemoryProjectionCheckpointLedger()
        self.fail_once = fail_once

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("postgresql_unavailable")
        return self.ledger.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )

    def history(self, **identity):
        return self.ledger.history(**identity)


class _Provider:
    def __init__(self, *, unknown: bool = False, recovered_receipt=None):
        self.unknown = unknown
        self.recovered_receipt = recovered_receipt
        self.execute_count = 0
        self.recover_count = 0

    def execute(self, plan):
        self.execute_count += 1
        if self.unknown:
            raise ProjectionProviderFailure("worker_hard_kill", outcome_known=False)
        return _receipt(plan)

    def observe(self, plan):
        return _observation(plan)

    def recover_receipt(self, _plan):
        self.recover_count += 1
        return self.recovered_receipt


def _worker(plan, provider, authority, ledger, *, compensation=None):
    return ProjectionRecoveryWorker(
        plan,
        checkpointed_by="workload:recovery-worker-test",
        provider=provider,
        authority=authority,
        ledger=ledger,
        compensation=compensation,
        now=lambda: NOW + timedelta(seconds=2),
    )


def test_worker_executes_provider_then_records_authority():
    plan = _plan()
    provider = _Provider()
    authority = _Authority()
    ledger = InMemoryProjectionRecoveryLedger()

    result = _worker(plan, provider, authority, ledger).run_once()

    assert result.snapshot.state is ProjectionRecoveryState.AUTHORITY_COMMITTED
    assert result.checkpoint is not None
    assert provider.execute_count == 1

    replay = _worker(plan, provider, authority, ledger).run_once()
    assert replay.action_taken == "none"
    assert provider.execute_count == 1


def test_worker_retries_authority_without_replaying_provider():
    plan = _plan()
    provider = _Provider()
    authority = _Authority(fail_once=True)
    ledger = InMemoryProjectionRecoveryLedger()

    pending = _worker(plan, provider, authority, ledger).run_once()
    assert pending.snapshot.state is ProjectionRecoveryState.AUTHORITY_PENDING
    assert pending.action_taken == "retry_authority"
    assert provider.execute_count == 1

    recovered = _worker(plan, provider, authority, ledger).run_once()
    assert recovered.snapshot.state is ProjectionRecoveryState.AUTHORITY_COMMITTED
    assert provider.execute_count == 1


def test_unknown_provider_outcome_reobserves_then_requires_explicit_compensation():
    plan = _plan()
    provider = _Provider(unknown=True)
    authority = _Authority()
    ledger = InMemoryProjectionRecoveryLedger()

    first = _worker(plan, provider, authority, ledger).run_once()
    assert first.action_taken == "reobserve_target"
    assert first.snapshot.state is ProjectionRecoveryState.RECONCILIATION_REQUIRED

    second = _worker(plan, provider, authority, ledger).run_once()
    assert second.action_taken == "await_operator"
    assert second.snapshot.state is ProjectionRecoveryState.COMPENSATION_REQUIRED
    assert provider.execute_count == 1

    recovery_provider = _Provider()
    compensated = _worker(
        plan,
        recovery_provider,
        authority,
        ledger,
        compensation=lambda current_plan, _snapshot: _receipt(current_plan),
    ).run_once()
    assert compensated.snapshot.state is ProjectionRecoveryState.AUTHORITY_COMMITTED
    assert recovery_provider.execute_count == 0


def test_unknown_provider_outcome_uses_exact_receipt_without_provider_replay():
    plan = _plan()
    ledger = InMemoryProjectionRecoveryLedger()
    first_provider = _Provider(unknown=True)
    authority = _Authority()

    first = _worker(plan, first_provider, authority, ledger).run_once()
    recovery_provider = _Provider(recovered_receipt=_receipt(plan))
    recovered = _worker(plan, recovery_provider, authority, ledger).run_once()

    assert first.snapshot.state is ProjectionRecoveryState.RECONCILIATION_REQUIRED
    assert recovered.snapshot.state is ProjectionRecoveryState.AUTHORITY_COMMITTED
    assert recovered.checkpoint is not None
    assert recovery_provider.recover_count == 1
    assert recovery_provider.execute_count == 0


def test_registered_executor_adapter_passes_rows_only_to_sql_providers():
    class Registry:
        def resolve(self, **_identity):
            return "registered-target"

    class Executor:
        def __init__(self):
            self.calls = []

        def execute(self, plan, **kwargs):
            self.calls.append(kwargs)
            return "receipt"

        def observe(self, target):
            assert target == "registered-target"
            return _observation(_plan())

        def recover_receipt(self, plan):
            return _receipt(plan)

    executor = Executor()
    adapter = RegisteredExecutorProjectionProvider(
        executor=executor,
        registry=Registry(),
        rows=({"id": 1},),
    )
    plan = _plan()
    assert adapter.execute(plan) == "receipt"
    assert executor.calls == [{"rows": ({"id": 1},)}]
    assert adapter.observe(plan).observed_content_sha256 == TARGET_SHA
    assert adapter.recover_receipt(plan).plan_sha256 == plan.plan_sha256

    rdf_plan = SimpleNamespace(
        tenant_id=plan.tenant_id,
        projection_id=plan.projection_id,
        target_engine=ProjectionEngine.RDF,
        target_ref=plan.target_ref,
    )
    assert adapter.execute(rdf_plan) == "receipt"
    assert executor.calls[-1] == {}
