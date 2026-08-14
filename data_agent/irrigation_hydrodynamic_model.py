"""Research-grade 1D hydrodynamic rollout for the irrigation workspace.

This adapter executes a conservative, Manning-parameterized kinematic-storage
network on a small synthetic irrigation network. The state transition and
water ledger are computed at runtime. Geometry, boundaries, observations and
parameters are not field calibrated, so results remain research diagnostics
rather than operating forecasts.
"""

from __future__ import annotations

import bisect
import math
import time
from dataclasses import dataclass
from typing import Any, Callable

from .uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    TrapezoidalChannelSection,
)
from .uwm.geospatial_kernel_v2.dynamic_wave_sources import (
    manning_uniform_discharge_m3s,
)


SECONDS_PER_DAY = 86_400.0
NOMINAL_SUPPLY_M3D = 960.0
FIELD_DEMAND_M3D = {"F1": 170.0, "F2": 150.0, "F3": 210.0, "F4": 190.0}
FIELD_ORDER = ("F1", "F2", "F3", "F4")
MODE_LABELS = {
    "baseline": "Baseline",
    "candidateA": "Candidate A",
    "candidateB": "Candidate B",
}


@dataclass(frozen=True, slots=True)
class ReachConfiguration:
    reach_id: str
    length_m: float
    cell_count: int
    upstream_bed_elevation_m: float
    bed_slope: float
    bottom_width_m: float
    side_slope: float
    manning_n: float
    capacity_m3s: float

    @property
    def cell_length_m(self) -> float:
        return self.length_m / self.cell_count

    @property
    def section(self) -> TrapezoidalChannelSection:
        return TrapezoidalChannelSection(self.bottom_width_m, self.side_slope)

    @property
    def bed_elevation_m(self) -> tuple[float, ...]:
        dx = self.cell_length_m
        return tuple(
            self.upstream_bed_elevation_m - self.bed_slope * (index + 0.5) * dx
            for index in range(self.cell_count)
        )


REACHES = {
    "C1": ReachConfiguration("C1", 2_400.0, 24, 100.0, 0.00035, 2.4, 1.0, 0.024, 0.020),
    "C2": ReachConfiguration("C2", 1_800.0, 18, 99.1, 0.00045, 1.5, 1.0, 0.026, 0.012),
    "C3": ReachConfiguration("C3", 2_600.0, 26, 99.1, 0.00030, 1.3, 1.0, 0.028, 0.012),
}

# Synthetic delivery-efficiency assumptions are applied after the hydraulic
# outlet flux. They are not inferred or calibrated and are returned in the
# model evidence so they cannot be mistaken for hidden learned parameters.
DELIVERY_EFFICIENCY = {"C2": 0.90, "C3": 0.82}


def _normal_area_m2(discharge_m3s: float, config: ReachConfiguration) -> float:
    """Solve the Manning normal area by bounded bisection."""
    target = max(float(discharge_m3s), 1e-8)
    section = config.section
    lower_depth = 0.005
    upper_depth = 0.20

    def capacity(depth: float) -> float:
        return manning_uniform_discharge_m3s(
            area_m2=section.area_m2(depth),
            bed_slope=config.bed_slope,
            manning_n=config.manning_n,
            section=section,
        )

    while capacity(upper_depth) < target and upper_depth < 5.0:
        upper_depth *= 1.6
    if capacity(upper_depth) < target:
        raise ValueError(f"normal_depth_bracket_failed:{config.reach_id}")
    for _ in range(70):
        middle = 0.5 * (lower_depth + upper_depth)
        if capacity(middle) < target:
            lower_depth = middle
        else:
            upper_depth = middle
    return section.area_m2(0.5 * (lower_depth + upper_depth))


