from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from data_agent.cross_store_projection_federated_recovery import (
    FederatedProjectionItemSnapshot,
    FederatedProjectionItemState,
    FederatedProjectionRecoveryCoordinator,
    FederatedProjectionRecoveryError,
    FederatedProjectionRecoveryEvent,
    FederatedProjectionRecoverySnapshot,
    FederatedProjectionRecoveryState,
    InMemoryFederatedProjectionRecoveryLedger,
    federated_projection_item_fingerprint,
)
from data_agent.cross_store_projection_recovery import (
    InMemoryProjectionRecoveryLedger,
)
from data_agent.cross_store_projection_recovery_worker import (
    ProjectionProviderFailure,
)

TENANT = "cq-federated-recovery"
NOW = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
ENGINES = (
    ProjectionEngine.POSTGIS,
    ProjectionEngine.RDF,
    ProjectionEngine.LAKEHOUSE,
)


def _plans(*, tenant_id: str = TENANT):
    plans = []
    for position, engine in enumerate(ENGINES):
        projection_id = f"cq.federated.{engine.value}"
        target_ref = f"{engine.value}://cq-customer/{projection_id}"
        target_sha = f"{position + 1:x}" * 64
        desired = ProjectionDesiredState(
            tenant_id=tenant_id,
            projection_id=projection_id,
            source_resource_version_ref=(f"gda://{tenant_id}/data_product/federated-source-v1"),
            source_content_sha256=f"{position + 4:x}" * 64,
            target_engine=engine,
            target_ref=target_ref,
            target_exists=True,
            expected_target_content_sha256=target_sha,
            expected_row_count=100 + position,
        )
        observation = ProjectionTargetObservation(
            tenant_id=tenant_id,
            projection_id=projection_id,
            target_engine=engine,
            target_ref=target_ref,
            target_exists=False,
            observed_content_sha256=None,
            observed_row_count=0,
            observed_by="workload:federated-recovery-test",
            observed_at=NOW,
        )
        plans.append(build_projection_repair_plan(desired, observation, None))
    return tuple(plans)


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
        observed_by="workload:federated-recovery-provider",
        observed_at=NOW + timedelta(seconds=1),
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


class _Provider:
    def __init__(self, mode="success"):
        self.mode = mode
        self.execute_count = 0
        self.observe_count = 0
        self.recover_count = 0

    def execute(self, plan):
        self.execute_count += 1
        if self.mode == "known_no_commit":
            raise ProjectionProviderFailure(
                "provider_rejected_before_commit",
                outcome_known=True,
            )
        if self.mode in {"unknown_with_receipt", "unknown_without_receipt"}:
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
        if self.mode == "unknown_with_receipt":
            return _receipt(plan)
        return None


class _Authority:
    def __init__(self, *, fail_once=False):
        self.ledger = InMemoryProjectionCheckpointLedger()
        self.fail_once = fail_once
        self.record_count = 0

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        self.record_count += 1
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("postgresql_unavailable")
        return self.ledger.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )

    def history(self, **identity):
        return self.ledger.history(**identity)


def _coordinator(
    plans,
    providers,
    authorities,
    *,
    run_id="cq-federated-run",
    ledger=None,
    plan_ledgers=None,
    max_provider_attempts=3,
):
    return FederatedProjectionRecoveryCoordinator(
        run_id,
        plans,
        checkpointed_by="workload:federated-recovery-test",
        provider_resolver=lambda plan: providers[plan.plan_sha256],
        authority_resolver=lambda plan: authorities[plan.plan_sha256],
        ledger=ledger,
        plan_ledger_resolver=(
            (lambda plan: plan_ledgers[plan.plan_sha256]) if plan_ledgers is not None else None
        ),
        max_provider_attempts=max_provider_attempts,
        now=lambda: NOW + timedelta(seconds=2),
    )


def _dependencies(plans, *, provider_modes=None, authority_fail_index=None):
    provider_modes = provider_modes or {}
    providers = {
        plan.plan_sha256: _Provider(provider_modes.get(position, "success"))
        for position, plan in enumerate(plans)
    }
    authorities = {
        plan.plan_sha256: _Authority(fail_once=position == authority_fail_index)
        for position, plan in enumerate(plans)
    }
    return providers, authorities


def test_three_different_providers_complete_in_sealed_plan_order():
    plans = _plans()
    providers, authorities = _dependencies(plans)

    snapshot = _coordinator(plans, providers, authorities).advance()

    assert snapshot.state is FederatedProjectionRecoveryState.COMPLETED
    assert snapshot.current_position == 3
    assert snapshot.committed_plan_sha256s == tuple(plan.plan_sha256 for plan in plans)
    assert all(provider.execute_count == 1 for provider in providers.values())
    assert [item.target_engine for item in snapshot.items] == [engine.value for engine in ENGINES]
    assert (
        FederatedProjectionRecoverySnapshot.model_validate(snapshot.model_dump(mode="json"))
        == snapshot
    )


def test_middle_authority_retry_does_not_replay_provider():
    plans = _plans()
    providers, authorities = _dependencies(plans, authority_fail_index=1)

    snapshot = _coordinator(plans, providers, authorities).advance()

    middle = snapshot.items[1]
    assert snapshot.state is FederatedProjectionRecoveryState.COMPLETED
    assert providers[plans[1].plan_sha256].execute_count == 1
    assert authorities[plans[1].plan_sha256].record_count == 2
    assert middle.provider_attempts == 1
    assert middle.authority_attempts == 2
    assert middle.last_error_code == "postgresql_unavailable"
    assert snapshot.last_error_code == "postgresql_unavailable"


