from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from data_agent.uwm.abu_dhabi_flood import (
    SolverWindowBalance,
    SwmmAnugaCouplingInterface,
    SwmmAnugaCouplingQualityPolicy,
    SwmmAnugaCouplingWindow,
    SwmmAnugaTransfer,
    build_swmm_anuga_coupling_receipt,
    evaluate_swmm_anuga_coupling,
)


def _interface(*, maximum_exchange_rate_m3s: float = 0.1):
    return SwmmAnugaCouplingInterface(
        interface_id="manhole-a-surface-zone-a",
        swmm_node_id="swmm-node-a",
        anuga_region_id="anuga-region-a",
        maximum_exchange_rate_m3s=maximum_exchange_rate_m3s,
        provenance_id="fixture:coupling-interface-a",
    )


def _transfers() -> tuple[SwmmAnugaTransfer, ...]:
    return (
        SwmmAnugaTransfer(
            transfer_id="surcharge-a",
            interface_id="manhole-a-surface-zone-a",
            direction="swmm_to_anuga",
            window_start_seconds=0.0,
            window_end_seconds=300.0,
            volume_m3=12.0,
            provenance_id="fixture:swmm-surcharge-a",
        ),
        SwmmAnugaTransfer(
            transfer_id="surface-return-a",
            interface_id="manhole-a-surface-zone-a",
            direction="anuga_to_swmm",
            window_start_seconds=0.0,
            window_end_seconds=300.0,
            volume_m3=3.0,
            provenance_id="fixture:anuga-surface-return-a",
        ),
    )


def _swmm_balance(**changes: float) -> SolverWindowBalance:
    values = {
        "solver_id": "epa_swmm",
        "solver_run_reference_id": "receipt:swmm-synthetic",
        "window_start_seconds": 0.0,
        "window_end_seconds": 300.0,
        "storage_start_m3": 100.0,
        "storage_end_m3": 106.0,
        "external_inflow_m3": 20.0,
        "external_outflow_m3": 5.0,
        "sent_to_counterpart_m3": 12.0,
        "received_from_counterpart_m3": 3.0,
        "provenance_id": "fixture:swmm-balance",
    }
    values.update(changes)
    return SolverWindowBalance(**values)


def _anuga_balance(**changes: float) -> SolverWindowBalance:
    values = {
        "solver_id": "anuga_2d",
        "solver_run_reference_id": "receipt:anuga-synthetic",
        "window_start_seconds": 0.0,
        "window_end_seconds": 300.0,
        "storage_start_m3": 50.0,
        "storage_end_m3": 65.0,
        "external_inflow_m3": 10.0,
        "external_outflow_m3": 4.0,
        "sent_to_counterpart_m3": 3.0,
        "received_from_counterpart_m3": 12.0,
        "provenance_id": "fixture:anuga-balance",
    }
    values.update(changes)
    return SolverWindowBalance(**values)


def _window(
    *,
    interface: SwmmAnugaCouplingInterface | None = None,
    transfers: tuple[SwmmAnugaTransfer, ...] | None = None,
    balances: tuple[SolverWindowBalance, ...] | None = None,
) -> SwmmAnugaCouplingWindow:
    return SwmmAnugaCouplingWindow(
        run_id="abu-dhabi-swmm-anuga-synthetic-coupling-contract",
        window_start_seconds=0.0,
        window_end_seconds=300.0,
        interfaces=(interface or _interface(),),
        transfers=transfers or _transfers(),
        balances=balances or (_swmm_balance(), _anuga_balance()),
    )


