"""Conservative candidate simulator for Abu Dhabi urban-flood scenarios.

This is a coarse control-volume adapter, not a calibrated 1-D/2-D hydraulic
solver.  Its purpose is to make the world-model contract executable while
keeping mass balance, action semantics and evidence status explicit.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from .contracts import (
    FloodAction,
    FloodNetwork,
    FloodState,
    RainfallForcing,
)

URBAN_FLOOD_OPERATOR_SCHEMA = "gwm.abu_dhabi_flood.conservative_reservoir_operator.v1"
_MILLIMETRES_TO_METRES_PER_HOUR = 1.0e-3


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name}_must_be_finite")
    return result


@dataclass(frozen=True)
class FloodModelConfig:
    timestep_seconds: float
    mass_tolerance_m3: float = 1.0e-8
    allow_unadmitted_network_for_diagnostics: bool = True
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        timestep = _finite(self.timestep_seconds, "flood_timestep")
        tolerance = _finite(self.mass_tolerance_m3, "flood_mass_tolerance")
        if timestep <= 0.0:
            raise ValueError("flood_timestep_must_be_positive")
        if tolerance < 0.0:
            raise ValueError("flood_mass_tolerance_must_be_nonnegative")
        if not isinstance(self.allow_unadmitted_network_for_diagnostics, bool):
            raise ValueError("flood_diagnostic_network_flag_must_be_boolean")
        if not isinstance(self.diagnostic_only, bool):
            raise ValueError("flood_diagnostic_only_flag_must_be_boolean")
        object.__setattr__(self, "timestep_seconds", timestep)
        object.__setattr__(self, "mass_tolerance_m3", tolerance)


@dataclass(frozen=True)
class FloodStepTrace:
    state_before: FloodState
    state_after: FloodState
    rainfall_input_m3: float
    infiltration_loss_m3: float
    pump_outflow_m3: float
    outfall_outflow_m3: float
    link_inflow_m3: tuple[float, ...]
    link_release_m3: tuple[float, ...]
    surface_depth_m: tuple[float, ...]
    peak_depth_m: float
    mass_balance_residual_m3: float
    action_id: str
    timestamp_s: float
    diagnostic_only: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": URBAN_FLOOD_OPERATOR_SCHEMA,
            "state_before": self.state_before.as_dict(),
            "state_after": self.state_after.as_dict(),
            "rainfall_input_m3": self.rainfall_input_m3,
            "infiltration_loss_m3": self.infiltration_loss_m3,
            "pump_outflow_m3": self.pump_outflow_m3,
            "outfall_outflow_m3": self.outfall_outflow_m3,
            "link_inflow_m3": list(self.link_inflow_m3),
            "link_release_m3": list(self.link_release_m3),
            "surface_depth_m": list(self.surface_depth_m),
            "peak_depth_m": self.peak_depth_m,
            "mass_balance_residual_m3": self.mass_balance_residual_m3,
            "mass_balance_closed": abs(self.mass_balance_residual_m3) <= 1.0e-8,
            "action_id": self.action_id,
            "timestamp_s": self.timestamp_s,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class FloodRollout:
    traces: tuple[FloodStepTrace, ...]
    final_state: FloodState
    peak_depth_by_patch_m: tuple[float, ...]
    total_rainfall_input_m3: float
    total_infiltration_loss_m3: float
    total_pump_outflow_m3: float
    total_outfall_outflow_m3: float
    maximum_abs_mass_balance_residual_m3: float
    diagnostic_only: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": URBAN_FLOOD_OPERATOR_SCHEMA,
            "steps": [trace.as_dict() for trace in self.traces],
            "final_state": self.final_state.as_dict(),
            "peak_depth_by_patch_m": list(self.peak_depth_by_patch_m),
            "total_rainfall_input_m3": self.total_rainfall_input_m3,
            "total_infiltration_loss_m3": self.total_infiltration_loss_m3,
            "total_pump_outflow_m3": self.total_pump_outflow_m3,
            "total_outfall_outflow_m3": self.total_outfall_outflow_m3,
            "maximum_abs_mass_balance_residual_m3": (
                self.maximum_abs_mass_balance_residual_m3
            ),
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


class AbuDhabiFloodWorldModel:
    """Action-conditioned recursive transition over a compiled flood graph."""

    def __init__(self, network: FloodNetwork, config: FloodModelConfig) -> None:
        if not network.links:
            raise ValueError("flood_network_requires_at_least_one_link")
        if not config.allow_unadmitted_network_for_diagnostics and not network.admitted:
            raise ValueError("unadmitted_flood_network_not_allowed")
        self.network = network
        self.config = config
        self._patch_index = network.patch_index
        self._link_index = network.link_index
        self._source_indices = tuple(
            self._patch_index[link.source_patch_id] for link in network.links
        )
        self._target_indices = tuple(
            None
            if link.target_patch_id is None
            else self._patch_index[link.target_patch_id]
            for link in network.links
        )
        self._outgoing_by_patch = tuple(
            tuple(index for index, source in enumerate(self._source_indices) if source == patch)
            for patch in range(len(network.patches))
        )

    def initial_state(
        self,
        *,
        surface_depth_m: Iterable[float] | None = None,
        link_storage_m3: Iterable[float] | None = None,
        timestamp_s: float = 0.0,
        provenance_id: str = "state:abu-dhabi-flood-initial",
    ) -> FloodState:
        patches = self.network.patches
        if surface_depth_m is None:
            surface = (0.0,) * len(patches)
        else:
            depths = tuple(_finite(value, "initial_surface_depth") for value in surface_depth_m)
            if len(depths) != len(patches) or any(value < 0.0 for value in depths):
                raise ValueError("initial_surface_depth_dimension_or_sign_invalid")
            surface = tuple(
                depth * patch.area_m2
                for depth, patch in zip(depths, patches, strict=True)
            )
        if link_storage_m3 is None:
            link_storage = (0.0,) * len(self.network.links)
        else:
            link_storage = tuple(
                _finite(value, "initial_link_storage") for value in link_storage_m3
            )
            if len(link_storage) != len(self.network.links) or any(
                value < 0.0 for value in link_storage
            ):
                raise ValueError("initial_link_storage_dimension_or_sign_invalid")
        return FloodState(
            surface,
            link_storage,
            _finite(timestamp_s, "initial_timestamp"),
            provenance_id,
        )

    def step(
        self,
        state: FloodState,
        rainfall: RainfallForcing,
        action: FloodAction | None = None,
    ) -> FloodStepTrace:
        self._validate_state(state)
        self._validate_rainfall(rainfall, state)
        resolved_action = action or FloodAction.noop(
            link_count=len(self.network.links),
            patch_count=len(self.network.patches),
        )
        self._validate_action(resolved_action)
        dt = self.config.timestep_seconds
        patch_count = len(self.network.patches)
        link_count = len(self.network.links)
        patches = self.network.patches

        rainfall_volume = tuple(
            intensity
            * _MILLIMETRES_TO_METRES_PER_HOUR
            / 3600.0
            * dt
            * patch.area_m2
            * patch.runoff_coefficient
            for intensity, patch in zip(rainfall.intensity_mm_per_h, patches, strict=True)
        )
        rainfall_total = float(sum(rainfall_volume))
        after_rain = [
            before + incoming
            for before, incoming in zip(
                state.surface_volume_m3,
                rainfall_volume,
                strict=True,
            )
        ]
        infiltration_volume = tuple(
            min(
                available,
                patch.infiltration_capacity_mm_per_h
                * _MILLIMETRES_TO_METRES_PER_HOUR
                / 3600.0
                * dt
                * patch.area_m2,
            )
            for available, patch in zip(after_rain, patches, strict=True)
        )
        available = [
            value - loss
            for value, loss in zip(after_rain, infiltration_volume, strict=True)
        ]
        infiltration_total = float(sum(infiltration_volume))

        effective_capacities = tuple(
            link.capacity_m3s * resolved_action.drainage_capacity_multipliers[index]
            for index, link in enumerate(self.network.links)
        )
        link_inflow = [0.0] * link_count
        for patch_index, outgoing in enumerate(self._outgoing_by_patch):
            total_capacity = sum(effective_capacities[index] for index in outgoing)
            if total_capacity <= 0.0:
                continue
            scale = min(1.0, available[patch_index] / (dt * total_capacity))
            for index in outgoing:
                link_inflow[index] = effective_capacities[index] * dt * scale
        for index, source_index in enumerate(self._source_indices):
            available[source_index] -= link_inflow[index]

        link_release = []
        next_link_storage = []
        arriving = [0.0] * patch_count
        outfall_total = 0.0
        for index, link in enumerate(self.network.links):
            release_fraction = 1.0 - math.exp(-dt / link.travel_time_seconds)
            released = state.link_storage_m3[index] * release_fraction
            link_release.append(released)
            next_link_storage.append(state.link_storage_m3[index] - released + link_inflow[index])
            target_index = self._target_indices[index]
            if target_index is None:
                outfall_total += released
            else:
                arriving[target_index] += released

        pump_outflow = []
        for patch_index in range(patch_count):
            available[patch_index] += arriving[patch_index]
            pump = min(
                available[patch_index],
                resolved_action.pump_capacity_m3s[patch_index] * dt,
            )
            pump_outflow.append(pump)
            available[patch_index] -= pump
        next_surface = tuple(max(0.0, value) for value in available)
        next_state = FloodState(
            next_surface,
            tuple(next_link_storage),
            state.timestamp_s + dt,
            provenance_id=(
                f"transition|{state.provenance_id}|{rainfall.provenance_id}|"
                f"{resolved_action.provenance_id}"
            ),
        )
        pump_total = float(sum(pump_outflow))
        residual = (
            next_state.total_storage_m3
            - state.total_storage_m3
            - rainfall_total
            + infiltration_total
            + pump_total
            + outfall_total
        )
        if abs(residual) > self.config.mass_tolerance_m3:
            raise RuntimeError("flood_mass_balance_failed")
        depths = tuple(
            volume / patch.area_m2
            for volume, patch in zip(next_state.surface_volume_m3, patches, strict=True)
        )
        return FloodStepTrace(
            state_before=state,
            state_after=next_state,
            rainfall_input_m3=rainfall_total,
            infiltration_loss_m3=infiltration_total,
            pump_outflow_m3=pump_total,
            outfall_outflow_m3=outfall_total,
            link_inflow_m3=tuple(link_inflow),
            link_release_m3=tuple(link_release),
            surface_depth_m=depths,
            peak_depth_m=max(depths, default=0.0),
            mass_balance_residual_m3=residual,
            action_id=resolved_action.action_id,
            timestamp_s=state.timestamp_s,
            diagnostic_only=self.config.diagnostic_only,
        )

    def rollout(
        self,
        initial_state: FloodState,
        rainfall_series: Iterable[RainfallForcing],
        action_series: Iterable[FloodAction | None] | None = None,
    ) -> FloodRollout:
        rainfalls = tuple(rainfall_series)
        actions = tuple(action_series) if action_series is not None else (None,) * len(rainfalls)
        if len(actions) != len(rainfalls):
            raise ValueError("flood_rollout_rainfall_action_length_mismatch")
        state = initial_state
        traces: list[FloodStepTrace] = []
        peak_depth = [0.0] * len(self.network.patches)
        for rainfall, action in zip(rainfalls, actions, strict=True):
            trace = self.step(state, rainfall, action)
            traces.append(trace)
            state = trace.state_after
            for index, depth in enumerate(trace.surface_depth_m):
                peak_depth[index] = max(peak_depth[index], depth)
        return FloodRollout(
            traces=tuple(traces),
            final_state=state,
            peak_depth_by_patch_m=tuple(peak_depth),
            total_rainfall_input_m3=sum(trace.rainfall_input_m3 for trace in traces),
            total_infiltration_loss_m3=sum(trace.infiltration_loss_m3 for trace in traces),
            total_pump_outflow_m3=sum(trace.pump_outflow_m3 for trace in traces),
            total_outfall_outflow_m3=sum(trace.outfall_outflow_m3 for trace in traces),
            maximum_abs_mass_balance_residual_m3=max(
                (abs(trace.mass_balance_residual_m3) for trace in traces),
                default=0.0,
            ),
            diagnostic_only=self.config.diagnostic_only,
        )

    def counterfactual(
        self,
        initial_state: FloodState,
        rainfall_series: Iterable[RainfallForcing],
        action_scenarios: dict[str, Iterable[FloodAction | None]],
    ) -> dict[str, FloodRollout]:
        rainfall = tuple(rainfall_series)
        return {
            name: self.rollout(initial_state, rainfall, actions)
            for name, actions in action_scenarios.items()
        }

    def _validate_state(self, state: FloodState) -> None:
        if len(state.surface_volume_m3) != len(self.network.patches):
            raise ValueError("flood_state_surface_dimension_mismatch")
        if len(state.link_storage_m3) != len(self.network.links):
            raise ValueError("flood_state_link_dimension_mismatch")

    def _validate_rainfall(self, rainfall: RainfallForcing, state: FloodState) -> None:
        if len(rainfall.intensity_mm_per_h) != len(self.network.patches):
            raise ValueError("rainfall_patch_dimension_mismatch")
        if rainfall.duration_seconds + 1.0e-9 < self.config.timestep_seconds:
            raise ValueError("rainfall_interval_shorter_than_model_timestep")
        if abs(rainfall.timestamp_s - state.timestamp_s) > 1.0e-6:
            raise ValueError("rainfall_timestamp_must_match_state_timestamp")

    def _validate_action(self, action: FloodAction) -> None:
        if len(action.drainage_capacity_multipliers) != len(self.network.links):
            raise ValueError("flood_action_link_dimension_mismatch")
        if len(action.pump_capacity_m3s) != len(self.network.patches):
            raise ValueError("flood_action_patch_dimension_mismatch")
