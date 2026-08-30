from __future__ import annotations

from typing import Literal

from data_agent.cross_store_projection_compensation_chongqing_internal_execution import (
    _issue_chongqing_federated_compensation_technical_test_execution_permit,
)


def _technical_execution_permit(
    intent,
    registry,
    *,
    purpose: Literal[
        "technical_contract_test",
        "reconciliation_fixture",
    ] = "technical_contract_test",
):
    return _issue_chongqing_federated_compensation_technical_test_execution_permit(
        intent=intent,
        registry=registry,
        purpose=purpose,
        production_execution_authorized=False,
    )
