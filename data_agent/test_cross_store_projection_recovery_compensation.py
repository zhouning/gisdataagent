from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_recovery import (
    InMemoryProjectionRecoveryLedger,
    ProjectionRecoveryCoordinator,
)
from data_agent.cross_store_projection_recovery_compensation import (
    ProjectionRecoveryCompensationAttempt,
    ProjectionRecoveryCompensationConfig,
    ProjectionRecoveryCompensationError,
    ProjectionRecoveryCompensationReconciliation,
    ProjectionRecoveryCompensationResolver,
    ProjectionRecoveryCompensationStrategy,
    compensation_receipt_fingerprint,
    compensation_reconciliation_target_fingerprint,
    projection_recovery_compensation_attempt_id,
)
from data_agent.cross_store_projection_recovery_rehearsal import _plan, _receipt
from data_agent.cross_store_projection_recovery_worker import ProjectionProviderFailure


def _waiting_state():
    plan = _plan()
    ledger = InMemoryProjectionRecoveryLedger()
    coordinator = ProjectionRecoveryCoordinator(
        plan,
        checkpointed_by="workload:compensation-test",
        ledger=ledger,
        now=lambda: datetime(2026, 8, 16, 1, 0, tzinfo=UTC),
    )
    snapshot = coordinator.require_compensation("operator_authority_required")
    job = SimpleNamespace(
        tenant_id=plan.tenant_id,
        job_id="49e9b36b-6aeb-4a4c-b3c8-a8c33d050736",
        plan_sha256=plan.plan_sha256,
        plan_idempotency_key=plan.plan_idempotency_key,
        projection_id=plan.projection_id,
        target_engine=plan.target_engine.value,
        target_ref=plan.target_ref,
        plan=plan,
        status="running",
        claimed_by="worker:compensation-test",
        lease_generation=2,
        resume_approval_case_ref=(
            f"gda://{plan.tenant_id}/approval_case/reapply-sealed-plan"
        ),
        resume_snapshot_sha256=snapshot.snapshot_sha256,
        resume_reason="bounded replay after exact target reconciliation",
        resumed_by="human:recovery-operator",
        resumed_at=datetime(2026, 8, 16, 0, 59, tzinfo=UTC),
    )
    return plan, ledger, snapshot, job


class _Authority:
    def __init__(self, *, reject=False, existing=None):
        self.reject = reject
        self.existing = existing
        self.begin_calls = []
        self.finish_calls = []

    def begin_compensation_execution(
        self,
        job,
        snapshot,
        *,
        strategy,
        compensation_attempt_id,
    ):
        self.begin_calls.append(
            (job, snapshot, strategy, compensation_attempt_id)
        )
        if self.reject:
            raise ProjectionRecoveryCompensationError(
                "compensation_authority_evidence_drifted"
            )
        return self.existing or ProjectionRecoveryCompensationAttempt(
            compensation_attempt_id=compensation_attempt_id,
            outcome="started",
        )

    def finish_compensation_execution(
        self,
        job,
        *,
        compensation_attempt_id,
        outcome,
        provider_commit_ref=None,
        receipt_sha256=None,
        error_code=None,
    ):
        self.finish_calls.append(
            {
                "job": job,
                "compensation_attempt_id": compensation_attempt_id,
                "outcome": outcome,
                "provider_commit_ref": provider_commit_ref,
                "receipt_sha256": receipt_sha256,
                "error_code": error_code,
            }
        )
        return ProjectionRecoveryCompensationAttempt(
            compensation_attempt_id=compensation_attempt_id,
            outcome=outcome,
            provider_commit_ref=provider_commit_ref,
            receipt_sha256=receipt_sha256,
            error_code=error_code,
        )


class _Provider:
    def __init__(
        self,
        *,
        bad_receipt=False,
        reject_target=False,
        known_failure=False,
    ):
        self.bad_receipt = bad_receipt
        self.reject_target = reject_target
        self.known_failure = known_failure
        self.executed = []

    def execute(self, plan):
        self.executed.append(plan)
        if self.reject_target:
            raise ValueError("registered target drifted")
        if self.known_failure:
            raise ProjectionProviderFailure(
                "provider_rejected_before_commit",
                outcome_known=True,
            )
        if self.bad_receipt:
            return SimpleNamespace(
                plan_sha256="f" * 64,
                idempotency_key=plan.plan_idempotency_key,
                provider_commit_ref={},
            )
        return _receipt(plan)

    def observe(self, plan):
        raise AssertionError("observation is not part of strategy resolution")


def _resolver(authority, strategy="approved_reapply_sealed_plan"):
    return ProjectionRecoveryCompensationResolver(
        config=ProjectionRecoveryCompensationConfig(strategy=strategy),
        authority=authority,
    )


