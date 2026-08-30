from __future__ import annotations

from dataclasses import replace

import pytest

from data_agent.platform_runtime.cross_store_recovery_controller import (
    CrossStoreRecoveryController,
    CrossStoreRecoveryControllerError,
    CrossStoreRecoveryRunState,
    InMemoryCrossStoreRecoveryControllerLedger,
)
from data_agent.test_cross_store_recovery_admission import _admit


def test_controller_restarts_from_durable_protocol_and_completes_idempotently():
    admission = _admit()
    ledger = InMemoryCrossStoreRecoveryControllerLedger()
    controller = CrossStoreRecoveryController("recovery-run-1", ledger=ledger)

    assert controller.snapshot.state is CrossStoreRecoveryRunState.PLANNED
    admitted = controller.admit(admission)
    assert admitted.state is CrossStoreRecoveryRunState.ADMITTED
    assert controller.admit(admission) == admitted

    completed = controller.complete(admission)
    assert completed.state is CrossStoreRecoveryRunState.COMPLETED
    assert controller.complete(admission) == completed

    restarted = CrossStoreRecoveryController("recovery-run-1", ledger=ledger)
    assert restarted.snapshot == completed
    assert len(ledger.history("recovery-run-1")) == 3


def test_controller_can_reconcile_then_complete_only_with_same_binding():
    admission = _admit()
    ledger = InMemoryCrossStoreRecoveryControllerLedger()
    controller = CrossStoreRecoveryController("recovery-run-2", ledger=ledger)
    controller.admit(admission)
    waiting = controller.require_reconciliation("provider restore was interrupted")
    assert waiting.state is CrossStoreRecoveryRunState.RECONCILIATION_REQUIRED
    with pytest.raises(CrossStoreRecoveryControllerError, match="tenant|evidence"):
        controller.reconcile(replace(admission, persisted_tenant_ids=("tenant-a",)))
    reconciled = controller.reconcile(admission)
    assert reconciled.state is CrossStoreRecoveryRunState.ADMITTED
    assert controller.complete(admission).state is CrossStoreRecoveryRunState.COMPLETED


def test_controller_fails_closed_and_never_completes_after_operator_boundary():
    admission = _admit()
    ledger = InMemoryCrossStoreRecoveryControllerLedger()
    controller = CrossStoreRecoveryController("recovery-run-3", ledger=ledger)
    failed = controller.fail_closed("restored object manifest drifted")
    assert failed.state is CrossStoreRecoveryRunState.FAILED_CLOSED
    assert controller.fail_closed("same evidence") == failed
    with pytest.raises(CrossStoreRecoveryControllerError, match="complete"):
        controller.complete(admission)


def test_controller_rejects_partial_admission_and_invalid_recovery_evidence():
    admission = _admit()
    partial = replace(admission, persisted_tenant_ids=("tenant-a",))
    controller = CrossStoreRecoveryController("recovery-run-4")
    with pytest.raises(CrossStoreRecoveryControllerError, match="every binding tenant"):
        controller.admit(partial)
    with pytest.raises(CrossStoreRecoveryControllerError, match="every binding tenant"):
        controller.complete(partial)