def test_unknown_outcome_recovers_provider_receipt_and_continues():
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_with_receipt"},
    )

    snapshot = _coordinator(plans, providers, authorities).advance()

    middle_provider = providers[plans[1].plan_sha256]
    assert snapshot.state is FederatedProjectionRecoveryState.COMPLETED
    assert middle_provider.execute_count == 1
    assert middle_provider.recover_count == 1
    assert snapshot.items[1].provider_attempts == 1
    assert snapshot.items[1].provider_commit_ref is not None


def test_missing_receipt_requires_compensation_and_never_starts_later_plan():
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )

    snapshot = _coordinator(plans, providers, authorities).advance()

    assert snapshot.state is FederatedProjectionRecoveryState.COMPENSATION_REQUIRED
    assert snapshot.current_position == 1
    assert snapshot.committed_plan_sha256s == (plans[0].plan_sha256,)
    assert snapshot.items[1].state is FederatedProjectionItemState.COMPENSATION_REQUIRED
    assert providers[plans[2].plan_sha256].execute_count == 0
    assert snapshot.items[2].state is FederatedProjectionItemState.PENDING


def test_known_no_commit_exhausts_retry_budget_and_fails_closed():
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "known_no_commit"},
    )

    snapshot = _coordinator(
        plans,
        providers,
        authorities,
        max_provider_attempts=2,
    ).advance()

    assert snapshot.state is FederatedProjectionRecoveryState.FAILED_CLOSED
    assert snapshot.current_position == 1
    assert snapshot.items[1].state is FederatedProjectionItemState.FAILED_CLOSED
    assert snapshot.items[1].provider_attempts == 2
    assert providers[plans[1].plan_sha256].execute_count == 2
    assert providers[plans[2].plan_sha256].execute_count == 0


def test_restart_resumes_from_durable_per_plan_ledger_without_provider_replay():
    plans = _plans()
    providers, authorities = _dependencies(plans, authority_fail_index=1)
    aggregate_ledger = InMemoryFederatedProjectionRecoveryLedger()
    plan_ledgers = {plan.plan_sha256: InMemoryProjectionRecoveryLedger() for plan in plans}
    first = _coordinator(
        plans,
        providers,
        authorities,
        ledger=aggregate_ledger,
        plan_ledgers=plan_ledgers,
    )

    yielded = first.advance(max_steps_per_item=1)

    assert yielded.state is FederatedProjectionRecoveryState.RUNNING
    assert yielded.next_action == "retry_item"
    assert yielded.current_position == 1
    assert providers[plans[1].plan_sha256].execute_count == 1
    assert providers[plans[2].plan_sha256].execute_count == 0

    resumed = _coordinator(
        plans,
        providers,
        authorities,
        ledger=aggregate_ledger,
        plan_ledgers=plan_ledgers,
    ).advance()

    assert resumed.state is FederatedProjectionRecoveryState.COMPLETED
    assert providers[plans[1].plan_sha256].execute_count == 1
    assert providers[plans[2].plan_sha256].execute_count == 1


def test_run_identity_cross_tenant_and_duplicate_plans_are_rejected():
    plans = _plans()
    providers, authorities = _dependencies(plans)
    ledger = InMemoryFederatedProjectionRecoveryLedger()
    _coordinator(plans, providers, authorities, ledger=ledger)

    with pytest.raises(FederatedProjectionRecoveryError, match="identity"):
        _coordinator(tuple(reversed(plans)), providers, authorities, ledger=ledger)

    other_tenant_plan = _plans(tenant_id="cq-other-tenant")[0]
    cross_tenant = (plans[0], other_tenant_plan)
    cross_providers, cross_authorities = _dependencies(cross_tenant)
    with pytest.raises(FederatedProjectionRecoveryError, match="tenant"):
        _coordinator(cross_tenant, cross_providers, cross_authorities)

    duplicate = (plans[0], plans[0])
    with pytest.raises(FederatedProjectionRecoveryError, match="unique"):
        _coordinator(duplicate, providers, authorities)


def test_item_event_snapshot_fingerprints_and_recovery_state_contracts_reject_tampering():
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )
    snapshot = _coordinator(plans, providers, authorities).advance()

    item_data = snapshot.items[0].model_dump(mode="json")
    item_data["projection_id"] = "cq.tampered.projection"
    with pytest.raises(ValidationError, match="fingerprint"):
        FederatedProjectionItemSnapshot.model_validate(item_data)

    event_data = snapshot.events[0].model_dump(mode="json")
    event_data["detail"] = {"plan_count": 99}
    with pytest.raises(ValidationError, match="fingerprint"):
        FederatedProjectionRecoveryEvent.model_validate(event_data)

    snapshot_data = snapshot.model_dump(mode="json")
    snapshot_data["last_error_code"] = "fabricated_error"
    with pytest.raises(ValidationError, match="fingerprint"):
        FederatedProjectionRecoverySnapshot.model_validate(snapshot_data)

    blocked_item = snapshot.items[1]
    invalid_state = blocked_item.model_dump(mode="json", exclude={"item_sha256"})
    invalid_state.update(
        {
            "state": FederatedProjectionItemState.RECOVERY_REQUIRED,
            "worker_next_action": "manual_compensation",
        }
    )
    with pytest.raises(ValidationError, match="re-observation evidence"):
        FederatedProjectionItemSnapshot(
            **invalid_state,
            item_sha256=federated_projection_item_fingerprint(**invalid_state),
        )