def test_compensation_strategy_is_disabled_by_default_and_rejects_unknown_values():
    config = ProjectionRecoveryCompensationConfig.from_environment({})
    assert config.strategy is ProjectionRecoveryCompensationStrategy.DISABLED
    with pytest.raises(ValidationError):
        ProjectionRecoveryCompensationConfig.from_environment(
            {"GDA_PROJECTION_RECOVERY_COMPENSATION_STRATEGY": "arbitrary_code"}
        )


def test_disabled_strategy_never_resolves_a_compensation_callback():
    _, ledger, _, job = _waiting_state()
    authority = _Authority()
    provider = _Provider()
    resolver = _resolver(authority, strategy="disabled")

    assert resolver(job, provider, ledger) is None
    assert not authority.begin_calls
    assert not authority.finish_calls
    assert not provider.executed


def test_approved_strategy_reapplies_only_the_original_sealed_plan():
    plan, ledger, snapshot, job = _waiting_state()
    authority = _Authority()
    provider = _Provider()
    compensation = _resolver(authority)(job, provider, ledger)

    assert compensation is not None
    receipt = compensation(plan, snapshot)

    assert provider.executed == [job.plan]
    attempt_id = projection_recovery_compensation_attempt_id(job)
    assert authority.begin_calls == [
        (
            job,
            snapshot,
            "approved_reapply_sealed_plan",
            attempt_id,
        )
    ]
    assert authority.finish_calls[0]["outcome"] == "succeeded"
    assert receipt.plan_sha256 == plan.plan_sha256
    assert receipt.idempotency_key == plan.plan_idempotency_key


def test_approved_strategy_rejects_plan_snapshot_authority_and_registry_drift():
    plan, ledger, snapshot, job = _waiting_state()
    other_plan = _plan(
        projection_id="cq.land_parcel.other",
        target_ref="postgis://cq-db/public.land_parcel_other",
    )

    with pytest.raises(ProjectionRecoveryCompensationError, match="sealed_job_plan"):
        _resolver(_Authority())(job, _Provider(), ledger)(other_plan, snapshot)

    drifted_job = SimpleNamespace(
        **{
            **vars(job),
            "resume_snapshot_sha256": "f" * 64,
        }
    )
    with pytest.raises(ProjectionRecoveryCompensationError, match="approved_waiting"):
        _resolver(_Authority())(drifted_job, _Provider(), ledger)(plan, snapshot)

    with pytest.raises(ProjectionRecoveryCompensationError, match="authority"):
        _resolver(_Authority(reject=True))(job, _Provider(), ledger)(plan, snapshot)

    with pytest.raises(ValueError, match="registered target"):
        _resolver(_Authority())(job, _Provider(reject_target=True), ledger)(
            plan,
            snapshot,
        )


def test_approved_strategy_rejects_unbound_provider_receipt_after_execution():
    plan, ledger, snapshot, job = _waiting_state()
    compensation = _resolver(_Authority())(job, _Provider(bad_receipt=True), ledger)

    with pytest.raises(ProjectionProviderFailure) as failure:
        compensation(plan, snapshot)

    assert failure.value.outcome_known is False
    assert "not_plan_bound" in str(failure.value)


def test_started_only_attempt_blocks_provider_replay_as_indeterminate():
    plan, ledger, snapshot, job = _waiting_state()
    attempt_id = projection_recovery_compensation_attempt_id(job)
    authority = _Authority(
        existing=ProjectionRecoveryCompensationAttempt(
            compensation_attempt_id=attempt_id,
            outcome="indeterminate",
        )
    )
    provider = _Provider()
    compensation = _resolver(authority)(job, provider, ledger)

    with pytest.raises(ProjectionProviderFailure) as failure:
        compensation(plan, snapshot)

    assert failure.value.outcome_known is False
    assert "indeterminate" in str(failure.value)
    assert not provider.executed
    assert not authority.finish_calls


def test_persisted_success_receipt_recovers_without_provider_reexecution():
    plan, ledger, snapshot, job = _waiting_state()
    attempt_id = projection_recovery_compensation_attempt_id(job)
    commit_ref = _receipt(plan).provider_commit_ref
    receipt_sha256 = compensation_receipt_fingerprint(
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=commit_ref,
    )
    authority = _Authority(
        existing=ProjectionRecoveryCompensationAttempt(
            compensation_attempt_id=attempt_id,
            outcome="succeeded",
            provider_commit_ref=commit_ref,
            receipt_sha256=receipt_sha256,
        )
    )
    provider = _Provider()
    compensation = _resolver(authority)(job, provider, ledger)

    recovered = compensation(plan, snapshot)

    assert recovered.receipt_sha256 == receipt_sha256
    assert recovered.provider_commit_ref == commit_ref
    assert not provider.executed
    assert not authority.finish_calls


