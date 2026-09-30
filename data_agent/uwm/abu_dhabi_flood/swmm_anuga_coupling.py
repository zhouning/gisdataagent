"""Fail-closed volume-exchange contract for diagnostic SWMM--ANUGA coupling.

This module reconciles normalized solver ledgers.  It deliberately does not
invoke either solver or infer inlet, manhole, boundary, elevation, or exchange
capacity data from public candidate layers.  Those engineering inputs remain
blocked by K0.  The contract is executable with synthetic ledgers so future
1-D/2-D integration has fixed direction, time-window, volume, and mass-balance
semantics before an Abu Dhabi coupling run is allowed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

SWMM_ANUGA_COUPLING_WINDOW_SCHEMA = "gwm.abu_dhabi_flood.swmm_anuga_coupling_window.v1"
SWMM_ANUGA_COUPLING_POLICY_SCHEMA = "gwm.abu_dhabi_flood.swmm_anuga_coupling_policy.v1"
SWMM_ANUGA_COUPLING_RECEIPT_SCHEMA = "gwm.abu_dhabi_flood.swmm_anuga_coupling_receipt.v1"

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SOLVERS = frozenset({"epa_swmm", "anuga_2d"})
_DIRECTIONS = frozenset({"swmm_to_anuga", "anuga_to_swmm"})
_EVIDENCE_CLASSES = frozenset({"synthetic_fixture", "public_proxy"})


def _finite_nonnegative(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"swmm_anuga_{field}_invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"swmm_anuga_{field}_invalid")
    return result


def _finite(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"swmm_anuga_{field}_invalid")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"swmm_anuga_{field}_invalid")
    return result


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"swmm_anuga_{field}_invalid")
    return value


@dataclass(frozen=True)
class SwmmAnugaCouplingInterface:
    """One explicit SWMM-node to ANUGA-surface exchange interface."""

    interface_id: str
    swmm_node_id: str
    anuga_region_id: str
    maximum_exchange_rate_m3s: float
    provenance_id: str
    evidence_class: str = "synthetic_fixture"
    diagnostic_only: bool = True
    admitted: bool = False

    def __post_init__(self) -> None:
        for field in ("interface_id", "swmm_node_id", "anuga_region_id", "provenance_id"):
            _identifier(getattr(self, field), field)
        _finite_nonnegative(self.maximum_exchange_rate_m3s, "maximum_exchange_rate_m3s")
        if self.evidence_class not in _EVIDENCE_CLASSES:
            raise ValueError("swmm_anuga_interface_evidence_class_invalid")
        if self.diagnostic_only is not True or self.admitted is not False:
            raise ValueError("swmm_anuga_interface_cannot_grant_admission")

    def as_dict(self) -> dict[str, object]:
        return {
            "interface_id": self.interface_id,
            "swmm_node_id": self.swmm_node_id,
            "anuga_region_id": self.anuga_region_id,
            "maximum_exchange_rate_m3s": float(self.maximum_exchange_rate_m3s),
            "provenance_id": self.provenance_id,
            "evidence_class": self.evidence_class,
            "diagnostic_only": True,
            "admitted": False,
        }


@dataclass(frozen=True)
class SwmmAnugaTransfer:
    """A canonical one-way water-volume transfer for one fixed coupling window."""

    transfer_id: str
    interface_id: str
    direction: str
    window_start_seconds: float
    window_end_seconds: float
    volume_m3: float
    provenance_id: str

    def __post_init__(self) -> None:
        for field in ("transfer_id", "interface_id", "provenance_id"):
            _identifier(getattr(self, field), field)
        if self.direction not in _DIRECTIONS:
            raise ValueError("swmm_anuga_transfer_direction_invalid")
        start = _finite(self.window_start_seconds, "transfer_window_start_seconds")
        end = _finite(self.window_end_seconds, "transfer_window_end_seconds")
        if end <= start:
            raise ValueError("swmm_anuga_transfer_window_invalid")
        _finite_nonnegative(self.volume_m3, "transfer_volume_m3")

    @property
    def source_solver_id(self) -> str:
        return "epa_swmm" if self.direction == "swmm_to_anuga" else "anuga_2d"

    @property
    def destination_solver_id(self) -> str:
        return "anuga_2d" if self.direction == "swmm_to_anuga" else "epa_swmm"

    def as_dict(self) -> dict[str, object]:
        return {
            "transfer_id": self.transfer_id,
            "interface_id": self.interface_id,
            "direction": self.direction,
            "source_solver_id": self.source_solver_id,
            "destination_solver_id": self.destination_solver_id,
            "window_start_seconds": float(self.window_start_seconds),
            "window_end_seconds": float(self.window_end_seconds),
            "volume_m3": float(self.volume_m3),
            "provenance_id": self.provenance_id,
        }


@dataclass(frozen=True)
class SolverWindowBalance:
    """Normalized storage ledger independently reported by either solver."""

    solver_id: str
    solver_run_reference_id: str
    window_start_seconds: float
    window_end_seconds: float
    storage_start_m3: float
    storage_end_m3: float
    external_inflow_m3: float
    external_outflow_m3: float
    sent_to_counterpart_m3: float
    received_from_counterpart_m3: float
    provenance_id: str

    def __post_init__(self) -> None:
        if self.solver_id not in _SOLVERS:
            raise ValueError("swmm_anuga_balance_solver_invalid")
        for field in ("solver_run_reference_id", "provenance_id"):
            _identifier(getattr(self, field), field)
        start = _finite(self.window_start_seconds, "balance_window_start_seconds")
        end = _finite(self.window_end_seconds, "balance_window_end_seconds")
        if end <= start:
            raise ValueError("swmm_anuga_balance_window_invalid")
        for field in (
            "storage_start_m3",
            "storage_end_m3",
            "external_inflow_m3",
            "external_outflow_m3",
            "sent_to_counterpart_m3",
            "received_from_counterpart_m3",
        ):
            _finite_nonnegative(getattr(self, field), field)

    @property
    def storage_change_m3(self) -> float:
        return float(self.storage_end_m3 - self.storage_start_m3)

    @property
    def mass_balance_residual_m3(self) -> float:
        return float(
            self.storage_change_m3
            - self.external_inflow_m3
            - self.received_from_counterpart_m3
            + self.external_outflow_m3
            + self.sent_to_counterpart_m3
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "solver_id": self.solver_id,
            "solver_run_reference_id": self.solver_run_reference_id,
            "window_start_seconds": float(self.window_start_seconds),
            "window_end_seconds": float(self.window_end_seconds),
            "storage_start_m3": float(self.storage_start_m3),
            "storage_end_m3": float(self.storage_end_m3),
            "storage_change_m3": self.storage_change_m3,
            "external_inflow_m3": float(self.external_inflow_m3),
            "external_outflow_m3": float(self.external_outflow_m3),
            "sent_to_counterpart_m3": float(self.sent_to_counterpart_m3),
            "received_from_counterpart_m3": float(self.received_from_counterpart_m3),
            "mass_balance_residual_m3": self.mass_balance_residual_m3,
            "provenance_id": self.provenance_id,
        }


@dataclass(frozen=True)
class SwmmAnugaCouplingQualityPolicy:
    """Numerical and reconciliation thresholds for a diagnostic coupling window."""

    maximum_absolute_solver_mass_balance_residual_m3: float = 1.0e-8
    maximum_absolute_coupled_mass_balance_residual_m3: float = 1.0e-8
    maximum_absolute_transfer_reconciliation_difference_m3: float = 1.0e-8
    require_exact_window_alignment: bool = True

    def __post_init__(self) -> None:
        for field in (
            "maximum_absolute_solver_mass_balance_residual_m3",
            "maximum_absolute_coupled_mass_balance_residual_m3",
            "maximum_absolute_transfer_reconciliation_difference_m3",
        ):
            _finite_nonnegative(getattr(self, field), field)
        if not isinstance(self.require_exact_window_alignment, bool):
            raise ValueError("swmm_anuga_coupling_window_alignment_flag_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SWMM_ANUGA_COUPLING_POLICY_SCHEMA,
            "maximum_absolute_solver_mass_balance_residual_m3": float(
                self.maximum_absolute_solver_mass_balance_residual_m3
            ),
            "maximum_absolute_coupled_mass_balance_residual_m3": float(
                self.maximum_absolute_coupled_mass_balance_residual_m3
            ),
            "maximum_absolute_transfer_reconciliation_difference_m3": float(
                self.maximum_absolute_transfer_reconciliation_difference_m3
            ),
            "require_exact_window_alignment": self.require_exact_window_alignment,
        }


@dataclass(frozen=True)
class SwmmAnugaCouplingWindow:
    """All normalized SWMM and ANUGA water ledgers for one shared time interval."""

    run_id: str
    window_start_seconds: float
    window_end_seconds: float
    interfaces: tuple[SwmmAnugaCouplingInterface, ...]
    transfers: tuple[SwmmAnugaTransfer, ...]
    balances: tuple[SolverWindowBalance, ...]
    evidence_class: str = "synthetic_fixture"
    diagnostic_only: bool = True
    traditional_model_admitted: bool = False
    gwm_training_admitted: bool = False
    production_admitted: bool = False

    def __post_init__(self) -> None:
        _identifier(self.run_id, "coupling_run_id")
        start = _finite(self.window_start_seconds, "coupling_window_start_seconds")
        end = _finite(self.window_end_seconds, "coupling_window_end_seconds")
        if end <= start:
            raise ValueError("swmm_anuga_coupling_window_invalid")
        if self.evidence_class not in _EVIDENCE_CLASSES:
            raise ValueError("swmm_anuga_coupling_evidence_class_invalid")
        if (
            self.diagnostic_only is not True
            or self.traditional_model_admitted is not False
            or self.gwm_training_admitted is not False
            or self.production_admitted is not False
        ):
            raise ValueError("swmm_anuga_coupling_cannot_grant_admission")
        if not self.interfaces:
            raise ValueError("swmm_anuga_coupling_interfaces_required")
        interface_ids = tuple(interface.interface_id for interface in self.interfaces)
        if len(set(interface_ids)) != len(interface_ids):
            raise ValueError("swmm_anuga_coupling_interface_ids_must_be_unique")
        transfer_ids = tuple(transfer.transfer_id for transfer in self.transfers)
        if len(set(transfer_ids)) != len(transfer_ids):
            raise ValueError("swmm_anuga_coupling_transfer_ids_must_be_unique")
        for transfer in self.transfers:
            if transfer.interface_id not in interface_ids:
                raise ValueError("swmm_anuga_coupling_transfer_interface_unknown")
            if (
                transfer.window_start_seconds != start
                or transfer.window_end_seconds != end
            ):
                raise ValueError("swmm_anuga_coupling_transfer_window_mismatch")
        if len(self.balances) != 2 or {balance.solver_id for balance in self.balances} != _SOLVERS:
            raise ValueError("swmm_anuga_coupling_solver_balances_required")
        for balance in self.balances:
            if balance.window_start_seconds != start or balance.window_end_seconds != end:
                raise ValueError("swmm_anuga_coupling_balance_window_mismatch")

    @property
    def balance_by_solver_id(self) -> dict[str, SolverWindowBalance]:
        return {balance.solver_id: balance for balance in self.balances}

    def claim_boundary(self) -> dict[str, object]:
        return {
            "diagnostic_only": True,
            "numerical_quality_is_not_engineering_validation": True,
            "traditional_model_admitted": False,
            "gwm_training_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
            "separate_k0_k1_k2_review_required_for_any_admission": True,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SWMM_ANUGA_COUPLING_WINDOW_SCHEMA,
            "run_id": self.run_id,
            "window_start_seconds": float(self.window_start_seconds),
            "window_end_seconds": float(self.window_end_seconds),
            "quantity": {"name": "water_volume", "unit": "m3"},
            "interfaces": [interface.as_dict() for interface in self.interfaces],
            "transfers": [transfer.as_dict() for transfer in self.transfers],
            "balances": [balance.as_dict() for balance in self.balances],
            "input_governance": {
                "evidence_class": self.evidence_class,
                "diagnostic_only": True,
            },
            "claim_boundary": self.claim_boundary(),
        }


def evaluate_swmm_anuga_coupling(
    window: SwmmAnugaCouplingWindow,
    policy: SwmmAnugaCouplingQualityPolicy,
) -> dict[str, object]:
    """Evaluate transfer reconciliation and system-level mass balance."""

    if not isinstance(window, SwmmAnugaCouplingWindow):
        raise ValueError("swmm_anuga_coupling_window_required")
    if not isinstance(policy, SwmmAnugaCouplingQualityPolicy):
        raise ValueError("swmm_anuga_coupling_quality_policy_required")
    balances = window.balance_by_solver_id
    swmm = balances["epa_swmm"]
    anuga = balances["anuga_2d"]
    swmm_to_anuga = sum(
        transfer.volume_m3
        for transfer in window.transfers
        if transfer.direction == "swmm_to_anuga"
    )
    anuga_to_swmm = sum(
        transfer.volume_m3
        for transfer in window.transfers
        if transfer.direction == "anuga_to_swmm"
    )
    coupled_storage_change = swmm.storage_change_m3 + anuga.storage_change_m3
    external_inflow = swmm.external_inflow_m3 + anuga.external_inflow_m3
    external_outflow = swmm.external_outflow_m3 + anuga.external_outflow_m3
    coupled_residual = coupled_storage_change - external_inflow + external_outflow
    duration_seconds = window.window_end_seconds - window.window_start_seconds
    transfer_volume_by_interface = {
        interface.interface_id: sum(
            transfer.volume_m3
            for transfer in window.transfers
            if transfer.interface_id == interface.interface_id
        )
        for interface in window.interfaces
    }
    interface_capacity_observations = [
        {
            "interface_id": interface.interface_id,
            "gross_transfer_volume_m3": transfer_volume_by_interface[
                interface.interface_id
            ],
            "maximum_window_volume_m3": (
                interface.maximum_exchange_rate_m3s * duration_seconds
            ),
        }
        for interface in window.interfaces
    ]
    interfaces_within_capacity = all(
        observation["gross_transfer_volume_m3"]
        <= observation["maximum_window_volume_m3"]
        for observation in interface_capacity_observations
    )
    window_aligned = all(
        transfer.window_start_seconds == window.window_start_seconds
        and transfer.window_end_seconds == window.window_end_seconds
        for transfer in window.transfers
    ) and all(
        balance.window_start_seconds == window.window_start_seconds
        and balance.window_end_seconds == window.window_end_seconds
        for balance in window.balances
    )
    checks = [
        _check(
            "all_exchange_windows_align_exactly",
            not policy.require_exact_window_alignment or window_aligned,
            window_aligned,
            True,
        ),
        _check(
            "all_interfaces_within_exchange_capacity",
            interfaces_within_capacity,
            interface_capacity_observations,
            "gross_transfer_volume_m3 <= maximum_window_volume_m3",
        ),
        _check(
            "swmm_surcharge_matches_anuga_received_volume",
            abs(swmm.sent_to_counterpart_m3 - swmm_to_anuga)
            <= policy.maximum_absolute_transfer_reconciliation_difference_m3,
            {
                "swmm_sent_m3": swmm.sent_to_counterpart_m3,
                "canonical_transfer_m3": swmm_to_anuga,
                "anuga_received_m3": anuga.received_from_counterpart_m3,
            },
            policy.maximum_absolute_transfer_reconciliation_difference_m3,
        ),
        _check(
            "anuga_received_matches_swmm_surcharge_volume",
            abs(anuga.received_from_counterpart_m3 - swmm_to_anuga)
            <= policy.maximum_absolute_transfer_reconciliation_difference_m3,
            {
                "anuga_received_m3": anuga.received_from_counterpart_m3,
                "canonical_transfer_m3": swmm_to_anuga,
            },
            policy.maximum_absolute_transfer_reconciliation_difference_m3,
        ),
        _check(
            "anuga_return_matches_swmm_received_volume",
            abs(anuga.sent_to_counterpart_m3 - anuga_to_swmm)
            <= policy.maximum_absolute_transfer_reconciliation_difference_m3,
            {
                "anuga_sent_m3": anuga.sent_to_counterpart_m3,
                "canonical_transfer_m3": anuga_to_swmm,
                "swmm_received_m3": swmm.received_from_counterpart_m3,
            },
            policy.maximum_absolute_transfer_reconciliation_difference_m3,
        ),
        _check(
            "swmm_received_matches_anuga_return_volume",
            abs(swmm.received_from_counterpart_m3 - anuga_to_swmm)
            <= policy.maximum_absolute_transfer_reconciliation_difference_m3,
            {
                "swmm_received_m3": swmm.received_from_counterpart_m3,
                "canonical_transfer_m3": anuga_to_swmm,
            },
            policy.maximum_absolute_transfer_reconciliation_difference_m3,
        ),
        _check(
            "swmm_ledger_mass_balance_within_threshold",
            abs(swmm.mass_balance_residual_m3)
            <= policy.maximum_absolute_solver_mass_balance_residual_m3,
            swmm.mass_balance_residual_m3,
            policy.maximum_absolute_solver_mass_balance_residual_m3,
        ),
        _check(
            "anuga_ledger_mass_balance_within_threshold",
            abs(anuga.mass_balance_residual_m3)
            <= policy.maximum_absolute_solver_mass_balance_residual_m3,
            anuga.mass_balance_residual_m3,
            policy.maximum_absolute_solver_mass_balance_residual_m3,
        ),
        _check(
            "coupled_system_mass_balance_within_threshold",
            abs(coupled_residual)
            <= policy.maximum_absolute_coupled_mass_balance_residual_m3,
            coupled_residual,
            policy.maximum_absolute_coupled_mass_balance_residual_m3,
        ),
    ]
    failed_checks = [str(check["check_id"]) for check in checks if not check["passed"]]
    return {
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "ledger": {
            "swmm_to_anuga_transfer_m3": float(swmm_to_anuga),
            "anuga_to_swmm_transfer_m3": float(anuga_to_swmm),
            "gross_transfer_volume_by_interface_m3": transfer_volume_by_interface,
            "coupled_storage_change_m3": float(coupled_storage_change),
            "external_inflow_m3": float(external_inflow),
            "external_outflow_m3": float(external_outflow),
            "coupled_mass_balance_residual_m3": float(coupled_residual),
        },
        "admission_effect": "none_diagnostic_quality_only",
    }


def build_swmm_anuga_coupling_receipt(
    window: SwmmAnugaCouplingWindow,
    policy: SwmmAnugaCouplingQualityPolicy,
) -> dict[str, object]:
    """Build a self-hashed diagnostic receipt; reject invalid coupling ledgers."""

    quality = evaluate_swmm_anuga_coupling(window, policy)
    if quality["passed"] is not True:
        raise ValueError("swmm_anuga_coupling_quality_gate_failed")
    receipt: dict[str, object] = {
        "schema": SWMM_ANUGA_COUPLING_RECEIPT_SCHEMA,
        "status": "validated_synthetic_coupling_contract_not_admitted",
        "coupling_window": window.as_dict(),
        "quality_policy": policy.as_dict(),
        "quality_gates": quality,
        "execution": {
            "solver_execution_invoked_by_coupling_component": False,
            "actual_swmm_anuga_coupled_run": False,
            "contract_only_synthetic_ledger": True,
            "engineering_interface_data_admitted": False,
        },
        "admission": window.claim_boundary(),
    }
    receipt["receipt_sha256"] = _sha256_json(receipt)
    return receipt


def _check(
    check_id: str, passed: bool, observed: object, threshold_or_required: object
) -> dict[str, object]:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "observed": observed,
        "threshold_or_required": threshold_or_required,
    }


def _sha256_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