def _piecewise_linear(points: list[dict[str, float]]) -> Callable[[float], float]:
    times = [point["time_seconds"] for point in points]
    values = [point["outflow_m3s"] for point in points]

    def sample(at_seconds: float) -> float:
        if at_seconds <= times[0]:
            return values[0]
        if at_seconds >= times[-1]:
            return values[-1]
        right = bisect.bisect_right(times, at_seconds)
        left = right - 1
        fraction = (at_seconds - times[left]) / (times[right] - times[left])
        return values[left] + fraction * (values[right] - values[left])

    return sample


def _integrate_hydrograph(points: list[dict[str, float]], until_seconds: float | None = None) -> float:
    limit = points[-1]["time_seconds"] if until_seconds is None else until_seconds
    total = 0.0
    for left, right in zip(points, points[1:], strict=False):
        start = left["time_seconds"]
        stop = min(right["time_seconds"], limit)
        if stop <= start:
            break
        if stop == right["time_seconds"]:
            end_value = right["outflow_m3s"]
        else:
            ratio = (stop - start) / (right["time_seconds"] - start)
            end_value = left["outflow_m3s"] + ratio * (
                right["outflow_m3s"] - left["outflow_m3s"]
            )
        total += 0.5 * (left["outflow_m3s"] + end_value) * (stop - start)
        if stop >= limit:
            break
    return total


def _simulate_reach(
    config: ReachConfiguration,
    *,
    horizon_seconds: float,
    initial_discharge_m3s: float,
    inflow: Callable[[float], float],
    report_interval_seconds: float = 60.0,
) -> dict[str, Any]:
    section = config.section
    initial_area = _normal_area_m2(initial_discharge_m3s, config)
    initial_velocity = initial_discharge_m3s / initial_area
    # For a Manning kinematic wave, dQ/dA is approximately 5/3 of mean
    # velocity for a wide prismatic section. The resulting travel time is
    # used as the storage constant of each directed reach.
    celerity = max((5.0 / 3.0) * initial_velocity, 1e-4)
    travel_time_seconds = config.length_m / celerity
    storage = travel_time_seconds * initial_discharge_m3s
    initial_storage = storage
    elapsed = 0.0
    next_report = 0.0
    steps = 0
    initial_depth = section.depth_m(initial_area)
    minimum_depth = initial_depth
    maximum_depth = initial_depth
    maximum_discharge = initial_discharge_m3s
    boundary_inflow_volume = 0.0
    boundary_outflow_volume = 0.0
    points = [{"time_seconds": 0.0, "outflow_m3s": float(initial_discharge_m3s)}]

    while elapsed < horizon_seconds - 1e-9:
        if next_report <= elapsed + 1e-9:
            next_report = min(horizon_seconds, elapsed + report_interval_seconds)
        timestep = min(300.0, next_report - elapsed, horizon_seconds - elapsed)
        if timestep <= 1e-9:
            elapsed = next_report
            continue
        prescribed_inflow = max(0.0, float(inflow(elapsed + 0.5 * timestep)))
        decay = math.exp(-timestep / travel_time_seconds)
        next_storage = (
            storage * decay
            + prescribed_inflow * travel_time_seconds * (1.0 - decay)
        )
        # Derive the average outlet flux from the discrete continuity ledger,
        # so every step closes I - O - dS/dt to floating point tolerance.
        average_outflow = prescribed_inflow - (next_storage - storage) / timestep
        end_outflow = max(0.0, next_storage / travel_time_seconds)
        boundary_inflow_volume += prescribed_inflow * timestep
        boundary_outflow_volume += average_outflow * timestep
        storage = next_storage
        elapsed += timestep
        steps += 1
        area = _normal_area_m2(end_outflow, config)
        depth = section.depth_m(area)
        minimum_depth = min(minimum_depth, depth)
        maximum_depth = max(maximum_depth, depth)
        maximum_discharge = max(maximum_discharge, prescribed_inflow, end_outflow)
        if elapsed >= next_report - 1e-7 or elapsed >= horizon_seconds - 1e-7:
            points.append(
                {
                    "time_seconds": min(elapsed, horizon_seconds),
                    "outflow_m3s": end_outflow,
                }
            )
            next_report = min(horizon_seconds, next_report + report_interval_seconds)

    final_storage = storage
    numerical_residual = (
        boundary_inflow_volume
        - boundary_outflow_volume
        - (final_storage - initial_storage)
    )
    return {
        "reach_id": config.reach_id,
        "scheme": "exact_linear_storage_route_with_manning_kinematic_celerity",
        "equations": "continuity_equation_with_kinematic_wave_storage_closure",
        "state_count": 1,
        "reach_length_m": config.length_m,
        "manning_n": config.manning_n,
        "bed_slope": config.bed_slope,
        "kinematic_celerity_mps": celerity,
        "travel_time_seconds": travel_time_seconds,
        "timestep_count": steps,
        "minimum_depth_m": minimum_depth,
        "maximum_depth_m": maximum_depth,
        "maximum_discharge_m3s": maximum_discharge,
        "capacity_m3s": config.capacity_m3s,
        "capacity_exceeded": maximum_discharge > config.capacity_m3s + 1e-9,
        "initial_storage_m3": initial_storage,
        "final_storage_m3": final_storage,
        "storage_change_m3": final_storage - initial_storage,
        "boundary_inflow_volume_m3": boundary_inflow_volume,
        "boundary_outflow_volume_m3": boundary_outflow_volume,
        "numerical_volume_residual_m3": numerical_residual,
        "hydrograph": points,
    }


