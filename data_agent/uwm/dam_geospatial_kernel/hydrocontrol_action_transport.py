"""Identifiable action-transport kernel for HydroControl DAM-GK v0.2."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


HYDROCONTROL_ACTION_TRANSPORT_SCHEMA = (
    "gwm.dam_gk.hydrocontrol_action_transport.v1"
)


@dataclass(frozen=True)
class HydroControlActionTransportKernel:
    """Persistence plus a gated, signed action-transport residual."""

    action_scale_cfs: float
    transport_coefficient: float

    @classmethod
    def fit(
        cls,
        *,
        action_change_cfs: np.ndarray,
        future_flow_change_cfs: np.ndarray,
    ) -> "HydroControlActionTransportKernel":
        action = _one_dimensional(action_change_cfs, "action_change_cfs")
        outcome = _one_dimensional(
            future_flow_change_cfs, "future_flow_change_cfs"
        )
        if action.shape != outcome.shape:
            raise ValueError("action_outcome_shape_mismatch")
        finite = np.isfinite(action) & np.isfinite(outcome)
        action = action[finite]
        outcome = outcome[finite]
        nonzero = np.abs(action[action != 0.0])
        if nonzero.size == 0:
            raise ValueError("nonzero_training_action_required")
        action_scale = float(np.mean(nonzero))
        transported = gated_action_transport(action, action_scale)
        denominator = float(np.dot(transported, transported))
        if denominator <= 0.0:
            raise ValueError("nonpositive_transport_denominator")
        coefficient = float(np.dot(transported, outcome) / denominator)
        return cls(
            action_scale_cfs=action_scale,
            transport_coefficient=coefficient,
        )

    def edge_gate(self, action_change_cfs: np.ndarray) -> np.ndarray:
        action = _one_dimensional(action_change_cfs, "action_change_cfs")
        return np.abs(action) / (np.abs(action) + self.action_scale_cfs)

    def transported_action(self, action_change_cfs: np.ndarray) -> np.ndarray:
        return gated_action_transport(
            action_change_cfs, self.action_scale_cfs
        )

    def predict(
        self,
        *,
        current_flow_cfs: np.ndarray,
        action_change_cfs: np.ndarray,
    ) -> np.ndarray:
        current = _one_dimensional(current_flow_cfs, "current_flow_cfs")
        action = _one_dimensional(action_change_cfs, "action_change_cfs")
        if current.shape != action.shape:
            raise ValueError("current_action_shape_mismatch")
        prediction = current + self.transport_coefficient * self.transported_action(
            action
        )
        return np.clip(prediction, 0.0, 1_000_000.0)

    def to_dict(self) -> dict[str, float | str]:
        return {
            "schema": HYDROCONTROL_ACTION_TRANSPORT_SCHEMA,
            "action_scale_cfs": round(self.action_scale_cfs, 12),
            "transport_coefficient": round(
                self.transport_coefficient, 12
            ),
        }


def gated_action_transport(
    action_change_cfs: np.ndarray, action_scale_cfs: float
) -> np.ndarray:
    if not np.isfinite(action_scale_cfs) or action_scale_cfs <= 0.0:
        raise ValueError("positive_finite_action_scale_required")
    action = _one_dimensional(action_change_cfs, "action_change_cfs")
    return action * np.abs(action) / (np.abs(action) + action_scale_cfs)


def _one_dimensional(values: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError(f"{name}_must_be_one_dimensional")
    return array
