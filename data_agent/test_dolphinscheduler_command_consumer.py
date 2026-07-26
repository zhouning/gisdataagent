from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerReconciliationRequired,
    DolphinSchedulerUnavailableError,
)
from data_agent.dolphinscheduler_command_consumer import (
    DolphinSchedulerCommandConsumer,
)
from data_agent.platform_contracts import PlatformCommand, PlatformCommandStatus

TENANT = "tenant-a"
RUN_ID = UUID("40000000-0000-4000-8000-000000000010")
PLAN_ID = UUID("40000000-0000-4000-8000-000000000020")
COMMAND_ID = UUID("40000000-0000-4000-8000-000000000030")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
WORKER = "worker:command-consumer-1"
ACTOR = "workload:dataops-adapter"


def _command(command_type="dolphinscheduler.dispatch", **overrides):
    values = {
        "tenant_id": TENANT,
        "command_id": COMMAND_ID,
        "run_id": RUN_ID,
        "command_type": command_type,
        "execution_plan_artifact_id": PLAN_ID,
        "dedupe_key": f"{command_type}:{RUN_ID}",
        "actor_subject": ACTOR,
        "status": "in_flight",
        "attempt_count": 1,
        "max_attempts": 5,
        "available_at": NOW,
        "claimed_by": WORKER,
        "claimed_until": NOW + timedelta(minutes=1),
        "created_at": NOW,
    }
    values.update(overrides)
    return PlatformCommand(**values)


class _Gateway:
    def __init__(self, command):
        self.command = command
        self.completed = []
        self.failed = []
        self.deferred = []

    def claim_commands(
        self, tenant_id, worker_id, *, actor_subject, limit, lease_seconds
    ):
        assert (tenant_id, worker_id) == (TENANT, WORKER)
        assert actor_subject == ACTOR
        assert limit == 10
        assert lease_seconds == 60
        return [self.command]

    def complete_command(self, tenant_id, command_id, *, worker_id):
        self.completed.append((tenant_id, command_id, worker_id))
        return self.command.model_copy(
            update={
                "status": PlatformCommandStatus.DONE,
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW,
            }
        )

    def fail_command(
        self,
        tenant_id,
        command_id,
        *,
        worker_id,
        error,
        retry_delay_seconds,
    ):
        self.failed.append(
            (tenant_id, command_id, worker_id, error, retry_delay_seconds)
        )
        terminal = self.command.attempt_count >= self.command.max_attempts
        return self.command.model_copy(
            update={
                "status": (
                    PlatformCommandStatus.FAILED
                    if terminal
                    else PlatformCommandStatus.PENDING
                ),
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW if terminal else None,
            }
        )

    def defer_dispatch_to_reconcile(self, command, *, worker_id):
        self.deferred.append((command.command_id, worker_id))
        return _command("dolphinscheduler.reconcile")


class _Adapter:
    def __init__(self, *, dispatch_error=None, reconcile_error=None):
        self.profile = SimpleNamespace(workload_subject=ACTOR)
        self.gateway = None
        self.dispatch_error = dispatch_error
        self.reconcile_error = reconcile_error
        self.dispatch_calls = []
        self.reconcile_calls = []

    def dispatch(self, *args, **kwargs):
        self.dispatch_calls.append((args, kwargs))
        if self.dispatch_error:
            raise self.dispatch_error

    def reconcile(self, *args, **kwargs):
        self.reconcile_calls.append((args, kwargs))
        if self.reconcile_error:
            raise self.reconcile_error


def test_consumer_completes_successful_dispatch():
    gateway = _Gateway(_command())
    adapter = _Adapter()
    result = DolphinSchedulerCommandConsumer(adapter, gateway=gateway).run_once(
        TENANT, worker_id=WORKER
    )

    assert result.completed == 1
    assert result.claimed == 1
    assert len(adapter.dispatch_calls) == 1
    assert gateway.completed == [(TENANT, COMMAND_ID, WORKER)]


def test_consumer_defers_unknown_dispatch_to_reconcile_atomically():
    gateway = _Gateway(_command())
    adapter = _Adapter(
        dispatch_error=DolphinSchedulerReconciliationRequired("unknown outcome")
    )
    result = DolphinSchedulerCommandConsumer(adapter, gateway=gateway).run_once(
        TENANT, worker_id=WORKER
    )

    assert result.deferred_to_reconcile == 1
    assert gateway.deferred == [(COMMAND_ID, WORKER)]
    assert gateway.completed == []
    assert gateway.failed == []


def test_consumer_retries_reconcile_failure_with_backoff():
    gateway = _Gateway(_command("dolphinscheduler.reconcile"))
    adapter = _Adapter(reconcile_error=DolphinSchedulerUnavailableError("offline"))
    result = DolphinSchedulerCommandConsumer(adapter, gateway=gateway).run_once(
        TENANT, worker_id=WORKER
    )

    assert result.retry_pending == 1
    assert len(adapter.reconcile_calls) == 1
    assert gateway.failed[0][-1] == 30
    assert "offline" in gateway.failed[0][-2]


def test_consumer_stops_retrying_at_command_attempt_limit():
    gateway = _Gateway(
        _command(
            "dolphinscheduler.reconcile",
            attempt_count=3,
            max_attempts=3,
        )
    )
    adapter = _Adapter(reconcile_error=DolphinSchedulerUnavailableError("offline"))
    result = DolphinSchedulerCommandConsumer(adapter, gateway=gateway).run_once(
        TENANT, worker_id=WORKER
    )

    assert result.failed == 1
    assert result.retry_pending == 0