def _allocation(mode: str, parameters: dict[str, float | int]) -> tuple[float, float, float]:
    if mode not in MODE_LABELS:
        raise ValueError(f"unsupported_irrigation_mode:{mode}")
    east_ratio = (
        float(parameters["candidate_east_ratio_percent"]) / 100.0
        if mode == "candidateB"
        else 0.55
    )
    shift_seconds = (
        float(parameters["west_shift_hours"]) * 3_600.0
        if mode in {"candidateA", "candidateB"}
        else 0.0
    )
    return east_ratio, 1.0 - east_ratio, shift_seconds


def _field_results(
    east_volume: float,
    west_volume: float,
    horizon_hours: int,
) -> dict[str, dict[str, float]]:
    demand_volume = {
        field_id: value * horizon_hours / 24.0
        for field_id, value in FIELD_DEMAND_M3D.items()
    }
    branch_demands = {
        "east": demand_volume["F1"] + demand_volume["F2"],
        "west": demand_volume["F3"] + demand_volume["F4"],
    }
    branch_volumes = {"east": max(0.0, east_volume), "west": max(0.0, west_volume)}
    fields: dict[str, dict[str, float]] = {}
    for field_id in FIELD_ORDER:
        branch = "east" if field_id in {"F1", "F2"} else "west"
        required = demand_volume[field_id]
        delivered_volume = min(
            required,
            branch_volumes[branch] * required / branch_demands[branch],
        )
        equivalent_rate = delivered_volume * 24.0 / horizon_hours
        fields[field_id] = {
            "demand": FIELD_DEMAND_M3D[field_id],
            "delivered": equivalent_rate,
            "coverage": 0.0 if required == 0.0 else delivered_volume / required,
            "demandVolumeM3": required,
            "deliveredVolumeM3": delivered_volume,
        }
    return fields