def _canonical_sha256(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def test_synthetic_bidirectional_exchange_closes_solver_and_system_ledgers():
    quality = evaluate_swmm_anuga_coupling(
        _window(), SwmmAnugaCouplingQualityPolicy()
    )

    assert quality["passed"] is True
    assert quality["failed_checks"] == []
    assert quality["ledger"] == {
        "swmm_to_anuga_transfer_m3": 12.0,
        "anuga_to_swmm_transfer_m3": 3.0,
        "gross_transfer_volume_by_interface_m3": {
            "manhole-a-surface-zone-a": 15.0
        },
        "coupled_storage_change_m3": 21.0,
        "external_inflow_m3": 30.0,
        "external_outflow_m3": 9.0,
        "coupled_mass_balance_residual_m3": 0.0,
    }
    assert quality["admission_effect"] == "none_diagnostic_quality_only"


@pytest.mark.parametrize(
    ("balances", "failed_check"),
    [
        (
            (_swmm_balance(), _anuga_balance(received_from_counterpart_m3=11.0)),
            "anuga_received_matches_swmm_surcharge_volume",
        ),
        (
            (_swmm_balance(storage_end_m3=106.5), _anuga_balance()),
            "swmm_ledger_mass_balance_within_threshold",
        ),
        (
            (
                _swmm_balance(storage_end_m3=106.5),
                _anuga_balance(storage_end_m3=65.5),
            ),
            "coupled_system_mass_balance_within_threshold",
        ),
    ],
)
def test_quality_gate_rejects_transfer_and_mass_ledger_disagreement(
    balances: tuple[SolverWindowBalance, ...], failed_check: str
):
    quality = evaluate_swmm_anuga_coupling(
        _window(balances=balances), SwmmAnugaCouplingQualityPolicy()
    )

    assert quality["passed"] is False
    assert failed_check in quality["failed_checks"]


def test_exchange_capacity_is_enforced_over_the_shared_window():
    quality = evaluate_swmm_anuga_coupling(
        _window(interface=_interface(maximum_exchange_rate_m3s=0.04)),
        SwmmAnugaCouplingQualityPolicy(),
    )

    assert quality["passed"] is False
    assert "all_interfaces_within_exchange_capacity" in quality["failed_checks"]


def test_unknown_interface_and_misaligned_window_fail_during_contract_construction():
    unknown = replace(_transfers()[0], interface_id="unknown-interface")
    with pytest.raises(
        ValueError, match="swmm_anuga_coupling_transfer_interface_unknown"
    ):
        _window(transfers=(unknown, _transfers()[1]))

    misaligned = replace(_transfers()[0], window_end_seconds=299.0)
    with pytest.raises(
        ValueError, match="swmm_anuga_coupling_transfer_window_mismatch"
    ):
        _window(transfers=(misaligned, _transfers()[1]))


def test_negative_volume_direction_and_admission_bypass_are_rejected():
    with pytest.raises(ValueError, match="swmm_anuga_transfer_volume_m3_invalid"):
        replace(_transfers()[0], volume_m3=-1.0)
    with pytest.raises(ValueError, match="swmm_anuga_transfer_direction_invalid"):
        replace(_transfers()[0], direction="ambiguous")
    with pytest.raises(ValueError, match="swmm_anuga_interface_cannot_grant_admission"):
        replace(_interface(), admitted=True)
    with pytest.raises(ValueError, match="swmm_anuga_coupling_cannot_grant_admission"):
        replace(_window(), traditional_model_admitted=True)


def test_contract_receipt_is_self_hashed_and_cannot_claim_actual_coupled_execution():
    receipt = build_swmm_anuga_coupling_receipt(
        _window(), SwmmAnugaCouplingQualityPolicy()
    )

    assert receipt["status"] == "validated_synthetic_coupling_contract_not_admitted"
    assert receipt["quality_gates"]["passed"] is True
    assert receipt["coupling_window"]["quantity"] == {
        "name": "water_volume",
        "unit": "m3",
    }
    assert receipt["execution"] == {
        "solver_execution_invoked_by_coupling_component": False,
        "actual_swmm_anuga_coupled_run": False,
        "contract_only_synthetic_ledger": True,
        "engineering_interface_data_admitted": False,
    }
    assert receipt["admission"]["traditional_model_admitted"] is False
    assert receipt["admission"]["gwm_training_admitted"] is False
    assert receipt["admission"]["production_admitted"] is False
    assert receipt["admission"]["city_scale_prediction_claim_allowed"] is False

    receipt_hash = receipt.pop("receipt_sha256")
    assert receipt_hash == _canonical_sha256(receipt)


def test_receipt_builder_fails_closed_when_quality_gate_fails():
    invalid = _window(balances=(_swmm_balance(), _anuga_balance(storage_end_m3=66.0)))

    with pytest.raises(ValueError, match="swmm_anuga_coupling_quality_gate_failed"):
        build_swmm_anuga_coupling_receipt(
            invalid, SwmmAnugaCouplingQualityPolicy()
        )
