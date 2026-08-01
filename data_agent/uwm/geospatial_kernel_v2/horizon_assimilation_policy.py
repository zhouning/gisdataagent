"""Fail-closed horizon routing for a frozen state-assimilation candidate."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

HORIZON_ASSIMILATION_POLICY_SCHEMA = (
    "gwm.geospatial_kernel.horizon_assimilation_policy.v1"
)
HORIZON_ASSIMILATION_CANDIDATE_ID = "distance_localized_horizon_policy_v1"
HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS = (1, 3, 6, 12)
HORIZON_ASSIMILATION_MODES = (
    "nominal",
    "outlet_only_observation_update",
    "linear_distance_localized_mainstem_update",
    "quadratic_distance_localized_mainstem_update",
)


@dataclass(frozen=True)
class HorizonAssimilationPolicy:
    """A candidate policy that cannot be enabled through deserialization."""

    candidate_id: str
    supported_forecast_horizons_hours: tuple[int, ...]
    selected_modes: tuple[str, ...]
    selection_scope: str
    admitted: bool = False
    runtime_default_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            self.candidate_id != HORIZON_ASSIMILATION_CANDIDATE_ID
            or self.supported_forecast_horizons_hours
            != HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
            or len(self.selected_modes) != len(self.supported_forecast_horizons_hours)
            or any(mode not in HORIZON_ASSIMILATION_MODES for mode in self.selected_modes)
            or not isinstance(self.selection_scope, str)
            or not self.selection_scope.strip()
            or self.admitted is not False
            or self.runtime_default_enabled is not False
        ):
            raise ValueError("horizon_assimilation_policy_invalid")

    def mode_for_horizon(self, forecast_horizon_hours: int) -> str:
        if isinstance(forecast_horizon_hours, bool):
            raise ValueError("horizon_assimilation_policy_horizon_unsupported")
        try:
            index = self.supported_forecast_horizons_hours.index(forecast_horizon_hours)
        except ValueError as exc:
            raise ValueError("horizon_assimilation_policy_horizon_unsupported") from exc
        return self.selected_modes[index]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HORIZON_ASSIMILATION_POLICY_SCHEMA,
            "candidate_id": self.candidate_id,
            "supported_forecast_horizons_hours": list(
                self.supported_forecast_horizons_hours
            ),
            "selected_mode_by_horizon_hours": {
                str(horizon): self.selected_modes[index]
                for index, horizon in enumerate(
                    self.supported_forecast_horizons_hours
                )
            },
            "selection_scope": self.selection_scope,
            "admitted": self.admitted,
            "runtime_default_enabled": self.runtime_default_enabled,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> HorizonAssimilationPolicy:
        expected_keys = {
            "schema",
            "candidate_id",
            "supported_forecast_horizons_hours",
            "selected_mode_by_horizon_hours",
            "selection_scope",
            "admitted",
            "runtime_default_enabled",
        }
        if set(payload) != expected_keys or payload.get("schema") != (
            HORIZON_ASSIMILATION_POLICY_SCHEMA
        ):
            raise ValueError("horizon_assimilation_policy_invalid")
        horizons = payload.get("supported_forecast_horizons_hours")
        mode_by_horizon = payload.get("selected_mode_by_horizon_hours")
        if (
            not isinstance(horizons, list)
            or any(not isinstance(value, int) or isinstance(value, bool) for value in horizons)
            or not isinstance(mode_by_horizon, Mapping)
        ):
            raise ValueError("horizon_assimilation_policy_invalid")
        try:
            normalized_horizons = tuple(horizons)
            selected_modes = tuple(
                str(mode_by_horizon[str(horizon)]) for horizon in normalized_horizons
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("horizon_assimilation_policy_invalid") from exc
        if set(mode_by_horizon) != {str(value) for value in normalized_horizons}:
            raise ValueError("horizon_assimilation_policy_invalid")
        return cls(
            candidate_id=payload["candidate_id"],  # type: ignore[arg-type]
            supported_forecast_horizons_hours=normalized_horizons,
            selected_modes=selected_modes,
            selection_scope=payload["selection_scope"],  # type: ignore[arg-type]
            admitted=payload["admitted"],  # type: ignore[arg-type]
            runtime_default_enabled=payload["runtime_default_enabled"],  # type: ignore[arg-type]
        )