def run_dynamic_wave_scenario(
    mode: str,
    parameters: dict[str, float | int],
) -> dict[str, Any]:
    started = time.perf_counter()
    horizon_hours = int(parameters["horizon_hours"])
    horizon_seconds = horizon_hours * 3_600.0
    supply_drop = float(parameters["supply_drop_percent"])
    nominal_supply = NOMINAL_SUPPLY_M3D / SECONDS_PER_DAY
    scenario_supply = nominal_supply * (1.0 - supply_drop / 100.0)
    east_ratio, west_ratio, west_shift_seconds = _allocation(mode, parameters)

    trunk = _simulate_reach(
        REACHES["C1"],
        horizon_seconds=horizon_seconds,
        initial_discharge_m3s=nominal_supply,
        inflow=lambda _time: scenario_supply,
    )
    trunk_outflow = _piecewise_linear(trunk["hydrograph"])

    east = _simulate_reach(
        REACHES["C2"],
        horizon_seconds=horizon_seconds,
        initial_discharge_m3s=nominal_supply * 0.55,
        inflow=lambda at: trunk_outflow(at) * east_ratio,
    )

    def west_inflow(at: float) -> float:
        if west_shift_seconds <= 0.0:
            gate_factor = 1.0
        else:
            ramp_seconds = 1_800.0
            gate_factor = max(0.0, min(1.0, (at - west_shift_seconds) / ramp_seconds))
        return trunk_outflow(at) * west_ratio * gate_factor

    west = _simulate_reach(
        REACHES["C3"],
        horizon_seconds=horizon_seconds,
        initial_discharge_m3s=nominal_supply * 0.45,
        inflow=west_inflow,
    )
    east_out_volume = east["boundary_outflow_volume_m3"]
    west_out_volume = west["boundary_outflow_volume_m3"]
    east_effective_volume = east_out_volume * DELIVERY_EFFICIENCY["C2"]
    west_effective_volume = west_out_volume * DELIVERY_EFFICIENCY["C3"]
    conveyance_loss = (
        east_out_volume
        + west_out_volume
        - east_effective_volume
        - west_effective_volume
    )
    fields = _field_results(east_effective_volume, west_effective_volume, horizon_hours)
    delivered_volume = sum(item["deliveredVolumeM3"] for item in fields.values())
    demand_volume = sum(item["demandVolumeM3"] for item in fields.values())
    delivered_rate = delivered_volume * 24.0 / horizon_hours
    shortage_rate = max(0.0, demand_volume - delivered_volume) * 24.0 / horizon_hours
    coverage = [item["coverage"] for item in fields.values()]
    mean_coverage = sum(coverage) / len(coverage)
    fairness_cv = (
        math.sqrt(sum((value - mean_coverage) ** 2 for value in coverage) / len(coverage))
        / mean_coverage
        if mean_coverage
        else 0.0
    )

    trunk_out_volume = trunk["boundary_outflow_volume_m3"]
    east_in_volume = east["boundary_inflow_volume_m3"]
    west_in_volume = west["boundary_inflow_volume_m3"]
    junction_unallocated = max(0.0, trunk_out_volume - east_in_volume - west_in_volume)
    tail_spill = max(
        0.0,
        east_effective_volume + west_effective_volume - delivered_volume,
    )
    storage_change = sum(item["storage_change_m3"] for item in (trunk, east, west))
    boundary_volume = trunk["boundary_inflow_volume_m3"]
    residual_volume = (
        boundary_volume
        - storage_change
        - delivered_volume
        - conveyance_loss
        - tail_spill
        - junction_unallocated
    )
    residual_rate = residual_volume * 24.0 / horizon_hours
    capacity_violations = sum(item["capacity_exceeded"] for item in (trunk, east, west))
    node_states = {
        "R1": {"value": scenario_supply * SECONDS_PER_DAY, "unit": "m³/d"},
        "C1": {"value": trunk["hydrograph"][-1]["outflow_m3s"] * SECONDS_PER_DAY, "unit": "m³/d"},
        "C2": {"value": east["hydrograph"][-1]["outflow_m3s"] * SECONDS_PER_DAY, "unit": "m³/d"},
        "C3": {"value": west["hydrograph"][-1]["outflow_m3s"] * SECONDS_PER_DAY, "unit": "m³/d"},
        "D1": {"value": east_ratio * 100.0, "unit": "%"},
        "D2": {"value": west_ratio * 100.0, "unit": "%"},
        **{
            field_id: {
                "value": fields[field_id]["delivered"],
                "unit": "m³/d",
                "demand": fields[field_id]["demand"],
            }
            for field_id in FIELD_ORDER
        },
    }

    timeline = []
    for hour in range(0, horizon_hours + 1, 6):
        seconds = hour * 3_600.0
        east_volume = (
            _integrate_hydrograph(east["hydrograph"], seconds)
            * DELIVERY_EFFICIENCY["C2"]
        )
        west_volume = (
            _integrate_hydrograph(west["hydrograph"], seconds)
            * DELIVERY_EFFICIENCY["C3"]
        )
        elapsed_hours = max(hour, 1)
        snapshot_fields = _field_results(east_volume, west_volume, elapsed_hours)
        snapshot_coverage = min(item["coverage"] for item in snapshot_fields.values())
        snapshot_delivered = sum(item["deliveredVolumeM3"] for item in snapshot_fields.values())
        snapshot_demand = sum(
            FIELD_DEMAND_M3D[field_id] * hour / 24.0 for field_id in FIELD_ORDER
        )
        timeline.append(
            {
                "hour": hour,
                "tailCoverage": snapshot_coverage * 100.0,
                "shortage": max(0.0, snapshot_demand - snapshot_delivered),
                "status": "初始状态" if hour == 0 else "动力波求解完成",
            }
        )

    runtime_ms = (time.perf_counter() - started) * 1_000.0
    numerical = {
        "scheme": "exact_linear_storage_route_with_manning_kinematic_celerity",
        "equations": "continuity_equation_with_kinematic_wave_storage_closure",
        "timestep_count": sum(item["timestep_count"] for item in (trunk, east, west)),
        "state_count": sum(item["state_count"] for item in (trunk, east, west)),
        "runtime_ms": runtime_ms,
        "minimum_depth_m": min(item["minimum_depth_m"] for item in (trunk, east, west)),
        "maximum_depth_m": max(item["maximum_depth_m"] for item in (trunk, east, west)),
        "operator_admitted": False,
        "diagnostic_only": True,
        "assumed_delivery_efficiency": DELIVERY_EFFICIENCY,
        "not_included": [
            "full Saint-Venant dynamic-wave junction solver",
            "field-calibrated canal geometry and boundaries",
            "Richards soil-water solver",
            "learned JEPA state transition",
        ],
    }
    return {
        "mode": mode,
        "label": MODE_LABELS[mode],
        "branchRatio": east_ratio,
        "delivered": delivered_rate,
        "deliveredVolumeM3": delivered_volume,
        "shortage": shortage_rate,
        "shortageVolumeM3": max(0.0, demand_volume - delivered_volume),
        "tailCoverage": min(coverage) * 100.0,
        "fairnessCv": fairness_cv,
        "capacityViolations": capacity_violations,
        "residual": residual_rate,
        "residualVolumeM3": residual_volume,
        "westDelay": west_shift_seconds / 3_600.0,
        "westEfficiency": None,
        "fields": fields,
        "nodeStates": node_states,
        "timeline": timeline,
        "waterBalance": {
            "boundarySupply": boundary_volume * 24.0 / horizon_hours,
            "trunkLoss": 0.0,
            "branchLoss": conveyance_loss * 24.0 / horizon_hours,
            "delivered": delivered_rate,
            "unallocated": (junction_unallocated + tail_spill) * 24.0 / horizon_hours,
            "storageChange": storage_change * 24.0 / horizon_hours,
            "residual": residual_rate,
            "boundaryVolumeM3": boundary_volume,
            "deliveredVolumeM3": delivered_volume,
            "junctionUnallocatedVolumeM3": junction_unallocated,
            "tailSpillVolumeM3": tail_spill,
            "conveyanceLossVolumeM3": conveyance_loss,
            "storageChangeM3": storage_change,
            "residualVolumeM3": residual_volume,
        },
        "numerical": numerical,
        "reaches": [
            {key: value for key, value in reach.items() if key != "hydrograph"}
            for reach in (trunk, east, west)
        ],
    }


def run_dynamic_wave_scenarios(parameters: dict[str, float | int]) -> list[dict[str, Any]]:
    return [run_dynamic_wave_scenario(mode, parameters) for mode in MODE_LABELS]