def test_reconciliation_contract_binds_attempt_and_observed_provider_receipt():
    plan, _, snapshot, job = _waiting_state()
    attempt_id = projection_recovery_compensation_attempt_id(job)
    commit_ref = _receipt(plan).provider_commit_ref
    receipt_sha256 = compensation_receipt_fingerprint(
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=commit_ref,
    )
    target_fingerprint = compensation_reconciliation_target_fingerprint(
        tenant_id=plan.tenant_id,
        job_id=job.job_id,
        compensation_attempt_id=attempt_id,
        resume_snapshot_sha256=snapshot.snapshot_sha256,
        plan_sha256=plan.plan_sha256,
        plan_idempotency_key=plan.plan_idempotency_key,
    )

    reconciliation = ProjectionRecoveryCompensationReconciliation(
        tenant_id=plan.tenant_id,
        reconciliation_event_id=uuid4(),
        compensation_attempt_id=attempt_id,
        job_id=job.job_id,
        original_approval_case_ref=job.resume_approval_case_ref,
        reconciliation_approval_case_ref=(
            f"gda://{plan.tenant_id}/approval_case/reconcile-committed"
        ),
        target_fingerprint=target_fingerprint,
        resume_snapshot_sha256=snapshot.snapshot_sha256,
        plan_sha256=plan.plan_sha256,
        plan_idempotency_key=plan.plan_idempotency_key,
        strategy="approved_reapply_sealed_plan",
        verdict="provider_committed",
        observed_by="human:recovery-operator",
        observation_ref=(
            f"gda://{plan.tenant_id}/projection_observation/provider-commit-1"
        ),
        observation_sha256="c" * 64,
        reason="provider commit identity was verified against the sealed target",
        provider_commit_ref=commit_ref,
        receipt_sha256=receipt_sha256,
    )

    assert reconciliation.target_fingerprint == target_fingerprint
    with pytest.raises(ValidationError, match="fingerprint"):
        ProjectionRecoveryCompensationReconciliation.model_validate(
            {
                **reconciliation.model_dump(),
                "receipt_sha256": "d" * 64,
            }
        )


def test_not_committed_reconciliation_rejects_receipt_evidence():
    plan, _, snapshot, job = _waiting_state()
    attempt_id = projection_recovery_compensation_attempt_id(job)
    values = {
        "tenant_id": plan.tenant_id,
        "reconciliation_event_id": uuid4(),
        "compensation_attempt_id": attempt_id,
        "job_id": job.job_id,
        "original_approval_case_ref": job.resume_approval_case_ref,
        "reconciliation_approval_case_ref": (
            f"gda://{plan.tenant_id}/approval_case/reconcile-not-committed"
        ),
        "target_fingerprint": compensation_reconciliation_target_fingerprint(
            tenant_id=plan.tenant_id,
            job_id=job.job_id,
            compensation_attempt_id=attempt_id,
            resume_snapshot_sha256=snapshot.snapshot_sha256,
            plan_sha256=plan.plan_sha256,
            plan_idempotency_key=plan.plan_idempotency_key,
        ),
        "verdict": "provider_not_committed",
        "resume_snapshot_sha256": snapshot.snapshot_sha256,
        "plan_sha256": plan.plan_sha256,
        "plan_idempotency_key": plan.plan_idempotency_key,
        "strategy": "approved_reapply_sealed_plan",
        "observed_by": "human:recovery-operator",
        "observation_ref": (
            f"gda://{plan.tenant_id}/projection_observation/provider-absence-1"
        ),
        "observation_sha256": "e" * 64,
        "reason": "provider proved that no commit exists for the idempotency key",
    }
    assert ProjectionRecoveryCompensationReconciliation(**values).receipt_sha256 is None
    with pytest.raises(ValidationError, match="contains a receipt"):
        ProjectionRecoveryCompensationReconciliation(
            **values,
            provider_commit_ref=_receipt(plan).provider_commit_ref,
            receipt_sha256="f" * 64,
        )


def test_provider_failure_records_known_or_unknown_terminal_outcome():
    plan, ledger, snapshot, job = _waiting_state()
    known_authority = _Authority()
    known = _resolver(known_authority)(
        job,
        _Provider(known_failure=True),
        ledger,
    )
    with pytest.raises(ProjectionProviderFailure) as failure:
        known(plan, snapshot)
    assert failure.value.outcome_known is True
    assert known_authority.finish_calls[0]["outcome"] == "failed_known"

    unknown_authority = _Authority()
    unknown = _resolver(unknown_authority)(
        job,
        _Provider(reject_target=True),
        ledger,
    )
    with pytest.raises(ValueError, match="registered target"):
        unknown(plan, snapshot)
    assert unknown_authority.finish_calls[0]["outcome"] == "failed_unknown"
